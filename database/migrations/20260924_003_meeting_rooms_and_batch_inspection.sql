SET NAMES utf8mb4;

-- 会议室巡检：把"会议室"作为第三类巡检对象（asset_site.site_type = meeting_room），
-- 支持一次巡检选择多个目标（一个目标一张任务，用 batch_no 归组后用横向巡检表导出），
-- 并新增"会议室设备"台账（可从 IT 物资分配，也可自定义登记）。
--
-- 只新增/放宽约束，不改写历史数据：已有机房、弱电间、模板与巡检任务保持不变。

-- 1) 巡检对象类型：机房 / 弱电间 / 会议室
ALTER TABLE asset_site
  DROP CHECK ck_asset_site_type;

ALTER TABLE asset_site
  ADD CONSTRAINT ck_asset_site_type
  CHECK (site_type IN ('server_room', 'weak_room', 'meeting_room'));

-- 2) 模板适用对象同样增加"会议室"（模板可在机房 / 弱电间 / 会议室 / 通用之间选择）
ALTER TABLE inspection_template
  DROP CHECK ck_inspection_template_site_type;

ALTER TABLE inspection_template
  ADD CONSTRAINT ck_inspection_template_site_type
  CHECK (site_type IN ('server_room', 'weak_room', 'meeting_room', 'both'));

-- 3) 巡检任务：批次号（一次多选开检的任务归为一批）+ 对象类型快照（删除会议室后仍能显示"会议室"）
ALTER TABLE inspection_task
  ADD COLUMN batch_no VARCHAR(32) NOT NULL DEFAULT '' AFTER task_no,
  ADD COLUMN site_type VARCHAR(32) NOT NULL DEFAULT '' AFTER site_name,
  ADD KEY idx_inspection_task_batch (batch_no, started_at);

