SET NAMES utf8mb4;

-- 设备类型不再限定在预设枚举内：网络设备种类多，预设覆盖不过来。
-- 1) 去掉 CHECK 约束，允许自定义类型；2) 放宽列宽，容纳更长的中文类型名。
-- 已有的 12 个枚举值仍然是"别名归一化"的目标，历史数据不受影响。

ALTER TABLE datacenter_device
  DROP CHECK ck_datacenter_device_category;

ALTER TABLE datacenter_device
  MODIFY COLUMN category VARCHAR(64) NOT NULL DEFAULT 'other';
