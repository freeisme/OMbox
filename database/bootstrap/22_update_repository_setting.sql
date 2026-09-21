-- Add the optional update-check repository URL setting.

SET NAMES utf8mb4;

INSERT INTO system_setting (setting_key, setting_value, setting_description)
VALUES
  (
    'update_repository_url',
    '',
    '用于版本检查的 Git 仓库地址（GitHub 或内网 Git）；为空时使用服务器部署目录 origin'
  )
ON DUPLICATE KEY UPDATE
  setting_description = VALUES(setting_description);
