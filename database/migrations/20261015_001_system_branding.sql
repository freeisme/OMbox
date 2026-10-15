-- 系统品牌：公司 Logo 可以上传，并在导出 Excel 时附带。
--
-- setting_value 原为 VARCHAR(1000)，放不下 PNG 的 base64（data URI），放宽到 MEDIUMTEXT；
-- 两个新键都只在缺失时插入，不覆盖管理员已经改过的值。

SET NAMES utf8mb4;

ALTER TABLE system_setting
  MODIFY COLUMN setting_value MEDIUMTEXT NOT NULL;

INSERT INTO system_setting (setting_key, setting_value, setting_description)
VALUES
  ('app_logo', '', '系统 Logo（PNG 的 data URI，显示在左上角与页面标题）'),
  ('export_logo_enabled', '0', '导出 Excel 时是否在表格左上角附带公司 Logo（1=附带）')
ON DUPLICATE KEY UPDATE
  setting_description = VALUES(setting_description);
