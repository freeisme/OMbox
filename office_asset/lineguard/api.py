"""LineGuard HTTP 路由：挂载到 OMbox 的 /api/lineguard/*。

权限：模块 code = "lineguard"，动作 view / create / update / delete / export。
公司隔离：所有读写都带公司过滤，取值来自「全局公司切换」的 companyId 参数，
再与该账号的 org 作用域取交集（超管不受限）。
"""
from __future__ import annotations

import base64
import json
import threading

from ..xlsx import WorkbookError, read_upload_rows
from .assets import STATUS_LABELS, AssetError, AssetService, new_token
from .config import LineGuardConfig
from .db import LineGuardDb
from .monitor import Monitor
from .reports import export_devices_csv, import_devices
from .scanner import scan_network

MODULE = "lineguard"
ALLOWED_SETTINGS = {"alert_cpu", "alert_mem", "alert_disk", "notify_webhook", "big_screen_title"}


class LineGuardRouter:
    def __init__(
        self,
        db: LineGuardDb,
        scope,
        config: LineGuardConfig,
        api_error,
        conflict_error,
        forbidden_error,
        read_context,
        write_context,
        payload,
        monitor: Monitor | None = None,
    ) -> None:
        self.db = db
        self.scope = scope
        self.config = config
        self.api_error = api_error
        self.conflict_error = conflict_error
        self.forbidden_error = forbidden_error
        self._read_context = read_context
        self._write_context = write_context
        self._payload = payload
        self.monitor = monitor
        self._scan_lock = threading.Lock()

    # ------------------------------------------------------------ 公司作用域
    def _company_scope(self, context: dict, params: dict) -> tuple[list[int] | None, int]:
        """返回 (允许的公司列表 | None=不限, 默认公司)。"""
        requested = self.db_text_int((params.get("companyId") or ["0"])[0])
        allowed = self.scope.scoped_company_ids(context)
        if requested > 0:
            if allowed is not None and requested not in allowed:
                raise self.forbidden_error("无权查看该公司的工控机数据。")
            return [requested], requested
        if allowed is None:
            return None, 0
        ordered = sorted(allowed)
        return ordered, (ordered[0] if ordered else 0)

    @staticmethod
    def db_text_int(value: object) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return 0

    def _company_sql(self, alias: str, company_ids: list[int] | None) -> str:
        if company_ids is None:
            return ""
        if not company_ids:
            return " AND 1=0"
        return " AND " + alias + ".company_id IN (" + ",".join(str(c) for c in company_ids) + ")"

    def _assets(self, context: dict, params: dict) -> AssetService:
        company_ids, default_company = self._company_scope(context, params)
        return AssetService(self.db, company_ids, default_company)

    # ------------------------------------------------------------ 分发
    def dispatch(self, handler, path: str, method: str, params: dict) -> bool:
        if not path.startswith("/api/lineguard"):
            return False
        send_json = getattr(handler, "send_json")
        try:
            return self._dispatch(handler, path, method, params, send_json)
        except AssetError as exc:
            status = int(getattr(exc, "status", 400) or 400)
            message = str(exc)
            if status == 409:
                raise self.conflict_error(message) from exc
            if status == 403:
                raise self.forbidden_error(message) from exc
            if status == 404:
                raise self.api_error(message) from exc
            raise self.api_error(message) from exc
        except WorkbookError as exc:
            raise self.api_error(str(exc)) from exc

    def _dispatch(self, handler, path: str, method: str, params: dict, send_json) -> bool:
        base = "/api/lineguard"

        # ---- 心跳：免登录（仅校验设备令牌），必须放在鉴权之前 ----
        if path == base + "/heartbeat" and method == "POST":
            if self.monitor is None:
                raise self.api_error("探测服务未启动。")
            body = self._payload(handler)
            headers = getattr(handler, "headers", None)
            token = ""
            if headers is not None:
                token = str(headers.get("X-Agent-Token") or "").strip()
            token = token or str(body.get("token") or "").strip()
            device = None
            if token:
                device = self.db.one("SELECT * FROM lg_device WHERE agent_token = %s", (token,))
            if device is None and body.get("hostname"):
                device = self.db.one("SELECT * FROM lg_device WHERE hostname = %s", (body.get("hostname"),))
            if device is None:
                send_json({"ok": False, "error": "未登记的设备，请先加入台账"}, status=404)
                return True
            send_json(self.monitor.heartbeat(device, body))
            return True

        if path == base + "/meta" and method == "GET":
            self._read_context(handler, MODULE)
            send_json({
                "statuses": STATUS_LABELS,
                "offline_seconds": self.config.offline_seconds,
                "probe_interval_seconds": self.config.probe_interval_seconds,
                "probe_modes": {"heartbeat": "心跳", "probe": "主动探测", "hybrid": "混合"},
            })
            return True

        if path == base + "/options" and method == "GET":
            context = self._read_context(handler, MODULE)
            company_ids, _ = self._company_scope(context, params)
            workshops = self.db.query(
                "SELECT id, code, name, company_id FROM lg_workshop WHERE 1=1"
                + self._company_sql("lg_workshop", company_ids)
                + " ORDER BY sort_order, id"
            )
            allowed_ids = [str(int(w["id"])) for w in workshops]
            lines: list[dict] = []
            stations: list[dict] = []
            if allowed_ids:
                lines = self.db.query(
                    "SELECT id, workshop_id, code, name FROM lg_line WHERE workshop_id IN ("
                    + ",".join(allowed_ids) + ") ORDER BY sort_order, id"
                )
                line_ids = [str(int(item["id"])) for item in lines]
                if line_ids:
                    stations = self.db.query(
                        "SELECT id, line_id, code, name FROM lg_station WHERE line_id IN ("
                        + ",".join(line_ids) + ") ORDER BY sort_order, id"
                    )
            send_json({"workshops": workshops, "lines": lines, "stations": stations})
            return True

        if path == base + "/overview" and method == "GET":
            context = self._read_context(handler, MODULE)
            company_ids, _ = self._company_scope(context, params)
            clause = self._company_sql("d", company_ids)
            stats = {row["status"]: int(row["c"]) for row in self.db.query(
                "SELECT d.status, COUNT(*) AS c FROM lg_device d WHERE 1=1" + clause + " GROUP BY d.status")}
            total = sum(stats.values())
            active = total - stats.get("retired", 0)
            health = round(stats.get("online", 0) / active * 100, 1) if active else 100.0
            by_workshop = self.db.query(
                "SELECT w.id, w.name, d.status, COUNT(*) AS c FROM lg_device d "
                "JOIN lg_line l ON l.id = d.line_id JOIN lg_workshop w ON w.id = l.workshop_id "
                "WHERE 1=1" + clause + " GROUP BY w.id, w.name, d.status")
            grouped: dict[int, dict] = {}
            for row in by_workshop:
                item = grouped.setdefault(int(row["id"]), {"id": int(row["id"]), "name": row["name"], "stats": {}})
                item["stats"][row["status"]] = int(row["c"])
            alerts = self.db.query(
                "SELECT a.id, a.level, a.alert_type, a.message, a.created_at, d.asset_no, d.hostname "
                "FROM lg_alert a JOIN lg_device d ON d.id = a.device_id "
                "WHERE a.resolved_at IS NULL" + clause + " ORDER BY a.created_at DESC LIMIT 20")
            unassigned_row = self.db.one(
                "SELECT COUNT(*) AS c FROM lg_device d WHERE d.line_id IS NULL AND d.status <> 'retired'" + clause)
            send_json({
                "summary": {
                    "online": stats.get("online", 0), "offline": stats.get("offline", 0),
                    "fault": stats.get("fault", 0), "maintenance": stats.get("maintenance", 0),
                    "retired": stats.get("retired", 0), "total": total, "health": health,
                },
                "by_workshop": list(grouped.values()),
                "alerts": alerts,
                "unassigned": int(unassigned_row["c"]) if unassigned_row else 0,
            })
            return True

        if path == base + "/tree" and method == "GET":
            context = self._read_context(handler, MODULE)
            company_ids, _ = self._company_scope(context, params)
            workshops = self.db.query(
                "SELECT * FROM lg_workshop WHERE 1=1" + self._company_sql("lg_workshop", company_ids)
                + " ORDER BY sort_order, id")
            if not workshops:
                send_json({"workshops": []})
                return True
            workshop_ids = ",".join(str(int(w["id"])) for w in workshops)
            lines = self.db.query(
                "SELECT * FROM lg_line WHERE workshop_id IN (" + workshop_ids + ") ORDER BY sort_order, id")
            stations = self.db.query(
                "SELECT * FROM lg_station ORDER BY sort_order, id") if lines else []
            devices = self.db.query(
                "SELECT id, asset_no, hostname, status, ip, station_id, line_id FROM lg_device d WHERE 1=1"
                + self._company_sql("d", company_ids))
            out = []
            for workshop in workshops:
                workshop_lines = []
                for line in [item for item in lines if int(item["workshop_id"]) == int(workshop["id"])]:
                    line_devices = [d for d in devices if d["line_id"] and int(d["line_id"]) == int(line["id"])]
                    line_stations = []
                    for station in [s for s in stations if int(s["line_id"]) == int(line["id"])]:
                        line_stations.append({
                            **station,
                            "devices": [d for d in line_devices if d["station_id"] and int(d["station_id"]) == int(station["id"])],
                        })
                    stats: dict[str, int] = {}
                    for device in line_devices:
                        key = str(device["status"])
                        stats[key] = stats.get(key, 0) + 1
                    workshop_lines.append({
                        **line, "stations": line_stations,
                        "unassigned": [d for d in line_devices if not d["station_id"]],
                        "stats": stats, "device_count": len(line_devices),
                    })
                out.append({**workshop, "lines": workshop_lines})
            send_json({"workshops": out})
            return True

        if path == base + "/devices" and method == "GET":
            context = self._read_context(handler, MODULE)
            assets = self._assets(context, params)
            send_json(assets.list_devices(
                q=str((params.get("q") or [""])[0]),
                status=str((params.get("status") or [""])[0]),
                workshop_id=self.db_text_int((params.get("workshopId") or [""])[0]) or None,
                line_id=self.db_text_int((params.get("lineId") or [""])[0]) or None,
                page=self.db_text_int((params.get("page") or ["1"])[0]) or 1,
                size=self.db_text_int((params.get("size") or ["50"])[0]) or 50,
            ))
            return True

        if path == base + "/devices" and method == "POST":
            context = self._write_context(handler, MODULE, "create")
            assets = self._assets(context, params)
            send_json(assets.create_device(self._payload(handler), operator=str(context.get("username") or "")), status=201)
            return True

        if path == base + "/devices/bulk-create" and method == "POST":
            context = self._write_context(handler, MODULE, "create")
            assets = self._assets(context, params)
            body = self._payload(handler)
            send_json(assets.bulk_create_from_scan(
                body.get("candidates") or [],
                self.db_text_int(body.get("line_id")) or None,
                self.db_text_int(body.get("station_id")) or None,
                probe_mode=str(body.get("probe_mode") or "probe"),
                operator=str(context.get("username") or ""),
            ))
            return True

        if path.startswith(base + "/devices/"):
            parts = path.split("/")
            # /api/lineguard/devices/{id}[/{action}]
            if len(parts) >= 5 and parts[4].isdigit():
                device_id = int(parts[4])
                action = parts[5] if len(parts) > 5 else ""
                if not action and method == "GET":
                    context = self._read_context(handler, MODULE)
                    self._assets(context, params).get_device(device_id)
                    send_json(self._assets(context, params).device_detail(device_id))
                    return True
                if not action and method == "PUT":
                    context = self._write_context(handler, MODULE, "update")
                    assets = self._assets(context, params)
                    assets.get_device(device_id)
                    body = {k: v for k, v in self._payload(handler).items() if k in AssetService.DEVICE_FIELDS}
                    if not body:
                        send_json({"ok": True, "changed": []})
                        return True
                    cols = ", ".join(key + " = %s" for key in body)
                    self.db.execute("UPDATE lg_device SET " + cols + " WHERE id = %s",
                                    list(body.values()) + [device_id])
                    assets.add_event(device_id, "edit", "修改设备信息",
                                     "变更字段：" + "、".join(body), {"changed": list(body)},
                                     str(context.get("username") or ""))
                    send_json({"ok": True, "changed": list(body)})
                    return True
                if not action and method == "DELETE":
                    context = self._write_context(handler, MODULE, "delete")
                    self._assets(context, params).get_device(device_id)
                    self.db.execute("DELETE FROM lg_device WHERE id = %s", (device_id,))
                    send_json({"ok": True})
                    return True
                if action == "transfer" and method == "POST":
                    context = self._write_context(handler, MODULE, "update")
                    assets = self._assets(context, params)
                    body = self._payload(handler)
                    result = assets.transfer(
                        device_id,
                        self.db_text_int(body.get("to_line_id")) or None,
                        self.db_text_int(body.get("to_station_id")) or None,
                        to_status=body.get("status") or None,
                        reason=str(body.get("reason") or ""),
                        note=str(body.get("note") or ""),
                        operator=str(context.get("username") or ""),
                    )
                    if body.get("condition"):
                        assets.add_condition(device_id, body["condition"], str(context.get("username") or ""))
                    send_json({"ok": True, **result})
                    return True
                if action == "status" and method == "POST":
                    context = self._write_context(handler, MODULE, "update")
                    assets = self._assets(context, params)
                    body = self._payload(handler)
                    changed = assets.change_status(
                        device_id, str(body.get("status") or ""),
                        detail=str(body.get("detail") or ""), event_type="manual",
                        operator=str(context.get("username") or ""))
                    send_json({"ok": True, "changed": changed})
                    return True
                if action == "conditions" and method == "POST":
                    context = self._write_context(handler, MODULE, "update")
                    assets = self._assets(context, params)
                    send_json({"ok": True, "id": assets.add_condition(
                        device_id, self._payload(handler), str(context.get("username") or ""))})
                    return True
                if action == "token" and method == "POST":
                    context = self._write_context(handler, MODULE, "update")
                    self._assets(context, params).get_device(device_id)
                    token = new_token()
                    self.db.execute("UPDATE lg_device SET agent_token = %s WHERE id = %s", (token, device_id))
                    send_json({"agent_token": token})
                    return True

        if path == base + "/scan" and method == "POST":
            context = self._write_context(handler, MODULE, "create")
            company_ids, default_company = self._company_scope(context, params)
            body = self._payload(handler)
            cidr = str(body.get("cidr") or "").strip()
            if not cidr:
                raise self.api_error("请填写要扫描的网段，例如 192.168.10.0/24")
            if not self._scan_lock.acquire(blocking=False):
                raise self.conflict_error("已有扫描任务在运行，请稍后再试。")
            try:
                known = {str(row["ip"]): int(row["id"]) for row in self.db.query(
                    "SELECT id, ip FROM lg_device WHERE ip <> ''" + self._company_sql("lg_device", company_ids))}
                result = scan_network(cidr, self.config, known_ips=known, probe_ports=body.get("ports"))
                self.db.execute(
                    "INSERT INTO lg_scan_task (cidr, status, total_hosts, alive_hosts, operator, result, finished_at) "
                    "VALUES (%s, 'done', %s, %s, %s, %s, NOW())",
                    (cidr, result["total"], result["alive_count"], str(context.get("username") or ""),
                     json.dumps(result, ensure_ascii=False)),
                )
                result["defaultCompanyId"] = default_company
                send_json(result)
            finally:
                self._scan_lock.release()
            return True

        if path == base + "/alerts" and method == "GET":
            context = self._read_context(handler, MODULE)
            company_ids, _ = self._company_scope(context, params)
            rows = self.db.query(
                "SELECT a.*, d.asset_no, d.hostname FROM lg_alert a JOIN lg_device d ON d.id = a.device_id "
                "WHERE 1=1" + self._company_sql("d", company_ids)
                + " ORDER BY a.resolved_at IS NULL DESC, a.created_at DESC LIMIT 300")
            send_json({"alerts": rows})
            return True

        if path.startswith(base + "/alerts/") and path.endswith("/resolve") and method == "POST":
            context = self._write_context(handler, MODULE, "update")
            parts = path.split("/")
            if len(parts) >= 6 and parts[4].isdigit():
                self.db.execute("UPDATE lg_alert SET resolved_at = NOW() WHERE id = %s", (int(parts[4]),))
                send_json({"ok": True})
                return True

        if path == base + "/settings" and method == "GET":
            self._read_context(handler, MODULE)
            send_json({"settings": self.db.settings_all(), "allowed": sorted(ALLOWED_SETTINGS)})
            return True

        if path == base + "/settings" and method == "PUT":
            self._write_context(handler, MODULE, "update")
            for key, value in (self._payload(handler) or {}).items():
                if key in ALLOWED_SETTINGS:
                    self.db.set_setting(str(key), str(value))
            send_json({"ok": True, "settings": self.db.settings_all()})
            return True

        if path == base + "/reports/export" and method == "GET":
            context = self._read_context(handler, MODULE, "export")
            company_ids, _ = self._company_scope(context, params)
            rows = self.db.query(
                "SELECT d.asset_no, d.hostname, d.ip, d.model, d.os_version, d.serial_no, d.owner, d.status, "
                "d.probe_mode, d.probe_port, d.last_heartbeat_at, d.cpu_percent, d.mem_percent, d.disk_percent, "
                "w.name AS workshop_name, l.name AS line_name, s.name AS station_name FROM lg_device d "
                "LEFT JOIN lg_line l ON l.id = d.line_id LEFT JOIN lg_workshop w ON w.id = l.workshop_id "
                "LEFT JOIN lg_station s ON s.id = d.station_id WHERE 1=1"
                + self._company_sql("d", company_ids)
                + " ORDER BY w.name, l.name, d.asset_no")
            send_json({"fileName": "工控机台账.csv", "content": export_devices_csv(rows), "count": len(rows)})
            return True

        if path == base + "/reports/import" and method == "POST":
            context = self._write_context(handler, MODULE, "create")
            assets = self._assets(context, params)
            body = self._payload(handler)
            file_name = str(body.get("fileName") or "")
            content = str(body.get("contentBase64") or "")
            if not content:
                raise self.api_error("请选择要导入的 Excel/CSV 文件。")
            try:
                raw = base64.b64decode(content)
            except Exception as exc:  # noqa: BLE001 - 统一转成可读错误
                raise self.api_error("文件内容无法解析，请重新选择。") from exc
            sheet = read_upload_rows(file_name, raw)
            if len(sheet) < 2:
                raise self.api_error("表格里没有数据行。")
            header = [str(cell or "").strip() for cell in sheet[0]]
            records = []
            for line in sheet[1:]:
                if not any(str(cell or "").strip() for cell in line):
                    continue
                records.append({header[i]: (line[i] if i < len(line) else "") for i in range(len(header))})
            sheet_headers = {name: name for name in header if name}
            if body.get("dryRun"):
                send_json({
                    "fileName": file_name,
                    "sheetHeaders": sheet_headers,
                    "totalRows": len(records),
                    "created": 0, "updated": 0, "skipped": 0,
                    "errors": [], "errorCount": 0,
                    "warnings": [{"row": 0, "code": "preview",
                                  "message": "将导入 %d 行，识别列：%s" % (len(records), "、".join(header))}],
                    "warningCount": 1,
                    "dryRun": True,
                })
                return True
            result = import_devices(self.db, assets, records, str(context.get("username") or ""))
            messages = [str(item) for item in (result.get("errors") or [])]
            send_json({
                "fileName": file_name,
                "sheetHeaders": sheet_headers,
                "totalRows": len(records),
                "created": int(result.get("created", 0)),
                "updated": int(result.get("updated", 0)),
                "skipped": int(result.get("skipped", 0)),
                "errors": [{"row": 0, "code": "import", "message": text} for text in messages],
                "errorCount": len(messages),
                "dryRun": False,
            })
            return True

        if path == base + "/workshops" and method == "POST":
            context = self._write_context(handler, MODULE, "create")
            company_ids, default_company = self._company_scope(context, params)
            body = self._payload(handler)
            if not body.get("code") or not body.get("name"):
                raise self.api_error("车间编码与名称必填。")
            company_id = self.db_text_int(body.get("company_id")) or default_company
            if company_ids is not None and company_id not in company_ids:
                raise self.forbidden_error("无权在该公司下新增车间。")
            new_id = self.db.execute(
                "INSERT INTO lg_workshop (code, name, description, company_id) VALUES (%s, %s, %s, %s)",
                (body["code"], body["name"], body.get("description", ""), company_id))
            send_json({"id": new_id}, status=201)
            return True

        if path == base + "/lines" and method == "POST":
            context = self._write_context(handler, MODULE, "create")
            body = self._payload(handler)
            if not body.get("workshop_id") or not body.get("code") or not body.get("name"):
                raise self.api_error("产线所属车间、编码与名称必填。")
            new_id = self.db.execute(
                "INSERT INTO lg_line (workshop_id, code, name) VALUES (%s, %s, %s)",
                (self.db_text_int(body["workshop_id"]), body["code"], body["name"]))
            send_json({"id": new_id}, status=201)
            return True

        if path == base + "/stations" and method == "POST":
            context = self._write_context(handler, MODULE, "create")
            body = self._payload(handler)
            if not body.get("line_id") or not body.get("code") or not body.get("name"):
                raise self.api_error("工位所属产线、编码与名称必填。")
            new_id = self.db.execute(
                "INSERT INTO lg_station (line_id, code, name) VALUES (%s, %s, %s)",
                (self.db_text_int(body["line_id"]), body["code"], body["name"]))
            send_json({"id": new_id}, status=201)
            return True

        raise self.api_error("工控机接口不存在：%s %s" % (method, path))
