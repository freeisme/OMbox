SET NAMES utf8mb4;

-- ============================================================================
-- 机房文件库：为机房/弱电间与其下设备提供配置文件归档
-- 迁移：20261118_001_file_library.sql
-- 结构：一级目录=机房(site)，二级目录=设备(device)，文件挂在二级目录下。
--       文件实体存磁盘卷（FILE_LIBRARY_ROOT），本表只存元数据。
-- 版本：同名文件默认保留历史版本（is_current 标记当前版本）。
-- 权限：复用机房模块 rack_layout（view/create/update/delete），不新增模块。
-- 幂等：CREATE TABLE IF NOT EXISTS，可重复执行。
-- ============================================================================

CREATE TABLE IF NOT EXISTS file_folder (
  folder_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  folder_type   ENUM('site','device') NOT NULL,
  site_id       BIGINT UNSIGNED NULL COMMENT '机房/弱电间；folder_type=site 时必填',
  device_id     BIGINT UNSIGNED NULL COMMENT '机房设备；folder_type=device 时必填',
  display_name  VARCHAR(255) NOT NULL DEFAULT '',
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (folder_id),
  UNIQUE KEY uq_file_folder_site (site_id),
  UNIQUE KEY uq_file_folder_device (device_id),
  KEY idx_file_folder_type (folder_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS file_object (
  file_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  folder_id       BIGINT UNSIGNED NOT NULL,
  file_name       VARCHAR(255) NOT NULL COMMENT '展示名（含扩展名）',
  stored_rel_path VARCHAR(500) NOT NULL COMMENT '相对 FILE_LIBRARY_ROOT 的路径',
  size_bytes      BIGINT UNSIGNED NOT NULL DEFAULT 0,
  sha256          CHAR(64) NOT NULL DEFAULT '',
  content_type    VARCHAR(128) NOT NULL DEFAULT '',
  description     VARCHAR(500) NOT NULL DEFAULT '',
  version_no      INT UNSIGNED NOT NULL DEFAULT 1,
  is_current      TINYINT(1) NOT NULL DEFAULT 1 COMMENT '1=当前版本，0=历史版本',
  uploaded_by     VARCHAR(64) NOT NULL DEFAULT '',
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at      DATETIME NULL,
  deleted_by      VARCHAR(64) NOT NULL DEFAULT '',
  PRIMARY KEY (file_id),
  KEY idx_file_folder (folder_id, is_current, deleted_at),
  KEY idx_file_name (folder_id, file_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS file_event (
  event_id   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  file_id    BIGINT UNSIGNED NULL,
  folder_id  BIGINT UNSIGNED NULL,
  action     VARCHAR(32) NOT NULL COMMENT 'upload/download/rename/delete/restore',
  actor      VARCHAR(64) NOT NULL DEFAULT '',
  detail     JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (event_id),
  KEY idx_file_event_folder (folder_id, created_at),
  KEY idx_file_event_file (file_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
