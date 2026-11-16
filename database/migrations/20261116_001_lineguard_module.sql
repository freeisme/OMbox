SET NAMES utf8mb4;

-- ============================================================================
-- 产线工控机（LineGuard）模块建表与权限注册
-- 迁移：20261116_001_lineguard_module.sql
-- 说明：12 张 lg_* 表与 OMbox 既有表同库共存（前缀隔离）。
--       为什么不建独立库：生产服务器不能访问 PyPI，装不了 Python MySQL 驱动，
--       数据访问复用 OMbox 已有的 mysql CLI 网关，因此必须同库。
--       多公司隔离：lg_workshop / lg_device 带 company_id，读写按公司过滤；
--       资产编号在「公司内」唯一，允许不同公司复用同一编号。
-- 幂等：全部 CREATE TABLE IF NOT EXISTS / INSERT IGNORE，可重复执行。
-- ============================================================================

CREATE TABLE IF NOT EXISTS lg_workshop (
  id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  company_id   INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '所属公司；0 表示未归属',
  code         VARCHAR(32)  NOT NULL,
  name         VARCHAR(64)  NOT NULL,
  description  VARCHAR(255) NOT NULL DEFAULT '',
  sort_order   INT          NOT NULL DEFAULT 0,
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_workshop_code (code),
  KEY idx_workshop_company (company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 产线

CREATE TABLE IF NOT EXISTS lg_line (
  id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  workshop_id  INT UNSIGNED NOT NULL,
  code         VARCHAR(32)  NOT NULL,
  name         VARCHAR(64)  NOT NULL,
  description  VARCHAR(255) NOT NULL DEFAULT '',
  sort_order   INT          NOT NULL DEFAULT 0,
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_line (workshop_id, code),
  CONSTRAINT fk_line_workshop FOREIGN KEY (workshop_id) REFERENCES lg_workshop (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 工位

CREATE TABLE IF NOT EXISTS lg_station (
  id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  line_id      INT UNSIGNED NOT NULL,
  code         VARCHAR(32)  NOT NULL,
  name         VARCHAR(64)  NOT NULL,
  sort_order   INT          NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uk_station (line_id, code),
  CONSTRAINT fk_station_line FOREIGN KEY (line_id) REFERENCES lg_line (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 设备（工控机）：唯一实体，产线/工位只是"当前位置"属性

CREATE TABLE IF NOT EXISTS lg_device (
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  company_id     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '所属公司；按公司隔离用',
  asset_no       VARCHAR(64)  NOT NULL COMMENT '资产编号（唯一）',
  hostname       VARCHAR(128) NOT NULL,
  ip             VARCHAR(64)  NOT NULL DEFAULT '',
  mac            VARCHAR(32)  NOT NULL DEFAULT '',
  model          VARCHAR(128) NOT NULL DEFAULT '',
  os_version     VARCHAR(128) NOT NULL DEFAULT '',
  serial_no      VARCHAR(128) NOT NULL DEFAULT '',
  vendor         VARCHAR(64)  NOT NULL DEFAULT '',
  line_id        INT UNSIGNED NULL,
  station_id     INT UNSIGNED NULL,
  status         ENUM('online','offline','fault','maintenance','retired') NOT NULL DEFAULT 'offline',
  probe_mode     ENUM('heartbeat','probe','hybrid') NOT NULL DEFAULT 'heartbeat',
  probe_port     SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  probe_interval INT UNSIGNED NOT NULL DEFAULT 60,
  location_note  VARCHAR(255) NOT NULL DEFAULT '',
  owner          VARCHAR(64)  NOT NULL DEFAULT '',
  remark         VARCHAR(500) NOT NULL DEFAULT '',
  source         ENUM('manual','import','scan','agent') NOT NULL DEFAULT 'manual' COMMENT '来源：手工/导入/网段扫描/Agent自动注册',
  agent_token    CHAR(48)     NOT NULL,
  cpu_model      VARCHAR(128) NOT NULL DEFAULT '',
  memory_gb      DECIMAL(8,1) NULL,
  disk_gb        DECIMAL(8,1) NULL,
  cpu_percent    DECIMAL(5,1) NULL,
  mem_percent    DECIMAL(5,1) NULL,
  disk_percent   DECIMAL(5,1) NULL,
  uptime_seconds BIGINT UNSIGNED NULL,
  last_heartbeat_at DATETIME NULL,
  last_seen_at   DATETIME NULL,
  last_state_changed_at DATETIME NULL,
  last_probe_ok  TINYINT(1) NULL,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_device_asset (company_id, asset_no),
  UNIQUE KEY uk_device_token (agent_token),
  KEY idx_device_line (line_id),
  KEY idx_device_status (status),
  KEY idx_device_ip (ip),
  KEY idx_device_company (company_id),
  CONSTRAINT fk_device_line FOREIGN KEY (line_id) REFERENCES lg_line (id) ON DELETE RESTRICT,
  CONSTRAINT fk_device_station FOREIGN KEY (station_id) REFERENCES lg_station (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 设备事件时间线（入库/换线/状态变更/状况登记/指令）

CREATE TABLE IF NOT EXISTS lg_device_event (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  device_id  INT UNSIGNED NOT NULL,
  event_type VARCHAR(32)  NOT NULL,
  line_id    INT UNSIGNED NULL,
  station_id INT UNSIGNED NULL,
  title      VARCHAR(255) NOT NULL DEFAULT '',
  detail     TEXT NULL,
  payload    JSON NULL,
  operator   VARCHAR(64)  NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_event_device (device_id, created_at),
  CONSTRAINT fk_event_device FOREIGN KEY (device_id) REFERENCES lg_device (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 换线/迁移履历：from_* 为换出位置，to_* 为换入位置

CREATE TABLE IF NOT EXISTS lg_device_transfer (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  device_id      INT UNSIGNED NOT NULL,
  from_status    VARCHAR(16) NULL,
  from_line_id   INT UNSIGNED NULL,
  from_station_id INT UNSIGNED NULL,
  to_status      VARCHAR(16) NULL,
  to_line_id     INT UNSIGNED NULL,
  to_station_id  INT UNSIGNED NULL,
  reason         VARCHAR(255) NOT NULL DEFAULT '',
  note           VARCHAR(500) NOT NULL DEFAULT '',
  operator       VARCHAR(64)  NOT NULL DEFAULT '',
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_transfer_device (device_id, created_at),
  CONSTRAINT fk_transfer_device FOREIGN KEY (device_id) REFERENCES lg_device (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 换下设备的手工状况登记

CREATE TABLE IF NOT EXISTS lg_device_condition (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  device_id   INT UNSIGNED NOT NULL,
  cond_type   VARCHAR(64)  NOT NULL,
  symptom     TEXT NULL,
  root_cause  TEXT NULL,
  resolution  TEXT NULL,
  result      ENUM('pending','repaired','standby','scrapped') NOT NULL DEFAULT 'pending',
  technician  VARCHAR(64)  NOT NULL DEFAULT '',
  repair_at   DATETIME NULL,
  attachment  VARCHAR(255) NULL,
  operator    VARCHAR(64)  NOT NULL DEFAULT '',
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_condition_device (device_id, created_at),
  CONSTRAINT fk_condition_device FOREIGN KEY (device_id) REFERENCES lg_device (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 探测/心跳采样记录

CREATE TABLE IF NOT EXISTS lg_health_check (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  device_id  INT UNSIGNED NOT NULL,
  source     ENUM('heartbeat','probe') NOT NULL,
  status     VARCHAR(16) NOT NULL,
  latency_ms INT NULL,
  detail     VARCHAR(255) NOT NULL DEFAULT '',
  checked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_check_device (device_id, checked_at),
  CONSTRAINT fk_check_device FOREIGN KEY (device_id) REFERENCES lg_device (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 告警

CREATE TABLE IF NOT EXISTS lg_alert (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  device_id   INT UNSIGNED NOT NULL,
  level       ENUM('info','warning','critical') NOT NULL DEFAULT 'warning',
  alert_type  VARCHAR(32) NOT NULL,
  message     VARCHAR(500) NOT NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_alert_open (resolved_at, device_id),
  CONSTRAINT fk_alert_device FOREIGN KEY (device_id) REFERENCES lg_device (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 网段扫描任务（结果先候选，人工确认后入库）

CREATE TABLE IF NOT EXISTS lg_scan_task (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  cidr        VARCHAR(64) NOT NULL,
  status      ENUM('running','done','failed') NOT NULL DEFAULT 'running',
  total_hosts INT NOT NULL DEFAULT 0,
  alive_hosts INT NOT NULL DEFAULT 0,
  operator    VARCHAR(64) NOT NULL DEFAULT '',
  result      JSON NULL,
  started_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY idx_scan_started (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 键值配置（阈值、推送地址、大屏标题等）

CREATE TABLE IF NOT EXISTS lg_setting (
  k VARCHAR(64) NOT NULL,
  v VARCHAR(1000) NOT NULL DEFAULT '',
  PRIMARY KEY (k)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 与宿主（OMbox）的对接：记录设备对应的宿主资产编号（可选）

CREATE TABLE IF NOT EXISTS lg_host_link (
  device_id     INT UNSIGNED NOT NULL,
  host_asset_no VARCHAR(64) NOT NULL DEFAULT '',
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (device_id),
  KEY idx_host_asset (host_asset_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------------------------------------------------------------- 权限注册
INSERT INTO auth_module (module_code, module_name, category, sort_order, is_active)
VALUES ('lineguard', '产线工控机', 'asset', 45, 1)
ON DUPLICATE KEY UPDATE
  module_name = VALUES(module_name),
  category = VALUES(category),
  sort_order = VALUES(sort_order),
  is_active = 1;

INSERT IGNORE INTO auth_permission (module_code, action_code)
VALUES
  ('lineguard', 'view'),
  ('lineguard', 'create'),
  ('lineguard', 'update'),
  ('lineguard', 'delete'),
  ('lineguard', 'approve'),
  ('lineguard', 'export');
