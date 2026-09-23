SET NAMES utf8mb4;

-- 设备类型放开到自定义之后，机柜内的设备类型也必须跟着放开：
-- 上架时服务层与这条 CHECK 都会拦住非预设类型（表现为「设备类型无效」）。
-- 1) 去掉枚举约束；2) 放宽列宽，容纳更长的自定义类型名。

ALTER TABLE rack_device_placement
  DROP CHECK ck_rack_placement_category;

ALTER TABLE rack_device_placement
  MODIFY COLUMN category VARCHAR(64) NOT NULL DEFAULT 'other';
