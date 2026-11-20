SET NAMES utf8mb4;

-- MCP / AI 网关：个人令牌、会话、工具调用留痕、高风险确认令牌
CREATE TABLE IF NOT EXISTS api_credential (
  credential_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(64) NOT NULL,
  token_prefix VARCHAR(16) NOT NULL,
  token_hash CHAR(64) NOT NULL,
  scopes JSON NULL,
  last_used_at DATETIME NULL,
  expires_at DATETIME NULL,
  revoked_at DATETIME NULL,
  created_by VARCHAR(64) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (credential_id),
  UNIQUE KEY uk_api_prefix (token_prefix),
  KEY idx_api_user (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ai_session (
  ai_session_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id BIGINT UNSIGNED NOT NULL,
  credential_id BIGINT UNSIGNED NOT NULL,
  channel VARCHAR(16) NOT NULL DEFAULT 'mcp',
  client_name VARCHAR(128) NOT NULL DEFAULT '',
  started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ip VARCHAR(64) NOT NULL DEFAULT '',
  PRIMARY KEY (ai_session_id),
  KEY idx_ai_session_user (user_id, started_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ai_tool_call (
  call_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ai_session_id BIGINT UNSIGNED NOT NULL,
  tool_name VARCHAR(64) NOT NULL,
  arguments_hash CHAR(64) NOT NULL,
  arguments_redacted JSON NOT NULL,
  decision VARCHAR(16) NOT NULL DEFAULT 'allow',
  result_code VARCHAR(32) NOT NULL DEFAULT '',
  result_summary VARCHAR(500) NOT NULL DEFAULT '',
  latency_ms INT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (call_id),
  KEY idx_call_session (ai_session_id),
  KEY idx_call_tool (tool_name, created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ai_confirm_token (
  token_hash CHAR(64) NOT NULL,
  requester_id BIGINT UNSIGNED NOT NULL,
  confirmer_id BIGINT UNSIGNED NULL,
  tool_name VARCHAR(64) NOT NULL,
  arguments_hash CHAR(64) NOT NULL,
  expires_at DATETIME NOT NULL,
  confirmed_at DATETIME NULL,
  used_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (token_hash)
) ENGINE=InnoDB;

-- 配置项（幂等）
INSERT INTO system_setting (setting_key, setting_value, is_active)
SELECT 'ai_gateway_enabled', '0', 1 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM system_setting WHERE setting_key = 'ai_gateway_enabled');
INSERT INTO system_setting (setting_key, setting_value, is_active)
SELECT 'ai_confirm_user_id', '', 1 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM system_setting WHERE setting_key = 'ai_confirm_user_id');
INSERT INTO system_setting (setting_key, setting_value, is_active)
SELECT 'ai_rate_limit_per_min', '60', 1 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM system_setting WHERE setting_key = 'ai_rate_limit_per_min');
INSERT INTO system_setting (setting_key, setting_value, is_active)
SELECT 'ai_write_limit_per_min', '20', 1 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM system_setting WHERE setting_key = 'ai_write_limit_per_min');
INSERT INTO system_setting (setting_key, setting_value, is_active)
SELECT 'ai_confirm_ttl_seconds', '300', 1 FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM system_setting WHERE setting_key = 'ai_confirm_ttl_seconds');
