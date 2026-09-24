# 设备面板与网络拓扑

阶段 1、2 的交付：**型号库 + 端口 + 线缆 + 拓扑图**。它们是「机柜视图」的延伸——
机柜视图回答"设备装在哪"，设备面板回答"端口的线插到哪"，网络拓扑回答"整张网怎么连"。

## 数据模型

迁移文件：`database/migrations/20260918_003_device_ports_and_cables.sql`（只新增表）。

| 表 | 用途 |
| --- | --- |
| `device_type_catalog` | 型号库：slug、厂商、型号、料号、U 高、类别、是否有正/背面板图与图片路径、来源 |
| `device_type_port_template` | 型号的端口模板：端口名、类型、类别（network/fiber/power/console/other）、面板、行列位置 |
| `rack_device_port` | 实例端口：属于某个已上架设备（`rack_device_placement`），含方向、速率、状态 |
| `rack_cable_run` | 线缆：A/B 两端端口、介质、长度、标签、状态，软删除 |
| `topology_node_position` | 拓扑节点的人工坐标（拖动后可保存） |

### 关键规则

1. **一个端口只能有一条活动链路**：用生成列 `a_active_key`/`b_active_key`（软删除时置 NULL）加唯一索引表达，
   删除链路后端口可重新连；
2. **不能自己连自己**，两端端口必须存在且属于已上架设备（服务层校验，DB 不建 CHECK 以避开外键限制）；
3. **端口模板 → 实例端口是快照**：按型号生成后，端口可单独增删改，改模板不影响已上架设备；
4. **删除端口会级联删除它的链路**（表级 `ON DELETE CASCADE`），并在审计中记录删掉了多少条链路；
5. **跨机柜、跨站点连线允许**（骨干需要），界面上会标注两端位置。

## 型号库（手工维护）

从 v2.14.0 起**不再从外部型号库抓取**（原先的 NetBox devicetype-library 导入工具已删除）。
型号与端口模板改为手工维护：管理员调用 `POST /api/device-types` 提交厂商、型号、U 高、
类别与端口列表（端口可以留空，之后在设备面板里逐个补）。

型号库的作用只有一个：给"按型号生成端口"提供模板、给设备面板提供排布参考。
没有型号也能用——设备面板支持逐条新增端口。

设备台账本身通过**上传 Excel 导入**，见[机房管理](datacenter-management.md)。

## 接口

```text
GET    /api/device-types                     型号库列表（按关键字过滤）
GET    /api/device-types/{id}                型号详情 + 端口模板
POST   /api/device-types                     手工新增/更新型号与端口模板（管理员）
GET    /api/rack-layout/racks/{id}/ports     机柜内全部端口（含链路对端）
POST   /api/rack-layout/placements/{id}/ports            新增端口
POST   /api/rack-layout/placements/{id}/ports/import     按型号模板生成端口
PUT    /api/rack-layout/ports/{id}                       修改端口
POST   /api/rack-layout/ports/{id}/remove                删除端口（连带链路）
GET    /api/rack-layout/cables?rackId=&siteId=           链路列表
POST   /api/rack-layout/cables                           新建链路（支持 Idempotency-Key）
POST   /api/rack-layout/cables/import                    批量导入链路（逐行容错）
PUT    /api/rack-layout/cables/{id}                      修改链路
POST   /api/rack-layout/cables/{id}/remove               删除链路
GET    /api/rack-layout/topology?siteId=&rackId=&onlyLinked=
POST   /api/rack-layout/topology/positions               保存节点坐标
```

权限沿用 `rack_layout` 模块：读需要 `view`，写端口/线缆/坐标需要 `create`/`update`/`delete`。
审计动作：`device_type_saved`、`placement_ports_initialized`、`rack_port_created`、
`rack_port_updated`、`rack_port_removed`、`rack_cable_created`、`rack_cable_updated`、
`rack_cable_removed`、`topology_positions_saved`。

## 前端（Vue）

v2.10.0 起前端是 Vue 3 + TypeScript + Vite + Element Plus，新增页面都写在 `frontend/src/views/`，
入口在 `frontend/src/navigation.ts` 的 `NAV_ITEMS`，路由在 `frontend/src/router/index.ts` 的
`VIEW_LOADERS` 里登记（全部懒加载）。旧前端已整体删除，仓库里只有 Vue 一套实现。

| 页面 | 路径 | 能力 |
| --- | --- | --- |
| 机柜视图 | `/rack-layout` | 机柜图、拖动换 U 位、上架/下架、属性编辑、导出清单、打印机柜图、发起巡检 |
| 设备面板 | `/device-panel` | 按型号渲染设备面板（有面板图用图 + 端口热点，没有则自绘）、端口列表与状态、点两个端口连线、按型号生成端口 |
| 网络拓扑 | `/topology` | 按端口连接自动分层（边界/核心 → 汇聚 → 接入）、节点拖动与坐标保存、**在图上加端口 / 连线 / 改链路属性**、聚焦查看、导出 SVG/PNG/链路清单/节点清单、打印 |

### 拓扑图上直接编辑（v3.0.15）

