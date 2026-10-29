from __future__ import annotations

from dataclasses import dataclass

from .scope import OrganizationScopeService
from .sql import SqlGateway, parse_bool


@dataclass
class CompanyService:
    """集团多公司：公司 CRUD、组织树、组织子树转移、员工多职位。"""

    db: SqlGateway
    scope: OrganizationScopeService
    api_error: type[Exception]
    conflict_error: type[Exception]
    forbidden_error: type[Exception]

    # ------------------------------------------------------------------ 公司
    def list_companies(self, context: dict) -> list[dict]:
        rows = self.db.json(
            """
            SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
              'id', CAST(company_id AS CHAR),
              'code', company_code,
              'name', company_name,
              'sortOrder', sort_order,
              'isActive', is_active
            )), JSON_ARRAY())
            FROM (
              SELECT company_id, company_code, company_name, sort_order, is_active
              FROM company
              ORDER BY sort_order, company_id
            ) ordered_companies
            """,
            [],
        )
        return list(rows or [])

    def company(self, company_id: object) -> dict | None:
        company_id_int = self.db.integer(company_id, 0)
        if company_id_int <= 0:
            return None
        return self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(company_id AS CHAR),
              'code', company_code,
              'name', company_name,
              'sortOrder', sort_order,
              'isActive', is_active
            )
            FROM company
            WHERE company_id = {company_id_int}
            LIMIT 1
            """,
            None,
        )

    def save_company(self, company_id: object | None, payload: dict, context: dict) -> dict:
        if not parse_bool(context.get("isSuperAdmin")):
            raise self.forbidden_error("只有超级管理员可以管理公司。")
        company_id_int = self.db.integer(company_id, 0)
        code = self.db.text(payload.get("code")).strip().upper()
        name = self.db.text(payload.get("name")).strip()
        sort_order = self.db.integer(payload.get("sortOrder"), 1000)
        is_active = 1 if parse_bool(payload.get("isActive"), True) else 0
        if not name:
            raise self.api_error("公司名称不能为空。")
        if not code:
            code = self._generated_company_code(name)
        existing = self.db.scalar(
            f"""
            SELECT company_id FROM company
            WHERE company_code = {self.db.quote(code)}
              AND company_id <> {company_id_int}
            LIMIT 1
            """
        )
        if existing:
            raise self.conflict_error("公司编码已经存在。")
        if company_id_int > 0:
            if not self.company(company_id_int):
                raise self.api_error("公司不存在。")
            self.db.execute(
                f"""
                UPDATE company
                SET company_code = {self.db.quote(code)},
                    company_name = {self.db.quote(name)},
                    sort_order = {sort_order},
                    is_active = {is_active}
                WHERE company_id = {company_id_int};
                """
            )
        else:
            company_id_int = self.db.one_id(
                f"""
                INSERT INTO company (company_code, company_name, sort_order, is_active)
                VALUES ({self.db.quote(code)}, {self.db.quote(name)}, {sort_order}, {is_active});
                SELECT LAST_INSERT_ID();
                """
            )
        return dict(self.company(company_id_int) or {})

    def _generated_company_code(self, name: str) -> str:
        ascii_text = "".join(c for c in name if c.isascii() and c.isalnum()).upper()
        if ascii_text:
            return ascii_text[:16] or "CMP"
        return "CMP"

    def delete_company(self, company_id: object, context: dict) -> dict:
        if not parse_bool(context.get("isSuperAdmin")):
            raise self.forbidden_error("只有超级管理员可以管理公司。")
        company_id_int = self.db.integer(company_id, 0)
        if company_id_int <= 0 or not self.company(company_id_int):
            raise self.api_error("公司不存在。")
        org_count = self.db.scalar(
            f"SELECT COUNT(*) FROM org_unit WHERE company_id = {company_id_int};"
        )
        if org_count > 0:
            raise self.conflict_error("该公司下仍有组织，请先转移或删除其组织架构。")
        self.db.execute(f"UPDATE company SET is_active = 0 WHERE company_id = {company_id_int};")
        return {"id": company_id_int, "deleted": True}

    # ---------------------------------------------------------------- 组织树
    def org_tree(self, context: dict, company_id: object = "") -> dict:
        company_filter = ""
        company_id_int = self.db.integer(company_id, 0)
        if company_id_int > 0:
            company_filter = f"WHERE company_id = {company_id_int}"
        org_rows = self.db.json(
            f"""
            SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
              'id', CAST(org_unit_id AS CHAR),
              'code', org_code,
              'name', org_name,
              'parentId', COALESCE(CAST(parent_org_unit_id AS CHAR), ''),
              'companyId', COALESCE(CAST(company_id AS CHAR), ''),
              'sortOrder', sort_order,
              'isActive', is_active
            )), JSON_ARRAY())
            FROM (
              SELECT org_unit_id, org_code, org_name, parent_org_unit_id, company_id, sort_order, is_active
              FROM org_unit
              {company_filter}
              ORDER BY sort_order, org_unit_id
            ) ordered_orgs
            """,
            [],
        )
        return {
            "companies": self.list_companies(context),
            "organizations": list(org_rows or []),
        }

    # -------------------------------------------------- 组织子树转移（建分公司）
    def _all_org_rows(self) -> list[dict]:
        rows = self.db.json(
            """
            SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
              'id', org_unit_id,
              'parentId', COALESCE(parent_org_unit_id, 0)
            )), JSON_ARRAY())
            FROM org_unit
            """,
            [],
        )
        return list(rows or [])

    def _subtree_org_ids(self, org_ids: set[int]) -> set[int]:
        children: dict[int, list[int]] = {}
        for row in self._all_org_rows():
            parent_id = self.db.integer(row.get("parentId"), 0)
            org_id = self.db.integer(row.get("id"), 0)
            children.setdefault(parent_id, []).append(org_id)
        result: set[int] = set()
        queue = list(org_ids)
        while queue:
            current = queue.pop()
            if current in result:
                continue
            result.add(current)
            queue.extend(children.get(current, []))
        return result

    def transfer_org_subtree(self, payload: dict, context: dict) -> dict:
        """把若干组织子树（含其下员工/终端/仓库/机房设备）划归目标公司。"""
        if not parse_bool(context.get("isSuperAdmin")):
            raise self.forbidden_error("只有超级管理员可以转移组织架构。")
        target_company_id = self.db.integer(payload.get("targetCompanyId"), 0)
        if target_company_id <= 0 or not self.company(target_company_id):
            raise self.api_error("目标公司不存在。")
        raw_ids = payload.get("orgUnitIds")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise self.api_error("请选择要转移的组织。")
        org_ids = {self.db.integer(v, 0) for v in raw_ids if self.db.integer(v, 0) > 0}
        if not org_ids:
            raise self.api_error("请选择要转移的组织。")
        subtree = self._subtree_org_ids(org_ids)
        id_list = ", ".join(str(i) for i in sorted(subtree))
        move_employees = parse_bool(payload.get("moveEmployees"), True)
        move_computers = parse_bool(payload.get("moveComputers"), True)
        move_warehouses = parse_bool(payload.get("moveWarehouses"), True)
        move_datacenter = parse_bool(payload.get("moveDatacenter"), True)

        statements = [
            "START TRANSACTION",
            f"UPDATE org_unit SET company_id = {target_company_id} WHERE org_unit_id IN ({id_list});",
        ]
        if move_employees:
            statements.append(
                f"UPDATE employee_position SET company_id = {target_company_id} WHERE org_unit_id IN ({id_list});"
            )
        if move_computers:
            statements.append(
                f"UPDATE computer_asset SET company_id = {target_company_id} WHERE org_unit_id IN ({id_list});"
            )
        if move_warehouses:
            statements.append(
                f"UPDATE inventory_warehouse SET company_id = {target_company_id} WHERE org_unit_id IN ({id_list});"
            )
        if move_datacenter:
            statements.append(
                f"UPDATE asset_site SET company_id = {target_company_id} WHERE org_unit_id IN ({id_list});"
            )
            statements.append(
                f"UPDATE asset_rack SET company_id = {target_company_id} WHERE org_unit_id IN ({id_list});"
            )
            statements.append(
                f"UPDATE datacenter_device SET company_id = {target_company_id} WHERE org_unit_id IN ({id_list});"
            )
            statements.append(
                """
                UPDATE site_device sd
                JOIN asset_site s ON s.site_id = sd.site_id
                SET sd.company_id = s.company_id
                WHERE s.org_unit_id IN (%s);
                """.replace("%s", id_list)
            )
        statements.append("COMMIT")
        self.db.execute(";\n".join(statements) + ";")
        return {
            "targetCompanyId": target_company_id,
            "movedOrganizations": len(subtree),
            "organizations": self.org_tree(context),
        }

    # ------------------------------------------------------------ 单资产调拨
    def _transfer_no(self) -> str:
        import secrets
        from datetime import datetime

        return "TRF-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(4).upper()

    def transfer_asset(self, payload: dict, context: dict) -> dict:
        """把单台资产（办公终端/机房设备）调拨到目标公司/组织。免审批、留审计。"""
        asset_kind = self.db.text(payload.get("assetKind")).strip()
        if asset_kind not in {"computer", "datacenter_device"}:
            raise self.api_error("不支持的调拨类型。")
        asset_id = self.db.integer(payload.get("assetId"), 0)
        target_company_id = self.db.integer(payload.get("targetCompanyId"), 0)
        target_org_unit_id = self.db.integer(payload.get("targetOrgUnitId"), 0)
        if asset_id <= 0:
            raise self.api_error("请选择要调拨的资产。")
        if target_company_id <= 0 or not self.company(target_company_id):
            raise self.api_error("目标公司不存在。")
        note = self.db.text(payload.get("note")).strip()

        table = "computer_asset" if asset_kind == "computer" else "datacenter_device"
        id_col = "computer_id" if asset_kind == "computer" else "device_id"
        if self.db.scalar(f"SELECT COUNT(*) FROM {table} WHERE {id_col} = {asset_id};") != 1:
            raise self.api_error("资产不存在。")
        source_company_id = self.db.scalar(
            f"SELECT COALESCE(company_id, 0) FROM {table} WHERE {id_col} = {asset_id};"
        )
        source_org_unit_id = self.db.scalar(
            f"SELECT COALESCE(org_unit_id, 0) FROM {table} WHERE {id_col} = {asset_id};"
        )
        if source_company_id == target_company_id:
            raise self.api_error("该资产已在目标公司名下。")
        allowed = self.scope.scoped_company_ids(context)
        if allowed is not None and source_company_id not in allowed:
            raise self.forbidden_error("没有权限调拨该资产。")

        target_org_sql = str(target_org_unit_id) if target_org_unit_id > 0 else "NULL"
        source_org_sql = str(source_org_unit_id) if source_org_unit_id > 0 else "NULL"
        if asset_kind == "computer":
            update_sql = (
                f"UPDATE computer_asset SET company_id = {target_company_id}, "
                f"org_unit_id = {target_org_sql} WHERE computer_id = {asset_id}"
            )
        else:
            # 机房设备调拨：先下架（清空机柜/机房、置为未上架），再改归属
            update_sql = (
                f"UPDATE datacenter_device SET company_id = {target_company_id}, "
                f"org_unit_id = {target_org_sql}, rack_id = NULL, site_id = NULL, "
                f"status = 'stock' WHERE device_id = {asset_id}"
            )
        transfer_no = self._transfer_no()
        statements = [
            "START TRANSACTION",
            update_sql,
            "INSERT INTO asset_transfer_record ("
            "transfer_no, asset_kind, asset_id, source_company_id, target_company_id, "
            "source_org_unit_id, target_org_unit_id, quantity, note, created_by"
            ") VALUES ("
            + self.db.quote(transfer_no)
            + ", " + self.db.quote(asset_kind)
            + ", " + str(asset_id)
            + ", " + str(source_company_id)
            + ", " + str(target_company_id)
            + ", " + source_org_sql
            + ", " + target_org_sql
            + ", 1, " + self.db.quote(note)
            + ", " + str(self.db.integer(context.get("id"), 0))
            + ")",
            "COMMIT",
        ]
        self.db.execute(";\n".join(statements) + ";")
        return {
            "transferNo": transfer_no,
            "assetKind": asset_kind,
            "assetId": asset_id,
            "targetCompanyId": target_company_id,
        }

    # ------------------------------------------------------------ 员工多职位
    def list_positions(self, employee_id: object, _context: dict) -> list[dict]:
        employee_id_int = self.db.integer(employee_id, 0)
        if employee_id_int <= 0:
            return []
        rows = self.db.json(
            f"""
            SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
              'id', CAST(position_id AS CHAR),
              'companyId', CAST(company_id AS CHAR),
              'companyName', company_name,
              'orgUnitId', COALESCE(CAST(org_unit_id AS CHAR), ''),
              'orgName', org_name,
              'department', department,
              'positionName', position_name,
              'isPrimary', is_primary,
              'isActive', is_active
            )), JSON_ARRAY())
            FROM (
              SELECT
                ep.position_id, ep.company_id, c.company_name,
                ep.org_unit_id, o.org_name, ep.department, ep.position_name,
                ep.is_primary, ep.is_active
              FROM employee_position ep
              LEFT JOIN company c ON c.company_id = ep.company_id
              LEFT JOIN org_unit o ON o.org_unit_id = ep.org_unit_id
              WHERE ep.employee_id = {employee_id_int}
              ORDER BY ep.is_primary DESC, ep.sort_order, ep.position_id
            ) ordered_positions
            """,
            [],
        )
        return list(rows or [])

    def save_positions(self, employee_id: object, payload: dict, context: dict) -> list[dict]:
        employee_id_int = self.db.integer(employee_id, 0)
        if employee_id_int <= 0:
            raise self.api_error("人员不存在。")
        exists = self.db.scalar(
            f"SELECT COUNT(*) FROM employee WHERE employee_id = {employee_id_int};"
        )
        if exists != 1:
            raise self.api_error("人员不存在。")
        items = payload.get("positions")
        if not isinstance(items, list) or not items:
            raise self.api_error("至少需要一个职位。")

        primary_company = 0
        primary_org = 0
        primary_department = ""
        primary_position = ""
        values: list[str] = []
        primary_count = 0
        for item in items:
            is_primary = parse_bool(item.get("isPrimary"), False)
            company_id = self.db.integer(item.get("companyId"), 0)
            org_unit_id = self.db.integer(item.get("orgUnitId"), 0)
            department = self.db.text(item.get("department")).strip()
            position_name = self.db.text(item.get("positionName")).strip()
            if company_id <= 0:
                # 公司可由组织推导
                if org_unit_id > 0:
                    company_id = self.db.scalar(
                        f"SELECT COALESCE(company_id, 0) FROM org_unit WHERE org_unit_id = {org_unit_id};"
                    )
                if company_id <= 0:
                    raise self.api_error("职位必须指定公司或组织。")
            if is_primary:
                primary_count += 1
                primary_company = company_id
                primary_org = org_unit_id
                primary_department = department
                primary_position = position_name
            values.append(
                "("
                + ", ".join(
                    [
                        str(employee_id_int),
                        str(company_id),
                        (str(org_unit_id) if org_unit_id > 0 else "NULL"),
                        self.db.quote(department or ""),
                        self.db.quote(position_name or ""),
                        "1" if is_primary else "0",
                        "0",
                        "1",
                    ]
                )
                + ")"
            )
        if primary_count != 1:
            raise self.api_error("必须且只能设置一个主职位。")

        statements = [
            "START TRANSACTION",
            f"DELETE FROM employee_position WHERE employee_id = {employee_id_int}",
            "INSERT INTO employee_position (employee_id, company_id, org_unit_id, department, position_name, is_primary, sort_order, is_active) VALUES "
            + ", ".join(values),
            f"""
            UPDATE employee
            SET org_unit_id = {primary_org if primary_org > 0 else 'NULL'},
                department = {self.db.quote(primary_department)},
                position_name = {self.db.quote(primary_position)}
            WHERE employee_id = {employee_id_int}
            """,
            "COMMIT",
        ]
        self.db.execute(";\n".join(statements) + ";")
        return self.list_positions(employee_id_int, context)