-- 4) 会议室设备台账：source=inventory 表示从 IT 物资分配（记录扣减的仓库与型号），
--    source=custom 表示自定义登记（不涉及库存）。
CREATE TABLE IF NOT EXISTS site_device (
  device_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  site_id BIGINT UNSIGNED NOT NULL,
  source VARCHAR(16) NOT NULL DEFAULT 'custom',
  device_name VARCHAR(128) NOT NULL DEFAULT '',
  device_type VARCHAR(64) NOT NULL DEFAULT '',
  brand VARCHAR(64) NOT NULL DEFAULT '',
  model VARCHAR(128) NOT NULL DEFAULT '',
  inventory_model_id BIGINT UNSIGNED NULL,
  warehouse_id BIGINT UNSIGNED NULL,
  quantity INT NOT NULL DEFAULT 1,
  status VARCHAR(16) NOT NULL DEFAULT 'in_use',
  notes VARCHAR(500) NOT NULL DEFAULT '',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_by BIGINT UNSIGNED NULL,
  updated_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (device_id),
  KEY idx_site_device_site (site_id, is_active),
  KEY idx_site_device_model (inventory_model_id, is_active),
  CONSTRAINT fk_site_device_site
    FOREIGN KEY (site_id) REFERENCES asset_site (site_id)
    ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_site_device_model
    FOREIGN KEY (inventory_model_id) REFERENCES it_inventory_model (model_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_site_device_warehouse
    FOREIGN KEY (warehouse_id) REFERENCES inventory_warehouse (warehouse_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_site_device_created_by
    FOREIGN KEY (created_by) REFERENCES user_account (user_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_site_device_updated_by
    FOREIGN KEY (updated_by) REFERENCES user_account (user_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT ck_site_device_source CHECK (source IN ('inventory', 'custom')),
  CONSTRAINT ck_site_device_status CHECK (status IN ('in_use', 'returned')),
  CONSTRAINT ck_site_device_quantity CHECK (quantity >= 1),
  CONSTRAINT ck_site_device_active CHECK (is_active IN (0, 1))
) ENGINE=InnoDB;

-- 5) 默认会议室巡检模板（33 项，来自会议室月度巡检表的检查类别 / 检查项目 / 检查内容·判定标准）。
--    判定标准放在 check_method 里，执行页会作为提示文字显示；结论统一用"正常 / 异常 / 不适用"。
INSERT INTO inspection_template (template_code, template_name, site_type, description, is_active)
VALUES (
  'XJ-MEETING-ROOM',
  '会议室巡检',
  'meeting_room',
  '会议室环境、显示与音频视频设备、网络、供电与安全隐患标准巡检表',
  1
)
ON DUPLICATE KEY UPDATE
  template_name = VALUES(template_name),
  site_type = VALUES(site_type),
  description = VALUES(description);

SET @tpl_meeting_room = (
  SELECT template_id FROM inspection_template WHERE template_code = 'XJ-MEETING-ROOM'
);
-- 只在模板还没有事项时写入，避免覆盖用户后来的修改。
SET @meeting_room_item_count = (
  SELECT COUNT(*) FROM inspection_template_item WHERE template_id = @tpl_meeting_room
);

INSERT INTO inspection_template_item (
  template_id, seq_no, category, item_title, check_method, value_type, unit, normal_range, is_required
)
SELECT
  @tpl_meeting_room,
  item.seq_no,
  item.category,
  item.item_title,
  item.check_method,
  'ok_fail',
  '',
  '',
  1
FROM (
  SELECT 10 AS seq_no, '环境' AS category, '卫生与桌面' AS item_title, '地面、桌面整洁，无明显杂物、污渍' AS check_method
  UNION ALL SELECT 20, '环境', '照明', '灯具正常，无明显闪烁、损坏'
  UNION ALL SELECT 30, '环境', '空调与温度', '空调运行正常，温度适宜，设备无过热'
  UNION ALL SELECT 40, '环境', '桌椅及布局', '桌椅完好、摆放整齐，不影响设备使用'
  UNION ALL SELECT 50, '显示设备', '设备开机', '电视/投影仪可正常开机、关机'
  UNION ALL SELECT 60, '显示设备', '画面亮度/色彩', '画面亮度、色彩正常，无明显异常'
  UNION ALL SELECT 70, '显示设备', '画面稳定性', '无黑屏、闪屏、花屏、雪花或间歇性断画'
  UNION ALL SELECT 80, '显示设备', '输入源切换', 'HDMI、无线投屏等输入源切换正常'
  UNION ALL SELECT 90, '连接功能', 'HDMI连接', '插拔正常，连接后能稳定输出画面/声音'
  UNION ALL SELECT 100, '连接功能', 'Type-C连接', '连接后能正常投屏及传输音视频'
  UNION ALL SELECT 110, '连接功能', '无线投屏', '设备可发现、可连接、投屏稳定'
  UNION ALL SELECT 120, '连接功能', '接口/转接头', '接口无松动、损坏，转接头工作正常'
  UNION ALL SELECT 130, '音频设备', '会议音响', '左右声道/扩声正常，无明显杂音'
  UNION ALL SELECT 140, '音频设备', '麦克风收音', '近距离及正常会议距离均能清晰拾音'
  UNION ALL SELECT 150, '音频设备', '麦克风状态', '无线麦电量正常，静音/开关功能正常'
  UNION ALL SELECT 160, '音频设备', '回声/啸叫', '会议测试无明显回声、啸叫、破音'
  UNION ALL SELECT 170, '视频设备', '摄像头画面', '画面清晰，无黑屏、卡顿、异常色偏'
  UNION ALL SELECT 180, '视频设备', '摄像头角度', '镜头角度合适，可覆盖主要参会区域'
  UNION ALL SELECT 190, '视频设备', '摄像头调用', '腾讯会议/钉钉rooms等可正常调用摄像头'
  UNION ALL SELECT 200, '视频会议', '会议登录/入会', '会议软件可正常启动、登录及加入会议'
  UNION ALL SELECT 210, '视频会议', '共享屏幕', '共享桌面/窗口功能正常'
  UNION ALL SELECT 220, '视频会议', '音视频联动', '入会后摄像头、麦克风、音箱均可正常使用'
  UNION ALL SELECT 230, '网络', 'Wi-Fi连接', 'Wi-Fi可正常连接，信号稳定'
  UNION ALL SELECT 240, '网络', '网络稳定性', '测试期间无明显掉线、卡顿'
  UNION ALL SELECT 250, '网络', '延迟/丢包', '会议过程中延迟可接受，无明显丢包现象'
  UNION ALL SELECT 260, '供电', '电源插座', '桌面及墙面插座供电正常，无松动/发热'
  UNION ALL SELECT 270, '控制设备', '中控/控制面板', '开关机、信号切换、音量等控制正常'
  UNION ALL SELECT 280, '控制设备', '遥控器/白板笔', '遥控器按键正常，电池电量充足'
  UNION ALL SELECT 290, '辅助设备', '白板/电子白板', '书写、触控或电子白板功能正常'
  UNION ALL SELECT 300, '辅助设备', '桌面设备', '会议电脑、键鼠等基础设备可正常使用'
  UNION ALL SELECT 310, '线缆与安全', '线缆整理', '线缆无破损、松脱、缠绕，走线整齐'
  UNION ALL SELECT 320, '线缆与安全', '设备安全', '设备固定牢靠，无明显安全隐患'
  UNION ALL SELECT 330, '其他', '其他配套设备', '其他会议配套设备均可正常使用'
) item
WHERE @meeting_room_item_count = 0;
