# OMbox 集团多公司（Multi-Company Group）改造方案

> 状态：方案已定稿（分歧点已确认）
> 目标版本：v4.0.0
> 基线：v3.0.41（分支 ombox-main）

## 0. 已确认决策（问答结论）

| # | 问题 | 结论 |
| --- | --- | --- |
| Q1 | 公司层级 | **平级**：所有公司并列挂在集团下，不引入 parent_company_id |
| Q2 | IT 物资目录归属 | **目录全局共享**（类型/品牌/型号全局），仓库与库存按公司分 |
| Q3 | 调拨审批 | **不需要审批**，直接生效并写审计/调拨记录 |
| Q4 | 分公司转移范围 | **全量**：组织节点 + 员工 + 办公终端 + IT 物资/仓库 + 机房设备/巡检对象 |
| Q4补充 | 机房设备组织信息 | **机房设备需新增「组织」信息栏**（当前界面缺组织字段，需补 org 输入/展示） |
| Q5 | 员工多职位 | **设主职位**；employee 旧三列保留为主职位冗余快照并同步 |
| Q6 | 数据范围/角色 | **新增「本公司」范围 + 公司管理员角色**；超管看集团，公司管理员看本公司 |
| Q7 | 存量升级命名 | **升级后首次登录强制进入「集团/公司初始化向导」** 填写后再用 |
| Q8 | 服务管理隔离 | **本次不隔离**（工单/服务/知识库/审批/同步质量仍全局） |

## 1. 背景与目标

把 OMbox 从「单公司」升级为「集团多公司」：

- 整个系统 = 一个**集团（Group）**；集团下多个**公司（Company）**平级、独立管理；
- 首次安装初始化创建集团+初始公司；系统管理员可新增公司并导入/转移组织架构；
- 组织架构增加**树状视图**（整个集团 / 单个公司两视角）；
- 员工支持**多职位**（可跨组织、跨公司，主职位唯一）；
- 办公终端、IT 物资仓库、机房设备按公司隔离，跨公司走**调拨**（免审批、留审计）；
- 机房管理/巡检管理可**开关**，新装初始化时选择；
- 平滑对接旧版本，升级后首次登录走「集团/公司初始化向导」。

## 2. 名词定义

| 词 | 含义 |
| --- | --- |
| 集团（Group） | 系统唯一顶层实体，每部署一个 |
| 公司（Company） | 集团下平级独立管理单元 |
| 组织（org_unit） | 公司内部门/团队节点 |
| 主职位 | 员工默认归属（资产/数据范围落点），每人唯一 |
| 调拨 | 变更资产/物资/设备的归属公司/组织（免审批，留审计） |

## 3. 数据模型

### 3.1 新增表

```text
company
  company_id PK, company_code UNIQUE, company_name,
  sort_order, is_active, created_at, updated_at

employee_position   -- 员工任职（多职位）
  position_id PK, employee_id FK→employee(CASCADE),
  company_id FK→company, org_unit_id FK→org_unit(SET NULL),
  department, position_name,
  is_primary TINYINT(1), sort_order, is_active, created_at, updated_at,
  UNIQUE(employee_id, company_id, org_unit_id, department, position_name)

asset_transfer_record  -- 跨公司调拨记录（统一审计）
  transfer_id PK, transfer_no UNIQUE,
  asset_kind(computer/inventory/datacenter_device),
  asset_id, source_company_id FK, target_company_id FK,
  source_org_unit_id, target_org_unit_id, quantity DEFAULT 1,
  status(completed), note, created_by, created_at, updated_at
```

### 3.2 修改表（+ company_id，回填后 NOT NULL）

| 表 | 变更 |
| --- | --- |
| `org_unit` | + company_id |
| `computer_asset` | + company_id |
| `inventory_warehouse` | + company_id |
| `asset_site` | + company_id |
| `asset_rack` | + company_id |
| `datacenter_device` | + company_id；**补 org 信息栏**（org_unit_id 已存在，补 UI/接口录入与展示） |
| `site_device` | + company_id |
| `employee` | 保留 org_unit_id/department/position_name 为主职位冗余快照 |

