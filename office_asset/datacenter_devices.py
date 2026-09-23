"""机房管理：网络设备 / 服务器台账。

这张台账独立于办公终端（`computer_asset`）与 IT 物资（`it_inventory_model`）：
机柜视图的"未上架设备"只从这里取。设备状态由机房管理维护：

* `stock`（未上架）：可被上架；
* `installed`（上架）：由机柜视图的上架操作写入，不能在台账里手工设置；
* `repair`（维修）：仍在机柜里占位，但标记为故障维修；
* `scrapped`（报废）：不再使用，不能上架。

上架/下架会同步 `site_id`、`rack_id` 与状态，保证台账与机柜视图一致。
"""

from __future__ import annotations

import base64
import csv
import io
import re
from dataclasses import dataclass

from .scope import OrganizationScopeService
from .sql import SqlGateway
from .xlsx import WorkbookError, read_sheet


STATUSES = {"stock", "installed", "repair", "scrapped"}
CATEGORIES = {
    "server",
    "network",
    "patch-panel",
    "power",
    "storage",
    "kvm",
    "av-media",
    "cooling",
    "shelf",
    "blank",
    "cable-management",
    "other",
}
CODE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{2,64}$")


def normalise_key(value: str) -> str:
    """Normalise a header or enum label for alias lookups (case/space/punctuation free)."""
    return re.sub(r"[\s_\-/（）()]", "", (value or "").strip().lower())

# 上传文件里允许的表头写法（大小写与空格会被忽略）
HEADER_ALIASES: dict[str, set[str]] = {
    "code": {"设备编号", "编号", "设备编码", "资产编号", "设备代码", "devicecode", "code", "assetno"},
    "name": {"设备名称", "名称", "设备名", "devicename", "name"},
    "brandModel": {"品牌型号", "型号", "品牌及型号", "品牌/型号", "brandmodel", "model", "型号规格"},
    "category": {"设备类型", "类型", "类型名称", "category", "type"},
    "uHeight": {"占用高度", "u高", "高度", "占用u位", "uheight", "uheight(u)", "高度u", "尺寸u"},
    "serialNumber": {"sn", "sn/st", "序列号", "serial", "serialnumber", "序列号st", "设备序列号"},
    "assetCode": {"固资编码", "固定资产编号", "资产编码", "固资编号", "assetcode", "固定资产编码"},
    "ownerLabel": {"使用人", "责任人", "负责人", "使用人/责任人", "owner", "ownerlabel", "保管人"},
    "purpose": {"用途", "设备用途", "用途说明", "功能", "purpose", "usage"},
    "remoteAccess": {
        "远程访问地址",
        "远程地址",
        "访问地址",
        "管理地址",
        "管理IP",
        "ip",
        "remoteaccess",
        "remote",
    },
    "cpu": {"cpu", "处理器", "cpu型号"},
    "memory": {"内存", "内存容量", "memory", "ram"},
    "disk": {"硬盘", "硬盘容量", "磁盘", "存储", "disk", "storage"},
    "status": {"状态", "设备状态", "使用状态", "status"},
    "notes": {"备注", "说明", "描述", "notes", "remark", "remarks"},
}

_CATEGORY_LABELS: dict[str, str] = {
    "服务器": "server",
    "server": "server",
    "网络": "network",
    "网络设备": "network",
    "交换机": "network",
    "路由器": "network",
    "路由": "network",
    "防火墙": "network",
    "network": "network",
    "配线架": "patch-panel",
    "配线": "patch-panel",
    "patch-panel": "patch-panel",
    "供电": "power",
    "电源": "power",
    "ups": "power",
    "pdu": "power",
    "power": "power",
    "存储": "storage",
    "nas": "storage",
    "storage": "storage",
    "kvm": "kvm",
    "音视频": "av-media",
    "av": "av-media",
    "散热": "cooling",
    "风扇": "cooling",
    "cooling": "cooling",
    "层板": "shelf",
    "shelf": "shelf",
    "挡板": "blank",
    "blank": "blank",
    "理线": "cable-management",
    "理线器": "cable-management",
    "其他": "other",
    "未知": "other",
    "other": "other",
}

