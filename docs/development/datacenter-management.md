# 机房管理（设备台账 / 机柜视图 / 设备面板 / 网络拓扑 / 机房巡检）

「机房管理」是导航里的一组页面，围绕机房里的**网络设备与服务器**展开：

| 页面 | 路径 | 作用 |
| --- | --- | --- |
| 网络设备/服务器 | `/datacenter-devices` | 机房设备台账：新增、修改、状态维护、删除 |
| 机柜视图 | `/rack-layout` | 把台账设备放到机柜 U 位，拖动改位置，上架/下架 |
| 设备面板 | `/device-panel` | 按型号渲染设备面板，维护端口与链路 |
| 网络拓扑 | `/topology` | 由端口连接自动分层生成拓扑图，可导出 SVG/PNG |
| 机房巡检 | `/inspection` | 按机房、弱电间或机柜发起巡检并输出巡检表 |

导航分组与页面路径都在 `frontend/src/navigation.ts` 的 `NAV_ITEMS`/`NAV_GROUPS`；
页面组件全部是 Vue，路由见 `frontend/src/router/index.ts` 的 `VIEW_LOADERS`（懒加载）。

## 设备台账为什么要独立

机房里的交换机、防火墙、UPS、服务器**不是**办公终端，也不是按数量管理的 IT 物资。
把它们混进办公终端台账会带来两个问题：未上架设备列表里出现大量笔记本，以及"领用/归还"
这类人员流程被套到机柜设备上。所以从 v2.12.0 起：

* 机房设备单独存 `datacenter_device`；
* **机柜视图的"未上架设备"只来自这张表**，办公终端（`computer_asset`）与 IT 物资
  （`it_inventory_model`）都不会出现；
* 办公终端与 IT 物资仍在各自模块里管理，两边互不影响。

## 设备状态

| 状态 | 含义 | 谁能改 |
| --- | --- | --- |
| `stock` 未上架 | 在库房或待上架，可以被上架 | 台账页、上架/下架自动 |
| `installed` 上架 | 已经放进某个机柜 | 只能由机柜视图的上架操作写入 |
| `repair` 维修 | 仍在机柜里占位，但标记为故障维修 | 台账页 |
| `scrapped` 报废 | 不再使用，不允许再上架 | 台账页 |

规则细节：

1. 在台账页手工选择"上架"会被拒绝，提示由上架操作设置；
2. 已上架设备要改回"未上架"，必须先在机柜视图下架，否则报冲突；
3. 设备仍在机柜里时不能在台账里删除；
4. 只有"未上架"的设备能出现在机柜视图的待上架列表里；
5. 上架时同步写入 `site_id`、`rack_id` 与状态；下架时清空位置并回到"未上架"。
6. 机柜视图**只接受机房设备台账里的设备**：办公终端与 IT 物资既不显示在待上架列表里，
   也不能通过接口手工上架（v2.15.0 起移除了这两条创建路径，历史记录仍可正常读取）。

## 数据模型

迁移文件：`database/migrations/20260918_004_datacenter_devices.sql`、
`database/migrations/20260922_001_datacenter_device_details.sql`（补充运维字段）、
`database/migrations/20260923_001_datacenter_device_category_free.sql`（设备类型改为自由填写）。

* 新增 `datacenter_device`：设备编号（唯一）、名称、型号库关联、品牌型号、类型、U 高、
  SN/ST、固资编码、使用人、用途、远程访问地址、CPU、内存、硬盘、状态、所在机房与机柜、备注；
* 设备类型 `category` **不再有枚举 CHECK 约束**：常见的 12 个预设值仍会被归一化
  （例如「交换机」→ `network`），预设外的取值按原文保存（最长 64 字符）；
  台账页的类型下拉按"已有类型"生成，并允许直接输入新类型；
* `rack_device_placement` 新增 `datacenter_device_id`（唯一索引：一台设备只能在一个机柜位置）
  与 FK，并把 `source_kind` 扩成 `computer | custom | datacenter`（历史记录继续有效）。

## 接口

```text
GET    /api/datacenter-devices?status=&keyword=&siteId=
POST   /api/datacenter-devices
PUT    /api/datacenter-devices/{id}
POST   /api/datacenter-devices/{id}/remove
POST   /api/datacenter-devices/import         上传 xlsx/csv 导入（支持 dryRun 预览）
GET    /api/rack-layout/available            未上架设备（只返回机房设备）
POST   /api/rack-layout/racks/{id}/placements  sourceKind=datacenter
```

权限沿用 `rack_layout` 模块（view / create / update / delete），审计动作：
`datacenter_device_created`、`datacenter_device_updated`、`datacenter_device_removed`，
上架/下架继续写 `rack_placement_created` / `rack_placement_removed`。

## 上传 Excel 导入设备

台账页「导入 Excel」支持 **.xlsx / .xlsm / .csv**（读取第一个工作表，上限 8MB、1000 行）。
解析用标准库实现（`office_asset/xlsx.py`），不引入第三方依赖。

表头必须包含**设备编号**与**设备名称**，其余列按名称自动识别（大小写、空格、下划线与连字符都会被忽略）：

| 列 | 别名示例 | 说明 |
| --- | --- | --- |
| 设备编号 | 编号、设备编码、资产编号 | 唯一；重复时按导入模式处理 |
| 设备名称 | 名称、设备名 | 必填 |
| 品牌型号 | 型号、品牌及型号、型号规格 | |
| 设备类型 | 类型、类型名称 | 支持中文（服务器/网络设备/交换机/配线架/UPS/存储…）或英文枚举 |
| 占用高度 | U高、高度、占用U位 | 允许写 `2U`、`2`、`2.0`；范围 1-50 |
| SN/ST | SN、序列号 | |
| 固资编码 | 固定资产编号、资产编码 | |
| 使用人 | 责任人、负责人、保管人 | |
| 状态 | 设备状态、使用状态 | 只接受「未上架 / 维修 / 报废」；写「上架」会被拒绝 |
| 备注 | 说明、描述 | |

流程与规则：

1. 选文件后先**预览**（`dryRun`）：显示识别到的列、总行数、将新增/更新/跳过的数量，以及逐行错误；
2. 确认后正式导入；重复设备（按设备编号）可选「跳过」或「更新」；
3. 一行有问题只影响这一行，其余照常导入，错误在结果里给出 Excel 行号与原因；
4. 已上架（`installed`）的设备不能被导入改成「未上架」，必须先到机柜视图下架；
5. 每行都走与手工新增相同的校验与审计，导入整体再写一条
   `datacenter_device_imported`（文件名、行数、新增/更新/跳过/错误数）。
6. 台账页「下载模板」会生成一个带表头与示例行的 CSV，按它填好另存为 xlsx 即可。

接口请求体形如：

```json
{"fileName":"设备清单.xlsx","contentBase64":"<base64>","dryRun":true,"mode":"skip"}
```

## 验证

```powershell
python -m unittest tests.test_regressions

$env:DB_PASSWORD = "<password>"
$env:DB_NAME = "office_asset_mgmt_codex_rack_layout_20260918"
$env:MYSQL_BIN = "mysql"
python .\tests\integration\qa_rack_layout_regression.py
```

端到端脚本覆盖：新建机房设备 → 未上架列表只出现机房设备（断言办公终端不出现）→
上架后状态变 `installed` 且写入机柜 → 下架后回到 `stock` 并清空位置。

健康检查 `/api/health` 的必需表数量为 70。
