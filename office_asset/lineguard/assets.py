"""资产核心业务：设备状态机、换线履历、换下状况登记、人工录入与批量入库。

核心不变量（对应"换到其他产线数据自动跟过去"）：
- lg_device 是唯一持久实体；line_id / station_id 只是"当前位置"；
- 任何位置变化都必须写一条 lg_device_transfer，并追加一条 lg_device_event；
- 心跳、指标、告警全部挂在 device_id 上，位置变化不搬移任何历史数据。
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime

from .db import Database

STATUS_LABELS = {
    "online": "在线", "offline": "离线", "fault": "故障", "maintenance": "检修中", "retired": "已下线",
}
AUTO_MANAGED = {"online", "offline"}
CONDITION_RESULTS = {"pending", "repaired", "standby", "scrapped"}


class AssetError(Exception):
    """业务校验错误，携带 HTTP 状态码。"""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_token() -> str:
    return secrets.token_hex(24)[:48]


class AssetService:
    def __init__(self, db: Database, company_ids: list[int] | None = None, default_company_id: int = 0) -> None:
        self.db = db
        # None = 不限制（超管/全部公司）；列表 = 只允许这些公司
        self.company_ids = sorted({int(c) for c in (company_ids or [])}) if company_ids is not None else None
        self.default_company_id = int(default_company_id or 0)

    def _company_sql(self, alias: str = "d") -> tuple[str, list]:
        """返回公司过滤片段；超管（None）返回空片段。"""
        if self.company_ids is None:
            return "", []
        if not self.company_ids:
            return " AND 1=0", []
        return f" AND {alias}.company_id IN (" + ", ".join(str(c) for c in self.company_ids) + ")", []

    # ------------------------------------------------------------------ 事件
    def add_event(self, device_id: int, event_type: str, title: str, detail: str = "", payload: dict | None = None,
                  operator: str = "", line_id: int | None = None, station_id: int | None = None) -> None:
        self.db.execute(
            "INSERT INTO lg_device_event (device_id, event_type, line_id, station_id, title, detail, payload, operator) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (device_id, event_type, line_id, station_id, title, detail, json.dumps(payload or {}, ensure_ascii=False), operator),
        )

    # ------------------------------------------------------------ 位置描述
    def location_text(self, line_id: int | None, station_id: int | None) -> str:
        if not line_id:
            return "未分配产线"
        row = self.db.one(
            "SELECT w.name AS wname, l.name AS lname FROM lg_line l "
            "JOIN lg_workshop w ON w.id = l.workshop_id WHERE l.id = %s",
            (line_id,),
        )
        if not row:
            return "未知产线"
        text = row["wname"] + " / " + row["lname"]
        if station_id:
            st = self.db.one("SELECT name FROM lg_station WHERE id = %s", (station_id,))
            if st:
                text += " / " + st["name"]
        return text

    # ------------------------------------------------------------ 查询
    def get_device(self, device_id: int) -> dict:
        row = self.db.one(
            "SELECT d.*, l.name AS line_name, w.id AS workshop_id, w.name AS workshop_name, s.name AS station_name "
            "FROM lg_device d LEFT JOIN lg_line l ON l.id = d.line_id "
            "LEFT JOIN lg_workshop w ON w.id = l.workshop_id LEFT JOIN lg_station s ON s.id = d.station_id "
            "WHERE d.id = %s" + self._company_sql("d")[0],
            (device_id,),
        )
        if not row:
            raise AssetError("设备不存在", 404)
        return row

    def device_detail(self, device_id: int) -> dict:
        device = self.get_device(device_id)
        transfers = self.db.query(
            "SELECT t.*, "
            "(SELECT CONCAT(w.name, ' / ', l.name) FROM lg_line l JOIN lg_workshop w ON w.id = l.workshop_id WHERE l.id = t.from_line_id) AS from_line_name, "
            "(SELECT CONCAT(w.name, ' / ', l.name) FROM lg_line l JOIN lg_workshop w ON w.id = l.workshop_id WHERE l.id = t.to_line_id) AS to_line_name "
            "FROM lg_device_transfer t WHERE t.device_id = %s ORDER BY t.created_at DESC, t.id DESC",
            (device_id,),
        )
        conditions = self.db.query("SELECT * FROM lg_device_condition WHERE device_id = %s ORDER BY created_at DESC, id DESC", (device_id,))
        events = self.db.query("SELECT * FROM lg_device_event WHERE device_id = %s ORDER BY created_at DESC, id DESC LIMIT 200", (device_id,))
        checks = self.db.query("SELECT * FROM lg_health_check WHERE device_id = %s ORDER BY checked_at DESC, id DESC LIMIT 30", (device_id,))
        token = device.pop("agent_token", "") or ""
        device["agent_token_masked"] = (token[:6] + "******" + token[-4:]) if token else ""
        return {"device": device, "transfers": transfers, "conditions": conditions, "events": events, "checks": checks}

    def list_devices(self, q: str = "", status: str = "", workshop_id: int | None = None, line_id: int | None = None,
                     page: int = 1, size: int = 50) -> dict:
        where, args = ["1=1"], []
        company_sql, company_args = self._company_sql("d")
        if company_sql:
            where.append(company_sql.strip()[4:])  # 去掉前缀的 "AND "
        if q:
            like = "%" + q + "%"
            where.append("(d.asset_no LIKE %s OR d.hostname LIKE %s OR d.ip LIKE %s OR d.model LIKE %s OR d.serial_no LIKE %s)")
            args += [like] * 5
        if status:
            where.append("d.status = %s")
            args.append(status)
        if workshop_id:
            where.append("l.workshop_id = %s")
            args.append(workshop_id)
        if line_id:
            where.append("d.line_id = %s")
            args.append(line_id)
        base = ("FROM lg_device d LEFT JOIN lg_line l ON l.id = d.line_id "
                "LEFT JOIN lg_workshop w ON w.id = l.workshop_id LEFT JOIN lg_station s ON s.id = d.station_id "
                "WHERE " + " AND ".join(where))
        total = self.db.one("SELECT COUNT(*) AS c " + base, args)["c"]
        size = max(1, min(500, int(size or 50)))
        page = max(1, int(page or 1))
        rows = self.db.query(
            "SELECT d.id, d.asset_no, d.hostname, d.ip, d.model, d.os_version, d.serial_no, d.status, d.probe_mode, "
            "d.probe_port, d.probe_interval, d.cpu_percent, d.mem_percent, d.disk_percent, d.last_heartbeat_at, "
            "d.last_seen_at, d.last_state_changed_at, d.owner, d.source, d.line_id, d.station_id, d.remark, "
            "l.name AS line_name, w.name AS workshop_name, s.name AS station_name "
            + base + " ORDER BY d.asset_no LIMIT %s OFFSET %s",
            args + [size, (page - 1) * size],
        )
        return {"total": total, "page": page, "size": size, "items": rows}

    # ------------------------------------------------------------ 状态机
    def change_status(self, device_id: int, next_status: str, title: str = "", detail: str = "",
                      event_type: str = "status", operator: str = "", payload: dict | None = None) -> bool:
        if next_status not in STATUS_LABELS:
            raise AssetError("非法状态：" + next_status)
        device = self.get_device(device_id)
        if device["status"] == next_status:
            return False
        self.db.execute("UPDATE lg_device SET status = %s, last_state_changed_at = NOW() WHERE id = %s", (next_status, device_id))
        text = title or ("状态变更：" + STATUS_LABELS[device["status"]] + " -> " + STATUS_LABELS[next_status])
        merged = {"from": device["status"], "to": next_status}
        merged.update(payload or {})
        self.add_event(device_id, event_type, text, detail, merged, operator, device["line_id"], device["station_id"])
        if next_status == "online":
            self.db.execute("UPDATE lg_alert SET resolved_at = NOW() WHERE device_id = %s AND alert_type = 'offline' AND resolved_at IS NULL", (device_id,))
        return True

    # ------------------------------------------------------------ 换线
    def transfer(self, device_id: int, to_line_id: int | None = None, to_station_id: int | None = None,
                 to_status: str | None = None, reason: str = "", note: str = "", operator: str = "") -> dict:
        device = self.get_device(device_id)
        if to_line_id and not self.db.one("SELECT id FROM lg_line WHERE id = %s", (to_line_id,)):
            raise AssetError("目标产线不存在")
        if to_station_id:
            station = self.db.one("SELECT id, line_id FROM lg_station WHERE id = %s", (to_station_id,))
            if not station:
                raise AssetError("目标工位不存在")
            if to_line_id and station["line_id"] != to_line_id:
                raise AssetError("目标工位不属于目标产线")
        if to_status and to_status not in STATUS_LABELS:
            raise AssetError("非法状态")

        from_text = self.location_text(device["line_id"], device["station_id"])
        to_text = self.location_text(to_line_id, to_station_id)
        next_status = to_status or device["status"]

        self.db.execute(
            "UPDATE lg_device SET line_id = %s, station_id = %s, status = %s, "
            "last_state_changed_at = IF(%s = status, last_state_changed_at, NOW()), "
            "last_heartbeat_at = IF(%s IS NULL, NULL, last_heartbeat_at), "
            "last_seen_at = IF(%s IS NULL, NULL, last_seen_at), "
            "last_probe_ok = IF(%s IS NULL, NULL, last_probe_ok) WHERE id = %s",
            (to_line_id, to_station_id, next_status, next_status, to_line_id, to_line_id, to_line_id, device_id),
        )
        self.db.execute(
            "INSERT INTO lg_device_transfer (device_id, from_status, from_line_id, from_station_id, to_status, "
            "to_line_id, to_station_id, reason, note, operator) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (device_id, device["status"], device["line_id"], device["station_id"], next_status,
             to_line_id, to_station_id, reason, note, operator),
        )
        self.add_event(device_id, "transfer", "换线：" + from_text + " -> " + to_text, reason or note,
                       {"from": {"line": device["line_id"], "station": device["station_id"], "status": device["status"]},
                        "to": {"line": to_line_id, "station": to_station_id, "status": next_status}},
                       operator, to_line_id, to_station_id)
        return {"from": from_text, "to": to_text, "from_status": device["status"], "to_status": next_status}

    # ------------------------------------------------------- 换下状况补录
    def add_condition(self, device_id: int, data: dict, operator: str = "") -> int:
        device = self.get_device(device_id)
        cond_type = (data.get("condition") or "").strip()
        if not cond_type:
            raise AssetError("状况类型必填")
        result = data.get("result") or "pending"
        if result not in CONDITION_RESULTS:
            raise AssetError("处理结论取值非法")
        cond_id = self.db.execute(
            "INSERT INTO lg_device_condition (device_id, cond_type, symptom, root_cause, resolution, result, "
            "technician, repair_at, attachment, operator) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (device_id, cond_type, data.get("symptom", ""), data.get("root_cause", ""), data.get("resolution", ""),
             result, data.get("technician", ""), data.get("repair_at") or None, data.get("attachment") or None, operator),
        )
        self.add_event(device_id, "condition", "登记设备状况：" + cond_type,
                       data.get("symptom") or data.get("resolution") or "", data, operator, device["line_id"], device["station_id"])
        return cond_id

    # ------------------------------------------------------------ 新建
    DEVICE_FIELDS = ("asset_no", "hostname", "ip", "mac", "model", "os_version", "serial_no", "vendor",
                     "line_id", "station_id", "probe_mode", "probe_port", "probe_interval",
                     "location_note", "owner", "remark", "source")

    def create_device(self, data: dict, operator: str = "") -> dict:
        asset_no = (data.get("asset_no") or "").strip()
        hostname = (data.get("hostname") or "").strip()
        if not asset_no or not hostname:
            raise AssetError("资产编号与主机名必填")
        if self.db.one("SELECT id FROM lg_device WHERE asset_no = %s", (asset_no,)):
            raise AssetError("资产编号已存在：" + asset_no, 409)
        token = new_token()
        values = {k: data.get(k) for k in self.DEVICE_FIELDS}
        values["asset_no"], values["hostname"] = asset_no, hostname
        values["probe_mode"] = values["probe_mode"] or "heartbeat"
        values["probe_port"] = int(values["probe_port"] or 0)
        values["probe_interval"] = int(values["probe_interval"] or 60)
        values["source"] = values["source"] or "manual"
        for key, val in list(values.items()):
            if isinstance(val, str):
                values[key] = val.strip()
            elif val is None and key not in ("line_id", "station_id"):
                # 表里这些列是 NOT NULL DEFAULT ''，None 会被当成 NULL 写进去
                values[key] = 0 if key in ("probe_port", "probe_interval") else ""
        status = data.get("status") or ("offline" if not values["line_id"] else "online")
        # 公司归属：显式传入优先，否则用当前作用域的唯一公司，最后回落到 0（未归属）
        company_id = int(data.get("company_id") or self.default_company_id or 0)
        if self.company_ids is not None:
            if not self.company_ids:
                raise AssetError("当前账号没有可用的公司范围，无法新增设备。", 403)
            if company_id not in self.company_ids:
                company_id = self.company_ids[0]
        cols = list(values) + ["agent_token", "status", "company_id"]
        placeholders = ", ".join(["%s"] * len(cols))
        device_id = self.db.execute(
            "INSERT INTO lg_device (" + ", ".join(cols) + ") VALUES (" + placeholders + ")",
            tuple(values[k] for k in values) + (token, status, company_id),
        )
        self.add_event(device_id, "create", "设备入库", "资产编号 " + asset_no + "（来源：" + values["source"] + "）",
                       operator=operator, line_id=values["line_id"], station_id=values["station_id"])
        return {"id": device_id, "agent_token": token}

    def bulk_create_from_scan(self, candidates: list[dict], line_id: int | None = None,
                              station_id: int | None = None,
                              probe_mode: str = "hybrid", operator: str = "") -> dict:
        """把网段扫描勾选的候选主机批量加入台账（幂等：按 IP 去重）。"""
        created, skipped = [], []
        for cand in candidates:
            ip = (cand.get("ip") or "").strip()
            if not ip:
                continue
            exist = self.db.one("SELECT id, asset_no FROM lg_device WHERE ip = %s", (ip,))
            if exist:
                skipped.append({"ip": ip, "reason": "已存在：" + exist["asset_no"]})
                continue
            hostname = (cand.get("hostname") or "").strip() or "IPC-" + ip.replace(".", "-")
            base = (cand.get("asset_no") or "").strip() or "JG-" + ip.split(".")[-2] + "-" + ip.split(".")[-1]
            asset_no, n = base, 1
            while self.db.one("SELECT id FROM lg_device WHERE asset_no = %s", (asset_no,)):
                n += 1
                asset_no = base + "-" + str(n)
            res = self.create_device({
                "asset_no": asset_no, "hostname": hostname, "ip": ip, "mac": cand.get("mac", ""),
                "line_id": line_id, "station_id": station_id, "probe_mode": probe_mode,
                "probe_port": 445 if 445 in (cand.get("open_ports") or []) else 0,
                "probe_interval": 60, "source": "scan", "remark": cand.get("reason", ""),
            }, operator=operator)
            if not line_id:
                self.db.execute("UPDATE lg_device SET status = 'offline' WHERE id = %s", (res["id"],))
            created.append({"id": res["id"], "ip": ip, "asset_no": asset_no, "hostname": hostname})
        return {"created": created, "skipped": skipped}
