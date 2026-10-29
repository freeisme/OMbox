-- ============================================================================
-- 集团多公司迁移核验脚本（只读，无副作用）
-- 用法：mysql -h <host> -u <user> -p <db> --default-character-set=utf8mb4 < 本文件
-- 每项应返回 0（无问题）；有问题的项会返回非 0 或列出明细。
-- ============================================================================
SET NAMES utf8mb4;

SELECT '=== 1) company 表存在且至少 1 条 ===' AS check_item;
SELECT IF(COUNT(*) >= 1, 0, 1) AS problem_count FROM company;

SELECT '=== 2) org_unit 无 NULL company_id ===' AS check_item;
SELECT COUNT(*) AS null_company_orgs FROM org_unit WHERE company_id IS NULL;

SELECT '=== 3) 各业务表无 NULL company_id ===' AS check_item;
SELECT
  (SELECT COUNT(*) FROM computer_asset WHERE company_id IS NULL) AS computer_null,
  (SELECT COUNT(*) FROM inventory_warehouse WHERE company_id IS NULL) AS warehouse_null,
  (SELECT COUNT(*) FROM asset_site WHERE company_id IS NULL) AS site_null,
  (SELECT COUNT(*) FROM asset_rack WHERE company_id IS NULL) AS rack_null,
  (SELECT COUNT(*) FROM datacenter_device WHERE company_id IS NULL) AS dc_device_null,
  (SELECT COUNT(*) FROM site_device WHERE company_id IS NULL) AS site_device_null;

SELECT '=== 4) 每个员工恰好一条主职位 ===' AS check_item;
SELECT COUNT(*) AS employees_without_primary
FROM employee e
WHERE NOT EXISTS (
  SELECT 1 FROM employee_position ep
  WHERE ep.employee_id = e.employee_id AND ep.is_primary = 1
);

SELECT '=== 5) 存在多个主职位的员工数（应为 0）===' AS check_item;
SELECT COUNT(*) AS employees_with_multiple_primary
FROM (
  SELECT employee_id
  FROM employee_position
  WHERE is_primary = 1
  GROUP BY employee_id
  HAVING COUNT(*) > 1
) bad;

SELECT '=== 6) 系统设置四键存在 ===' AS check_item;
SELECT
  SUM(setting_key = 'group_name') AS group_name,
  SUM(setting_key = 'group_setup_done') AS group_setup_done,
  SUM(setting_key = 'module_datacenter_enabled') AS dc_enabled,
  SUM(setting_key = 'module_inspection_enabled') AS inspection_enabled
FROM system_setting;

SELECT '=== 7) 权限：company_admin 角色存在 ===' AS check_item;
SELECT COUNT(*) AS company_admin_roles FROM auth_role WHERE role_code = 'company_admin';

SELECT '=== 8) 权限：company_management / asset_transfer 模块存在 ===' AS check_item;
SELECT
  SUM(module_code = 'company_management') AS company_mgmt,
  SUM(module_code = 'asset_transfer') AS asset_transfer
FROM auth_module;

SELECT '=== 9) 数据范围约束已含 company ===' AS check_item;
SELECT COUNT(*) AS scope_check_constraints_without_company
FROM information_schema.table_constraints
WHERE constraint_schema = DATABASE()
  AND table_name IN ('auth_role_permission', 'auth_user_permission')
  AND constraint_name LIKE 'ck_%scope'
  AND constraint_type = 'CHECK'
  AND NOT EXISTS (
    SELECT 1 FROM information_schema.check_constraints cc
    WHERE cc.constraint_schema = DATABASE()
      AND cc.constraint_name = table_constraints.constraint_name
      AND cc.check_clause LIKE '%company%'
  );
