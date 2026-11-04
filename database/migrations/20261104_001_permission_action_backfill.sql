SET NAMES utf8mb4;

-- ============================================================================
-- 权限动作补齐
-- 迁移：20261104_001_permission_action_backfill.sql
-- 说明：历史迁移为后续新增模块登记动作时只写了其中几项——巡检管理、机柜视图
--       缺少 approve，外链应用缺少 approve / export。权限保存接口按
--       (module_code, action_code) 定位 auth_permission，组合不存在时整批
--       保存失败并报 Unsupported permission module.。
--       本迁移按「活跃模块 × 六个标准动作」补齐缺失行，幂等，可重复执行；
--       已存在的行为不受影响，角色授权也不改动。
-- ============================================================================

INSERT IGNORE INTO auth_permission (module_code, action_code)
SELECT m.module_code, a.action_code
FROM auth_module m
CROSS JOIN (
  SELECT 'view' AS action_code
  UNION ALL SELECT 'create'
  UNION ALL SELECT 'update'
  UNION ALL SELECT 'delete'
  UNION ALL SELECT 'approve'
  UNION ALL SELECT 'export'
) a
LEFT JOIN auth_permission p
  ON p.module_code = m.module_code
 AND p.action_code = a.action_code
WHERE m.is_active = 1
  AND p.permission_id IS NULL;
