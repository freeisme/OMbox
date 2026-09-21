# 前端结构与构建说明

## 结论速览

| 项目 | 现状 |
| --- | --- |
| 技术栈 | Vue 3 + TypeScript + Vite + Element Plus + Vue Router |
| 源码 | `frontend/`（`src/` 下按 api / router / layouts / views / components / composables / styles 分层） |
| 构建产物 | `web/app/`，由 `server.py` 在 `/` 与前端路由上回落该入口 |
| 路由 | 真实路径（History API）：`/dashboard`、`/computers`、`/settings`…；全部按需懒加载 |
| 组件引入 | Element Plus 按需引入（`unplugin-vue-components` + `unplugin-auto-import`） |
| 旧前端 | 已整体删除：`web/app.js`、`web/styles.css`、`web/index.html` 与 `/legacy/` 路由都不再存在 |
| 版本号 | 仓库根目录 `VERSION`，后端 `GET /api/meta` 暴露，前端构建时注入 |

## 开发与构建

```bash
cd frontend
pnpm install --frozen-lockfile   # 首次或依赖变更后
pnpm dev                         # 本地开发服务器（Vite，需自行把 /api 代理到后端）
pnpm build                       # vue-tsc 类型检查 + 生产构建，产物写入 ../web/app
pnpm typecheck                   # 只做类型检查
```

后端仍然是一个进程：`python server.py` 同时提供 `/api/*` 与前端静态资源。
本地调试时先 `pnpm build`，再启动 `server.py`，访问 `http://127.0.0.1:8000/` 即可。
仓库里只有 SPA 一套入口，没有构建产物时 `/` 会返回 404。

`Dockerfile` 使用多阶段构建（`AS frontend` 阶段跑 `pnpm install --frozen-lockfile` 与
`pnpm build`），运行镜像里已经包含 `web/app/`，部署时无需在服务器上装 Node。

### 按需引入的注意点

- 模板里的 `el-*` 组件由 `unplugin-vue-components` 解析，组件样式随组件一起打包；
- 命令式 API（`ElMessage` / `ElMessageBox`）在各页面显式 `import`，样式在 `main.ts`
  里统一登记 `message` 与 `message-box` 两份；
- 两个插件都不生成 `dts`：Element Plus 把表格/树的作用域插槽标成 `DefaultRow`，
  自动生成的类型声明会把现有 90 多处模板调用判成类型错误；
- **样式顺序敏感**：Element Plus 的组件样式按需加载，排在 `tokens.css` / `app.css` 之后，
  同权重的手写规则会被组件样式盖掉。两条铁律：
  1. 能改组件变量的就改变量（侧栏用 `--el-menu-bg-color` / `--el-menu-text-color` 等，
     表格行高用 `.el-table.el-table--small` 这类两级类名）；
  2. 组件不提供变量的（如菜单选中项底色）再写覆盖规则，并且一定要提高权重，
     例如 `.oa-rail .oa-nav .el-menu-item.is-active`、`.oa-filter-bar .oa-filter-form .el-form-item__label`。
  历史上踩过两次：表格 32px 行高失效、侧栏菜单变白底灰字，`tests/test_regressions.py` 都有对应断言。

首屏 JS（入口 + `modulepreload` 的公共块）约 268 KB、gzip 约 114 KB；全量引入时是 1.3 MB。

## 路由与权限

路由由 `frontend/src/navigation.ts` 的 `NAV_ITEMS` 驱动：侧边栏菜单、路径映射、页面标题和
权限规则都来自这一处。`router/index.ts` 的 `VIEW_LOADERS` 把页面 key 映射到懒加载组件：

```ts
const VIEW_LOADERS: Record<string, () => Promise<unknown>> = {
  computers: () => import("../views/ComputersView.vue"),
  // ...
};
```

新增页面：在 `frontend/src/views/` 写组件 → 在 `NAV_ITEMS` 加一条 → 在 `VIEW_LOADERS` 登记。

权限判定见 `frontend/src/session.ts`：

- 超级管理员直接放行；
- 其他账号按 `/api/auth/permissions` 返回的 `{resource, action}` 判断，`view` 权限决定菜单可见性；
- 无权限访问某页时，路由守卫会跳到第一个有权限的页面，避免出现空白页。

## 设计令牌与页面骨架

布局、间距、字号、色彩与组件规范见
[前端页面整体设计计划](frontend-design-plan.md)。落地约定：

- 令牌在 `frontend/src/styles/tokens.css`，公共类与断点在 `frontend/src/styles/app.css`；
- 共享组件在 `frontend/src/components/ui/`（`PageHeader`、`FilterBar`、`ToolbarActions`、
  `DataPanel`、`StatusTag`、`EmptyHint`、`MetricCard`、`FormDialog`、`DetailDrawer`）；
