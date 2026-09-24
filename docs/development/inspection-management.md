# 巡检管理（机房 / 弱电间 / 会议室 / 机柜）

巡检模块覆盖**机房、弱电间、会议室与它们下面的机柜**，不包含办公区终端和 IT 物资仓库。
一次巡检的完整流程是：选择模板与对象（可多选）→ 开始巡检 → 逐项记录结论 → 提交 → 输出整张巡检表。
巡检在导航里是独立分组「巡检管理」（页面 `/inspection`，标题「巡检中心」），不再挂在机房管理下。

## 数据模型

迁移文件：`database/migrations/20260918_001_inspection_management.sql`（只新增对象，不改历史数据）。

| 表 | 用途 |
| --- | --- |
| `asset_site` | 巡检对象：机房 / 弱电间 / 会议室，`site_type` 取 `server_room`、`weak_room` 或 `meeting_room` |
| `asset_rack` | 机柜，归属某个 `asset_site`，含高度（1-100U）与上下方向 |
| `inspection_template` | 巡检模板，`site_type` 取 `server_room`、`weak_room`、`meeting_room` 或 `both` |
| `inspection_template_item` | 模板事项：类别、事项、检查方法、取值类型、单位、正常范围、是否必填 |
| `inspection_task` | 一次巡检：任务号、**批次号**、模板快照、对象快照（含对象类型）、执行人、状态与统计 |
| `inspection_task_item` | 逐项记录：事项快照、结论、实测值、说明、检查人与检查时间 |
| `site_device` | 会议室内设备台账：`source=inventory`（从 IT 物资分配，记录仓库与型号）或 `custom`（自定义登记） |

关键规则：

1. **快照**：开始巡检时把模板事项复制进 `inspection_task_item`，之后修改模板不影响已开始的巡检表；
2. **对象二选一**：任务要么指向一个机房/弱电间/会议室（覆盖其下机柜），要么指向单个机柜；
   该约束由服务层校验，因为 MySQL 不允许在 `ON DELETE SET NULL` 外键引用的列上再建 `CHECK`；
3. **模板匹配**：模板适用对象与巡检对象类型不一致时拒绝开始巡检；
4. **异常必须说明**：结论为异常时，填写与提交两个环节都会校验说明非空；
5. **提交即定稿**：提交后任务与明细只读，不能继续修改，也不能作废；
6. **手动发起**：没有周期计划、没有自动派单，只能由有权限的账号点击“开始巡检”。
7. **多选开检（v3.0.18）**：一次可以勾选多个对象，**一个对象生成一张任务**，
   同批任务共用一个 `batch_no`；导出时把该批次的任务横向排列（一行一个检查项、一列一个对象）。
8. **模板可编辑/删除（v3.0.18）**：模板支持改编码 / 名称 / 适用对象 / 说明与整份替换检查项，也支持删除；
   删除模板会把引用它的历史任务的 `template_id` 置空，任务仍保留模板名称与事项快照。
9. **会议室内设备（v3.0.18）**：从 IT 物资分配会按数量扣减所选仓库与型号库存，并写
   `inventory_movement_log`（`trigger_action=site_allocation`），移除时原路退回（`site_return`）；
   自定义登记不涉及库存。库存不足（仓库数量或型号总量任一不够）直接拒绝，不会把库存扣成负数。
10. **会议室是独立模块（v3.0.18）**：页面 `/meeting-rooms`（侧边栏「巡检管理 → 会议室」）维护
    会议室基本信息与会议室内设备，列表显示 `deviceCount`（来自 `GET /api/inspection/sites` 的新字段）；
    「巡检中心 → 巡检对象」只保留机房 / 弱电间 / 机柜，并用一条提示指向会议室模块，避免两处重复维护。
11. **任务操作下拉 + 作废后可删除（v3.0.18）**：任务列表的「操作」列改为下拉菜单
    （查看 / 下载巡检表 / 导出本次巡检表 / 作废 / 删除（已作废））；
    `DELETE /api/inspection/tasks/{id}` → `delete_task()` 只允许删除 `status='void'` 的任务
    （其余状态返回「只有已作废的巡检任务才能删除，请先作废。」），删除会连带 `inspection_task_item`
    明细（外键级联），并先写一条 `inspection_task_deleted` 审计（含项数与批次号）。

迁移会写入三张标准模板：`XJ-SERVER-ROOM`（机房巡检，16 项）、`XJ-WEAK-ROOM`（弱电间巡检，14 项）
与 `XJ-MEETING-ROOM`（会议室巡检，33 项：来自会议室月度巡检表的检查类别 / 检查项目 / 检查内容·判定标准，
判定标准放在模板事项的“检查方法”里，执行页会作为提示文字显示）。

## 权限与审计

权限模块 `inspection_management`，动作 `view`、`create`、`update`、`delete`、`export`。
管理员角色在迁移中默认获得 `view`、`create`、`update`、`export`。后端逐项校验权限，
前端隐藏按钮不构成安全边界。

审计动作写入 `audit_log`：

| 动作 | 触发点 |
| --- | --- |
| `inspection_site_created` / `inspection_site_updated` | 维护机房、弱电间 |
| `inspection_rack_created` / `inspection_rack_updated` | 维护机柜 |
| `inspection_template_created` / `inspection_template_updated` | 维护模板与事项 |
| `inspection_started` | 开始巡检 |
| `inspection_submitted` | 提交巡检表 |
| `inspection_voided` | 作废未提交的巡检任务 |

## 接口

