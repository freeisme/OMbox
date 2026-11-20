"""MCP 工具注册表：把现有 service 能力包成工具。

设计约束：
- 工具不新写 SQL，一律调用 service 层，权限与数据范围自动沿用；
- 每个工具声明所需权限，tools/list 只返回调用者有权使用的工具；
- 参数按 inputSchema 做最小校验（类型/必填/枚举/长度），避免脏数据进入业务层。
"""
from __future__ import annotations

from typing import Callable

MCP_TOOL_ERROR_CODE = "TOOL_NOT_FOUND"


class ToolError(Exception):
    def __init__(self, code: int, message: str, data_code: str = "INVALID_ARGUMENT") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data_code = data_code


def _check_type(value: object, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def validate_arguments(schema: dict, arguments: dict) -> None:
    if not isinstance(arguments, dict):
        raise ToolError(-32602, "参数必须是 JSON 对象。")
    properties = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in arguments or arguments[key] in (None, ""):
            raise ToolError(-32602, f"缺少必填参数：{key}")
    if schema.get("additionalProperties") is False:
        for key in arguments:
            if key not in properties and not key.startswith("_"):
                raise ToolError(-32602, f"不支持的参数：{key}")
    for key, value in arguments.items():
        spec = properties.get(key)
        if not isinstance(spec, dict) or value is None:
            continue
        expected = spec.get("type")
        if expected and not _check_type(value, expected):
            raise ToolError(-32602, f"参数 {key} 类型应为 {expected}。")
        if "enum" in spec and value not in spec["enum"]:
            raise ToolError(-32602, f"参数 {key} 只能是 {'/'.join(spec['enum'])}。")
        if expected == "string" and "maxLength" in spec and len(value) > int(spec["maxLength"]):
            raise ToolError(-32602, f"参数 {key} 超过 {spec['maxLength']} 字。")
        if expected == "array" and "maxItems" in spec and len(value) > int(spec["maxItems"]):
            raise ToolError(-32602, f"参数 {key} 最多 {spec['maxItems']} 项。")


class AiToolRegistry:
    def __init__(
        self,
        *,
        router: object,
        db: object,
        require_permission: Callable[[dict, str, str], None],
        permission_allows: Callable[[dict, str, str], bool],
        permission_map: Callable[[dict], dict],
    ) -> None:
        self.router = router
        self.db = db
        self.require_permission = require_permission
        self.permission_allows = permission_allows
        self.permission_map = permission_map
        self._tools: dict[str, dict] = {
            "session.whoami": {
                "description": "返回当前账号的身份、数据范围与可用工具清单，用于自检。",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "requires": None,
                "handler": self._whoami,
            },
            "ticket.create": {
                "description": "创建工单（报修用 incident，申领/申请用 request），返回工单号与状态。",
                "inputSchema": {
                    "type": "object",
                    "required": ["title", "kind"],
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string", "maxLength": 120},
                        "kind": {"type": "string", "enum": ["repair", "request"]},
                        "description": {"type": "string", "maxLength": 2000},
                        "assetId": {"type": "string", "maxLength": 32},
                    },
                },
                "requires": ("tickets", "create"),
                "handler": self._ticket_create,
            },
            "ticket.list_mine": {
                "description": "列出我提交的工单（可按状态过滤），最多 20 条。",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "status": {"type": "string", "maxLength": 24},
                        "limit": {"type": "integer"},
                    },
                },
                "requires": ("tickets", "view"),
                "handler": self._ticket_list_mine,
            },
        }

    # ---------------------------------------------------------------- 对外
    def list_tools(self, context: dict) -> list[dict]:
        result = []
        for name, spec in self._tools.items():
            requires = spec.get("requires")
            if requires and not self.permission_allows(context, *requires):
                continue
            result.append(
                {
                    "name": name,
                    "description": spec["description"],
                    "inputSchema": spec["inputSchema"],
                }
            )
        return result

    def call(self, name: str, arguments: dict, context: dict) -> dict:
        spec = self._tools.get(name)
        if not spec:
            raise ToolError(-32602, f"未知工具：{name}", MCP_TOOL_ERROR_CODE)
        validate_arguments(spec["inputSchema"], arguments or {})
        requires = spec.get("requires")
        if requires:
            self.require_permission(context, *requires)
        return spec["handler"](arguments or {}, context)

    # ---------------------------------------------------------------- 工具实现
    def _whoami(self, arguments: dict, context: dict) -> dict:
        employee = context.get("employee") if isinstance(context.get("employee"), dict) else {}
        modules = sorted(
            code
            for code, row in self.permission_map(context).items()
            if self.db.integer(row.get("canView"), 0)
        )
        return {
            "username": self.db.text(context.get("username")),
            "displayName": self.db.text(context.get("displayName")),
            "role": self.db.text(context.get("role")),
            "isSuperAdmin": bool(context.get("isSuperAdmin")),
            "employeeId": self.db.text(employee.get("employeeId")),
            "employeeName": self.db.text(employee.get("employeeName")),
            "modules": modules,
            "tools": [item["name"] for item in self.list_tools(context)],
        }

    def _ticket_create(self, arguments: dict, context: dict) -> dict:
        kind = self.db.text(arguments.get("kind")).strip()
        title = self.db.text(arguments.get("title")).strip()
        description = self.db.text(arguments.get("description")).strip() or title
        payload = {
            "type": "incident" if kind == "repair" else "request",
            "title": title,
            "description": description,
            "impact": "medium",
            "urgency": "medium",
            "source": "portal",
        }
        asset_id = self.db.text(arguments.get("assetId")).strip()
        if asset_id:
            payload["relatedComputerId"] = asset_id
        created = self.router.tickets.create_ticket(payload, context)
        ticket = created.get("ticket") if isinstance(created, dict) else None
        ticket = ticket or {}
        number = self.db.text(ticket.get("number")) or self.db.text(ticket.get("id"))
        status = self.db.text(ticket.get("status")) or "open"
        return {
            "ticketId": self.db.text(ticket.get("id")),
            "number": number,
            "status": status,
            "summary": f"已创建工单 {number}，当前状态：{status}",
        }

    def _ticket_list_mine(self, arguments: dict, context: dict) -> dict:
        filters: dict[str, list[str]] = {"requester": ["me"]}
        status = self.db.text(arguments.get("status")).strip()
        if status:
            filters["status"] = [status]
        limit = min(max(self.db.integer(arguments.get("limit"), 20), 1), 20)
        rows = self.router.tickets.list_tickets(context, filters)[:limit]
        return {
            "count": len(rows),
            "tickets": [
                {
                    "id": self.db.text(row.get("id")),
                    "number": self.db.text(row.get("number")),
                    "title": self.db.text(row.get("title")),
                    "status": self.db.text(row.get("status")),
                    "type": self.db.text(row.get("type")),
                    "createdAt": self.db.text(row.get("createdAt")),
                }
                for row in rows
            ],
        }
