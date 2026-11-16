"""设备健康检测：Agent 心跳 + 主动探测（Ping / TCP 端口），并维护在线状态。

判定规则（逐台可配）：
- heartbeat：只看心跳，超过 offline_seconds 未上报 -> 离线；
- probe    ：只看探测，连续 2 次失败 -> 离线；
- hybrid   ：心跳与探测任一可达即在线，心跳超时且探测连续 3 次失败才离线；
- 人工标记的 fault / maintenance / retired 不被自动覆盖。
"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

from .assets import AUTO_MANAGED, STATUS_LABELS, AssetService
from .config import LineGuardConfig
from .db import Database


def ping(host: str, timeout_ms: int) -> dict:
    if not host:
        return {"ok": False, "error": True, "detail": "未配置 IP"}
    timeout_s = max(1, round(timeout_ms / 1000))
    if sys.platform == "win32":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(timeout_s), host]
    started = time.perf_counter()
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=timeout_s + 1)
        latency = int((time.perf_counter() - started) * 1000)
        return {"ok": res.returncode == 0, "latency": latency,
                "detail": "ping 成功" if res.returncode == 0 else "ping 超时或不可达"}
    except FileNotFoundError:
        return {"ok": False, "error": True, "latency": None, "detail": "系统未安装 ping 命令"}
    except PermissionError:
        return {"ok": False, "error": True, "latency": None, "detail": "无权限执行 ping"}
    except (subprocess.SubprocessError, OSError) as exc:
        return {"ok": False, "error": True, "latency": None, "detail": "ping 执行失败：" + str(exc)}


def tcp_check(host: str, port: int, timeout_ms: int) -> dict:
    started = time.perf_counter()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_ms / 1000)
            code = sock.connect_ex((host, port))
        latency = int((time.perf_counter() - started) * 1000)
        ok = code == 0
        return {"ok": ok, "latency": latency, "detail": ("端口 %d 可达" % port) if ok else ("端口 %d 不可达" % port)}
    except OSError as exc:
        return {"ok": False, "latency": None, "detail": "端口探测失败：" + str(exc)}


class Monitor:
    def __init__(self, db: Database, assets: AssetService, config: LineGuardConfig) -> None:
        self.db = db
        self.assets = assets
        self.config = config
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fail: dict[int, int] = {}
        self._next: dict[int, float] = {}
        self._warned = False

    # ----------------------------------------------------------- 心跳
    def heartbeat(self, device: dict, payload: dict) -> dict:
        fields, values = [], []
        mapping = {
            "hostname": "hostname", "ip": "ip", "mac": "mac", "os_version": "os_version",
            "cpu_model": "cpu_model", "memory_gb": "memory_gb", "disk_gb": "disk_gb",
            "cpu_percent": "cpu_percent", "mem_percent": "mem_percent", "disk_percent": "disk_percent",
            "uptime_seconds": "uptime_seconds",
        }
        for src, col in mapping.items():
            val = payload.get(src)
            if val not in (None, ""):
                fields.append(col + " = %s")
                values.append(val)
        fields.append("last_heartbeat_at = NOW()")
        fields.append("last_seen_at = NOW()")
        self.db.execute("UPDATE lg_device SET " + ", ".join(fields) + " WHERE id = %s", values + [device["id"]])
        self.db.execute(
            "INSERT INTO lg_health_check (device_id, source, status, detail) VALUES (%s, 'heartbeat', 'ok', %s)",
            (device["id"], payload.get("ip") or device.get("ip") or ""),
        )
        if device["status"] == "offline":
            self.assets.change_status(device["id"], "online", "心跳恢复，设备重新在线", "来自 " + str(payload.get("ip") or ""), "heartbeat")
        self.check_thresholds(device["id"])
        return {"ok": True, "device_id": device["id"], "asset_no": device["asset_no"]}

    # ----------------------------------------------------------- 阈值
    def check_thresholds(self, device_id: int) -> None:
        settings = self.db.settings_all()
        limits = {
            "cpu": int(settings.get("alert_cpu", 90) or 90),
            "mem": int(settings.get("alert_mem", 90) or 90),
            "disk": int(settings.get("alert_disk", 90) or 90),
        }
        device = self.db.one("SELECT * FROM lg_device WHERE id = %s", (device_id,))
        if not device:
            return
        labels = {"cpu": "CPU", "mem": "内存", "disk": "磁盘"}
        for key, limit in limits.items():
            val = device.get(key + "_percent")
            if val is None:
                continue
            val = float(val)
            open_alert = self.db.one(
                "SELECT id FROM lg_alert WHERE device_id = %s AND alert_type = %s AND resolved_at IS NULL",
                (device_id, key),
            )
            if val >= limit and not open_alert:
                self.db.execute(
                    "INSERT INTO lg_alert (device_id, level, alert_type, message) VALUES (%s, 'warning', %s, %s)",
                    (device_id, key, "%s %s 使用率 %.1f%% 超过阈值 %d%%" % (device["asset_no"], labels[key], val, limit)),
                )
            elif val < limit and open_alert:
                self.db.execute("UPDATE lg_alert SET resolved_at = NOW() WHERE id = %s", (open_alert["id"],))

    # ----------------------------------------------------------- 探测
    def _probe_one(self, device: dict) -> dict:
        """只做探测并返回结果，写库交给 _apply_probe_results 批量完成。

        300 台工控机每轮如果逐台 UPDATE/INSERT，会起上千次 mysql 进程；
        这里把「网络探测」和「结果回写」拆开，回写按批合并成一条 SQL。
        """
        port = int(device.get("probe_port") or 0)
        host = device.get("ip") or ""
        return {"device": device, "result": self.ping_or_tcp(host, port)}

    def _apply_probe_results(self, batch: list[dict]) -> None:
        if not batch:
            return
        errors = [item for item in batch if item["result"].get("error")]
        normal = [item for item in batch if not item["result"].get("error")]

        if errors and not self._warned:
            self._warned = True
            print("[lineguard] 主动探测不可用：" + errors[0]["result"]["detail"], flush=True)

        # 1) 采样记录：多行 INSERT，分批提交
        for start in range(0, len(batch), 200):
            chunk = batch[start:start + 200]
            values = []
            for item in chunk:
                device, result = item["device"], item["result"]
                status = "error" if result.get("error") else ("ok" if result["ok"] else "fail")
                values.append("(%d, 'probe', %s, %s, %s)" % (
                    int(device["id"]), self.db._literal(status),
                    self.db._literal(result.get("latency")),
                    self.db._literal((result.get("detail") or "")[:250]),
                ))
            self.db._execute_sql(
                "INSERT INTO lg_health_check (device_id, source, status, latency_ms, detail) VALUES "
                + ", ".join(values)
            )

        # 2) 设备探测结果：一条 CASE 批量 UPDATE
        if normal:
            for start in range(0, len(normal), 100):
                chunk = normal[start:start + 100]
                ok_cases = " ".join(
                    "WHEN %d THEN %d" % (int(i["device"]["id"]), 1 if i["result"]["ok"] else 0) for i in chunk)
                seen_cases = " ".join(
                    "WHEN %d THEN %s" % (int(i["device"]["id"]), "NOW()" if i["result"]["ok"] else "last_seen_at")
                    for i in chunk)
                ids = ", ".join(str(int(i["device"]["id"])) for i in chunk)
                self.db._execute_sql(
                    "UPDATE lg_device SET last_probe_ok = CASE id " + ok_cases + " END, "
                    "last_seen_at = CASE id " + seen_cases + " END WHERE id IN (" + ids + ")"
                )

        # 3) 状态流转：只有需要变更的设备才逐台写（伴随事件与告警）
        for item in normal:
            device, result = item["device"], item["result"]
            device_id = int(device["id"])
            if result["ok"]:
                self._fail[device_id] = 0
                if device["status"] not in AUTO_MANAGED:
                    continue
                if device["status"] != "online" and device["probe_mode"] != "heartbeat":
                    self.assets.change_status(device_id, "online", "主动探测恢复在线",
                                              result["detail"], "probe")
                continue
            self._fail[device_id] = self._fail.get(device_id, 0) + 1
            if device["status"] not in AUTO_MANAGED:
                continue
            need = 2 if device["probe_mode"] == "probe" else 3
            if (device["probe_mode"] != "heartbeat" and not self._heartbeat_fresh(device)
                    and device["status"] == "online" and self._fail[device_id] >= need):
                self.assets.change_status(device_id, "offline", "主动探测连续失败，判定离线",
                                          result["detail"], "probe")
                self._raise_offline(device, result["detail"])

    def ping_or_tcp(self, host: str, port: int) -> dict:
        if not host:
            return {"ok": False, "error": True, "latency": None, "detail": "未配置 IP"}
        if port:
            return tcp_check(host, port, self.config.probe_timeout_ms)
        return ping(host, self.config.probe_timeout_ms)

    def _heartbeat_fresh(self, device: dict) -> bool:
        last = device.get("last_heartbeat_at")
        if not last:
            return False
        if isinstance(last, str):
            last = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - last).total_seconds() < self.config.offline_seconds

    def _raise_offline(self, device: dict, detail: str) -> None:
        open_alert = self.db.one(
            "SELECT id FROM lg_alert WHERE device_id = %s AND alert_type = 'offline' AND resolved_at IS NULL",
            (device["id"],),
        )
        if not open_alert:
            self.db.execute(
                "INSERT INTO lg_alert (device_id, level, alert_type, message) VALUES (%s, 'critical', 'offline', %s)",
                (device["id"], (device["asset_no"] + " " + device["hostname"] + " 离线：" + detail)[:500]),
            )

    # ------------------------------------------------------- 心跳超时
    def reconcile_heartbeat(self) -> None:
        rows = self.db.query(
            "SELECT * FROM lg_device WHERE status = 'online' AND probe_mode IN ('heartbeat', 'hybrid')"
        )
        for device in rows:
            if self._heartbeat_fresh(device):
                continue
            if device["probe_mode"] == "hybrid" and device.get("last_probe_ok") == 1:
                continue
            self.assets.change_status(device["id"], "offline", "心跳超时，判定离线",
                                       "最近心跳：" + str(device.get("last_heartbeat_at") or "从未上报"), "heartbeat")
            self._raise_offline(device, "心跳中断超过 %d 秒" % self.config.offline_seconds)

    # ----------------------------------------------------------- 循环
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.reconcile_heartbeat()
                now = time.time()
                devices = self.db.query("SELECT * FROM lg_device WHERE status <> 'retired' AND ip <> ''")
                due = [d for d in devices if self._next.get(int(d["id"]), 0) <= now]
                results: list[dict] = []
                lock = threading.Lock()
                threads: list[threading.Thread] = []

                def run(device: dict) -> None:
                    item = self._probe_one(device)
                    with lock:
                        results.append(item)

                for device in due:
                    interval = max(10, int(device.get("probe_interval") or self.config.probe_interval_seconds))
                    self._next[int(device["id"])] = now + interval
                    thread = threading.Thread(target=run, args=(device,), daemon=True)
                    thread.start()
                    threads.append(thread)
                    if len(threads) >= self.config.probe_concurrency:
                        for running in threads:
                            running.join()
                        threads = []
                        # 每满一批就回写，避免一次攒太多
                        if results:
                            self._apply_probe_results(results)
                            results = []
                for running in threads:
                    running.join()
                if results:
                    self._apply_probe_results(results)
                self.db.execute(
                    "DELETE FROM lg_health_check WHERE checked_at < NOW() - INTERVAL %d DAY"
                    % max(1, int(self.config.check_retention_days))
                )
            except Exception as exc:  # 循环不允许因单次异常退出
                print("[lineguard] 检测循环异常：" + str(exc), flush=True)
            self._stop.wait(5)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="lineguard-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
