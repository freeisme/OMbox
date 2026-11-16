"""LineGuard 运行参数：全部来自环境变量，默认值按 300 台/3 网段调过。"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class LineGuardConfig:
    """数据库连接参数不在这里：数据访问复用 OMbox 的 mysql 网关。"""

    # 超过该时长未探测成功即判定离线
    offline_seconds: int
    # 主动探测
    probe_interval_seconds: int
    probe_timeout_ms: int
    probe_concurrency: int
    # 网段扫描
    scan_timeout_ms: int
    scan_concurrency: int
    # 状态采样保留天数（超过由清理任务删除）
    check_retention_days: int

    @property
    def dsn(self) -> dict:  # 兼容旧代码里的引用
        return {}


def load_config() -> LineGuardConfig:
    return LineGuardConfig(
        offline_seconds=_env_int("LINEGUARD_OFFLINE_SECONDS", 90),
        probe_interval_seconds=_env_int("LINEGUARD_PROBE_INTERVAL_SECONDS", 30),
        probe_timeout_ms=_env_int("LINEGUARD_PROBE_TIMEOUT_MS", 2000),
        probe_concurrency=_env_int("LINEGUARD_PROBE_CONCURRENCY", 64),
        scan_timeout_ms=_env_int("LINEGUARD_SCAN_TIMEOUT_MS", 800),
        scan_concurrency=_env_int("LINEGUARD_SCAN_CONCURRENCY", 256),
        check_retention_days=_env_int("LINEGUARD_CHECK_RETENTION_DAYS", 30),
    )