拓扑图不再只是只读展示，选中设备就能加端口、连链路；后端接口全部复用设备面板那一套
（`POST /api/rack-layout/placements/{id}/ports`、`/ports/import`、`/ports/copy`、`/ports/batch`、
`PUT /api/rack-layout/ports/{id}`、`POST /api/rack-layout/ports/{id}/remove`、
`POST /api/rack-layout/cables`、`PUT /api/rack-layout/cables/{id}`、`POST /api/rack-layout/cables/{id}/remove`），
因此校验规则（一个端口只能有一条活动链路、不能自连、两端必须属于已上架设备）完全一致，**没有新迁移**。

连线交互是"点选式"四步：`新建链路` → 点 A 端设备 → 选端口或新建端口 → 点 B 端设备 → 选端口或新建端口 → 填介质/长度/标签。
顶栏会显示当前步骤与已选的 A/B 端，随时可以「取消连线」；B 端选同一台设备、选中已被占用的端口都会在前端先拦下来。

端口弹窗有四个页签：

| 页签 | 用途 |
| --- | --- |
| 端口列表 | 看该设备端口、速率、IP/VLAN、占用与对端；向导模式下点「选择」即选定该端口 |
| 按型号生成 | 用型号库的端口模板生成；也可以选**另一台已配好端口的设备**整份复制（同名端口跳过） |
| 批量生成 | 按 `GE1/0/{n}` 这类模板批量生成（序号范围、步长、每行个数可调，一次最多 256 个） |
| 手工添加 | 逐条新增/编辑端口；除名称外都是可选字段，含 IP/掩码、VLAN、速率、面板/行/位、备注 |

链路属性在右侧「链路属性」卡片里改（介质、长度、标签、状态、备注），也可以直接删除；点画布上的连线即选中它。

**三种连线方式并存**（v3.0.16 起）：除上面的点选式向导外，还可以
把节点右边缘的**连线手柄**拖到另一台设备上，松手后用弹窗确认两端端口（自动预选两端的第一条空闲端口）；
以及在空白处**拉框多选**设备后拖动其中任意一台，实现整组平移。

布局操作可以**撤销 / 重做**（工具栏按钮或 `Ctrl+Z` / `Ctrl+Y`，最多保留 50 步）：
栈里只记节点坐标，端口与链路属于服务端数据，不进这个栈（要删链路用「链路属性 → 删除链路」）。

展示与导出：介质决定连线颜色（电口灰蓝、光纤橙黄、DAC 绿、电源红）、同一对设备之间的多条链路
（堆叠 / LACP）横向错开显示而不是合并成一条、可在「正交走线 / 直线走线」之间切换、链路标签可开关、
拖动节点可以开「网格吸附」；「只看选中设备相关」会把画面收敛到选中节点与它的一跳邻居。
除原有的 SVG / PNG / 打印外，新增两个 CSV 导出：**链路清单**（A/B 端设备与端口、介质、长度、标签、状态、备注）
与**节点清单**（设备、型号、类别、机房、机柜、U 位、端口数、已连端口、层级）。

### 面板图片（阶段 3）

设备面板页的「型号与面板图」可以：

* 新建或编辑型号（厂商、型号、型号编码、U 高、类别、端口列表——每行一个 `端口名,类型`）；
* 上传正面 / 背面面板图（PNG、JPEG、WebP，单张 2MB 以内），保存到
  `web/assets/device-images/<厂商>/<型号>.<面>.<扩展名>`，路径写回型号库；
* 面板页把端口热点叠在图片上，顶栏的「显示面板图」可以随时切回自绘模式；
  图片加载失败时自动回退到自绘，不影响端口操作。

接口：`POST /api/device-types/{id}/image`、`POST /api/device-types/{id}/image/remove`
（审计动作 `device_type_image_saved` / `device_type_image_removed`）。

### 多机柜并排（阶段 3）

机柜视图顶栏的「单柜 / 并排」切换：并排模式把同一机房的机柜横向排开共用 U 行高，
只读展示，点任意设备回到单柜视图编辑它。机柜数量多时横向滚动。

拓扑分层在前端计算：以度数最高的节点（通常是核心交换机或防火墙）为根做 BFS，
同层按机柜与名称排序；保存过坐标的节点优先使用保存值。整张图是纯 SVG，导出 PNG 走
`SVG → Image → Canvas → toBlob`，不需要服务端渲染。

## 验证

```powershell
python -m unittest tests.test_regressions

$env:DB_PASSWORD = "<password>"
$env:DB_NAME = "office_asset_mgmt_codex_device_topology_20260918"
$env:MYSQL_BIN = "mysql"
python .\tests\integration\qa_device_topology_regression.py
```

端到端脚本覆盖：型号导入与端口模板解析、按模板生成端口（幂等）、手工新增端口、
机柜端口清单、建链路与幂等重复提交、端口占用冲突、同端口重复连接、拓扑节点与链路、
坐标保存、删除链路与端口、审计留痕、只读账号被拒绝。

健康检查 `/api/health` 的必需表数量为 71（v3.0.18 起加入 `site_device`）。

## 本版不做的事

- 不做 SNMP/LLDP 自动发现（阶段 4），链路仍以人工维护为主；
- 不做 0.5U/半宽端口与面板像素级定位，端口按行列序号渲染；
- 不做 IP/VLAN 地址管理（这属于 NetBox 的 IPAM 范畴）；端口上的 IP / VLAN 只是台账备注字段，不做冲突校验；
- 批量导入链路只提供接口与 CSV 结构，界面暂不做导入向导。
