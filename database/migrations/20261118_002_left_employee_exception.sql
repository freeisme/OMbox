SET NAMES utf8mb4;

-- ============================================================================
-- 离职异常项结清：记录「异常待处理」资产的后续处理与撤销
-- 迁移：20261118_002_left_employee_exception.sql
-- 说明：离职归档本身是历史快照（不可改），结清状态单独存本表；
--       item_index 为该归档 device_snapshot 数组中的下标（快照不变，下标稳定）。
--       撤销结清保留记录（revoked_at/revoked_by），不删除行。
-- 幂等：CREATE TABLE IF NOT EXISTS。
-- ============================================================================

CREATE TABLE IF NOT EXISTS left_employee_exception (
  exception_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  archive_id   BIGINT UNSIGNED NOT NULL,
  item_index   INT UNSIGNED NOT NULL COMMENT '归档 device_snapshot 数组下标',
  item_label   VARCHAR(255) NOT NULL DEFAULT '',
  resolution   VARCHAR(32) NOT NULL COMMENT 'recovered 已找回 / scrapped 已报废 / compensated 已赔付 / other 其他',
  note         VARCHAR(500) NOT NULL DEFAULT '',
  resolved_by  VARCHAR(64) NOT NULL DEFAULT '',
  resolved_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revoked_at   DATETIME NULL,
  revoked_by   VARCHAR(64) NOT NULL DEFAULT '',
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (exception_id),
  UNIQUE KEY uq_left_employee_exception (archive_id, item_index),
  KEY idx_left_employee_exception_open (archive_id, revoked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
