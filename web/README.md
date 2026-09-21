# 前端与接口

前端是 Vue 3 + TypeScript + Vite + Element Plus 的单页应用，源码在 `frontend/`，
构建产物输出到 `web/app/`，由根目录 `server.py` 提供静态文件、SPA 回落和 API。

旧版无构建前端（原 `web/app.js`、`web/styles.css`、`web/index.html` 与 `/legacy/` 路由）
已在页面全部迁移到 Vue 后整体删除，仓库里只保留一套实现。

## 目录

| 路径 | 说明 |
| --- | --- |
| `frontend/src/views/` | 页面组件，与 `navigation.ts` 中的导航项一一对应 |
| `frontend/src/components/ui/` | 共享骨架组件（页头、筛选栏、数据面板、状态标签等） |
| `frontend/src/styles/tokens.css` | 设计令牌：间距、字号、圆角、表格行高、面层色 |
| `frontend/src/api/` | 接口封装，视图不直接拼 URL |
| `web/app/` | `pnpm build` 产物（不入库，由 CI/Docker 生成） |
| `web/assets/device-images/` | 设备面板图上传目录（运行时写入，保留） |

## 构建

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm build        # vue-tsc 类型检查 + vite 构建到 ../web/app
```

构建在 Dockerfile 的 `AS frontend` 阶段完成，运行阶段只拷贝 `web/app`。

## 前端约束

- 业务数据以 MySQL 为唯一来源；浏览器本地存储只保存主题与界面偏好。
- 页面统一走「页头 → 筛选 → 批量操作 → 数据面板 → 分页」骨架，间距/字号/颜色只允许取
  `tokens.css` 里的令牌，不写裸 px 与十六进制色值。
- 组件按需引入：Element Plus 由 `unplugin-vue-components` 解析，命令式 API
  （`ElMessage` / `ElMessageBox`）显式 import，样式在 `main.ts` 登记。
- 路由全部懒加载，首屏只加载外壳与登录页。
- 会话过期（接口返回 401）时统一清会话并跳回登录页，不允许停在"看起来已登录"的页面。
- 导航会根据当前用户的模块权限隐藏不可用入口，但所有写入和读取范围都由 API 再次校验。

## 常用接口

| 接口 | 说明 |
| --- | --- |
| `GET /api/health` | 服务与数据库健康检查。 |
| `GET /api/state` | 兼容性只读状态快照。 |
| `PUT /api/state` | 已退役，返回 `405 STATE_WRITE_RETIRED`。 |
| `POST /api/inventory/receipts` | IT 物资入库命令。 |
| `POST /api/inventory/allocations` | IT 物资领用命令。 |
| `POST /api/inventory/allocations/{id}/return` | IT 物资归还命令。 |
| `POST /api/computers/{id}/assignments` | 办公终端分配命令。 |
| `POST /api/computers/{id}/assignments/return` | 办公终端归还命令。 |
| `GET /api/computers/{id}/movement-history` | 当前用户数据范围内的设备流转时间线。 |
| `GET/POST /api/tickets` | 工单查询与创建。 |
| `GET/POST /api/service-forms` | 服务表单设计和发布。 |
| `GET/POST /api/sync-runs` | 同步暂存任务和结果。 |
| `POST /api/data-quality/run` | 数据质量审计。 |
