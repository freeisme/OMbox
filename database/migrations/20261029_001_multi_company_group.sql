SET NAMES utf8mb4;

-- ============================================================================
-- 集团多公司（Multi-Company Group）
-- 迁移：20261029_001_multi_company_group.sql
-- 目标版本：v4.0.0
-- 说明：
--   1) 新增 company（公司）、employee_position（员工任职/多职位）、
--      asset_transfer_record（跨公司调拨记录）三张表；
--   2) 为组织/办公终端/仓库/机房/机柜/机房设备/巡检对象设备/报废记录 增加 company_id；
--   3) 建立"初始公司"占位并把存量数据回填到初始公司；
--   4) 为每个员工生成一条主职位任职记录；
--   5) 新增系统设置键（集团名称、机房/巡检开关、集团初始化完成标记）；
--   6) 权限数据范围增加 'company'，新增"公司管理员"角色与"公司管理/跨公司调拨"模块。
-- 幂等：所有 DDL 使用 information_schema 探测，可重复执行。
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) company（公司）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS company (
  company_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  company_code VARCHAR(64) NOT NULL,
  company_name VARCHAR(128) NOT NULL,
  sort_order INT NOT NULL DEFAULT 1000,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (company_id),
  UNIQUE KEY uq_company_code (company_code),
  KEY idx_company_active (is_active, sort_order),
  CONSTRAINT ck_company_active CHECK (is_active IN (0, 1))
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 2) employee_position（员工任职，一个员工多条 = 多职位；主职位唯一）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS employee_position (
  position_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  employee_id BIGINT UNSIGNED NOT NULL,
  company_id BIGINT UNSIGNED NOT NULL,
  org_unit_id BIGINT UNSIGNED NULL,
  department VARCHAR(128) NULL,
  position_name VARCHAR(128) NULL,
  is_primary TINYINT(1) NOT NULL DEFAULT 0,
  sort_order INT NOT NULL DEFAULT 1000,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (position_id),
  KEY idx_employee_position_employee (employee_id, is_active),
  KEY idx_employee_position_company (company_id, is_active),
  KEY idx_employee_position_org (org_unit_id),
  KEY idx_employee_position_name (position_name),
  CONSTRAINT fk_employee_position_employee
    FOREIGN KEY (employee_id) REFERENCES employee (employee_id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_employee_position_company
    FOREIGN KEY (company_id) REFERENCES company (company_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_employee_position_org
    FOREIGN KEY (org_unit_id) REFERENCES org_unit (org_unit_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT ck_employee_position_primary CHECK (is_primary IN (0, 1)),
  CONSTRAINT ck_employee_position_active CHECK (is_active IN (0, 1))
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 3) asset_transfer_record（跨公司调拨记录，免审批直接生效，留审计）
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS asset_transfer_record (
  transfer_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  transfer_no VARCHAR(64) NOT NULL,
  asset_kind VARCHAR(32) NOT NULL,
  asset_id BIGINT UNSIGNED NOT NULL,
  source_company_id BIGINT UNSIGNED NOT NULL,
  target_company_id BIGINT UNSIGNED NOT NULL,
  source_org_unit_id BIGINT UNSIGNED NULL,
  target_org_unit_id BIGINT UNSIGNED NULL,
  quantity INT UNSIGNED NOT NULL DEFAULT 1,
  note VARCHAR(500) NOT NULL DEFAULT '',
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (transfer_id),
  UNIQUE KEY uq_asset_transfer_no (transfer_no),
  KEY idx_asset_transfer_kind (asset_kind, asset_id, created_at),
  KEY idx_asset_transfer_source (source_company_id, created_at),
  KEY idx_asset_transfer_target (target_company_id, created_at),
  CONSTRAINT fk_asset_transfer_source
    FOREIGN KEY (source_company_id) REFERENCES company (company_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_asset_transfer_target
    FOREIGN KEY (target_company_id) REFERENCES company (company_id)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_asset_transfer_creator
    FOREIGN KEY (created_by) REFERENCES user_account (user_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT ck_asset_transfer_kind
    CHECK (asset_kind IN ('computer', 'inventory', 'datacenter_device')),
  CONSTRAINT ck_asset_transfer_quantity CHECK (quantity > 0)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 4) 为各业务表增加 company_id 列（先 NULL，回填后收紧由服务层保证非空）
-- ----------------------------------------------------------------------------

-- 4.1 org_unit
SET @has = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'org_unit' AND column_name = 'company_id');
SET @ddl = IF(@has = 0,
  'ALTER TABLE org_unit ADD COLUMN company_id BIGINT UNSIGNED NULL AFTER org_unit_id, ADD KEY idx_org_unit_company (company_id, is_active), ADD CONSTRAINT fk_org_unit_company FOREIGN KEY (company_id) REFERENCES company (company_id) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4.2 computer_asset
SET @has = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'computer_asset' AND column_name = 'company_id');
SET @ddl = IF(@has = 0,
  'ALTER TABLE computer_asset ADD COLUMN company_id BIGINT UNSIGNED NULL AFTER org_unit_id, ADD KEY idx_computer_company (company_id, is_active), ADD CONSTRAINT fk_computer_company FOREIGN KEY (company_id) REFERENCES company (company_id) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4.3 inventory_warehouse
SET @has = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'inventory_warehouse' AND column_name = 'company_id');
SET @ddl = IF(@has = 0,
  'ALTER TABLE inventory_warehouse ADD COLUMN company_id BIGINT UNSIGNED NULL AFTER org_unit_id, ADD KEY idx_warehouse_company (company_id, is_active), ADD CONSTRAINT fk_warehouse_company FOREIGN KEY (company_id) REFERENCES company (company_id) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4.4 asset_site
SET @has = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'asset_site' AND column_name = 'company_id');
SET @ddl = IF(@has = 0,
  'ALTER TABLE asset_site ADD COLUMN company_id BIGINT UNSIGNED NULL AFTER org_unit_id, ADD KEY idx_asset_site_company (company_id, is_active), ADD CONSTRAINT fk_asset_site_company FOREIGN KEY (company_id) REFERENCES company (company_id) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4.5 asset_rack
SET @has = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'asset_rack' AND column_name = 'company_id');
SET @ddl = IF(@has = 0,
  'ALTER TABLE asset_rack ADD COLUMN company_id BIGINT UNSIGNED NULL AFTER org_unit_id, ADD KEY idx_asset_rack_company (company_id, is_active), ADD CONSTRAINT fk_asset_rack_company FOREIGN KEY (company_id) REFERENCES company (company_id) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4.6 datacenter_device
SET @has = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'datacenter_device' AND column_name = 'company_id');
SET @ddl = IF(@has = 0,
  'ALTER TABLE datacenter_device ADD COLUMN company_id BIGINT UNSIGNED NULL AFTER org_unit_id, ADD KEY idx_datacenter_device_company (company_id, is_active), ADD CONSTRAINT fk_datacenter_device_company FOREIGN KEY (company_id) REFERENCES company (company_id) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4.7 site_device（会议室/巡检对象设备，公司经 site → asset_site 冗余）
SET @tbl = (SELECT COUNT(*) FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'site_device');
SET @has = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'site_device' AND column_name = 'company_id');
SET @ddl = IF(@tbl = 1 AND @has = 0,
  'ALTER TABLE site_device ADD COLUMN company_id BIGINT UNSIGNED NULL AFTER site_id, ADD KEY idx_site_device_company (company_id, is_active), ADD CONSTRAINT fk_site_device_company FOREIGN KEY (company_id) REFERENCES company (company_id) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4.8 asset_scrap_record
SET @has = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'asset_scrap_record' AND column_name = 'company_id');
SET @ddl = IF(@has = 0,
  'ALTER TABLE asset_scrap_record ADD COLUMN company_id BIGINT UNSIGNED NULL AFTER org_unit_id, ADD KEY idx_asset_scrap_company (company_id, scrap_at), ADD CONSTRAINT fk_asset_scrap_company FOREIGN KEY (company_id) REFERENCES company (company_id) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 4.9 inventory_scrap_record
SET @has = (SELECT COUNT(*) FROM information_schema.columns
  WHERE table_schema = DATABASE() AND table_name = 'inventory_scrap_record' AND column_name = 'company_id');
SET @ddl = IF(@has = 0,
  'ALTER TABLE inventory_scrap_record ADD COLUMN company_id BIGINT UNSIGNED NULL AFTER org_unit_id, ADD KEY idx_inventory_scrap_company (company_id, scrap_at), ADD CONSTRAINT fk_inventory_scrap_company FOREIGN KEY (company_id) REFERENCES company (company_id) ON DELETE RESTRICT ON UPDATE CASCADE',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------------------------------------------------------
-- 5) 建立"初始公司"占位（存量数据全部归入初始公司；命名由初始化向导补全，见 Q7）
-- ----------------------------------------------------------------------------
INSERT INTO company (company_code, company_name, sort_order, is_active)
VALUES ('CMP-001', '初始公司', 0, 1)
ON DUPLICATE KEY UPDATE company_name = VALUES(company_name), is_active = 1;

SET @initial_company_id = (SELECT company_id FROM company WHERE company_code = 'CMP-001' LIMIT 1);

-- ----------------------------------------------------------------------------
-- 6) 回填 company_id
-- ----------------------------------------------------------------------------

-- 6.1 org_unit：整棵现有组织树 → 初始公司
UPDATE org_unit SET company_id = @initial_company_id WHERE company_id IS NULL;

-- 6.2 经 org_unit_id 推导的实体
UPDATE computer_asset c
  LEFT JOIN org_unit o ON o.org_unit_id = c.org_unit_id
  SET c.company_id = COALESCE(o.company_id, @initial_company_id)
  WHERE c.company_id IS NULL;

UPDATE inventory_warehouse w
  LEFT JOIN org_unit o ON o.org_unit_id = w.org_unit_id
  SET w.company_id = COALESCE(o.company_id, @initial_company_id)
  WHERE w.company_id IS NULL;

UPDATE asset_site s
  LEFT JOIN org_unit o ON o.org_unit_id = s.org_unit_id
  SET s.company_id = COALESCE(o.company_id, @initial_company_id)
  WHERE s.company_id IS NULL;

UPDATE asset_rack r
  LEFT JOIN org_unit o ON o.org_unit_id = r.org_unit_id
  SET r.company_id = COALESCE(o.company_id, @initial_company_id)
  WHERE r.company_id IS NULL;

UPDATE datacenter_device d
  LEFT JOIN org_unit o ON o.org_unit_id = d.org_unit_id
  SET d.company_id = COALESCE(o.company_id, @initial_company_id)
  WHERE d.company_id IS NULL;

UPDATE asset_scrap_record a
  LEFT JOIN org_unit o ON o.org_unit_id = a.org_unit_id
  SET a.company_id = COALESCE(o.company_id, @initial_company_id)
  WHERE a.company_id IS NULL;

UPDATE inventory_scrap_record i
  LEFT JOIN org_unit o ON o.org_unit_id = i.org_unit_id
  SET i.company_id = COALESCE(o.company_id, @initial_company_id)
  WHERE i.company_id IS NULL;

-- 6.3 site_device：经 site → asset_site 推导
SET @tbl = (SELECT COUNT(*) FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'site_device');
SET @ddl = IF(@tbl = 1,
  'UPDATE site_device sd LEFT JOIN asset_site s ON s.site_id = sd.site_id SET sd.company_id = COALESCE(s.company_id, @initial_company_id) WHERE sd.company_id IS NULL',
  'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ----------------------------------------------------------------------------
-- 7) 员工任职回填：每个员工生成一条主职位（复用原 org/department/position）
-- ----------------------------------------------------------------------------
INSERT INTO employee_position (
  employee_id, company_id, org_unit_id, department, position_name, is_primary, sort_order
)
SELECT
  e.employee_id,
  COALESCE(o.company_id, @initial_company_id),
  e.org_unit_id,
  e.department,
  e.position_name,
  1,
  0
FROM employee e
LEFT JOIN org_unit o ON o.org_unit_id = e.org_unit_id
WHERE NOT EXISTS (
  SELECT 1 FROM employee_position ep
  WHERE ep.employee_id = e.employee_id AND ep.is_primary = 1
);

-- ----------------------------------------------------------------------------
-- 8) 系统设置键
-- ----------------------------------------------------------------------------
INSERT INTO system_setting (setting_key, setting_value, setting_description)
VALUES
  ('group_name', '', '集团名称（空表示尚未完成集团/公司初始化）'),
  ('group_setup_done', '0', '集团/公司初始化向导是否完成（0/1）'),
  ('module_datacenter_enabled', '1', '机房管理开关（1 开启 / 0 关闭）'),
  ('module_inspection_enabled', '1', '巡检管理开关（1 开启 / 0 关闭）')
ON DUPLICATE KEY UPDATE setting_description = VALUES(setting_description);

-- ----------------------------------------------------------------------------
-- 9) 权限：数据范围增加 'company'，新增公司管理员角色与公司管理/调拨模块
-- ----------------------------------------------------------------------------

-- 9.1 放宽 auth_role_permission.data_scope 与 auth_user_permission.data_scope 约束
SET @has = (SELECT COUNT(*) FROM information_schema.table_constraints
  WHERE constraint_schema = DATABASE() AND table_name = 'auth_role_permission'
    AND constraint_name = 'ck_auth_role_permission_scope');
SET @ddl = IF(@has > 0, 'ALTER TABLE auth_role_permission DROP CHECK ck_auth_role_permission_scope', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
ALTER TABLE auth_role_permission
  ADD CONSTRAINT ck_auth_role_permission_scope
  CHECK (data_scope IN ('all', 'company', 'organization', 'own', 'submitted', 'assigned', 'none'));

SET @has = (SELECT COUNT(*) FROM information_schema.table_constraints
  WHERE constraint_schema = DATABASE() AND table_name = 'auth_user_permission'
    AND constraint_name = 'ck_auth_user_permission_scope');
SET @ddl = IF(@has > 0, 'ALTER TABLE auth_user_permission DROP CHECK ck_auth_user_permission_scope', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
ALTER TABLE auth_user_permission
  ADD CONSTRAINT ck_auth_user_permission_scope
  CHECK (data_scope IN ('all', 'company', 'organization', 'own', 'submitted', 'assigned', 'none'));

-- 9.2 公司管理员角色
INSERT INTO auth_role (role_code, role_name, is_system, is_super_admin, is_active)
VALUES ('company_admin', '公司管理员', 1, 0, 1)
ON DUPLICATE KEY UPDATE role_name = VALUES(role_name), is_active = 1;

-- 9.3 公司管理与跨公司调拨模块
INSERT INTO auth_module (module_code, module_name, category, sort_order, is_active)
VALUES
  ('company_management', '公司管理', 'system', 145, 1),
  ('asset_transfer', '跨公司调拨', 'asset', 26, 1)
ON DUPLICATE KEY UPDATE
  module_name = VALUES(module_name),
  category = VALUES(category),
  sort_order = VALUES(sort_order),
  is_active = 1;

INSERT IGNORE INTO auth_permission (module_code, action_code)
SELECT m.module_code, a.action_code
FROM (
  SELECT 'company_management' AS module_code
  UNION ALL SELECT 'asset_transfer'
) m
CROSS JOIN (
  SELECT 'view' AS action_code
  UNION ALL SELECT 'create'
  UNION ALL SELECT 'update'
  UNION ALL SELECT 'delete'
  UNION ALL SELECT 'approve'
  UNION ALL SELECT 'export'
) a;

-- 9.4 公司管理权限赋给超级管理员/管理员（data_scope=all）
INSERT INTO auth_role_permission (
  role_id, permission_id, can_view, can_create, can_update,
  can_delete, can_approve, can_export, data_scope
)
SELECT
  role.role_id, permission.permission_id,
  1, 1, 1, 1, 0, 0, 'all'
FROM auth_role role
JOIN auth_permission permission ON permission.module_code = 'company_management'
WHERE role.is_active = 1 AND (role.is_super_admin = 1 OR role.role_code = 'admin')
ON DUPLICATE KEY UPDATE can_view = 1, can_create = 1, can_update = 1, can_delete = 1, data_scope = 'all';

-- 9.5 跨公司调拨权限：管理员可 create/export，公司管理员可 create（本公司范围）
INSERT INTO auth_role_permission (
  role_id, permission_id, can_view, can_create, can_update,
  can_delete, can_approve, can_export, data_scope
)
SELECT
  role.role_id, permission.permission_id,
  1, 1, 0, 0, 0, 1,
  CASE WHEN role.role_code = 'company_admin' THEN 'company' ELSE 'all' END
FROM auth_role role
JOIN auth_permission permission ON permission.module_code = 'asset_transfer'
WHERE role.is_active = 1
  AND (role.is_super_admin = 1 OR role.role_code IN ('admin', 'company_admin'))
ON DUPLICATE KEY UPDATE
  can_view = 1, can_create = 1, can_export = 1,
  data_scope = IF(VALUES(role_id) = (SELECT role_id FROM auth_role WHERE role_code = 'company_admin' LIMIT 1), 'company', 'all');

-- ============================================================================
-- 迁移登记（migration_runner 会登记 schema_migration；此处不手工插表）
-- ============================================================================