- 列表页固定骨架：页头 → 筛选 → 批量操作 → 数据面板 → 分页；
- 详情用右侧抽屉，编辑表单用弹窗，危险操作统一走 `composables/useConfirm.ts`；
- 断点助手在 `composables/useBreakpoint.ts`：XL ≥1200 / L 992–1199 / M 768–991 / S <768，
  弹窗与抽屉在小屏自动改成近满宽。

状态与设备类型标签统一放在 `frontend/src/labels.ts`，页面上不要再各写一份。

## 数据接口

### 工作台

工作台首屏只调用 `GET /api/workbench/summary`（实现见 `server.py` 的 `build_workbench_summary`）：

- 复用 `/api/state` 的权限与数据范围过滤，保证与列表页口径一致；
- 只返回计数与少量最近记录（最近登记 5 条、最近入库 8 条、数据质量 Top 5、通知最近 5 条）；
- 按模块判权限后再取数，无权限模块不出现；单模块失败按空值降级，不影响其它模块；
- 结果按账号缓存 15 秒（`WORKBENCH_CACHE_TTL_SECONDS`），`?refresh=1` 强制刷新。

### 状态快照裁剪与服务端分页

- `GET /api/state?include=orgs,employees,warehouses,inventoryModels`：按需裁剪状态快照的
  返回字段，`stateRevision` 始终保留。整包约 549 KB，办公终端页只需要约 91 KB，
  IT 物资页只需要约 45 KB。
- `GET /api/list/computers?page&pageSize&keyword&status&orgId`：办公终端列表的服务端分页，
  返回 `{items, total, page, pageSize}`。关键字命中字段（设备名、品牌、型号、固资编码、
  SN/ST、位置、组织名、使用人）与前端原有过滤逻辑一一对应，组织筛选按子树展开，
  权限与数据范围复用 `filter_state_payload`。`pageSize=0` 返回全部，供「全选当前结果」与导出使用。
  另有两个给使用人员页用的参数：`userId=<人员>`（设备弹窗取该人名下终端）、
  `unassigned=1`（取可分配终端）、`fields=names`（只回 id / userId / deviceName / brand / model，
  约 26 KB，完整行是 144 KB）。
- 使用人员的**人员清单**仍要全量（组织树人数、离职转交候选人），保留「裁剪后的快照 + 前端过滤」；
  但终端不再整包下载：「名下设备」一列走 `fields=names`，设备弹窗打开时按人取数。
  IT 物资是目录树，同样保留裁剪后的快照。

### 会话过期

`api/client.ts` 里非 `/api/auth/*` 的 401 会触发 `setUnauthorizedHandler` 注册的回调；
`main.ts` 清空会话状态并跳转 `/login?redirect=<原地址>`，避免停在
「看起来已登录，但所有操作都失败」的状态。

## 主题色

设置页「外观主题」提供预设色板、自定义取色器与恢复默认，实现见 `frontend/src/theme.ts`：

- 写入 `--el-color-primary` 以及 Element Plus 派生的 `--el-color-primary-light-3/5/7/8/9`
  与 `--el-color-primary-dark-2`（按 sRGB 插值计算），Element Plus 组件自动跟随；
- 侧栏选中项与品牌块使用 `var(--el-color-primary)`，因此同步生效；
- 选择结果写入 `localStorage` 的 `oa-theme-color`，启动时由 `main.ts` 在挂载前应用，
  避免首屏闪色。

主题色按浏览器保存，不写入服务端配置；深浅色模式（`oa-theme`）与主题色相互独立。

## 页面清单

19 个导航页面 + 登录页全部是 Vue 组件：

