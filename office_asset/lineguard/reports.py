"""设备台账导入导出（CSV，可直接用 Excel 打开）。"""
from __future__ import annotations

import csv
import io

from .assets import AssetError, AssetService
from .db import Database

EXPORT_HEADERS = ["资产编号", "主机名", "IP地址", "型号", "操作系统", "序列号", "责任人", "状态",
                  "检测方式", "探测端口", "最近心跳", "CPU%", "内存%", "磁盘%", "车间", "产线", "工位"]

STATUS_LABELS = {"online": "在线", "offline": "离线", "fault": "故障", "maintenance": "检修中", "retired": "已下线"}
PROBE_LABELS = {"heartbeat": "心跳", "probe": "主动探测", "hybrid": "混合"}

IMPORT_MAP = {
    "资产编号": "asset_no", "设备编号": "asset_no",
    "主机名": "hostname", "计算机名": "hostname",
    "ip地址": "ip", "ip": "ip",
    "型号": "model", "操作系统": "os_version", "序列号": "serial_no",
    "mac地址": "mac", "mac": "mac", "厂商": "vendor",
    "车间": "workshop", "产线": "line", "工位": "station",
    "检测方式": "probe_mode", "探测端口": "probe_port", "检测端口": "probe_port",
    "责任人": "owner", "备注": "remark",
}

PROBE_VALUES = {"心跳": "heartbeat", "主动探测": "probe", "探测": "probe", "混合": "hybrid",
                "heartbeat": "heartbeat", "probe": "probe", "hybrid": "hybrid"}


def export_devices_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    buffer.write("\ufeff")  # BOM：让 Excel 正确识别 UTF-8
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_HEADERS)
    for row in rows:
        writer.writerow([
            row.get("asset_no", ""), row.get("hostname", ""), row.get("ip", ""), row.get("model", ""),
            row.get("os_version", ""), row.get("serial_no", ""), row.get("owner", ""),
            STATUS_LABELS.get(row.get("status", ""), row.get("status", "")),
            PROBE_LABELS.get(row.get("probe_mode", ""), row.get("probe_mode", "")),
            row.get("probe_port") or "", str(row.get("last_heartbeat_at") or ""),
            row.get("cpu_percent") if row.get("cpu_percent") is not None else "",
            row.get("mem_percent") if row.get("mem_percent") is not None else "",
            row.get("disk_percent") if row.get("disk_percent") is not None else "",
            row.get("workshop_name", ""), row.get("line_name", ""), row.get("station_name", ""),
        ])
    return buffer.getvalue()


def resolve_org(db: Database, workshop: str, line: str, station: str) -> tuple[int | None, int | None]:
    """按名称查找/创建车间-产线-工位，返回 (line_id, station_id)。"""
    workshop = (workshop or "").strip()
    line = (line or "").strip()
    station = (station or "").strip()
    if not workshop or not line:
        return None, None
    row = db.one("SELECT id FROM lg_workshop WHERE name = %s OR code = %s", (workshop, workshop))
    workshop_id = row["id"] if row else db.execute("INSERT INTO lg_workshop (code, name) VALUES (%s, %s)", (workshop, workshop))
    row = db.one("SELECT id FROM lg_line WHERE workshop_id = %s AND (name = %s OR code = %s)", (workshop_id, line, line))
    line_id = row["id"] if row else db.execute(
        "INSERT INTO lg_line (workshop_id, code, name) VALUES (%s, %s, %s)", (workshop_id, line, line))
    station_id = None
    if station:
        row = db.one("SELECT id FROM lg_station WHERE line_id = %s AND (name = %s OR code = %s)", (line_id, station, station))
        station_id = row["id"] if row else db.execute(
            "INSERT INTO lg_station (line_id, code, name) VALUES (%s, %s, %s)", (line_id, station, station))
    return line_id, station_id


def import_devices(db: Database, assets: AssetService, rows: list[dict], operator: str = "") -> dict:
    """rows 为已解析的字典列表（键为表格表头）。已存在的资产编号按更新处理。"""
    if not rows:
        raise AssetError("没有可导入的数据")
    created = updated = skipped = 0
    errors: list[str] = []
    for index, raw in enumerate(rows, start=2):
        mapped: dict[str, str] = {}
        for key, value in raw.items():
            target = IMPORT_MAP.get(str(key).strip().lower()) or IMPORT_MAP.get(str(key).strip())
            if target:
                mapped[target] = "" if value is None else str(value).strip()
        asset_no = mapped.get("asset_no", "")
        hostname = mapped.get("hostname", "")
        if not asset_no or not hostname:
            skipped += 1
            errors.append("第 %d 行：资产编号或主机名为空" % index)
            continue
        line_id, station_id = resolve_org(db, mapped.get("workshop", ""), mapped.get("line", ""), mapped.get("station", ""))
        probe_mode = PROBE_VALUES.get((mapped.get("probe_mode") or "").lower(), mapped.get("probe_mode") or "heartbeat")
        exist = db.one("SELECT id, line_id FROM lg_device WHERE asset_no = %s", (asset_no,))
        if exist:
            db.execute(
                "UPDATE lg_device SET hostname = %s, ip = %s, model = %s, os_version = %s, serial_no = %s, "
                "mac = %s, line_id = %s, station_id = %s, probe_mode = %s, probe_port = %s, owner = %s, remark = %s "
                "WHERE id = %s",
                (hostname, mapped.get("ip", ""), mapped.get("model", ""), mapped.get("os_version", ""),
                 mapped.get("serial_no", ""), mapped.get("mac", ""), line_id, station_id, probe_mode,
                 int(mapped.get("probe_port") or 0), mapped.get("owner", ""), mapped.get("remark", ""), exist["id"]),
            )
            if (exist.get("line_id") or None) != (line_id or None):
                assets.add_event(exist["id"], "transfer", "Excel 导入导致位置变更", "",
                                 {"to_line": line_id}, operator, line_id, station_id)
            updated += 1
        else:
            assets.create_device({
                "asset_no": asset_no, "hostname": hostname, "ip": mapped.get("ip", ""),
                "model": mapped.get("model", ""), "os_version": mapped.get("os_version", ""),
                "serial_no": mapped.get("serial_no", ""), "mac": mapped.get("mac", ""),
                "line_id": line_id, "station_id": station_id, "probe_mode": probe_mode,
                "probe_port": int(mapped.get("probe_port") or 0), "owner": mapped.get("owner", ""),
                "remark": mapped.get("remark", ""), "source": "import",
            }, operator=operator)
            created += 1
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors[:50]}
