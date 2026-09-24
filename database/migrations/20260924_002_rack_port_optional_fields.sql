SET NAMES utf8mb4;

-- 端口补充两个可选字段（非必填，默认空串，不改变既有数据）：
--   ip_address：端口上的 IP/掩码或管理地址，便于在拓扑图与设备面板上直接看到三层地址；
--   vlan：端口所属 VLAN（号或名称），只在用户愿意填写时记录。

ALTER TABLE rack_device_port
  ADD COLUMN ip_address VARCHAR(64) NOT NULL DEFAULT '' AFTER status,
  ADD COLUMN vlan VARCHAR(32) NOT NULL DEFAULT '' AFTER ip_address;
