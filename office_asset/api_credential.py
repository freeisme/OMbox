"""个人 API 令牌：签发、校验、吊销。

令牌只用于 MCP / HTTP API，不参与页面会话；权限永远按用户实时求值，
因此不存在"令牌带权限"的问题——吊销或降权立即生效。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

TOKEN_PREFIX = "ombox_"
PREFIX_LENGTH = 12
SECRET_BYTES = 32


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_token(token: str) -> tuple[str, str] | None:
    """拆出前缀与密文；格式不符直接返回 None。"""
    raw = (token or "").strip()
    if not raw.startswith(TOKEN_PREFIX):
        return None
    rest = raw[len(TOKEN_PREFIX):]
    prefix, _, secret = rest.partition("_")
    if len(prefix) != PREFIX_LENGTH or not secret:
        return None
    return prefix, secret


@dataclass
class ApiCredentialService:
    db: object
    api_error: type[Exception]
    forbidden_error: type[Exception]

    # ---------------------------------------------------------------- 签发
    def issue(
        self,
        user_id: object,
        name: object,
        actor: str,
        expires_days: object = 0,
    ) -> dict:
        uid = self.db.integer(user_id, 0)
        if uid <= 0:
            raise self.api_error("用户无效。")
        label = self.db.text(name).strip()[:64] or "默认令牌"
        days = max(0, min(self.db.integer(expires_days, 0), 3650))
        prefix = secrets.token_hex(PREFIX_LENGTH // 2)
        secret = secrets.token_urlsafe(SECRET_BYTES)
        token = f"{TOKEN_PREFIX}{prefix}_{secret}"
        expires_sql = "NULL" if days == 0 else f"DATE_ADD(NOW(), INTERVAL {days} DAY)"
        self.db.execute(
            f"""
            INSERT INTO api_credential
              (user_id, name, token_prefix, token_hash, expires_at, created_by)
            VALUES
              ({uid}, {self.db.quote(label)}, {self.db.quote(prefix)},
               {self.db.quote(token_hash(token))}, {expires_sql},
               {self.db.quote(self.db.text(actor)[:64])});
            """
        )
        row = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(credential_id AS CHAR),
              'name', name,
              'prefix', token_prefix,
              'expiresAt', COALESCE(CAST(expires_at AS CHAR), ''),
              'createdAt', CAST(created_at AS CHAR)
            )
            FROM api_credential WHERE token_prefix = {self.db.quote(prefix)}
            """,
            None,
        )
        # 明文只在这里返回一次，之后无法再取回
        return {"token": token, "credential": row or {}}

    # ---------------------------------------------------------------- 校验
    def authenticate(self, token: str) -> dict | None:
        parsed = parse_token(token)
        if not parsed:
            return None
        prefix, _secret = parsed
        row = self.db.json(
            f"""
            SELECT JSON_OBJECT(
              'credentialId', CAST(credential_id AS CHAR),
              'userId', CAST(user_id AS CHAR),
              'tokenHash', token_hash,
              'revoked', CASE WHEN revoked_at IS NULL THEN 0 ELSE 1 END,
              'expired', CASE WHEN expires_at IS NOT NULL AND expires_at <= NOW() THEN 1 ELSE 0 END
            )
            FROM api_credential
            WHERE token_prefix = {self.db.quote(prefix)}
            LIMIT 1
            """,
            None,
        )
        if not row:
            return None
        if not hmac.compare_digest(self.db.text(row.get("tokenHash")), token_hash(token)):
            return None
        if self.db.integer(row.get("revoked"), 0) or self.db.integer(row.get("expired"), 0):
            return None
        self.db.execute(
            f"UPDATE api_credential SET last_used_at = NOW() "
            f"WHERE credential_id = {self.db.integer(row.get('credentialId'), 0)};"
        )
        return row

    # ---------------------------------------------------------------- 管理
    def list_for_user(self, user_id: object) -> list[dict]:
        rows = self.db.json(
            f"""
            SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT(
              'id', CAST(credential_id AS CHAR),
              'name', name,
              'prefix', token_prefix,
              'lastUsedAt', COALESCE(CAST(last_used_at AS CHAR), ''),
              'expiresAt', COALESCE(CAST(expires_at AS CHAR), ''),
              'revoked', CASE WHEN revoked_at IS NULL THEN 0 ELSE 1 END,
              'createdAt', CAST(created_at AS CHAR)
            )), JSON_ARRAY())
            FROM (
              SELECT * FROM api_credential
              WHERE user_id = {self.db.integer(user_id, 0)}
              ORDER BY credential_id DESC
              LIMIT 100
            ) ordered_credentials
            """,
            [],
        )
        return [dict(row) for row in (rows or [])]

    def revoke(self, credential_id: object, user_id: object) -> dict:
        cid = self.db.integer(credential_id, 0)
        uid = self.db.integer(user_id, 0)
        if cid <= 0:
            raise self.api_error("令牌不存在。")
        exists = self.db.json(
            f"SELECT JSON_OBJECT('id', CAST(credential_id AS CHAR), 'userId', CAST(user_id AS CHAR)) "
            f"FROM api_credential WHERE credential_id = {cid} LIMIT 1",
            None,
        )
        if not exists:
            raise self.api_error("令牌不存在。")
        if self.db.integer(exists.get("userId"), 0) != uid:
            raise self.forbidden_error("只能吊销自己的令牌。")
        self.db.execute(
            f"UPDATE api_credential SET revoked_at = NOW() "
            f"WHERE credential_id = {cid} AND revoked_at IS NULL;"
        )
        return {"id": str(cid), "revoked": True}
