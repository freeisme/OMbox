SET NAMES utf8mb4;

-- 机房管理：网络设备/服务器台账（独立于办公终端与 IT 物资）。
-- 未上架设备列表只来自这张表；设备状态包含未上架、上架、维修、报废。
-- 本迁移只新增表与列，不改动历史业务数据。

CREATE TABLE IF NOT EXISTS datacenter_device (
  device_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  device_code VARCHAR(64) NOT NULL,
  device_name VARCHAR(128) NOT NULL,
  catalog_id BIGINT UNSIGNED NULL,
  brand_model VARCHAR(160) NOT NULL DEFAULT '',
  category VARCHAR(32) NOT NULL DEFAULT 'other',
  u_height INT NOT NULL DEFAULT 1,
  serial_number VARCHAR(128) NOT NULL DEFAULT '',
  asset_code VARCHAR(128) NOT NULL DEFAULT '',
  owner_label VARCHAR(128) NOT NULL DEFAULT '',
  status VARCHAR(16) NOT NULL DEFAULT 'stock',
  org_unit_id BIGINT UNSIGNED NULL,
  site_id BIGINT UNSIGNED NULL,
  rack_id BIGINT UNSIGNED NULL,
  notes VARCHAR(500) NOT NULL DEFAULT '',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_by BIGINT UNSIGNED NULL,
  updated_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (device_id),
  UNIQUE KEY uq_datacenter_device_code (device_code),
  KEY idx_datacenter_device_status (status, is_active),
  KEY idx_datacenter_device_catalog (catalog_id),
  KEY idx_datacenter_device_scope (site_id, rack_id),
  CONSTRAINT fk_datacenter_device_catalog
    FOREIGN KEY (catalog_id) REFERENCES device_type_catalog (catalog_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_datacenter_device_org
    FOREIGN KEY (org_unit_id) REFERENCES org_unit (org_unit_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_datacenter_device_site
    FOREIGN KEY (site_id) REFERENCES asset_site (site_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_datacenter_device_rack
    FOREIGN KEY (rack_id) REFERENCES asset_rack (rack_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_datacenter_device_created_by
    FOREIGN KEY (created_by) REFERENCES user_account (user_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_datacenter_device_updated_by
    FOREIGN KEY (updated_by) REFERENCES user_account (user_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT ck_datacenter_device_status
    CHECK (status IN ('stock', 'installed', 'repair', 'scrapped')),
  CONSTRAINT ck_datacenter_device_height CHECK (u_height BETWEEN 1 AND 50),
  CONSTRAINT ck_datacenter_device_category CHECK (
    category IN (
      'server', 'network', 'patch-panel', 'power', 'storage',
      'kvm', 'av-media', 'cooling', 'shelf', 'blank', 'cable-management', 'other'
    )
  ),
  CONSTRAINT ck_datacenter_device_active CHECK (is_active IN (0, 1))
) ENGINE=InnoDB;

-- 机柜位置记录新增“机房设备”来源：一台设备同时只能出现在一个机柜位置。
SET @has_datacenter_column = (
  SELECT COUNT(*)
  FROM information_schema.columns
  WHERE table_schema = DATABASE()
    AND table_name = 'rack_device_placement'
    AND column_name = 'datacenter_device_id'
);
SET @add_datacenter_column_sql = IF(
  @has_datacenter_column = 0,
  'ALTER TABLE rack_device_placement ADD COLUMN datacenter_device_id BIGINT UNSIGNED NULL AFTER computer_id',
  'SELECT 1'
);
PREPARE add_datacenter_column_stmt FROM @add_datacenter_column_sql;
EXECUTE add_datacenter_column_stmt;
DEALLOCATE PREPARE add_datacenter_column_stmt;

SET @has_datacenter_index = (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'rack_device_placement'
    AND index_name = 'uq_rack_placement_datacenter'
);
SET @add_datacenter_index_sql = IF(
  @has_datacenter_index = 0,
  'ALTER TABLE rack_device_placement ADD UNIQUE KEY uq_rack_placement_datacenter (datacenter_device_id)',
  'SELECT 1'
);
PREPARE add_datacenter_index_stmt FROM @add_datacenter_index_sql;
EXECUTE add_datacenter_index_stmt;
DEALLOCATE PREPARE add_datacenter_index_stmt;

SET @has_datacenter_fk = (
  SELECT COUNT(*)
  FROM information_schema.table_constraints
  WHERE constraint_schema = DATABASE()
    AND table_name = 'rack_device_placement'
    AND constraint_name = 'fk_rack_placement_datacenter'
);
SET @add_datacenter_fk_sql = IF(
  @has_datacenter_fk = 0,
  'ALTER TABLE rack_device_placement ADD CONSTRAINT fk_rack_placement_datacenter FOREIGN KEY (datacenter_device_id) REFERENCES datacenter_device (device_id) ON DELETE SET NULL ON UPDATE CASCADE',
  'SELECT 1'
);
PREPARE add_datacenter_fk_stmt FROM @add_datacenter_fk_sql;
EXECUTE add_datacenter_fk_stmt;
DEALLOCATE PREPARE add_datacenter_fk_stmt;

-- 允许 source_kind = 'datacenter'（原有 computer/custom 记录继续有效）。
SET @has_source_kind_check = (
  SELECT COUNT(*)
  FROM information_schema.table_constraints
  WHERE constraint_schema = DATABASE()
    AND table_name = 'rack_device_placement'
    AND constraint_name = 'ck_rack_placement_source_kind'
);
SET @drop_source_kind_check_sql = IF(
  @has_source_kind_check > 0,
  'ALTER TABLE rack_device_placement DROP CHECK ck_rack_placement_source_kind',
  'SELECT 1'
);
PREPARE drop_source_kind_check_stmt FROM @drop_source_kind_check_sql;
EXECUTE drop_source_kind_check_stmt;
DEALLOCATE PREPARE drop_source_kind_check_stmt;

ALTER TABLE rack_device_placement
  ADD CONSTRAINT ck_rack_placement_source_kind
  CHECK (source_kind IN ('computer', 'custom', 'datacenter'));