| 页面 | 说明 |
| --- | --- |
| 工作台 `/dashboard` | 待办事项、快捷入口、核心统计、通知公告、处理进度、最近登记资产、我的设备、最近入库物资、数据质量待办 |
| 办公终端 `/computers` | 服务端分页；关键字/状态/组织树筛选、批量选择与 CSV 导出、新增/编辑、报废 |
| 使用人员 `/employees` | 组织树 + 人员清单、关键字/物资/状态/组织筛选、批量导出、新增/编辑、办理离职（逐项处置）、设备清单弹窗 |
| 离职人员 `/left-employees` | 关键字检索、分页、详情抽屉与离职设备快照 |
| IT物资 `/inventory` | 仓库切换、类型/品牌筛选、库存树、类型/品牌/型号维护、入库/调拨/仓库维护、采购入库记录、CSV 导出 |
| 物资流转记录 `/flow-control` | 多条件筛选、库存影响、备注修正、CSV 导出 |
| 报废记录 `/scrap-records` | 关键字/类型筛选、详情弹窗、CSV 导出 |
| 工单 `/tickets` | 筛选、SLA 展示、处理记录、状态流转、新建工单 |
| 服务管理 `/service-management` | 变更/问题/知识库/SLA/审批/通知标签页，含新建与审批决策 |
| 同步与质量 `/governance` | 同步批次应用、数据质量问题解决/忽略、运行质量检查 |
| 机房巡检 `/inspection` | 任务/模板/机房机柜标签页，任务详情逐项检查与提交 |
| 基础字典 `/dictionary` | 组织树新增/编辑、设备类型维护、引用人数统计 |
| 操作日志 `/audit` | 筛选、分页、详情抽屉、CSV 导出 |
| 设置 `/settings` | 外观主题、系统信息、系统参数、安全与密码、数据库备份、账号管理、角色与权限、系统更新 |
| 机房设备 / 机柜视图 / 设备面板 / 网络拓扑 | 见 [机房设备管理](datacenter-management.md) 与 [设备面板与拓扑](device-panel-and-topology.md) |

## 目录树表格（IT物资）

「类型 → 品牌 → 型号」三层用 `el-table` 的树形数据渲染（`children` + `row-key`），
踩过三个坑，改页面前先看这几条：

1. **`row-key` 必须带层级前缀**。类型 / 品牌 / 型号的主键各自独立编号，会跨层撞号
   （类型 22 与品牌 22 同号），Element Plus 按 `row-key` 记账，撞号会让行挂到错误层级、
   展开状态串行。`buildInventoryTree` 给每个节点加 `key = "type:1" / "brand:1" / "model:1"`，
   表格用 `row-key="key"`。
2. **第一列的插槽内容必须是行内级元素**。`el-table` 的缩进是 `.cell` 里的
   `el-table__indent` + `el-table__placeholder` 两个行内元素，插槽里放块级 `<div>`
   会另起一行，缩进完全看不出效果（表现为「所有层级都不缩进」）。用
   `display: inline-flex` 承接。
3. **排序在取数层做一次**。`loadInventoryData` 里的 `sortInventoryRefs` 统一排序：
   类型按名称（拼音），品牌与型号先按 `sortOrder` 再按名称，数字按数值比较。
   `buildInventoryTree` 与各个下拉框共用同一份已排序数组，避免两处口径不一致。

缩进量用 `el-table` 的 `:indent="32"`（默认 16），实测每级距行左边 32 / 64 / 96px。
默认展开类型与品牌，筛选时用 `effectiveExpandKeys` 强制展开命中的分支，避免「搜到了
型号但折在品牌下面」。行样式用 `:row-class-name` 加 `oa-inv-row--<level>`，类型行给浅色底。

## 旧前端下线记录

页面全部迁到 Vue 后，旧前端（无构建步骤的 `web/app.js` + `web/styles.css` + `web/index.html`）
整体删除，配套清理项：

- `server.py`：去掉 `LEGACY_PREFIX`、`/legacy/` 前缀重写与 `_legacy_request` 标记；
  `X-Frame-Options` 恒为 `DENY`，Content-Security-Policy 不再有 `frame-ancestors 'self'` 分支；
  `send_spa_index` 不再回落到旧入口；
- 前端：删除 `LegacyPage.vue`、`LegacyFrame.vue`、`legacyBridge.ts`，`theme.ts` 去掉
  `applyLegacyAccent`；
- 顶栏「消息」按钮改为跳转 `/service-management`（未读计数走 `/api/notifications`），
  「重新加载」改为整页刷新；
- `web/` 目录只保留 `app/`（构建产物，不入库）与 `assets/device-images/`（面板图上传目录）。

结构回归 `tests/test_regressions.py::FrontendLegacyRemovalTests` 会守住这几点：
三个旧文件不存在、`server.py` 里没有 legacy 字样与 `SAMEORIGIN`、Vue 源码里不再出现
`legacyBridge` / `LegacyFrame` / `LegacyPage` / `oaLegacy` / `applyLegacyAccent`。

## 已知待办

- 使用人员的**人员清单**、IT 物资的**目录树**仍是「裁剪后的快照 + 前端过滤」。要做成服务端分页，
  需要先把组织树人数与离职转交候选人的数据来源拆成独立接口（终端侧已经拆完了）。
- 小屏（<768px）筛选区按单列堆叠，尚未做「更多筛选」折叠。
