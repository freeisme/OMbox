SET NAMES utf8mb4;

-- 网络拓扑"自由画布"：设备改为手动放到画布上（坐标仍存 topology_node_position），
-- 画布上还可以放文字批注（本表）。这里只新增一张表，不改动历史数据。

CREATE TABLE IF NOT EXISTS topology_annotation (
  annotation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  text VARCHAR(500) NOT NULL,
  x INT NOT NULL DEFAULT 0,
  y INT NOT NULL DEFAULT 0,
  style VARCHAR(16) NOT NULL DEFAULT 'note',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_by BIGINT UNSIGNED NULL,
  updated_by BIGINT UNSIGNED NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (annotation_id),
  KEY idx_topology_annotation_active (is_active, annotation_id),
  CONSTRAINT fk_topology_annotation_created_by
    FOREIGN KEY (created_by) REFERENCES user_account (user_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT fk_topology_annotation_updated_by
    FOREIGN KEY (updated_by) REFERENCES user_account (user_id)
    ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT ck_topology_annotation_style CHECK (style IN ('note', 'title', 'warn')),
  CONSTRAINT ck_topology_annotation_active CHECK (is_active IN (0, 1))
) ENGINE=InnoDB;
