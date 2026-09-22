SET NAMES utf8mb4;

-- 机房设备台账补充运维字段：用途、远程访问地址、CPU、内存、硬盘。
-- 只新增列，已有设备这些列为空字符串，不影响历史数据与查询。

ALTER TABLE datacenter_device
  ADD COLUMN purpose VARCHAR(160) NOT NULL DEFAULT '' AFTER owner_label,
  ADD COLUMN remote_access VARCHAR(255) NOT NULL DEFAULT '' AFTER purpose,
  ADD COLUMN cpu VARCHAR(64) NOT NULL DEFAULT '' AFTER remote_access,
  ADD COLUMN memory VARCHAR(64) NOT NULL DEFAULT '' AFTER cpu,
  ADD COLUMN disk VARCHAR(64) NOT NULL DEFAULT '' AFTER memory;
