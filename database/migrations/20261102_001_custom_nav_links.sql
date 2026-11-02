SET NAMES utf8mb4;

-- ============================================================================
-- 自定义外链应用（左侧导航栏）
-- 迁移：20261102_001_custom_nav_links.sql
-- 说明：管理员可在「设置 → 外链应用」维护若干外部链接，显示在左侧导航栏
--       「外链应用」分组里，点击后在新标签页打开。
-- ============================================================================

CREATE TABLE IF NOT EXISTS custom_nav_link (
  link_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  title VARCHAR(128) NOT NULL,
  url VARCHAR(500) NOT NULL,
  icon VARCHAR(64) NOT NULL DEFAULT '',
  sort_order INT NOT NULL DEFAULT 1000,
  open_mode VARCHAR(16) NOT NULL DEFAULT 'new_tab',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (link_id),
  KEY idx_custom_nav_link_active (is_active, sort_order),
  CONSTRAINT fk_custom_nav_link_created_by
    FOREIGN KEY (created_by) REFERENCES user_account (user_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT ck_custom_nav_link_open_mode CHECK (open_mode IN ('new_tab', 'same_tab')),
  CONSTRAINT ck_custom_nav_link_active CHECK (is_active IN (0, 1))
) ENGINE=InnoDB;

INSERT INTO auth_module (module_code, module_name, category, sort_order, is_active)
VALUES ('custom_nav_links', '外链应用', 'system', 146, 1)
ON DUPLICATE KEY UPDATE
  module_name = VALUES(module_name),
  category = VALUES(category),
  sort_order = VALUES(sort_order),
  is_active = 1;

INSERT IGNORE INTO auth_permission (module_code, action_code)
SELECT 'custom_nav_links', a.action_code
FROM (
  SELECT 'view' AS action_code
  UNION ALL SELECT 'create'
  UNION ALL SELECT 'update'
  UNION ALL SELECT 'delete'
) a;

INSERT INTO auth_role_permission (
  role_id, permission_id, can_view, can_create, can_update,
  can_delete, can_approve, can_export, data_scope
)
SELECT role.role_id, permission.permission_id, 1, 1, 1, 1, 0, 0, 'all'
FROM auth_role role
JOIN auth_permission permission ON permission.module_code = 'custom_nav_links'
WHERE role.is_active = 1 AND (role.is_super_admin = 1 OR role.role_code = 'admin')
ON DUPLICATE KEY UPDATE
  can_view = 1, can_create = 1, can_update = 1, can_delete = 1, data_scope = 'all';