> 注：Q2 决定目录全局共享，故 `non_asset_type`/`it_inventory_brand`/`it_inventory_model` **不加** company_id。

### 3.3 新增系统设置键

`group_name`、`module_datacenter_enabled`、`module_inspection_enabled`。

## 4. 模块改造

### 4.1 初始化
- 全新安装：/api/auth/bootstrap 多步向导（集团名 + 初始公司名 + 是否开启机房/巡检 + 管理员）。
- 存量升级：迁移建默认占位公司；**首次登录强制进入集团/公司初始化向导**补全名称后才可进入系统（Q7）。

### 4.2 组织架构
- 树视图两视角：整个集团（集团→公司→组织树）/ 单个公司。
- 新增公司：可勾选源公司某子树**整体转移**（组织+员工+终端+物资/仓库+机房设备，Q4）。
- 组织导入归属当前公司。

### 4.3 员工多职位
- employee_position 为任职来源；员工编辑改为任职列表，主职位唯一（Q5）。
- 旧三列=主职位冗余快照，写入同步；离职/资产/数据范围以主职位为准。

### 4.4 办公终端
- 按 company_id 过滤；跨公司=调拨（改 company_id+org_unit_id，写调拨记录+流转历史+审计）。

### 4.5 IT 物资
- 仓库按公司、库存按仓库；目录全局共享（Q2）。
- 跨公司=跨仓库调拨（复用 inventory_transfer_log + 写 asset_transfer_record）。

### 4.6 机房设备/巡检
- 按 company_id 隔离；**机房设备补组织信息栏**（录入/展示 org）。
- 跨公司=调拨（下架→改归属→重新上架）。
- 开关 module_datacenter_enabled / module_inspection_enabled：前端菜单隐藏 + 后端接口拒绝；数据保留。

### 4.7 权限
- 新增数据范围 `company` + 角色「公司管理员」；超管=集团，公司管理员=本公司（Q6）。
- 服务端校验公司边界，前端仅做体验优化。

## 5. 平滑升级与迁移

### 5.1 增量迁移（幂等、只增不删）
新增 `database/migrations/2026xxxx_001_multi_company_group.sql`：建 3 张表、各表 + company_id、建占位初始公司并回填、加系统设置键、加权限模块/权限项并赋管理员。

### 5.2 存量回填（逐表，无遗漏）
org_unit → 初始公司；employee → 每条 1 主职位；computer_asset / inventory_warehouse / asset_site / asset_rack / datacenter_device / site_device 经 org_unit_id 回填 company_id；孤儿记录归初始公司并审计。

### 5.3 升级指引（逐项打勾，无遗漏）
1 备份库→2 执行迁移→3 migration_runner --verify→4 核对 company/org_unit/employee_position→5 核对各表 company_id 非空→6 核对三设置键→7 重启 + /api/health（表数门槛提升）→8 pnpm build 刷新→9 首次登录向导命名→10 组织树/新增公司/调拨/开关/多职位全链路→11 权限回归→12 更新 VERSION_NOTES/README/Wiki/交接文档。

## 6. 接口与前端改动
后端：server.py（bootstrap/开关/公司范围/向导）、scope.py、permissions.py、asset_service.py、inspection.py、datacenter_devices.py、rack_layout.py、operations.py、api_router.py。
前端：views/（组织树、员工多职位、调拨、设置开关、集团/公司向导）、navigation.ts、api/。

## 7. 测试计划（本地深度测试）
迁移幂等与回填（空库/带数据/孤儿）、多公司隔离、三类调拨闭环、多职位、开关、初始化向导、权限回归、全量结构/接口回归。

## 8. 发布与回滚
v4.0.0；VERSION + VERSION_NOTES.md 增 ## v4.0.0；发布前 scan_release_safety；本地测试通过后**向你申请确认再推 GitHub**；回滚=代码回退 v3.0.41 + 备份恢复。
