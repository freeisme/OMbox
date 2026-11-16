"""LineGuard 数据访问层：适配 OMbox 的 mysql CLI 网关。

为什么不直接用 MySQL 驱动：
生产服务器不能访问 PyPI，装不了 `mysql-connector-python`。这里把 LineGuard 原本
「%s 参数化 + 字典行」的调用约定，翻译成 OMbox 既有 `SqlGateway` 能执行的 SQL 文本，
业务代码（assets/monitor/reports）因此可以基本原样复用。

约定：
- 所有参数都经 `quote` 转义后内联，不接受拼接未转义的字符串；
- `execute` 遇到 INSERT 时额外取一次 LAST_INSERT_ID()；
- 批量写请优先拼一条多行 SQL（见 monitor 的探测结果回写），避免每行一次进程。
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable


# mysql CLI 输出的所有值都是文本；按列名把数值列还原成数字，
# 否则业务代码里的 `device["probe_interval"] > 60` 这类比较会退化成字符串比较。
_INT_COLUMNS = {
    "id", "c", "total", "sort_order",
    "device_id", "line_id", "station_id", "workshop_id",
    "probe_port", "probe_interval", "latency_ms", "uptime_seconds",
    "total_hosts", "alive_hosts", "last_probe_ok",
}
_INT_SUFFIXES = ("_id", "_ms", "_gb", "_count", "_seconds", "_days", "_port", "_interval", "_num")
_FLOAT_HINTS = ("percent",)


def _coerce(column: str, value: object) -> object:
    if value is None:
        return None
    name = column.lower()
    if not isinstance(value, str):
        return value
    try:
        if name in _INT_COLUMNS or name.endswith(_INT_SUFFIXES):
            return int(float(value))
        if any(hint in name for hint in _FLOAT_HINTS):
            return float(value)
    except (TypeError, ValueError):
        return value
    return value


class LineGuardDb:
    def __init__(
        self,
        query_rows: Callable[[str], list[dict]],
        execute: Callable[[str], str],
        quote: Callable[[object], str],
    ) -> None:
        self._query_rows = query_rows
        self._execute_sql = execute
        self._quote = quote

    # ------------------------------------------------------------ 参数内联
    def _literal(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        return self._quote(value)

    def _render(self, sql: str, params: Iterable[Any] | None = None) -> str:
        args = list(params or [])
        if not args:
            return sql
        pieces = sql.split("%s")
        if len(pieces) - 1 != len(args):
            raise ValueError(f"SQL 占位符数量不匹配：期望 {len(args)}，实际 {len(pieces) - 1}")
        out: list[str] = [pieces[0]]
        for index, value in enumerate(args):
            out.append(self._literal(value))
            out.append(pieces[index + 1])
        return "".join(out)

    # ------------------------------------------------------------ 查询
    def query(self, sql: str, params: Iterable[Any] | None = None) -> list[dict]:
        rows = self._query_rows(self._render(sql, params))
        return [{key: _coerce(key, value) for key, value in dict(row).items()} for row in (rows or [])]

    def one(self, sql: str, params: Iterable[Any] | None = None) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ------------------------------------------------------------ 写入
    def execute(self, sql: str, params: Iterable[Any] | None = None) -> int:
        rendered = self._render(sql, params)
        if rendered.lstrip()[:6].upper() == "INSERT":
            # LAST_INSERT_ID() 只在同一连接内有效：INSERT 与取值必须一次提交，
            # 否则每次都是新进程，永远拿到 0。
            rows = self._query_rows(rendered.rstrip().rstrip(";") + ";\nSELECT LAST_INSERT_ID() AS id;")
            return int(rows[0]["id"]) if rows else 0
        self._execute_sql(rendered)
        return 0

    def execute_many(self, sql: str, rows: list[tuple]) -> int:
        affected = 0
        for row in rows or []:
            self._execute_sql(self._render(sql, row))
            affected += 1
        return affected

    # ------------------------------------------------------------ 配置项
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.one("SELECT v FROM lg_setting WHERE k = %s", (key,))
        return str(row["v"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO lg_setting (k, v) VALUES (%s, %s) ON DUPLICATE KEY UPDATE v = VALUES(v)",
            (key, value),
        )

    def settings_all(self) -> dict[str, str]:
        return {str(r["k"]): str(r["v"]) for r in self.query("SELECT k, v FROM lg_setting")}


# 兼容移植代码里的类型标注（from .db import Database）
Database = LineGuardDb