```text
GET    /api/inspection/sites                 POST   /api/inspection/sites
PUT    /api/inspection/sites/{id}
GET    /api/inspection/racks                 POST   /api/inspection/racks
PUT    /api/inspection/racks/{id}
GET    /api/inspection/templates             POST   /api/inspection/templates
GET    /api/inspection/templates/{id}        PUT    /api/inspection/templates/{id}
GET    /api/inspection/tasks?status=         POST   /api/inspection/tasks
GET    /api/inspection/tasks/{id}
POST   /api/inspection/tasks/{id}/items/{itemId}/check
POST   /api/inspection/tasks/{id}/submit
POST   /api/inspection/tasks/{id}/void
```

`POST /api/inspection/tasks` 支持 `Idempotency-Key`：同一键与同一请求体重复提交返回同一个任务，
键与请求体不一致时返回冲突。所有写接口都需要 CSRF 令牌。

## 前端

侧栏“机房巡检”对应 `data-page="inspection"`，页面分三个分区：

| 分区 | 内容 |
| --- | --- |
| 巡检任务 | 任务列表、状态筛选、开始巡检、继续巡检、查看巡检表、下载巡检表、导入巡检表、作废 |
| 巡检模板 | 模板与事项维护（类别、检查方法、取值类型、单位、正常范围、是否必填） |
| 机房与机柜 | 机房/弱电间与机柜的维护 |

执行页按事项逐行输出：每行三个结论按钮（正常 / 异常 / 不适用）、实测值输入、说明输入。
点击结论按钮即保存，异常项缺少说明时前端提示并阻止保存，后端同样拒绝。
底部提供“异常情况与处理建议”，留空时提交会自动汇总异常项说明。

提交后可“下载巡检表”（CSV：任务信息 + 事项明细，含检查人与检查时间）、“导出巡检表”
（Excel 两个页签：巡检表摘要 + 巡检明细）或“打印”（浏览器打印视图，带巡检人 / 复核人签字栏）。

### 表格导入（v3.0.13 起）

`POST /api/inspection/tasks/import`（权限 `inspection_management` / 创建）接收
`{ fileName, contentBase64, remarks? }`，直接生成一份 `submitted` 的巡检任务，
不需要先“开始巡检”：

* 表头固定为 `机房、机柜、检查项分类、检查项、检查方法、结论、实测值、说明`，
  其中首列在 v3.0.18 起改名为 `巡检对象`（机房 / 弱电间 / 会议室名称都写这一列，
  旧表头 `机房` 仍然识别）；允许同义词（如“机房名称”“会议室名称”“检查内容”“备注”），
  大小写、空格与标点会被忽略；
* 一份表格只能是**一个**机房（可再限定到一个机柜）：与首行不一致的行被跳过并报行号；
* 结论支持“正常 / 异常 / 不适用”与 `ok / fail / na`；异常行必须有说明；
* 接受 `.xlsx`、`.xlsm`（复用 `office_asset.xlsx.read_sheet`）与 `.csv`（UTF-8 BOM 或 GBK），
  单文件 8MB、单次 1000 行以内；
* 机房 / 机柜必须先存在，按名称匹配，且要过组织数据范围校验；匹配不上直接报错，不静默新建；
* 模板表的列定义在前后端各有一份（`office_asset/inspection.py` 的 `IMPORT_COLUMNS` 与
  `frontend/src/api/governance.ts` 的 `INSPECTION_IMPORT_COLUMNS`），回归测试会比对两者一致。

### 填写与保存规则（v2.18.0 起）

判定“已检查”的唯一依据是**该行选了结论**（正常 / 异常 / 不适用）；只在输入框里写实测值或说明
不算已检查，这正是“填完了还提示有未检查”的原因。为此执行页做了四处调整：

1. 数值 / 文本 / 选项型事项多一个「保存」按钮：点它按当前结论（没选就按正常）保存该行，
   在任一输入框里按回车等价；
2. **保存单项只刷新这一行**与顶部统计，不再整表重绘，所以不会把其它行还没保存的输入冲掉；
3. 输入框内容实时暂存为草稿，任何重绘（切页面、重新加载任务）都会把草稿带回来；
4. 点「提交巡检表」时，如果存在“填了内容但还没确认结论”的行，会按事项名称提示（最多 5 项）；
   后端提交校验的报错同样列出未检查 / 缺说明的事项名称，而不是只报数量，
   顶部统计也直接显示「未检查」条数。

### 扫码开检

打开形如 `/#inspection?rack=<机柜编码>` 的链接会自动切到巡检页并预选该机柜，
配合机柜上的二维码即可扫码开检。预选只在编码存在时生效，不存在时不弹窗。

## 验证

```powershell
# 结构回归
python -m unittest tests.test_regressions

# 端到端回归（需要一个已应用全部迁移的一次性数据库）
$env:DB_PASSWORD = "<password>"
$env:DB_NAME = "office_asset_mgmt_codex_inspection_20260918"
$env:MYSQL_BIN = "mysql"
python .\tests\integration\qa_inspection_regression.py
```

端到端脚本覆盖：模板读取、机房与机柜创建、开始巡检快照、幂等重复提交、异常项必须填说明、
未完成不可提交、提交后只读、模板与对象不匹配被拒绝、审计留痕、只读账号被拒绝。

健康检查 `/api/health` 的表数量门槛已从 57 提升为 63，包含巡检相关表。

## 本版不做的事

- 不生成周期巡检计划，也不自动派单；
- 不上传照片，`inspection_task_item` 不保存附件；
- 异常项不自动创建工单，需人工在工单模块登记；
- 巡检对象不包含办公区设备与仓库；
- 机房与机柜暂不参与资产范围（组织数据范围）过滤，统一按巡检权限控制。
