SET NAMES utf8mb4;

-- 只读角色（viewer）恢复最小权限。
-- 种子脚本 20260817_001_access_control.sql 第 172-173 行明确排除了
-- user_management / role_management / system_updates 三个模块，
-- 但历史库中这三类权限被授予了 can_view，导致只读账号能读到权限矩阵与账号清单。
-- 本迁移幂等：重复执行结果一致，不影响其它角色。
UPDATE auth_role_permission rp
JOIN auth_role r ON r.role_id = rp.role_id
JOIN auth_permission p ON p.permission_id = rp.permission_id
SET rp.can_view = 0,
    rp.can_export = 0
WHERE r.role_code = 'viewer'
  AND p.module_code IN ('user_management', 'role_management', 'system_updates');