_STATUS_LABELS: dict[str, str] = {
    "未上架": "stock",
    "在库": "stock",
    "库存": "stock",
    "待上架": "stock",
    "未安装": "stock",
    "stock": "stock",
    "上架": "installed",
    "已上架": "installed",
    "安装": "installed",
    "installed": "installed",
    "维修": "repair",
    "维修中": "repair",
    "故障": "repair",
    "repair": "repair",
    "报废": "scrapped",
    "已报废": "scrapped",
    "scrapped": "scrapped",
}

CATEGORY_ALIASES: dict[str, str] = {normalise_key(key): value for key, value in _CATEGORY_LABELS.items()}
STATUS_ALIASES: dict[str, str] = {normalise_key(key): value for key, value in _STATUS_LABELS.items()}

MAX_IMPORT_ROWS = 1000
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


@dataclass
class DatacenterDeviceService:
    db: SqlGateway
    scope: OrganizationScopeService
    api_error: type[Exception]
    conflict_error: type[Exception]
    forbidden_error: type[Exception]

    def _actor_id(self, context: dict) -> int:
        return self.db.integer(context.get("id"), 0)

    def _actor_name(self, context: dict) -> str:
        return self.db.text(context.get("username")) or "web"

    def _last_int(self, output: str, default: int = 0) -> int:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return self.db.integer(lines[-1] if lines else default, default)

    def _audit_sql(
        self,
        action: str,
        entity_type: str,
        entity_id_sql: str,
        entity_name: str,
        summary: str,
        context: dict,
        old_value: dict | None = None,
        new_value: dict | None = None,
    ) -> str:
        return f"""
        INSERT INTO audit_log (
          action_type, entity_type, entity_id, entity_name,
          old_value, new_value, summary, actor, source
        )
        VALUES (
          {self.db.quote(action)},
          {self.db.quote(entity_type)},
          {entity_id_sql},
          {self.db.quote(entity_name)},
          {self.db.json_value(old_value or {})},
          {self.db.json_value(new_value or {})},
          {self.db.quote(summary[:500])},
          {self.db.quote(self._actor_name(context))},
          'api'
        )
        """

    def _validate(self, payload: dict, context: dict, current: dict | None = None) -> dict:
        current = current or {}
        code = self.db.text(payload.get("code", current.get("code")))
        if not CODE_PATTERN.match(code):
            raise self.api_error("设备编号只能使用字母、数字、点、下划线、冒号和短横线，长度 2-64。")
        name = self.db.text(payload.get("name", current.get("name")))[:128]
        if not name:
            raise self.api_error("设备名称不能为空。")
        category = self._normalise_category(payload.get("category", current.get("category")))
        status = self.db.text(payload.get("status", current.get("status"))) or "stock"
        if status not in STATUSES:
            raise self.api_error("设备状态无效。")
        if status == "installed":
            raise self.api_error("“上架”状态由机柜视图的上架操作设置，不能在这里手工选择。")
        u_height = self.db.integer(payload.get("uHeight", current.get("uHeight")), 1)
        if u_height < 1 or u_height > 50:
            raise self.api_error("占用高度必须在 1-50U 之间。")
        catalog_id = self.db.integer(payload.get("catalogId", current.get("catalogId")), 0)
        if catalog_id > 0:
            exists = self.db.scalar(
                f"SELECT COUNT(*) FROM device_type_catalog WHERE catalog_id = {catalog_id} AND is_active = 1;"
            )
            if exists <= 0:
                raise self.api_error("型号库里的型号不存在。")
        org_id = self.db.integer(payload.get("orgId", current.get("orgId")), 0)
        if org_id > 0:
            self.scope.assert_org_access(context, org_id)
        return {
            "code": code,
            "name": name,
            "catalogId": catalog_id,
            "brandModel": self.db.text(payload.get("brandModel", current.get("brandModel")))[:160],
            "category": category,
            "uHeight": u_height,
            "serialNumber": self.db.text(payload.get("serialNumber", current.get("serialNumber")))[:128],
            "assetCode": self.db.text(payload.get("assetCode", current.get("assetCode")))[:128],
            "ownerLabel": self.db.text(payload.get("ownerLabel", current.get("ownerLabel")))[:128],
            "purpose": self.db.text(payload.get("purpose", current.get("purpose")))[:160],
            "remoteAccess": self.db.text(payload.get("remoteAccess", current.get("remoteAccess")))[:255],
            "cpu": self.db.text(payload.get("cpu", current.get("cpu")))[:64],
            "memory": self.db.text(payload.get("memory", current.get("memory")))[:64],
            "disk": self.db.text(payload.get("disk", current.get("disk")))[:64],
            "status": status,
            "orgId": org_id,
            "notes": self.db.text(payload.get("notes", current.get("notes")))[:500],
        }

    def _normalise_category(self, value: object) -> str:
        """设备类型不再限枚举：已知中文名/枚举值归一化，其余按原文保留（最多 64 字符）。"""
        raw = self.db.text(value)
        if not raw:
            return "other"
        mapped = CATEGORY_ALIASES.get(normalise_key(raw))
        if mapped:
            return mapped
        if len(raw) > 64:
            raise self.api_error("设备类型最多 64 个字符。")
        return raw

    def _placement_of(self, device_id: int) -> dict | None:
        return self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'placementId', CAST(placement.placement_id AS CHAR),
              'rackName', rack.rack_name,
              'siteName', site.site_name,
              'positionU', placement.position_u
            )
            FROM rack_device_placement placement
            JOIN asset_rack rack ON rack.rack_id = placement.rack_id
            JOIN asset_site site ON site.site_id = rack.site_id
            WHERE placement.datacenter_device_id = {device_id}
              AND placement.is_active = 1
            LIMIT 1
            """,
            None,
        )

    def list_devices(self, context: dict, params: dict[str, list[str]] | None = None) -> list[dict]:
        params = params or {}
        status = self.db.text(params.get("status", [""])[0])
        keyword = self.db.text(params.get("keyword", [""])[0])[:64]
        site_id = self.db.integer(params.get("siteId", [""])[0], 0)
        filters = ["device.is_active = 1"]
        if status in STATUSES:
            filters.append(f"device.status = {self.db.quote(status)}")
        if site_id > 0:
            filters.append(f"(device.site_id = {site_id} OR device.site_id IS NULL)")
        if keyword:
            keyword_sql = self.db.quote(f"%{keyword}%")
            filters.append(
                f"(device.device_name LIKE {keyword_sql} OR device.device_code LIKE {keyword_sql} "
                f"OR device.brand_model LIKE {keyword_sql} OR device.serial_number LIKE {keyword_sql})"
            )
        allowed = self.scope.permitted_org_ids(context)
        if allowed is not None:
            if not allowed:
                return []
            allowed_sql = ", ".join(str(value) for value in sorted(allowed))
            filters.append(f"(device.org_unit_id IS NULL OR device.org_unit_id IN ({allowed_sql}))")
        return list(
            self.db.json(
                f"""
                SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
                  'id', CAST(device.device_id AS CHAR),
                  'code', device.device_code,
                  'name', device.device_name,
                  'catalogId', COALESCE(CAST(device.catalog_id AS CHAR), ''),
                  'catalogSlug', COALESCE(catalog.slug, ''),
                  'brandModel', device.brand_model,
                  'category', device.category,
                  'uHeight', device.u_height,
                  'serialNumber', device.serial_number,
                  'assetCode', device.asset_code,
                  'ownerLabel', device.owner_label,
                  'purpose', device.purpose,
                  'remoteAccess', device.remote_access,
                  'cpu', device.cpu,
                  'memory', device.memory,
                  'disk', device.disk,
                  'status', device.status,
                  'siteId', COALESCE(CAST(device.site_id AS CHAR), ''),
                  'siteName', COALESCE(site.site_name, ''),
                  'rackId', COALESCE(CAST(device.rack_id AS CHAR), ''),
                  'rackName', COALESCE(rack.rack_name, ''),
                  'notes', device.notes
                )), JSON_ARRAY())
                FROM (
                  SELECT device.*
                  FROM datacenter_device device
                  LEFT JOIN device_type_catalog catalog ON catalog.catalog_id = device.catalog_id
                  LEFT JOIN asset_site site ON site.site_id = device.site_id
                  LEFT JOIN asset_rack rack ON rack.rack_id = device.rack_id
                  WHERE {' AND '.join(filters)}
                  ORDER BY device.status, device.device_code
                  LIMIT 500
                ) device
                LEFT JOIN device_type_catalog catalog ON catalog.catalog_id = device.catalog_id
                LEFT JOIN asset_site site ON site.site_id = device.site_id
                LEFT JOIN asset_rack rack ON rack.rack_id = device.rack_id
                """,
                [],
            )
            or []
        )

    def create_device(self, payload: dict, context: dict) -> dict:
        fields = self._validate(payload, context)
        actor_id = self._actor_id(context)
        catalog_sql = str(fields["catalogId"]) if fields["catalogId"] > 0 else "NULL"
        org_sql = str(fields["orgId"]) if fields["orgId"] > 0 else "NULL"
        device_id = self._last_int(
            self.db.execute(
                f"""
            INSERT INTO datacenter_device (
              device_code, device_name, catalog_id, brand_model, category, u_height,
              serial_number, asset_code, owner_label, purpose, remote_access, cpu, memory, disk,
              status, org_unit_id, notes,
              created_by, updated_by
            )
            VALUES (
              {self.db.quote(fields['code'])},
              {self.db.quote(fields['name'])},
              {catalog_sql},
              {self.db.quote(fields['brandModel'])},
              {self.db.quote(fields['category'])},
              {fields['uHeight']},
              {self.db.quote(fields['serialNumber'])},
              {self.db.quote(fields['assetCode'])},
              {self.db.quote(fields['ownerLabel'])},
              {self.db.quote(fields['purpose'])},
              {self.db.quote(fields['remoteAccess'])},
              {self.db.quote(fields['cpu'])},
              {self.db.quote(fields['memory'])},
              {self.db.quote(fields['disk'])},
              {self.db.quote(fields['status'])},
              {org_sql},
              {self.db.quote(fields['notes'])},
              {actor_id if actor_id > 0 else 'NULL'},
              {actor_id if actor_id > 0 else 'NULL'}
            );
            SELECT LAST_INSERT_ID();
            """
            )
        )
        if device_id <= 0:
            raise self.conflict_error("设备编号已存在。")
        self.db.execute(
            self._audit_sql(
                "datacenter_device_created",
                "datacenter_device",
                str(device_id),
                fields["name"],
                f"新增机房设备：{fields['code']} {fields['name']}",
                context,
                None,
                fields,
            )
            + ";"
        )
        return {"id": str(device_id), "code": fields["code"], "status": fields["status"]}

    def update_device(self, device_id: object, payload: dict, context: dict) -> dict:
        device_id_int = self.db.integer(device_id, 0)
        current = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(device_id AS CHAR),
              'code', device_code,
              'name', device_name,
              'catalogId', COALESCE(CAST(catalog_id AS CHAR), ''),
              'brandModel', brand_model,
              'category', category,
              'uHeight', u_height,
              'serialNumber', serial_number,
              'assetCode', asset_code,
              'ownerLabel', owner_label,
              'purpose', purpose,
              'remoteAccess', remote_access,
              'cpu', cpu,
              'memory', memory,
              'disk', disk,
              'status', status,
              'orgId', COALESCE(CAST(org_unit_id AS CHAR), ''),
              'notes', notes
            )
            FROM datacenter_device
            WHERE device_id = {device_id_int} AND is_active = 1
            """,
            None,
        )
        if not current:
            raise self.api_error("机房设备不存在或已删除。")
        placement = self._placement_of(device_id_int)
        fields = self._validate(payload, context, current)
        if self.db.text(current.get("status")) == "installed" and fields["status"] == "stock":
            raise self.conflict_error("设备当前是「上架」状态，请先在机柜视图下架再改回未上架。")
        if placement and fields["status"] == "stock":
            raise self.conflict_error(
                f"设备已上架在 {self.db.text(placement.get('siteName'))}/{self.db.text(placement.get('rackName'))}，"
                "请先在机柜视图下架再改回未上架。"
            )
        actor_id = self._actor_id(context)
        catalog_sql = str(fields["catalogId"]) if fields["catalogId"] > 0 else "NULL"
        org_sql = str(fields["orgId"]) if fields["orgId"] > 0 else "NULL"
        self.db.execute(
            f"""
            UPDATE datacenter_device
            SET device_code = {self.db.quote(fields['code'])},
                device_name = {self.db.quote(fields['name'])},
                catalog_id = {catalog_sql},
                brand_model = {self.db.quote(fields['brandModel'])},
                category = {self.db.quote(fields['category'])},
                u_height = {fields['uHeight']},
                serial_number = {self.db.quote(fields['serialNumber'])},
                asset_code = {self.db.quote(fields['assetCode'])},
                owner_label = {self.db.quote(fields['ownerLabel'])},
                purpose = {self.db.quote(fields['purpose'])},
                remote_access = {self.db.quote(fields['remoteAccess'])},
                cpu = {self.db.quote(fields['cpu'])},
                memory = {self.db.quote(fields['memory'])},
                disk = {self.db.quote(fields['disk'])},
                status = {self.db.quote(fields['status'])},
                org_unit_id = {org_sql},
                notes = {self.db.quote(fields['notes'])},
                updated_by = {actor_id if actor_id > 0 else 'NULL'}
            WHERE device_id = {device_id_int};
            """
        )
        self.db.execute(
            self._audit_sql(
                "datacenter_device_updated",
                "datacenter_device",
                str(device_id_int),
                fields["name"],
                f"更新机房设备：{fields['code']} {fields['name']}"
                + (f"（状态 {current.get('status')} → {fields['status']}）" if current.get("status") != fields["status"] else ""),
                context,
                current,
                fields,
            )
            + ";"
        )
        return {"id": str(device_id_int), **fields}

    def remove_device(self, device_id: object, payload: dict, context: dict) -> dict:
        device_id_int = self.db.integer(device_id, 0)
        current = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(device_id AS CHAR),
              'code', device_code,
              'name', device_name,
              'status', status
            )
            FROM datacenter_device
            WHERE device_id = {device_id_int} AND is_active = 1
            """,
            None,
        )
        if not current:
            raise self.api_error("机房设备不存在或已删除。")
        placement = self._placement_of(device_id_int)
        if placement:
            raise self.conflict_error("设备仍在机柜里，请先在机柜视图下架。")
        reason = self.db.text(payload.get("reason"))[:255]
        self.db.execute(
            f"""
            UPDATE datacenter_device
            SET is_active = 0
            WHERE device_id = {device_id_int};
            """
        )
        self.db.execute(
            self._audit_sql(
                "datacenter_device_removed",
                "datacenter_device",
                str(device_id_int),
                self.db.text(current.get("name")),
                f"删除机房设备：{self.db.text(current.get('code'))} {self.db.text(current.get('name'))}"
                + (f"，原因：{reason}" if reason else ""),
                context,
                current,
                {"isActive": False, "reason": reason},
            )
            + ";"
        )
        return {"id": str(device_id_int), "removed": True}

    # ------------------------------------------------------------------ xlsx 导入

    @staticmethod
    def _normalise_header(value: str) -> str:
        return normalise_key(value)

    def _read_upload(self, file_name: str, data: bytes) -> list[list[str]]:
        if len(data) > MAX_UPLOAD_BYTES:
            raise self.api_error(f"文件过大（上限 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB）。")
        lower = file_name.lower()
        if lower.endswith(".csv"):
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                try:
                    text = data.decode("gbk")
                except UnicodeDecodeError as exc:
                    raise self.api_error("CSV 编码无法识别，请另存为 UTF-8 或 xlsx。") from exc
            return [list(row) for row in csv.reader(io.StringIO(text))]
        if lower.endswith((".xlsx", ".xlsm")):
            try:
                return read_sheet(data)
            except WorkbookError as exc:
                raise self.api_error(str(exc)) from exc
        raise self.api_error("只支持 .xlsx、.xlsm 或 .csv 文件。")

    def _map_headers(self, header_row: list[str]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for index, raw in enumerate(header_row):
            key = self._normalise_header(raw)
            if not key:
                continue
            for field, aliases in HEADER_ALIASES.items():
                if field in mapping:
                    continue
                if key in {self._normalise_header(alias) for alias in aliases}:
                    mapping[field] = index
                    break
        return mapping

    @staticmethod
    def _cell(row: list[str], index: int | None) -> str:
        if index is None or index >= len(row):
            return ""
        return (row[index] or "").strip()

    def _row_to_payload(self, row: list[str], mapping: dict[str, int]) -> tuple[dict, list[str]]:
        problems: list[str] = []
        payload = {
            "code": self._cell(row, mapping.get("code")),
            "name": self._cell(row, mapping.get("name")),
            "brandModel": self._cell(row, mapping.get("brandModel")),
            "serialNumber": self._cell(row, mapping.get("serialNumber")),
            "assetCode": self._cell(row, mapping.get("assetCode")),
            "ownerLabel": self._cell(row, mapping.get("ownerLabel")),
            "purpose": self._cell(row, mapping.get("purpose")),
            "remoteAccess": self._cell(row, mapping.get("remoteAccess")),
            "cpu": self._cell(row, mapping.get("cpu")),
            "memory": self._cell(row, mapping.get("memory")),
            "disk": self._cell(row, mapping.get("disk")),
            "notes": self._cell(row, mapping.get("notes")),
        }
        category_raw = self._cell(row, mapping.get("category"))
        if category_raw:
            if len(category_raw) > 64:
                problems.append("设备类型最多 64 个字符")
            else:
                # 已知中文名/枚举值归一化成标准值，其余（如「光模块」）按原文保留
                payload["category"] = self._normalise_category(category_raw)
        height_raw = self._cell(row, mapping.get("uHeight"))
        if height_raw:
            match = re.search(r"\d+(?:\.\d+)?", height_raw)
            if not match:
                problems.append(f"占用高度「{height_raw}」不是数字")
            else:
                value = int(round(float(match.group(0))))
                if value < 1 or value > 50:
                    problems.append(f"占用高度 {value}U 超出 1-50U")
                else:
                    payload["uHeight"] = value
        status_raw = self._cell(row, mapping.get("status"))
        if status_raw:
            status = STATUS_ALIASES.get(self._normalise_header(status_raw))
            if not status:
                problems.append(f"状态「{status_raw}」无法识别（可用：未上架/维修/报废）")
            elif status == "installed":
                problems.append("状态不能是「上架」，该状态由机柜视图的上架操作写入")
            else:
                payload["status"] = status
        if not payload["code"]:
            problems.append("缺少设备编号")
        if not payload["name"]:
            problems.append("缺少设备名称")
        return payload, problems

    def import_workbook(self, payload: dict, context: dict) -> dict:
        file_name = self.db.text(payload.get("fileName"))[:200]
        content = self.db.text(payload.get("contentBase64"))
        if not content:
            raise self.api_error("请上传 .xlsx 或 .csv 文件。")
        try:
            data = base64.b64decode(content, validate=True)
        except (ValueError, TypeError) as exc:
            raise self.api_error("文件内容不是合法的 base64 编码。") from exc

        rows = self._read_upload(file_name, data)
        if not rows:
            raise self.api_error("文件里没有可读取的内容。")

        header_index = 0
        mapping: dict[str, int] = {}
        for index, row in enumerate(rows[:10]):
            candidate = self._map_headers(row)
            if len(candidate) >= 2:
                header_index = index
                mapping = candidate
                break
        if not mapping:
            raise self.api_error(
                "没有识别到表头。请至少包含「设备编号」和「设备名称」两列，"
                "可选：品牌型号、设备类型、占用高度、SN/ST、固资编码、使用人、用途、"
                "远程访问地址、CPU、内存、硬盘、状态、备注。"
            )
        if "code" not in mapping or "name" not in mapping:
            raise self.api_error("表头必须包含「设备编号」与「设备名称」两列。")

        dry_run = bool(payload.get("dryRun"))
        mode = self.db.text(payload.get("mode")) or "skip"
        if mode not in {"skip", "update"}:
            raise self.api_error("重复设备的处理方式只支持 skip（跳过）或 update（覆盖）。")

        data_rows = [row for row in rows[header_index + 1 :] if any((cell or "").strip() for cell in row)]
        if len(data_rows) > MAX_IMPORT_ROWS:
            raise self.api_error(f"一次最多导入 {MAX_IMPORT_ROWS} 行，请拆分文件。")
        if not data_rows:
            raise self.api_error("表头下面没有数据行。")

        prepared: list[dict] = []
        errors: list[dict] = []
        seen: dict[str, int] = {}
        for offset, row in enumerate(data_rows):
            excel_row = header_index + offset + 2
            record, problems = self._row_to_payload(row, mapping)
            code = record.get("code", "")
            if code and code in seen:
                problems.append(f"设备编号与第 {seen[code]} 行重复")
            if problems:
                errors.append({"row": excel_row, "code": code, "message": "；".join(problems)})
                continue
            seen[code] = excel_row
            prepared.append(record)

        existing: dict[str, dict] = {}
        if prepared:
            codes = ", ".join(self.db.quote(item["code"]) for item in prepared)
            rows_existing = list(
                self.db.json(
                    f"""
                    SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
                      'id', CAST(device_id AS CHAR),
                      'code', device_code,
                      'status', status,
                      'name', device_name,
                      'brandModel', brand_model,
                      'category', category,
                      'uHeight', u_height,
                      'serialNumber', serial_number,
                      'assetCode', asset_code,
                      'ownerLabel', owner_label,
                      'purpose', purpose,
                      'remoteAccess', remote_access,
                      'cpu', cpu,
                      'memory', memory,
                      'disk', disk,
                      'notes', notes
                    )), JSON_ARRAY())
                    FROM datacenter_device
                    WHERE device_code IN ({codes})
                    """,
                    [],
                )
                or []
            )
            existing = {self.db.text(item.get("code")): item for item in rows_existing}

        summary = {
            "fileName": file_name,
            "sheetHeaders": {
                field: (rows[header_index][index] if index < len(rows[header_index]) else "")
                for field, index in sorted(mapping.items(), key=lambda item: item[1])
            },
            "totalRows": len(data_rows),
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": errors[:50],
            "errorCount": len(errors),
            "dryRun": dry_run,
        }
        if dry_run:
            for record in prepared:
                if record["code"] in existing:
                    summary["updated" if mode == "update" else "skipped"] += 1
                else:
                    summary["created"] += 1
            return summary

        for record in prepared:
            current = existing.get(record["code"])
            try:
                if current:
                    if mode == "skip":
                        summary["skipped"] += 1
                        continue
                    merged = {**current, **{k: v for k, v in record.items() if v not in ("", None)}}
                    merged["code"] = record["code"]
                    self.update_device(current["id"], merged, context)
                    summary["updated"] += 1
                else:
                    self.create_device(record, context)
                    summary["created"] += 1
            except Exception as exc:  # 逐行容错，导入结果里能看到具体原因
                summary["errors"].append({"row": seen.get(record["code"], 0), "code": record["code"], "message": str(exc)})
                summary["errorCount"] += 1

        self.db.execute(
            self._audit_sql(
                "datacenter_device_imported",
                "datacenter_device",
                "'batch'",
                file_name or "批量导入",
                f"导入机房设备：{file_name}（新增 {summary['created']}，更新 {summary['updated']}，"
                f"跳过 {summary['skipped']}，错误 {summary['errorCount']}）",
                context,
                None,
                {
                    "fileName": file_name,
                    "totalRows": summary["totalRows"],
                    "created": summary["created"],
                    "updated": summary["updated"],
                    "skipped": summary["skipped"],
                    "errors": summary["errorCount"],
                    "mode": mode,
                },
            )
            + ";"
        )
        return summary
