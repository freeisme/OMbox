"""机房、弱电间与机柜巡检管理。

巡检对象只包含机房、弱电间和它们下面的机柜。一次巡检会先把模板事项快照进
任务明细，之后修改模板不会影响已经开始的巡检表。

重要规则：

* 执行人默认是发起巡检的账号，也允许显式指定其他账号；
* 异常项必须填写说明，填写时和提交时都会校验；
* 只有手动发起巡检，没有周期计划或自动派单。
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime

from .scope import OrganizationScopeService
from .sql import SqlGateway, parse_bool
from .xlsx import WorkbookError, read_sheet


SITE_TYPES = {"server_room", "weak_room", "meeting_room"}
SITE_TYPE_LABELS = {
    "server_room": "机房",
    "weak_room": "弱电间",
    "meeting_room": "会议室",
    "both": "通用",
}
TEMPLATE_SITE_TYPES = {"server_room", "weak_room", "meeting_room", "both"}
# 一次"批量开检"最多选择多少个目标
MAX_TASK_TARGETS = 30
SCOPE_KINDS = {"site", "rack"}
VALUE_TYPES = {"ok_fail", "number", "text", "select"}
CHECK_RESULTS = {"pending", "ok", "fail", "na"}
TASK_STATUSES = {"running", "submitted", "void"}
CODE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{2,64}$")

# 巡检表导入：允许的表头写法（大小写、空格与标点会被忽略）
IMPORT_HEADER_ALIASES: dict[str, set[str]] = {
    # 巡检对象：机房 / 弱电间 / 会议室（"巡检对象" 是模板表头，其余为兼容写法）
    "site": {
        "巡检对象",
        "对象",
        "机房",
        "机房名称",
        "弱电间",
        "弱电间名称",
        "会议室",
        "会议室名称",
        "site",
        "sitename",
    },
    "rack": {"机柜", "机柜名称", "rack", "rackname"},
    "category": {"检查项分类", "分类", "类别", "category"},
    "title": {"检查项", "检查内容", "巡检项", "巡检事项", "事项", "title", "item"},
    "checkMethod": {"检查方法", "方法", "checkmethod"},
    "result": {"结论", "检查结论", "结果", "result"},
    "valueText": {"实测值", "数值", "记录值", "valuetext", "value"},
    "notes": {"说明", "备注", "问题说明", "notes", "remark", "remarks"},
}
IMPORT_RESULT_ALIASES = {
    "正常": "ok",
    "合格": "ok",
    "通过": "ok",
    "ok": "ok",
    "异常": "fail",
    "不合格": "fail",
    "fail": "fail",
    "不适用": "na",
    "na": "na",
    "n/a": "na",
}
IMPORT_COLUMNS = (
    "巡检对象",
    "机柜",
    "检查项分类",
    "检查项",
    "检查方法",
    "结论",
    "实测值",
    "说明",
)
MAX_IMPORT_ROWS = 1000
MAX_IMPORT_BYTES = 8 * 1024 * 1024


@dataclass
class InspectionService:
    db: SqlGateway
    scope: OrganizationScopeService
    api_error: type[Exception]
    conflict_error: type[Exception]
    forbidden_error: type[Exception]

    # ------------------------------------------------------------------ helpers

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
        """Build an audit insert; entity_id_sql is a raw SQL expression."""
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

    def _conditional_audit_sql(
        self,
        action: str,
        entity_type: str,
        entity_id_sql: str,
        entity_name: str,
        summary: str,
        context: dict,
        condition: str,
        old_value: dict | None = None,
        new_value: dict | None = None,
    ) -> str:
        """Audit insert that only runs when the SQL condition holds."""
        return f"""
        INSERT INTO audit_log (
          action_type, entity_type, entity_id, entity_name,
          old_value, new_value, summary, actor, source
        )
        SELECT
          {self.db.quote(action)},
          {self.db.quote(entity_type)},
          {entity_id_sql},
          {self.db.quote(entity_name)},
          {self.db.json_value(old_value or {})},
          {self.db.json_value(new_value or {})},
          {self.db.quote(summary[:500])},
          {self.db.quote(self._actor_name(context))},
          'api'
        FROM DUAL
        WHERE {condition}
        """

    def _idempotency_result(self, operation: str, key: str, payload: dict) -> dict | None:
        if not key:
            return None
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", key):
            raise self.api_error("Idempotency-Key must be 8-128 safe characters.")
        record = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'requestHash', request_hash,
              'response', response_json
            )
            FROM api_idempotency_key
            WHERE idempotency_key = {self.db.quote(key)}
              AND operation_code = {self.db.quote(operation)}
              AND expires_at > CURRENT_TIMESTAMP
            """,
            None,
        )
        if not record:
            return None
        request_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if self.db.text(record.get("requestHash")) != request_hash:
            raise self.conflict_error("The idempotency key was already used with another request.")
        return dict(record.get("response") or {})

    def _store_idempotency_result(self, operation: str, key: str, payload: dict, response: dict) -> None:
        if not key:
            return
        request_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.db.execute(
            f"""
            INSERT INTO api_idempotency_key (
              idempotency_key, operation_code, request_hash, response_json, expires_at
            )
            VALUES (
              {self.db.quote(key)},
              {self.db.quote(operation)},
              {self.db.quote(request_hash)},
              {self.db.json_value(response)},
              DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 24 HOUR)
            )
            ON DUPLICATE KEY UPDATE
              request_hash = VALUES(request_hash),
              response_json = VALUES(response_json),
              expires_at = VALUES(expires_at);
            """
        )

    def _require_code(self, value: object, field_label: str) -> str:
        code = self.db.text(value)
        if not CODE_PATTERN.match(code):
            raise self.api_error(f"{field_label}只能使用字母、数字、点、下划线和短横线，长度 2-64。")
        return code

    def _require_text(self, value: object, field_label: str, limit: int) -> str:
        text = self.db.text(value)
        if not text:
            raise self.api_error(f"{field_label}不能为空。")
        return text[:limit]

    # -------------------------------------------------------------------- sites

    def list_sites(self, context: dict, params: dict[str, list[str]] | None = None) -> list[dict]:
        include_inactive = parse_bool((params or {}).get("includeInactive", ["0"])[0])
        active_filter = "" if include_inactive else "WHERE site.is_active = 1"
        return list(
            self.db.json(
                f"""
                SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
                  'id', CAST(site.site_id AS CHAR),
                  'code', site.site_code,
                  'name', site.site_name,
                  'siteType', site.site_type,
                  'orgId', COALESCE(CAST(site.org_unit_id AS CHAR), ''),
                  'orgName', site.org_name,
                  'location', site.location_desc,
                  'remarks', site.remarks,
                  'isActive', site.is_active,
                  'rackCount', site.rack_count,
                  'deviceCount', site.device_count
                )), JSON_ARRAY())
                FROM (
                  SELECT site.*, COALESCE(org.org_name, '') AS org_name,
                    (
                    SELECT COUNT(*) FROM asset_rack rack
                    WHERE rack.site_id = site.site_id AND rack.is_active = 1
                    ) AS rack_count,
                    (
                    SELECT COUNT(*) FROM site_device device
                    WHERE device.site_id = site.site_id AND device.is_active = 1
                    ) AS device_count
                  FROM asset_site site
                  LEFT JOIN org_unit org ON org.org_unit_id = site.org_unit_id
                  {active_filter}
                  ORDER BY site.site_type, site.site_code
                ) site
                """,
                [],
            )
            or []
        )

    def create_site(self, payload: dict, context: dict) -> dict:
        code = self._require_code(payload.get("code"), "机房/弱电间编码")
        name = self._require_text(payload.get("name"), "机房/弱电间名称", 128)
        site_type = self.db.text(payload.get("siteType")) or "server_room"
        if site_type not in SITE_TYPES:
            raise self.api_error("机房/弱电间类型无效。")
        org_id = self.db.integer(payload.get("orgId"), 0)
        if org_id > 0:
            self.scope.assert_org_access(context, org_id)
        location = self.db.text(payload.get("location"))[:255]
        remarks = self.db.text(payload.get("remarks"))[:500]
        output = self.db.execute(
            f"""
            START TRANSACTION;
            INSERT INTO asset_site (site_code, site_name, site_type, org_unit_id, location_desc, remarks)
            VALUES (
              {self.db.quote(code)},
              {self.db.quote(name)},
              {self.db.quote(site_type)},
              {org_id if org_id > 0 else 'NULL'},
              {self.db.quote(location)},
              {self.db.quote(remarks)}
            );
            SET @new_site_id = LAST_INSERT_ID();
            {self._audit_sql(
                "inspection_site_created",
                "asset_site",
                "'new'",
                name,
                f"新增{SITE_TYPE_LABELS.get(site_type, '机房')}：{name}",
                context,
                None,
                {"code": code, "siteType": site_type},
            )};
            UPDATE audit_log
            SET entity_id = CAST(@new_site_id AS CHAR)
            WHERE audit_log_id = LAST_INSERT_ID();
            SELECT @new_site_id;
            COMMIT;
            """
        )
        site_id = self._last_int(output)
        if site_id <= 0:
            raise self.conflict_error("机房/弱电间编码已存在。")
        return {"id": str(site_id), "code": code, "name": name}

    def update_site(self, site_id: object, payload: dict, context: dict) -> dict:
        site = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(site_id AS CHAR),
              'code', site_code,
              'name', site_name,
              'siteType', site_type,
              'orgId', COALESCE(CAST(org_unit_id AS CHAR), ''),
              'location', location_desc,
              'remarks', remarks,
              'isActive', is_active
            )
            FROM asset_site
            WHERE site_id = {self.db.integer(site_id, 0)}
            """,
            None,
        )
        if not site:
            raise self.api_error("机房/弱电间不存在。")
        code = self._require_code(payload.get("code", site.get("code")), "机房/弱电间编码")
        name = self._require_text(payload.get("name", site.get("name")), "机房/弱电间名称", 128)
        site_type = self.db.text(payload.get("siteType", site.get("siteType"))) or "server_room"
        if site_type not in SITE_TYPES:
            raise self.api_error("机房/弱电间类型无效。")
        org_id = self.db.integer(payload.get("orgId", site.get("orgId")), 0)
        if org_id > 0:
            self.scope.assert_org_access(context, org_id)
        location = self.db.text(payload.get("location", site.get("location")))[:255]
        remarks = self.db.text(payload.get("remarks", site.get("remarks")))[:500]
        is_active = 1 if parse_bool(payload.get("isActive", site.get("isActive")), True) else 0
        self.db.execute(
            f"""
            START TRANSACTION;
            UPDATE asset_site
            SET site_code = {self.db.quote(code)},
                site_name = {self.db.quote(name)},
                site_type = {self.db.quote(site_type)},
                org_unit_id = {org_id if org_id > 0 else 'NULL'},
                location_desc = {self.db.quote(location)},
                remarks = {self.db.quote(remarks)},
                is_active = {is_active}
            WHERE site_id = {self.db.integer(site.get("id"), 0)};
            {self._audit_sql(
                "inspection_site_updated",
                "asset_site",
                str(self.db.integer(site.get("id"), 0)),
                name,
                f"更新{SITE_TYPE_LABELS.get(site_type, '机房')}：{name}",
                context,
                site,
                {"code": code, "name": name, "siteType": site_type, "isActive": is_active},
            )};
            COMMIT;
            """
        )
        return {"id": str(site.get("id")), "code": code, "name": name}

    # -------------------------------------------------------------------- racks

    def list_racks(self, context: dict, params: dict[str, list[str]] | None = None) -> list[dict]:
        site_filter = self.db.integer((params or {}).get("siteId", [""])[0], 0)
        where = ["rack.is_active = 1"] if not parse_bool((params or {}).get("includeInactive", ["0"])[0]) else ["1 = 1"]
        if site_filter > 0:
            where.append(f"rack.site_id = {site_filter}")
        return list(
            self.db.json(
                f"""
                SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
                  'id', CAST(rack.rack_id AS CHAR),
                  'code', rack.rack_code,
                  'name', rack.rack_name,
                  'siteId', CAST(rack.site_id AS CHAR),
                  'siteName', rack.site_name,
                  'siteType', rack.site_type,
                  'heightU', rack.height_u,
                  'descUnits', rack.desc_units,
                  'remarks', rack.remarks,
                  'isActive', rack.is_active
                )), JSON_ARRAY())
                FROM (
                  SELECT rack.rack_id, rack.rack_code, rack.rack_name, rack.site_id,
                         rack.height_u, rack.desc_units, rack.remarks, rack.is_active,
                         site.site_name, site.site_type
                  FROM asset_rack rack
                  JOIN asset_site site ON site.site_id = rack.site_id
                  WHERE {' AND '.join(where)}
                  ORDER BY site.site_code, rack.rack_code
                ) rack
                """,
                [],
            )
            or []
        )

    def create_rack(self, payload: dict, context: dict) -> dict:
        code = self._require_code(payload.get("code"), "机柜编码")
        name = self._require_text(payload.get("name"), "机柜名称", 128)
        site_id = self.db.integer(payload.get("siteId"), 0)
        if site_id <= 0:
            raise self.api_error("机柜必须归属一个机房或弱电间。")
        site = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(site_id AS CHAR),
              'name', site_name,
              'orgId', COALESCE(CAST(org_unit_id AS CHAR), '')
            )
            FROM asset_site
            WHERE site_id = {site_id} AND is_active = 1
            """,
            None,
        )
        if not site:
            raise self.api_error("机房/弱电间不存在或已停用。")
        height_u = self.db.integer(payload.get("heightU"), 42)
        if height_u < 1 or height_u > 100:
            raise self.api_error("机柜高度必须在 1-100U 之间。")
        desc_units = 1 if parse_bool(payload.get("descUnits")) else 0
        remarks = self.db.text(payload.get("remarks"))[:500]
        org_id = self.db.integer(site.get("orgId"), 0)
        output = self.db.execute(
            f"""
            START TRANSACTION;
            INSERT INTO asset_rack (
              rack_code, rack_name, site_id, height_u, desc_units, org_unit_id, remarks
            )
            VALUES (
              {self.db.quote(code)},
              {self.db.quote(name)},
              {site_id},
              {height_u},
              {desc_units},
              {org_id if org_id > 0 else 'NULL'},
              {self.db.quote(remarks)}
            );
            SET @new_rack_id = LAST_INSERT_ID();
            {self._audit_sql(
                "inspection_rack_created",
                "asset_rack",
                "'new'",
                name,
                f"新增机柜：{site.get('name')} / {name}",
                context,
                None,
                {"code": code, "siteId": str(site_id), "heightU": height_u},
            )};
            UPDATE audit_log
            SET entity_id = CAST(@new_rack_id AS CHAR)
            WHERE audit_log_id = LAST_INSERT_ID();
            SELECT @new_rack_id;
            COMMIT;
            """
        )
        rack_id = self._last_int(output)
        if rack_id <= 0:
            raise self.conflict_error("机柜编码已存在。")
        return {"id": str(rack_id), "code": code, "name": name}

    def update_rack(self, rack_id: object, payload: dict, context: dict) -> dict:
        rack = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(rack_id AS CHAR),
              'code', rack_code,
              'name', rack_name,
              'siteId', CAST(site_id AS CHAR),
              'heightU', height_u,
              'descUnits', desc_units,
              'remarks', remarks,
              'isActive', is_active
            )
            FROM asset_rack
            WHERE rack_id = {self.db.integer(rack_id, 0)}
            """,
            None,
        )
        if not rack:
            raise self.api_error("机柜不存在。")
        code = self._require_code(payload.get("code", rack.get("code")), "机柜编码")
        name = self._require_text(payload.get("name", rack.get("name")), "机柜名称", 128)
        site_id = self.db.integer(payload.get("siteId", rack.get("siteId")), 0)
        if site_id <= 0:
            raise self.api_error("机柜必须归属一个机房或弱电间。")
        height_u = self.db.integer(payload.get("heightU", rack.get("heightU")), 42)
        if height_u < 1 or height_u > 100:
            raise self.api_error("机柜高度必须在 1-100U 之间。")
        desc_units = 1 if parse_bool(payload.get("descUnits", rack.get("descUnits"))) else 0
        remarks = self.db.text(payload.get("remarks", rack.get("remarks")))[:500]
        is_active = 1 if parse_bool(payload.get("isActive", rack.get("isActive")), True) else 0
        self.db.execute(
            f"""
            START TRANSACTION;
            UPDATE asset_rack
            SET rack_code = {self.db.quote(code)},
                rack_name = {self.db.quote(name)},
                site_id = {site_id},
                height_u = {height_u},
                desc_units = {desc_units},
                remarks = {self.db.quote(remarks)},
                is_active = {is_active}
            WHERE rack_id = {self.db.integer(rack.get("id"), 0)};
            {self._audit_sql(
                "inspection_rack_updated",
                "asset_rack",
                str(self.db.integer(rack.get("id"), 0)),
                name,
                f"更新机柜：{name}",
                context,
                rack,
                {"code": code, "name": name, "heightU": height_u, "isActive": is_active},
            )};
            COMMIT;
            """
        )
        return {"id": str(rack.get("id")), "code": code, "name": name}

    def delete_site(self, site_id: object, payload: dict, context: dict) -> dict:
        """删除机房 / 弱电间；下面还挂着机柜、或已有巡检记录时拒绝，避免留下孤儿数据。"""
        site = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(site_id AS CHAR),
              'code', site_code,
              'name', site_name,
              'siteType', site_type,
              'isActive', is_active
            )
            FROM asset_site
            WHERE site_id = {self.db.integer(site_id, 0)}
            """,
            None,
        )
        if not site:
            raise self.api_error("巡检对象不存在。")
        site_id_int = self.db.integer(site.get("id"), 0)
        rack_count = self.db.scalar(
            f"SELECT COUNT(*) FROM asset_rack WHERE site_id = {site_id_int} AND is_active = 1;"
        )
        if self.db.integer(rack_count, 0) > 0:
            raise self.conflict_error(
                f"该对象下还有 {self.db.integer(rack_count, 0)} 个机柜，请先删除或转移机柜。"
            )
        device_count = self.db.scalar(
            f"SELECT COUNT(*) FROM site_device WHERE site_id = {site_id_int} AND is_active = 1;"
        )
        if self.db.integer(device_count, 0) > 0:
            raise self.conflict_error(
                f"该会议室还有 {self.db.integer(device_count, 0)} 台设备，请先移除设备记录。"
            )
        task_count = self.db.scalar(
            f"SELECT COUNT(*) FROM inspection_task WHERE site_id = {site_id_int};"
        )
        if self.db.integer(task_count, 0) > 0:
            raise self.conflict_error("该对象已有巡检任务记录，删除会破坏巡检历史，不能删除。")
        reason = self.db.text(payload.get("reason"))[:200]
        self.db.execute(
            f"""
            START TRANSACTION;
            DELETE FROM asset_site WHERE site_id = {site_id_int};
            {self._audit_sql(
                "inspection_site_deleted",
                "asset_site",
                str(site_id_int),
                self.db.text(site.get("name")),
                f"删除巡检对象：{SITE_TYPE_LABELS.get(self.db.text(site.get('siteType')), '机房')}"
                f"·{self.db.text(site.get('name'))}"
                + (f"（原因：{reason}）" if reason else ""),
                context,
                site,
                None,
            )};
            COMMIT;
            """
        )
        return {"id": str(site_id_int), "code": self.db.text(site.get("code"))}

    def delete_rack(self, rack_id: object, payload: dict, context: dict) -> dict:
        """删除机柜；柜内有已上架设备、端口 / 链路或巡检记录时拒绝。"""
        rack = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(rack_id AS CHAR),
              'code', rack_code,
              'name', rack_name,
              'siteId', CAST(site_id AS CHAR),
              'heightU', height_u,
              'isActive', is_active
            )
            FROM asset_rack
            WHERE rack_id = {self.db.integer(rack_id, 0)}
            """,
            None,
        )
        if not rack:
            raise self.api_error("机柜不存在。")
        rack_id_int = self.db.integer(rack.get("id"), 0)
        placement_count = self.db.scalar(
            f"SELECT COUNT(*) FROM rack_device_placement WHERE rack_id = {rack_id_int};"
        )
        if self.db.integer(placement_count, 0) > 0:
            raise self.conflict_error(
                f"机柜内还有 {self.db.integer(placement_count, 0)} 台已上架设备，请先在机柜视图下架。"
            )
        port_count = self.db.scalar(
            f"""
            SELECT COUNT(*) FROM rack_device_port port
            JOIN rack_device_placement placement ON placement.placement_id = port.placement_id
            WHERE placement.rack_id = {rack_id_int};
            """
        )
        if self.db.integer(port_count, 0) > 0:
            raise self.conflict_error("该机柜还登记着设备端口，请先清理端口与链路。")
        task_count = self.db.scalar(
            f"SELECT COUNT(*) FROM inspection_task WHERE rack_id = {rack_id_int};"
        )
        if self.db.integer(task_count, 0) > 0:
            raise self.conflict_error("该机柜已有巡检任务记录，删除会破坏巡检历史，不能删除。")
        reason = self.db.text(payload.get("reason"))[:200]
        self.db.execute(
            f"""
            START TRANSACTION;
            DELETE FROM asset_rack WHERE rack_id = {rack_id_int};
            {self._audit_sql(
                "inspection_rack_deleted",
                "asset_rack",
                str(rack_id_int),
                self.db.text(rack.get("name")),
                f"删除机柜：{self.db.text(rack.get('name'))}"
                + (f"（原因：{reason}）" if reason else ""),
                context,
                rack,
                None,
            )};
            COMMIT;
            """
        )
        return {"id": str(rack_id_int), "code": self.db.text(rack.get("code"))}

    # ---------------------------------------------------------------- templates

    # ----------------------------------------------------------- site devices

    def _site_row(self, site_id: object) -> dict:
        site = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(site_id AS CHAR),
              'code', site_code,
              'name', site_name,
              'siteType', site_type,
              'isActive', is_active
            )
            FROM asset_site
            WHERE site_id = {self.db.integer(site_id, 0)}
            """,
            None,
        )
        if not site:
            raise self.api_error("巡检对象不存在。")
        return dict(site)

    def list_site_devices(self, site_id: object, context: dict) -> dict:
        """会议室（或任意巡检对象）里的设备清单：IT 物资分配的 + 自定义登记的。"""
        site = self._site_row(site_id)
        site_id_int = self.db.integer(site.get("id"), 0)
        devices = list(
            self.db.json(
                f"""
                SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
                  'id', CAST(device.device_id AS CHAR),
                  'source', device.source,
                  'name', device.device_name,
                  'deviceType', device.device_type,
                  'brand', device.brand,
                  'model', device.model,
                  'quantity', device.quantity,
                  'status', device.status,
                  'notes', device.notes,
                  'modelId', COALESCE(CAST(device.inventory_model_id AS CHAR), ''),
                  'warehouseId', COALESCE(CAST(device.warehouse_id AS CHAR), ''),
                  'warehouseName', COALESCE(warehouse.warehouse_name, ''),
                  'createdAt', DATE_FORMAT(device.created_at, '%Y-%m-%d %H:%i:%s')
                )), JSON_ARRAY())
                FROM site_device device
                LEFT JOIN inventory_warehouse warehouse
                  ON warehouse.warehouse_id = device.warehouse_id
                WHERE device.site_id = {site_id_int}
                  AND device.is_active = 1
                ORDER BY device.source, device.device_id
                """,
                [],
            )
            or []
        )
        return {
            "site": {
                "id": str(site_id_int),
                "name": self.db.text(site.get("name")),
                "siteType": self.db.text(site.get("siteType")),
            },
            "devices": devices,
        }

    def add_site_device(self, site_id: object, payload: dict, context: dict) -> dict:
        """把设备登记到会议室：来源可以是 IT 物资（按仓库出库）或自定义登记。"""
        site = self._site_row(site_id)
        if not parse_bool(site.get("isActive"), True):
            raise self.conflict_error("该巡检对象已停用。")
        site_id_int = self.db.integer(site.get("id"), 0)
        site_name = self.db.text(site.get("name"))
        source = self.db.text(payload.get("source")) or "custom"
        if source not in {"inventory", "custom"}:
            raise self.api_error("设备来源必须是 IT 物资或自定义登记。")
        quantity = self.db.integer(payload.get("quantity"), 1)
        if quantity <= 0 or quantity > 999:
            raise self.api_error("数量必须在 1-999 之间。")
        notes = self.db.text(payload.get("notes"))[:500]
        actor_id = self._actor_id(context)

        device_name = ""
        device_type = ""
        brand = ""
        model = ""
        model_id = 0
        warehouse_id = 0
        movement_sql = ""
        stock_guard = "1 = 1"

        if source == "inventory":
            model_id = self.db.integer(payload.get("modelId"), 0)
            if model_id <= 0:
                raise self.api_error("请选择要分配的 IT 物资型号。")
            model_row = self.db.json(
                f"""
                SELECT JSON_OBJECT(
                  'name', model.model_name,
                  'brand', brand.brand_name,
                  'typeName', type_row.type_name
                )
                FROM it_inventory_model model
                JOIN it_inventory_brand brand ON brand.brand_id = model.brand_id
                JOIN non_asset_type type_row ON type_row.non_asset_type_id = model.non_asset_type_id
                WHERE model.model_id = {model_id} AND model.is_active = 1
                """,
                None,
            )
            if not model_row:
                raise self.api_error("IT 物资型号不存在。")
            warehouse_id = self.db.integer(payload.get("warehouseId"), 0)
            if warehouse_id <= 0:
                raise self.api_error("从 IT 物资分配时必须选择出库仓库。")
            warehouse = self.db.json(
                f"""
                SELECT JSON_OBJECT('id', CAST(warehouse_id AS CHAR), 'name', warehouse_name)
                FROM inventory_warehouse
                WHERE warehouse_id = {warehouse_id} AND is_active = 1
                """,
                None,
            )
            if not warehouse:
                raise self.api_error("出库仓库不存在或已停用。")
            brand = self.db.text(model_row.get("brand"))
            model = self.db.text(model_row.get("name"))
            device_type = self.db.text(model_row.get("typeName"))
            device_name = f"{brand} {model}".strip()
            # 从仓库扣减库存并写流转日志；库存不足时整条语句不生效。
            stock_guard = "@stock_moved = 1"
            movement_sql = f"""
            INSERT INTO inventory_movement_log (
              movement_direction, type_name, brand_name, model_name, quantity,
              source_label, source_warehouse_id, target_label, target_warehouse_id,
              note, related_employee_no, related_employee_name, trigger_action
            )
            SELECT
              'decrease',
              {self.db.quote(device_type)},
              {self.db.quote(brand)},
              {self.db.quote(model)},
              {quantity},
              {self.db.quote(self.db.text(warehouse.get('name')))},
              {warehouse_id},
              {self.db.quote(site_name)},
              NULL,
              {self.db.quote(notes)},
              '',
              '',
              'site_allocation'
            FROM DUAL
            WHERE @stock_moved = 1;
            """
        else:
            device_name = self.db.text(payload.get("name"))[:128]
            if not device_name:
                raise self.api_error("自定义设备必须填写设备名称。")
            device_type = self.db.text(payload.get("deviceType"))[:64]
            brand = self.db.text(payload.get("brand"))[:64]
            model = self.db.text(payload.get("model"))[:128]

        statements = [
            "START TRANSACTION",
            "SET @stock_moved = 1",
        ]
        if source == "inventory":
            statements.extend(
                [
                    f"""
                    SELECT quantity INTO @model_available_quantity
                    FROM it_inventory_model
                    WHERE model_id = {model_id}
                    FOR UPDATE
                    """,
                    f"""
                    INSERT INTO inventory_warehouse_stock (warehouse_id, model_id, quantity)
                    SELECT {warehouse_id}, {model_id}, 0
                    FROM DUAL
                    ON DUPLICATE KEY UPDATE warehouse_id = VALUES(warehouse_id)
                    """,
                    f"""
                    SELECT COALESCE(quantity, 0) INTO @warehouse_available_quantity
                    FROM inventory_warehouse_stock
                    WHERE warehouse_id = {warehouse_id}
                      AND model_id = {model_id}
                    FOR UPDATE
                    """,
                    f"""
                    SET @stock_moved = IF(
                      @model_available_quantity >= {quantity}
                      AND @warehouse_available_quantity >= {quantity},
                      1,
                      0
                    )
                    """,
                    f"""
                    UPDATE it_inventory_model
                    SET quantity = quantity - {quantity}
                    WHERE model_id = {model_id}
                      AND @stock_moved = 1
                    """,
                    f"""
                    UPDATE inventory_warehouse_stock
                    SET quantity = quantity - {quantity}
                    WHERE warehouse_id = {warehouse_id}
                      AND model_id = {model_id}
                      AND @stock_moved = 1
                    """,
                ]
            )
        statements.append(
            f"""
            INSERT INTO site_device (
              site_id, source, device_name, device_type, brand, model,
              inventory_model_id, warehouse_id, quantity, status, notes, created_by, updated_by
            )
            SELECT
              {site_id_int},
              {self.db.quote(source)},
              {self.db.quote(device_name)},
              {self.db.quote(device_type)},
              {self.db.quote(brand)},
              {self.db.quote(model)},
              {model_id if model_id > 0 else 'NULL'},
              {warehouse_id if warehouse_id > 0 else 'NULL'},
              {quantity},
              'in_use',
              {self.db.quote(notes)},
              {actor_id if actor_id > 0 else 'NULL'},
              {actor_id if actor_id > 0 else 'NULL'}
            FROM DUAL
            WHERE {stock_guard}
            """
        )
        statements.extend(
            [
                "SET @new_site_device_id = IF(@stock_moved = 1, LAST_INSERT_ID(), 0)",
                f"""
                {movement_sql}
                """ if movement_sql else "SELECT 1",
                self._conditional_audit_sql(
                    "site_device_added",
                    "site_device",
                    "@new_site_device_id",
                    device_name,
                    f"登记会议室内设备：{site_name} / {device_name} ×{quantity}",
                    context,
                    "@new_site_device_id > 0",
                    None,
                    {
                        "source": source,
                        "quantity": quantity,
                        "modelId": str(model_id) if model_id > 0 else "",
                        "warehouseId": str(warehouse_id) if warehouse_id > 0 else "",
                    },
                ),
                "SELECT @new_site_device_id, @stock_moved",
                "COMMIT",
            ]
        )
        output = self.db.execute(";\n".join(statement.strip() for statement in statements) + ";")
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        result = (lines[-1] if lines else "").split("\t")
        device_id = self.db.integer(result[0] if result else 0, 0)
        stock_moved = self.db.integer(result[1] if len(result) > 1 else 1, 1)
        if device_id <= 0:
            if source == "inventory" and not stock_moved:
                raise self.conflict_error("所选仓库的库存不足，无法分配。")
            raise self.conflict_error("设备登记失败，请重试。")
        return {
            "id": str(device_id),
            "siteId": str(site_id_int),
            "name": device_name,
            "quantity": quantity,
            "source": source,
        }

    def remove_site_device(self, device_id: object, payload: dict, context: dict) -> dict:
        """移除会议室内设备；来自 IT 物资的记录会把数量退回原仓库。"""
        device = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(device.device_id AS CHAR),
              'siteId', CAST(device.site_id AS CHAR),
              'siteName', site.site_name,
              'source', device.source,
              'name', device.device_name,
              'typeName', device.device_type,
              'brand', device.brand,
              'model', device.model,
              'modelId', COALESCE(CAST(device.inventory_model_id AS CHAR), ''),
              'warehouseId', COALESCE(CAST(device.warehouse_id AS CHAR), ''),
              'quantity', device.quantity,
              'isActive', device.is_active
            )
            FROM site_device device
            JOIN asset_site site ON site.site_id = device.site_id
            WHERE device.device_id = {self.db.integer(device_id, 0)}
            """,
            None,
        )
        if not device:
            raise self.api_error("设备记录不存在。")
        if not parse_bool(device.get("isActive"), True):
            raise self.conflict_error("该设备记录已经移除。")
        device_id_int = self.db.integer(device.get("id"), 0)
        source = self.db.text(device.get("source"))
        quantity = max(1, self.db.integer(device.get("quantity"), 1))
        model_id = self.db.integer(device.get("modelId"), 0)
        warehouse_id = self.db.integer(payload.get("warehouseId"), 0) or self.db.integer(
            device.get("warehouseId"), 0
        )
        reason = self.db.text(payload.get("reason"))[:200]
        actor_id = self._actor_id(context)
        return_stock = source == "inventory" and model_id > 0
        warehouse_name = ""
        if return_stock and warehouse_id > 0:
            warehouse = self.db.json(
                f"""
                SELECT JSON_OBJECT('name', warehouse_name)
                FROM inventory_warehouse
                WHERE warehouse_id = {warehouse_id}
                """,
                None,
            )
            warehouse_name = self.db.text((warehouse or {}).get("name"))

        statements = ["START TRANSACTION"]
        if return_stock:
            statements.extend(
                [
                    f"""
                    INSERT INTO inventory_warehouse_stock (warehouse_id, model_id, quantity)
                    VALUES ({warehouse_id}, {model_id}, {quantity})
                    ON DUPLICATE KEY UPDATE quantity = quantity + VALUES(quantity)
                    """,
                    f"""
                    UPDATE it_inventory_model
                    SET quantity = quantity + {quantity}
                    WHERE model_id = {model_id}
                    """,
                    f"""
                    INSERT INTO inventory_movement_log (
                      movement_direction, type_name, brand_name, model_name, quantity,
                      source_label, source_warehouse_id, target_label, target_warehouse_id,
                      note, related_employee_no, related_employee_name, trigger_action
                    )
                    SELECT
                      'increase',
                      {self.db.quote(self.db.text(device.get('typeName')))},
                      {self.db.quote(self.db.text(device.get('brand')))},
                      {self.db.quote(self.db.text(device.get('model')))},
                      {quantity},
                      {self.db.quote(self.db.text(device.get('siteName')))},
                      NULL,
                      {self.db.quote(warehouse_name)},
                      {warehouse_id},
                      {self.db.quote(reason)},
                      '',
                      '',
                      'site_return'
                    FROM DUAL
                    WHERE {1 if warehouse_id > 0 else 0} = 1
                    """,
                ]
            )
        statements.append(
            f"""
            UPDATE site_device
            SET is_active = 0,
                status = 'returned',
                notes = CONCAT_WS(' ', notes, {self.db.quote(reason)}),
                updated_by = {actor_id if actor_id > 0 else 'NULL'}
            WHERE device_id = {device_id_int}
            """
        )
        statements.append(
            self._audit_sql(
                "site_device_removed",
                "site_device",
                str(device_id_int),
                self.db.text(device.get("name")),
                f"移除会议室内设备：{self.db.text(device.get('siteName'))} / "
                f"{self.db.text(device.get('name'))} ×{quantity}"
                + (f"（原因：{reason}）" if reason else ""),
                context,
                {
                    "source": source,
                    "quantity": quantity,
                    "warehouseId": str(warehouse_id) if warehouse_id > 0 else "",
                },
                None,
            )
        )
        statements.append("COMMIT")
        self.db.execute(";\n".join(statement.strip() for statement in statements) + ";")
        return {
            "id": str(device_id_int),
            "returnedToStock": bool(return_stock),
            "quantity": quantity,
        }

    def list_templates(self, context: dict) -> list[dict]:
        return list(
            self.db.json(
                """
                SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
                  'id', CAST(template.template_id AS CHAR),
                  'code', template.template_code,
                  'name', template.template_name,
                  'siteType', template.site_type,
                  'description', template.description,
                  'isActive', template.is_active,
                  'itemCount', template.item_count
                )), JSON_ARRAY())
                FROM (
                  SELECT template.*, (
                    SELECT COUNT(*) FROM inspection_template_item item
                    WHERE item.template_id = template.template_id
                  ) AS item_count
                  FROM inspection_template template
                  ORDER BY template.template_code
                ) template
                """,
                [],
            )
            or []
        )

    def get_template(self, template_id: object, context: dict) -> dict:
        template = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(template_id AS CHAR),
              'code', template_code,
              'name', template_name,
              'siteType', site_type,
              'description', description,
              'isActive', is_active
            )
            FROM inspection_template
            WHERE template_id = {self.db.integer(template_id, 0)}
            """,
            None,
        )
        if not template:
            raise self.api_error("巡检模板不存在。")
        template["items"] = self._template_items(self.db.integer(template.get("id"), 0))
        return template

    def _template_items(self, template_id: int) -> list[dict]:
        if template_id <= 0:
            return []
        return list(
            self.db.json(
                f"""
                SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
                  'seqNo', seq_no,
                  'category', category,
                  'title', item_title,
                  'checkMethod', check_method,
                  'valueType', value_type,
                  'unit', unit,
                  'normalRange', normal_range,
                  'isRequired', is_required,
                  'remarks', remarks
                )), JSON_ARRAY())
                FROM (
                  SELECT *
                  FROM inspection_template_item
                  WHERE template_id = {template_id}
                  ORDER BY seq_no, item_id
                ) item
                """,
                [],
            )
            or []
        )

    def _validated_items(self, payload: dict) -> list[dict]:
        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise self.api_error("巡检事项至少需要一项。")
        if len(raw_items) > 200:
            raise self.api_error("单个模板的巡检事项不能超过 200 项。")
        items: list[dict] = []
        for index, raw in enumerate(raw_items):
            if not isinstance(raw, dict):
                raise self.api_error("巡检事项格式无效。")
            title = self._require_text(raw.get("title"), "巡检事项名称", 200)
            value_type = self.db.text(raw.get("valueType")) or "ok_fail"
            if value_type not in VALUE_TYPES:
                raise self.api_error("巡检事项取值类型无效。")
            seq_no = self.db.integer(raw.get("seqNo"), (index + 1) * 10)
            items.append(
                {
                    "seqNo": seq_no,
                    "category": self.db.text(raw.get("category"))[:64] or "通用",
                    "title": title,
                    "checkMethod": self.db.text(raw.get("checkMethod"))[:255],
                    "valueType": value_type,
                    "unit": self.db.text(raw.get("unit"))[:32],
                    "normalRange": self.db.text(raw.get("normalRange"))[:128],
                    "isRequired": 1 if parse_bool(raw.get("isRequired", True), True) else 0,
                }
            )
        return items

    def _template_item_insert_sql(self, template_id_sql: str, items: list[dict]) -> str:
        values = []
        for item in items:
            values.append(
                "("
                + ", ".join(
                    [
                        template_id_sql,
                        str(item["seqNo"]),
                        self.db.quote(item["category"]),
                        self.db.quote(item["title"]),
                        self.db.quote(item["checkMethod"]),
                        self.db.quote(item["valueType"]),
                        self.db.quote(item["unit"]),
                        self.db.quote(item["normalRange"]),
                        str(item["isRequired"]),
                    ]
                )
                + ")"
            )
        return (
            "INSERT INTO inspection_template_item ("
            "template_id, seq_no, category, item_title, check_method, value_type, unit, normal_range, "
            "is_required) VALUES " + ", ".join(values)
        )

    def create_template(self, payload: dict, context: dict) -> dict:
        code = self._require_code(payload.get("code"), "模板编码")
        name = self._require_text(payload.get("name"), "模板名称", 128)
        site_type = self.db.text(payload.get("siteType")) or "both"
        if site_type not in TEMPLATE_SITE_TYPES:
            raise self.api_error("模板适用对象无效。")
        description = self.db.text(payload.get("description"))[:500]
        items = self._validated_items(payload)
        actor_id = self._actor_id(context)
        output = self.db.execute(
            f"""
            START TRANSACTION;
            INSERT INTO inspection_template (
              template_code, template_name, site_type, description, created_by, updated_by
            )
            VALUES (
              {self.db.quote(code)},
              {self.db.quote(name)},
              {self.db.quote(site_type)},
              {self.db.quote(description)},
              {actor_id if actor_id > 0 else 'NULL'},
              {actor_id if actor_id > 0 else 'NULL'}
            );
            SET @new_template_id = LAST_INSERT_ID();
            {self._template_item_insert_sql('@new_template_id', items)};
            {self._audit_sql(
                "inspection_template_created",
                "inspection_template",
                "'new'",
                name,
                f"新增巡检模板：{name}",
                context,
                None,
                {"code": code, "siteType": site_type, "itemCount": len(items)},
            )};
            UPDATE audit_log
            SET entity_id = CAST(@new_template_id AS CHAR)
            WHERE audit_log_id = LAST_INSERT_ID();
            SELECT @new_template_id;
            COMMIT;
            """
        )
        template_id = self._last_int(output)
        if template_id <= 0:
            raise self.conflict_error("模板编码已存在。")
        return {"id": str(template_id), "code": code, "name": name, "itemCount": len(items)}

    def update_template(self, template_id: object, payload: dict, context: dict) -> dict:
        template = self.get_template(template_id, context)
        code = self._require_code(payload.get("code", template.get("code")), "模板编码")
        name = self._require_text(payload.get("name", template.get("name")), "模板名称", 128)
        site_type = self.db.text(payload.get("siteType", template.get("siteType"))) or "both"
        if site_type not in TEMPLATE_SITE_TYPES:
            raise self.api_error("模板适用对象无效。")
        description = self.db.text(payload.get("description", template.get("description")))[:500]
        is_active = 1 if parse_bool(payload.get("isActive", template.get("isActive")), True) else 0
        items = template.get("items") or []
        replace_items = isinstance(payload.get("items"), list)
        if replace_items:
            items = self._validated_items(payload)
        template_id_int = self.db.integer(template.get("id"), 0)
        actor_id = self._actor_id(context)
        statements = [
            "START TRANSACTION",
            f"""
            UPDATE inspection_template
            SET template_code = {self.db.quote(code)},
                template_name = {self.db.quote(name)},
                site_type = {self.db.quote(site_type)},
                description = {self.db.quote(description)},
                is_active = {is_active},
                updated_by = {actor_id if actor_id > 0 else 'NULL'}
            WHERE template_id = {template_id_int}
            """,
        ]
        if replace_items:
            statements.append(f"DELETE FROM inspection_template_item WHERE template_id = {template_id_int}")
            statements.append(self._template_item_insert_sql(str(template_id_int), items))
        statements.append(
            self._audit_sql(
                "inspection_template_updated",
                "inspection_template",
                template_id_int,
                name,
                f"更新巡检模板：{name}",
                context,
                {"code": template.get("code"), "itemCount": len(template.get("items") or [])},
                {"code": code, "itemCount": len(items), "isActive": is_active},
            )
        )
        statements.append("COMMIT")
        self.db.execute(";\n".join(statements) + ";")
        return {"id": str(template_id_int), "code": code, "name": name, "itemCount": len(items)}

    def delete_template(self, template_id: object, payload: dict, context: dict) -> dict:
        """删除巡检模板；历史任务保留当时的模板名称与事项快照（template_id 置空）。"""
        template = self.get_template(template_id, context)
        template_id_int = self.db.integer(template.get("id"), 0)
        if template_id_int <= 0:
            raise self.api_error("巡检模板不存在。")
        task_count = self.db.integer(
            self.db.scalar(
                f"SELECT COUNT(*) FROM inspection_task WHERE template_id = {template_id_int};"
            ),
            0,
        )
        reason = self.db.text(payload.get("reason"))[:200]
        self.db.execute(
            f"""
            START TRANSACTION;
            UPDATE inspection_task
            SET template_id = NULL
            WHERE template_id = {template_id_int};
            DELETE FROM inspection_template WHERE template_id = {template_id_int};
            {self._audit_sql(
                "inspection_template_deleted",
                "inspection_template",
                str(template_id_int),
                self.db.text(template.get("name")),
                f"删除巡检模板：{self.db.text(template.get('name'))}"
                f"（保留 {task_count} 张历史巡检表的快照）"
                + (f"，原因：{reason}" if reason else ""),
                context,
                {
                    "code": self.db.text(template.get("code")),
                    "itemCount": len(template.get("items") or []),
                },
                None,
            )};
            COMMIT;
            """
        )
        return {
            "id": str(template_id_int),
            "tasks": task_count,
            "items": len(template.get("items") or []),
        }

    # -------------------------------------------------------------------- tasks

    def _next_task_no(self) -> str:
        today = datetime.now().strftime("%Y%m%d")
        prefix = f"XJ-{today}-"
        sequence = self.db.scalar(
            f"""
            SELECT COALESCE(MAX(CAST(RIGHT(task_no, 3) AS UNSIGNED)), 0)
            FROM inspection_task
            WHERE task_no LIKE {self.db.quote(prefix + '%')};
            """
        )
        return f"{prefix}{sequence + 1:03d}"

    def list_tasks(self, context: dict, params: dict[str, list[str]] | None = None) -> list[dict]:
        status = self.db.text((params or {}).get("status", [""])[0])
        where = []
        if status in TASK_STATUSES:
            where.append(f"task.status = {self.db.quote(status)}")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        return list(
            self.db.json(
                f"""
                SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
                  'id', CAST(task.task_id AS CHAR),
                  'taskNo', task.task_no,
                  'batchNo', task.batch_no,
                  'templateId', COALESCE(CAST(task.template_id AS CHAR), ''),
                  'templateName', task.template_name,
                  'scopeKind', task.scope_kind,
                  'siteType', task.site_type,
                  'scopeName', TRIM(BOTH ' /' FROM CONCAT(
                    COALESCE(task.site_name, ''), ' / ', COALESCE(task.rack_name, '')
                  )),
                  'siteName', task.site_name,
                  'rackName', task.rack_name,
                  'inspectorName', task.inspector_name,
                  'status', task.status,
                  'startedAt', COALESCE(CAST(task.started_at AS CHAR), ''),
                  'submittedAt', COALESCE(CAST(task.submitted_at AS CHAR), ''),
                  'itemTotal', task.item_total,
                  'itemOk', task.item_ok,
                  'itemFail', task.item_fail,
                  'itemNa', task.item_na,
                  'abnormalSummary', task.abnormal_summary
                )), JSON_ARRAY())
                FROM (
                  SELECT task.*
                  FROM inspection_task task
                  {clause}
                  ORDER BY task.started_at DESC, task.task_id DESC
                ) task
                """,
                [],
            )
            or []
        )

    def start_task(self, payload: dict, context: dict, idempotency_key: str = "") -> dict:
        cached = self._idempotency_result("inspection.task.start", idempotency_key, payload)
        if cached:
            return cached

        template_id = self.db.integer(payload.get("templateId"), 0)
        if template_id <= 0:
            raise self.api_error("请选择巡检模板。")
        template = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(template_id AS CHAR),
              'name', template_name,
              'siteType', site_type,
              'isActive', is_active
            )
            FROM inspection_template
            WHERE template_id = {template_id}
            """,
            None,
        )
        if not template:
            raise self.api_error("巡检模板不存在。")
        if not parse_bool(template.get("isActive"), True):
            raise self.conflict_error("该巡检模板已停用。")
        items = self._template_items(template_id)
        if not items:
            raise self.conflict_error("该巡检模板没有巡检事项，请先补充后再开始巡检。")

        # 巡检目标可以一次选多个（机房 / 弱电间 / 会议室 / 机柜），一个目标生成一张任务，
        # 同一个批次号把它们串起来，导出时横向排列本次巡检的目标。
        targets = self._resolve_start_targets(payload, context)
        template_site_type = self.db.text(template.get("siteType")) or "both"
        if template_site_type != "both":
            for target in targets:
                target_type = self.db.text(target.get("siteType"))
                if target_type and template_site_type != target_type:
                    raise self.api_error(
                        f"模板「{template.get('name')}」适用于"
                        f"{SITE_TYPE_LABELS.get(template_site_type, '指定对象')}，"
                        f"与所选巡检对象（{target.get('scopeLabel')}）不匹配。"
                    )

        inspector_id = self.db.integer(payload.get("inspectorUserId"), 0)
        if inspector_id <= 0:
            inspector_id = self._actor_id(context)
        inspector_name = ""
        if inspector_id > 0:
            inspector_name = self.db.text(
                self.db.execute(
                    f"SELECT COALESCE(display_name, username) FROM user_account WHERE user_id = {inspector_id};"
                ).strip()
            )
        if not inspector_name:
            inspector_name = self._actor_name(context)

        remarks = self.db.text(payload.get("remarks"))[:500]
        batch_no = self._next_batch_no()
        created: list[dict] = []
        for target in targets:
            created.append(
                self._create_inspection_task(
                    template=template,
                    items=items,
                    target=target,
                    batch_no=batch_no,
                    inspector_id=inspector_id,
                    inspector_name=inspector_name,
                    remarks=remarks,
                    context=context,
                )
            )
        if not created:
            raise self.conflict_error("巡检任务创建失败，请重试。")
        response = {
            "batchNo": batch_no,
            "tasks": created,
            "taskCount": len(created),
            # 兼容既有前端与接口调用：单目标时直接给出这张任务的编号。
            "id": created[0]["id"],
            "taskNo": created[0]["taskNo"],
            "itemTotal": created[0]["itemTotal"],
        }
        self._store_idempotency_result("inspection.task.start", idempotency_key, payload, response)
        return response

    def _next_batch_no(self) -> str:
        """一次多选开检的批次号：同批次的任务可以用横向巡检表一起导出。"""
        return f"B{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"

    def _resolve_start_targets(self, payload: dict, context: dict) -> list[dict]:
        """解析本次开检的目标：支持新的 targets 数组，也兼容原来的单个 siteId / rackId。"""
        raw_targets = payload.get("targets")
        entries: list[dict] = []
        if isinstance(raw_targets, list) and raw_targets:
            for item in raw_targets:
                if not isinstance(item, dict):
                    raise self.api_error("巡检目标格式无效。")
                entries.append(
                    {
                        "scopeKind": self.db.text(item.get("kind") or item.get("scopeKind"))
                        or "site",
                        "targetId": self.db.integer(
                            item.get("id") or item.get("siteId") or item.get("rackId"), 0
                        ),
                    }
                )
        else:
            scope_kind = self.db.text(payload.get("scopeKind")) or "site"
            entries.append(
                {
                    "scopeKind": scope_kind,
                    "targetId": self.db.integer(
                        payload.get("rackId") if scope_kind == "rack" else payload.get("siteId"),
                        0,
                    ),
                }
            )
        if len(entries) > MAX_TASK_TARGETS:
            raise self.api_error(f"一次最多选择 {MAX_TASK_TARGETS} 个巡检对象。")
        targets: list[dict] = []
        seen: set[str] = set()
        for entry in entries:
            scope_kind = entry["scopeKind"]
            target_id = entry["targetId"]
            if scope_kind not in SCOPE_KINDS:
                raise self.api_error("巡检对象类型无效。")
            if target_id <= 0:
                raise self.api_error("请选择要巡检的对象。")
            key = f"{scope_kind}:{target_id}"
            if key in seen:
                continue
            seen.add(key)
            targets.append(self._resolve_start_target(scope_kind, target_id, context))
        if not targets:
            raise self.api_error("请选择要巡检的对象。")
        return targets

    def _resolve_start_target(self, scope_kind: str, target_id: int, context: dict) -> dict:
        if scope_kind == "site":
            site = self.db.json(
                f"""
                SELECT JSON_OBJECT(
                  'id', CAST(site_id AS CHAR),
                  'name', site_name,
                  'siteType', site_type,
                  'isActive', is_active
                )
                FROM asset_site
                WHERE site_id = {target_id}
                """,
                None,
            )
            if not site:
                raise self.api_error("巡检对象不存在。")
            if not parse_bool(site.get("isActive"), True):
                raise self.conflict_error("该巡检对象已停用。")
            site_type = self.db.text(site.get("siteType"))
            site_name = self.db.text(site.get("name"))
            return {
                "scopeKind": "site",
                "siteId": self.db.integer(site.get("id"), 0),
                "siteName": site_name,
                "rackId": 0,
                "rackName": "",
                "siteType": site_type,
                "scopeLabel": f"{SITE_TYPE_LABELS.get(site_type, '机房')}·{site_name}",
            }
        rack = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(rack.rack_id AS CHAR),
              'name', rack.rack_name,
              'siteId', CAST(rack.site_id AS CHAR),
              'siteName', site.site_name,
              'siteType', site.site_type,
              'isActive', rack.is_active
            )
            FROM asset_rack rack
            JOIN asset_site site ON site.site_id = rack.site_id
            WHERE rack.rack_id = {target_id}
            """,
            None,
        )
        if not rack:
            raise self.api_error("机柜不存在。")
        if not parse_bool(rack.get("isActive"), True):
            raise self.conflict_error("该机柜已停用。")
        site_name = self.db.text(rack.get("siteName"))
        rack_name = self.db.text(rack.get("name"))
        return {
            "scopeKind": "rack",
            "siteId": self.db.integer(rack.get("siteId"), 0),
            "siteName": site_name,
            "rackId": self.db.integer(rack.get("id"), 0),
            "rackName": rack_name,
            "siteType": self.db.text(rack.get("siteType")),
            "scopeLabel": f"机柜·{site_name}/{rack_name}",
        }

    def _create_inspection_task(
        self,
        *,
        template: dict,
        items: list[dict],
        target: dict,
        batch_no: str,
        inspector_id: int,
        inspector_name: str,
        remarks: str,
        context: dict,
    ) -> dict:
        template_id = self.db.integer(template.get("id"), 0)
        scope_kind = self.db.text(target.get("scopeKind")) or "site"
        site_id = self.db.integer(target.get("siteId"), 0)
        rack_id = self.db.integer(target.get("rackId"), 0)
        site_name = self.db.text(target.get("siteName"))
        rack_name = self.db.text(target.get("rackName"))
        site_type = self.db.text(target.get("siteType"))
        task_no = self._next_task_no()
        item_values = []
        for item in items:
            item_values.append(
                "("
                + ", ".join(
                    [
                        "@new_task_id",
                        str(self.db.integer(item.get("seqNo"), 10)),
                        self.db.quote(self.db.text(item.get("category")) or "通用"),
                        self.db.quote(self.db.text(item.get("title"))),
                        self.db.quote(self.db.text(item.get("checkMethod"))),
                        self.db.quote(self.db.text(item.get("valueType")) or "ok_fail"),
                        self.db.quote(self.db.text(item.get("unit"))),
                        self.db.quote(self.db.text(item.get("normalRange"))),
                        str(1 if parse_bool(item.get("isRequired", True), True) else 0),
                    ]
                )
                + ")"
            )
        output = self.db.execute(
            f"""
            START TRANSACTION;
            INSERT INTO inspection_task (
              task_no, batch_no, template_id, template_name, scope_kind, site_id, site_name,
              site_type, rack_id, rack_name, inspector_user_id, inspector_name, status,
              item_total, remarks
            )
            VALUES (
              {self.db.quote(task_no)},
              {self.db.quote(batch_no)},
              {template_id},
              {self.db.quote(self.db.text(template.get('name')))},
              {self.db.quote(scope_kind)},
              {site_id if site_id > 0 else 'NULL'},
              {self.db.quote(site_name)},
              {self.db.quote(site_type)},
              {rack_id if rack_id > 0 else 'NULL'},
              {self.db.quote(rack_name)},
              {inspector_id if inspector_id > 0 else 'NULL'},
              {self.db.quote(inspector_name)},
              'running',
              {len(items)},
              {self.db.quote(remarks)}
            );
            SET @new_task_id = LAST_INSERT_ID();
            INSERT INTO inspection_task_item (
              task_id, seq_no, category, item_title, check_method, value_type, unit, normal_range,
              is_required
            ) VALUES {", ".join(item_values)};
            {self._audit_sql(
                "inspection_started",
                "inspection_task",
                "'new'",
                task_no,
                f"开始巡检：{task_no} / {target.get('scopeLabel')}",
                context,
                None,
                {
                    "taskNo": task_no,
                    "batchNo": batch_no,
                    "templateId": str(template_id),
                    "scopeKind": scope_kind,
                    "siteId": str(site_id) if site_id > 0 else "",
                    "rackId": str(rack_id) if rack_id > 0 else "",
                    "itemTotal": len(items),
                },
            )};
            UPDATE audit_log
            SET entity_id = CAST(@new_task_id AS CHAR)
            WHERE audit_log_id = LAST_INSERT_ID();
            SELECT @new_task_id;
            COMMIT;
            """
        )
        task_id = self._last_int(output)
        if task_id <= 0:
            raise self.conflict_error("巡检任务创建失败，请重试。")
        return {
            "id": str(task_id),
            "taskNo": task_no,
            "itemTotal": len(items),
            "scopeKind": scope_kind,
            "scopeLabel": self.db.text(target.get("scopeLabel")),
            "siteName": site_name,
            "rackName": rack_name,
            "siteType": site_type,
        }

    # ------------------------------------------------------------------ 表格导入

    @staticmethod
    def _import_key(value: str) -> str:
        return re.sub(r"[\s_\-/（）()]", "", (value or "").strip().lower())

    def _map_import_headers(self, header_row: list[str]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for index, raw in enumerate(header_row):
            key = self._import_key(raw)
            if not key:
                continue
            for field, aliases in IMPORT_HEADER_ALIASES.items():
                if field in mapping:
                    continue
                if key in {self._import_key(alias) for alias in aliases}:
                    mapping[field] = index
                    break
        return mapping

    @staticmethod
    def _import_cell(row: list[str], index: int | None) -> str:
        if index is None or index >= len(row):
            return ""
        return (row[index] or "").strip()

    def _read_import_rows(self, file_name: str, data: bytes) -> list[list[str]]:
        if len(data) > MAX_IMPORT_BYTES:
            raise self.api_error(f"文件过大（上限 {MAX_IMPORT_BYTES // (1024 * 1024)}MB）。")
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

    def import_task(self, payload: dict, context: dict) -> dict:
        """按模板导入巡检表：一次生成一份"已提交"的巡检记录。

        表头：机房、机柜（可空，空则按机房巡检）、检查项分类、检查项、检查方法、结论、实测值、说明。
        结论文案支持 正常 / 异常 / 不适用（也接受 ok / fail / na）。
        """
        file_name = self.db.text(payload.get("fileName"))[:200]
        content = self.db.text(payload.get("contentBase64"))
        if not content:
            raise self.api_error("请上传 .xlsx 或 .csv 巡检表。")
        try:
            data = base64.b64decode(content, validate=True)
        except (ValueError, TypeError) as exc:
            raise self.api_error("文件内容不是合法的 base64 编码。") from exc
        rows = self._read_import_rows(file_name, data)
        if not rows:
            raise self.api_error("文件里没有可读取的内容。")

        header_index = 0
        mapping: dict[str, int] = {}
        for index, row in enumerate(rows[:10]):
            candidate = self._map_import_headers(row)
            if len(candidate) >= 2:
                header_index, mapping = index, candidate
                break
        if not mapping:
            raise self.api_error(
                "没有识别到表头。请用「下载模板」生成表头："
                + "、".join(IMPORT_COLUMNS)
                + "。"
            )
        required = {"site": "机房", "title": "检查项", "result": "结论"}
        missing = [label for key, label in required.items() if key not in mapping]
        if missing:
            raise self.api_error(f"表头缺少：{'、'.join(missing)}。")

        data_rows = [
            row for row in rows[header_index + 1 :] if any((cell or "").strip() for cell in row)
        ]
        if not data_rows:
            raise self.api_error("表头下面没有数据行。")
        if len(data_rows) > MAX_IMPORT_ROWS:
            raise self.api_error(f"一次最多导入 {MAX_IMPORT_ROWS} 行，请拆分文件。")

        errors: list[dict] = []
        items: list[dict] = []
        site_name = ""
        rack_name = ""
        for offset, row in enumerate(data_rows):
            excel_row = header_index + 2 + offset
            row_site = self._import_cell(row, mapping.get("site"))
            row_rack = self._import_cell(row, mapping.get("rack"))
            title = self._import_cell(row, mapping.get("title"))
            result_raw = self._import_cell(row, mapping.get("result"))
            notes = self._import_cell(row, mapping.get("notes"))[:500]
            if not title:
                errors.append({"row": excel_row, "message": "缺少检查项"})
                continue
            if not row_site:
                errors.append({"row": excel_row, "message": "缺少机房名称"})
                continue
            if site_name and row_site != site_name:
                errors.append({"row": excel_row, "message": f"与首行的巡检对象「{site_name}」不一致"})
                continue
            if rack_name and row_rack and row_rack != rack_name:
                errors.append({"row": excel_row, "message": f"与首行的机柜「{rack_name}」不一致"})
                continue
            result = IMPORT_RESULT_ALIASES.get(result_raw.lower() if result_raw.isascii() else result_raw)
            if not result:
                errors.append({"row": excel_row, "message": f"结论「{result_raw}」无法识别（可用：正常/异常/不适用）"})
                continue
            if result == "fail" and not notes:
                errors.append({"row": excel_row, "message": "异常项必须填写说明"})
                continue
            site_name = site_name or row_site
            rack_name = rack_name or row_rack
            items.append(
                {
                    "category": self._import_cell(row, mapping.get("category"))[:64] or "通用",
                    "title": title[:200],
                    "checkMethod": self._import_cell(row, mapping.get("checkMethod"))[:255],
                    "valueText": self._import_cell(row, mapping.get("valueText"))[:255],
                    "notes": notes,
                    "result": result,
                }
            )

        if not items:
            raise self.api_error("没有可导入的巡检项，请检查表格内容。")

        site = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(site_id AS CHAR),
              'name', site_name,
              'siteType', site_type,
              'orgId', COALESCE(CAST(org_unit_id AS CHAR), '')
            )
            FROM asset_site
            WHERE site_name = {self.db.quote(site_name)} AND is_active = 1
            LIMIT 1
            """,
            None,
        )
        if not site:
            raise self.api_error(
                f"巡检对象「{site_name}」不存在，请先在「巡检对象」或「会议室」里创建。"
            )
        site_id = self.db.integer(site.get("id"), 0)
        site_type = self.db.text(site.get("siteType"))
        self.scope.assert_org_access(context, self.db.integer(site.get("orgId"), 0))

        scope_kind = "site"
        rack_id = 0
        if rack_name:
            rack = self.db.json(
                f"""
                SELECT JSON_OBJECT('id', CAST(rack_id AS CHAR), 'name', rack_name)
                FROM asset_rack
                WHERE rack_name = {self.db.quote(rack_name)}
                  AND site_id = {site_id}
                  AND is_active = 1
                LIMIT 1
                """,
                None,
            )
            if not rack:
                raise self.api_error(f"机柜「{rack_name}」不在 {site_name} 下，请先创建或核对名称。")
            scope_kind = "rack"
            rack_id = self.db.integer(rack.get("id"), 0)

        inspector_id = self._actor_id(context)
        inspector_name = self._actor_name(context)
        task_no = self._next_task_no()
        fails = [item for item in items if item["result"] == "fail"]
        na_items = [item for item in items if item["result"] == "na"]
        ok_items = [item for item in items if item["result"] == "ok"]
        summary = "；".join(f"{item['title']}：{item['notes']}" for item in fails)[:1000]
        remarks = self.db.text(payload.get("remarks"))[:500] or f"由表格导入：{file_name}"
        item_values = []
        for index, item in enumerate(items, start=1):
            item_values.append(
                "("
                + ", ".join(
                    [
                        "@new_task_id",
                        str(index * 10),
                        self.db.quote(item["category"]),
                        self.db.quote(item["title"]),
                        self.db.quote(item["checkMethod"]),
                        "'ok_fail'",
                        "''",
                        "''",
                        "1",
                        self.db.quote(item["result"]),
                        self.db.quote(item["valueText"]),
                        self.db.quote(item["notes"]),
                        "1" if item["result"] == "fail" else "0",
                        "NOW()",
                        str(inspector_id) if inspector_id > 0 else "NULL",
                        self.db.quote(inspector_name),
                    ]
                )
                + ")"
            )
        output = self.db.execute(
            f"""
            START TRANSACTION;
            INSERT INTO inspection_task (
              task_no, template_id, template_name, scope_kind, site_id, site_name,
              rack_id, rack_name, inspector_user_id, inspector_name, status,
              submitted_at, item_total, item_ok, item_fail, item_na, abnormal_summary, remarks
            )
            VALUES (
              {self.db.quote(task_no)},
              NULL,
              '表格导入',
              {self.db.quote(scope_kind)},
              {site_id},
              {self.db.quote(site_name)},
              {rack_id if rack_id > 0 else 'NULL'},
              {self.db.quote(rack_name)},
              {inspector_id if inspector_id > 0 else 'NULL'},
              {self.db.quote(inspector_name)},
              'submitted',
              NOW(),
              {len(items)},
              {len(ok_items)},
              {len(fails)},
              {len(na_items)},
              {self.db.quote(summary)},
              {self.db.quote(remarks)}
            );
            SET @new_task_id = LAST_INSERT_ID();
            INSERT INTO inspection_task_item (
              task_id, seq_no, category, item_title, check_method, value_type, unit, normal_range,
              is_required, result, value_text, notes, is_abnormal, checked_at,
              checked_by_user_id, checked_by_name
            ) VALUES {", ".join(item_values)};
            {self._audit_sql(
                "inspection_imported",
                "inspection_task",
                "'new'",
                task_no,
                f"导入巡检表：{task_no} / {site_name}{rack_name}",
                context,
                None,
                {
                    "taskNo": task_no,
                    "fileName": file_name,
                    "siteName": site_name,
                    "rackName": rack_name,
                    "itemTotal": len(items),
                    "itemFail": len(fails),
                },
            )};
            UPDATE audit_log
            SET entity_id = CAST(@new_task_id AS CHAR)
            WHERE audit_log_id = LAST_INSERT_ID();
            SELECT @new_task_id;
            COMMIT;
            """
        )
        task_id = self._last_int(output)
        if task_id <= 0:
            raise self.conflict_error("巡检表导入失败，请重试。")
        return {
            "id": str(task_id),
            "taskNo": task_no,
            "siteName": site_name,
            "rackName": rack_name,
            "siteType": site_type,
            "itemTotal": len(items),
            "itemOk": len(ok_items),
            "itemFail": len(fails),
            "itemNa": len(na_items),
            "errors": errors[:50],
            "errorCount": len(errors),
        }

    def _task_items(self, task_id: int) -> list[dict]:
        return list(
            self.db.json(
                f"""
                SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
                  'id', CAST(task_item_id AS CHAR),
                  'seqNo', seq_no,
                  'category', category,
                  'title', item_title,
                  'checkMethod', check_method,
                  'valueType', value_type,
                  'unit', unit,
                  'normalRange', normal_range,
                  'isRequired', is_required,
                  'result', result,
                  'valueText', value_text,
                  'notes', notes,
                  'isAbnormal', is_abnormal,
                  'checkedAt', COALESCE(CAST(checked_at AS CHAR), ''),
                  'checkedByName', checked_by_name
                )), JSON_ARRAY())
                FROM (
                  SELECT *
                  FROM inspection_task_item
                  WHERE task_id = {task_id}
                  ORDER BY seq_no, task_item_id
                ) item
                """,
                [],
            )
            or []
        )

    def get_task(self, task_id: object, context: dict) -> dict:
        task_id_int = self.db.integer(task_id, 0)
        task = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(task.task_id AS CHAR),
              'taskNo', task.task_no,
              'batchNo', task.batch_no,
              'templateId', COALESCE(CAST(task.template_id AS CHAR), ''),
              'templateName', task.template_name,
              'scopeKind', task.scope_kind,
              'siteId', COALESCE(CAST(task.site_id AS CHAR), ''),
              'siteName', task.site_name,
              'rackId', COALESCE(CAST(task.rack_id AS CHAR), ''),
              'rackName', task.rack_name,
              'inspectorUserId', COALESCE(CAST(task.inspector_user_id AS CHAR), ''),
              'inspectorName', task.inspector_name,
              'status', task.status,
              'startedAt', COALESCE(CAST(task.started_at AS CHAR), ''),
              'submittedAt', COALESCE(CAST(task.submitted_at AS CHAR), ''),
              'itemTotal', task.item_total,
              'itemOk', task.item_ok,
              'itemFail', task.item_fail,
              'itemNa', task.item_na,
              'abnormalSummary', task.abnormal_summary,
              'remarks', task.remarks,
              -- 对象类型优先用开始巡检时的快照，对象被删掉后仍能显示
              'siteType', COALESCE(NULLIF(task.site_type, ''), site.site_type, '')
            )
            FROM inspection_task task
            LEFT JOIN asset_site site ON site.site_id = task.site_id
            WHERE task.task_id = {task_id_int}
            """,
            None,
        )
        if not task:
            raise self.api_error("巡检任务不存在。")
        task["items"] = self._task_items(task_id_int)
        return task

    def check_item(
        self,
        task_id: object,
        item_id: object,
        payload: dict,
        context: dict,
    ) -> dict:
        task = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(task_id AS CHAR),
              'taskNo', task_no,
              'status', status
            )
            FROM inspection_task
            WHERE task_id = {self.db.integer(task_id, 0)}
            """,
            None,
        )
        if not task:
            raise self.api_error("巡检任务不存在。")
        if self.db.text(task.get("status")) != "running":
            raise self.conflict_error("该巡检任务已提交或已作废，不能再修改。")
        result = self.db.text(payload.get("result"))
        if result not in CHECK_RESULTS - {"pending"}:
            raise self.api_error("巡检结论必须是正常、异常或不适用。")
        notes = self.db.text(payload.get("notes"))[:500]
        if result == "fail" and not notes:
            raise self.api_error("异常项必须填写说明。")
        value_text = self.db.text(payload.get("valueText"))[:255]
        item_id_int = self.db.integer(item_id, 0)
        actor_id = self._actor_id(context)
        actor_name = self._actor_name(context)
        is_abnormal = 1 if result == "fail" else 0
        output = self.db.execute(
            f"""
            START TRANSACTION;
            UPDATE inspection_task_item
            SET result = {self.db.quote(result)},
                value_text = {self.db.quote(value_text)},
                notes = {self.db.quote(notes)},
                is_abnormal = {is_abnormal},
                checked_at = CURRENT_TIMESTAMP,
                checked_by_user_id = {actor_id if actor_id > 0 else 'NULL'},
                checked_by_name = {self.db.quote(actor_name)}
            WHERE task_item_id = {item_id_int}
              AND task_id = {self.db.integer(task.get('id'), 0)};
            SET @checked_rows = ROW_COUNT();
            UPDATE inspection_task task
            SET item_ok = (
                  SELECT COUNT(*) FROM inspection_task_item item
                  WHERE item.task_id = task.task_id AND item.result = 'ok'
                ),
                item_fail = (
                  SELECT COUNT(*) FROM inspection_task_item item
                  WHERE item.task_id = task.task_id AND item.result = 'fail'
                ),
                item_na = (
                  SELECT COUNT(*) FROM inspection_task_item item
                  WHERE item.task_id = task.task_id AND item.result = 'na'
                )
            WHERE task.task_id = {self.db.integer(task.get('id'), 0)}
              AND @checked_rows > 0;
            SELECT @checked_rows;
            COMMIT;
            """
        )
        updated = self._last_int(output)
        if updated <= 0:
            raise self.api_error("巡检事项不存在。")
        return {"taskId": str(task.get("id")), "itemId": str(item_id_int), "result": result}

    def submit_task(self, task_id: object, payload: dict, context: dict) -> dict:
        task = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(task_id AS CHAR),
              'taskNo', task_no,
              'status', status,
              'itemTotal', item_total,
              'siteName', site_name,
              'rackName', rack_name
            )
            FROM inspection_task
            WHERE task_id = {self.db.integer(task_id, 0)}
            """,
            None,
        )
        if not task:
            raise self.api_error("巡检任务不存在。")
        if self.db.text(task.get("status")) == "submitted":
            raise self.conflict_error("该巡检任务已经提交。")
        if self.db.text(task.get("status")) != "running":
            raise self.conflict_error("该巡检任务已作废，不能提交。")

        items = self._task_items(self.db.integer(task.get("id"), 0))
        if not items:
            raise self.conflict_error("该巡检任务没有巡检事项。")
        pending = [item for item in items if self.db.text(item.get("result")) == "pending"]
        if pending:
            names = "、".join(
                f"第 {self.db.integer(item.get('seqNo'), 0)} 项 {self.db.text(item.get('title'))}"
                for item in pending[:5]
            )
            suffix = f" 等 {len(pending)} 项" if len(pending) > 5 else ""
            raise self.conflict_error(
                f"还有 {len(pending)} 项未检查，请补全后再提交：{names}{suffix}"
                "（填写实测值或说明后，还需要点该行的正常 / 异常 / 不适用，或点保存）。"
            )
        missing_notes = [
            item for item in items if self.db.text(item.get("result")) == "fail" and not self.db.text(item.get("notes"))
        ]
        if missing_notes:
            names = "、".join(
                f"第 {self.db.integer(item.get('seqNo'), 0)} 项 {self.db.text(item.get('title'))}"
                for item in missing_notes[:5]
            )
            raise self.api_error(f"有 {len(missing_notes)} 个异常项未填写说明，请补全后再提交：{names}")

        fails = [item for item in items if self.db.text(item.get("result")) == "fail"]
        na_items = [item for item in items if self.db.text(item.get("result")) == "na"]
        ok_items = [item for item in items if self.db.text(item.get("result")) == "ok"]
        summary = self.db.text(payload.get("abnormalSummary"))[:1000]
        if not summary and fails:
            summary = "；".join(
                f"{self.db.text(item.get('title'))}：{self.db.text(item.get('notes'))}" for item in fails
            )[:1000]
        remarks = self.db.text(payload.get("remarks"))[:500]
        task_id_int = self.db.integer(task.get("id"), 0)
        output = self.db.execute(
            f"""
            START TRANSACTION;
            UPDATE inspection_task
            SET status = 'submitted',
                submitted_at = CURRENT_TIMESTAMP,
                item_total = {len(items)},
                item_ok = {len(ok_items)},
                item_fail = {len(fails)},
                item_na = {len(na_items)},
                abnormal_summary = {self.db.quote(summary)},
                remarks = {self.db.quote(remarks)}
            WHERE task_id = {task_id_int}
              AND status = 'running';
            SET @submitted_rows = ROW_COUNT();
            {self._conditional_audit_sql(
                "inspection_submitted",
                "inspection_task",
                str(task_id_int),
                self.db.text(task.get("taskNo")),
                f"提交巡检：{self.db.text(task.get('taskNo'))}，异常 {len(fails)} 项",
                context,
                "@submitted_rows > 0",
                None,
                {
                    "itemTotal": len(items),
                    "itemOk": len(ok_items),
                    "itemFail": len(fails),
                    "itemNa": len(na_items),
                },
            )};
            SELECT @submitted_rows;
            COMMIT;
            """
        )
        if self._last_int(output) <= 0:
            raise self.conflict_error("该巡检任务已经提交或已作废。")
        return {
            "id": str(task_id_int),
            "taskNo": self.db.text(task.get("taskNo")),
            "itemTotal": len(items),
            "itemOk": len(ok_items),
            "itemFail": len(fails),
            "itemNa": len(na_items),
        }

    def void_task(self, task_id: object, payload: dict, context: dict) -> dict:
        task_id_int = self.db.integer(task_id, 0)
        task = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(task_id AS CHAR),
              'taskNo', task_no,
              'status', status
            )
            FROM inspection_task
            WHERE task_id = {task_id_int}
            """,
            None,
        )
        if not task:
            raise self.api_error("巡检任务不存在。")
        if self.db.text(task.get("status")) == "submitted":
            raise self.conflict_error("已提交的巡检表不能作废。")
        reason = self.db.text(payload.get("reason"))[:500]
        if not reason:
            raise self.api_error("作废巡检任务必须填写原因。")
        output = self.db.execute(
            f"""
            START TRANSACTION;
            UPDATE inspection_task
            SET status = 'void',
                remarks = {self.db.quote(reason)}
            WHERE task_id = {task_id_int}
              AND status = 'running';
            SET @voided_rows = ROW_COUNT();
            {self._conditional_audit_sql(
                "inspection_voided",
                "inspection_task",
                str(task_id_int),
                self.db.text(task.get("taskNo")),
                f"作废巡检：{self.db.text(task.get('taskNo'))}，原因：{reason}",
                context,
                "@voided_rows > 0",
                {"status": self.db.text(task.get("status"))},
                {"status": "void", "reason": reason},
            )};
            SELECT @voided_rows;
            COMMIT;
            """
        )
        if self._last_int(output) <= 0:
            raise self.conflict_error("该巡检任务已提交或已作废。")
        return {"id": str(task_id_int), "taskNo": self.db.text(task.get("taskNo")), "status": "void"}

    def delete_task(self, task_id: object, payload: dict, context: dict) -> dict:
        """删除**已作废**的巡检任务及其明细；未作废的任务必须先作废再删除。

        已提交的巡检表属于历史记录，既不能作废也不能删除。
        """
        task_id_int = self.db.integer(task_id, 0)
        task = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(task_id AS CHAR),
              'taskNo', task_no,
              'batchNo', batch_no,
              'status', status
            )
            FROM inspection_task
            WHERE task_id = {task_id_int}
            """,
            None,
        )
        if not task:
            raise self.api_error("巡检任务不存在。")
        status = self.db.text(task.get("status"))
        if status != "void":
            raise self.conflict_error("只有已作废的巡检任务才能删除，请先作废。")
        task_no = self.db.text(task.get("taskNo"))
        item_count = self.db.integer(
            self.db.scalar(
                f"SELECT COUNT(*) FROM inspection_task_item WHERE task_id = {task_id_int};"
            ),
            0,
        )
        reason = self.db.text(payload.get("reason"))[:200]
        output = self.db.execute(
            f"""
            START TRANSACTION;
            {self._audit_sql(
                "inspection_task_deleted",
                "inspection_task",
                str(task_id_int),
                task_no,
                f"删除已作废的巡检任务：{task_no}（{item_count} 项）"
                + (f"，原因：{reason}" if reason else ""),
                context,
                {
                    "status": status,
                    "itemCount": item_count,
                    "batchNo": self.db.text(task.get("batchNo")),
                },
                None,
            )};
            DELETE FROM inspection_task
            WHERE task_id = {task_id_int}
              AND status = 'void';
            SELECT ROW_COUNT();
            COMMIT;
            """
        )
        if self._last_int(output) <= 0:
            raise self.conflict_error("该巡检任务状态已变化，请刷新后重试。")
        return {"id": str(task_id_int), "taskNo": task_no, "deleted": True}
