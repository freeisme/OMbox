"""产线工控机（LineGuard）模块。

与 OMbox 的关系：
- 表结构使用 `lg_` 前缀，与既有表同库共存（不新建数据库，因为数据访问复用 mysql CLI 网关）；
- 业务层 assets/monitor/scanner/reports 移植自 LineGuard，通过 `LineGuardDb` 适配到 `SqlGateway`；
- HTTP 由 `office_asset.lineguard.api.LineGuardRouter` 挂到 `/api/lineguard/*`。
"""
from .config import LineGuardConfig, load_config
from .db import LineGuardDb

__all__ = ["LineGuardConfig", "load_config", "LineGuardDb"]
