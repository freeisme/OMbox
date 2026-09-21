# OMbox · 运维（O&M）盒子

**OMbox**（Operations & Maintenance Box）是一套可以单机部署的企业 IT 运维管理盒子，
把「资产台账 → 物资仓库 → 人员与离职 → 机房设备与巡检 → 工单与服务」串成一条完整链路，
并自带细粒度中文权限、数据范围、审计日志与数据库备份。

一条 `docker compose up -d --build` 就能起完整环境；也可以只跑 `python server.py` 单进程，
不需要额外安装 Python 依赖。

## 能力

| 模块 | 说明 |
| --- | --- |
| 工作台 | 待办事项、处理进度、核心统计、快捷入口、通知公告，按角色差异化显示且可自定义 |
| 办公终端 | 设备台账、自定义 / 从库存两种登记方式、分配与归还、报废登记、流转时间线 |
| 使用人员 | 组织树 + 人员清单、一键搜索名下设备、**公用人员**（设备挂靠用虚拟使用人） |
| 离职回收 | 逐项处理名下资产：**回收到指定仓库**、转交他人、异常待处理，全部留痕并可导出 |
| IT 物资 | 类型 → 品牌 → 型号三层目录、**多仓库**独立记账、入库 / 领用 / 归还 / 调拨 / 调整 |
| 物资流转 | 全量流转记录、库存影响、**追加式**备注更正（原始记录与更正原因都保留） |
| 报废记录 | 报废登记、原因字典、库存影响与操作人追溯 |
| 机房管理 | 机房与机柜、机柜视图（拖拽换 U 位）、设备面板与端口链路、网络拓扑、机房巡检 |
| 服务管理 | 工单、变更、问题、知识库、SLA 策略、审批、通知，支持表单设计器与工作流 |
| 同步与质量 | 同步暂存批次、数据质量审计与问题处置 |
| 权限与审计 | 中文权限项、数据范围（全部 / 组织 / 本人）、操作日志、数据库备份与恢复 |
| 版本更新 | 内置更新通道，从 GitHub（或自定义地址）检查并更新到指定版本 |

## 技术形态

| 项 | 说明 |
| --- | --- |
| 后端 | Python 标准库（`http.server`），单进程同时提供 `/api/*` 与前端静态资源，无第三方依赖 |
| 前端 | Vue 3 + TypeScript + Vite + Element Plus；按需引入 + 路由懒加载，首屏 JS 约 268 KB |
| 数据库 | MySQL 8.0+，结构变更全部走 `database/migrations/` 增量迁移 |
| 部署 | Docker Compose（推荐）、systemd、Ubuntu 原生脚本、Windows PowerShell 脚本 |
| 界面 | 中文，深浅色主题 + 可换主题色，四档响应式断点，列表统一 32px 紧凑行高 |

## 快速开始

### Docker Compose（推荐）

```bash
git clone https://github.com/freeisme/OMbox.git
cd OMbox
cp .env.example .env
# 修改 .env：DB_PASSWORD、MYSQL_ROOT_PASSWORD 必须换成强口令；
# 生产环境保持 AUTH_COOKIE_SECURE=true 并通过 HTTPS 访问。
docker compose up -d --build
```

Compose 会在数据库健康后运行一次迁移器，迁移成功后应用才启动。
首次访问会进入初始化页面，创建第一个管理员账号。

### 本地运行

```bash
cd frontend && pnpm install --frozen-lockfile && pnpm build   # 生成 web/app
cd ..
python server.py          # 读取 DB_* / SERVER_* 环境变量，默认 http://127.0.0.1:8000
```

### Windows

```powershell
.\scripts\windows\deploy.ps1 -User root -Database office_asset_mgmt
```

## 空库即全新系统

仓库里只有代码、结构 SQL 与通用字典，**不含任何业务数据**。按部署流程建出来的库只有：

- 权限字典（模块、权限项、角色）与系统设置；
- 参考数据：组织根节点、默认仓库「仓库1」、IT 物资类型、报废原因、服务表单模板、
  SLA 策略、巡检模板等；
- 迁移登记表。

人员、办公终端、离职档案、登录账号、审计日志、库存型号、机房设备、工单等业务表**全部 0 条**。
首次登录时按引导创建管理员，再按需建立组织与人员。

## 版本与更新

- 版本号唯一来源是仓库根目录的 `VERSION`，后端通过 `GET /api/meta` 暴露，前端构建时注入；
- 每个可部署版本在 `VERSION_NOTES.md` 里有同名小节（`## vX.Y.Z`），并打 SemVer 注释标签；
- 设置页「系统更新」可以直接检查并更新到指定版本，支持内置 GitHub 地址与自定义仓库地址；
- 升级前请先备份数据库（设置页或 `deploy/scripts/backup_compose_database.sh`）。

## 仓库结构

```text
.
├── server.py                    # HTTP 应用入口（API + 静态资源 + SPA 回落）
├── office_asset/                # 领域服务、仓储、权限与数据范围
├── frontend/                    # Vue 3 + TypeScript + Vite 前端源码
│   └── src/{api,views,components/ui,composables,styles}
├── web/
│   ├── app/                     # 前端构建产物（不入库，pnpm build / Docker 生成）
│   └── assets/device-images/    # 设备面板图上传目录
├── database/
│   ├── bootstrap/               # 空库初始化 SQL（仅结构与通用字典）
│   ├── migrations/              # 增量迁移，已发布文件不可修改
│   └── manual/                  # 手工维护 SQL，不参与自动部署
├── deploy/                      # Docker / Nginx / systemd / 更新服务 / 备份脚本
├── docs/                        # 开发、部署、安全与发布文档（含 Wiki 源文件）
├── tests/                       # 结构回归与接口权限回归
├── tools/                       # 迁移器、脱敏扫描等工具
├── compose.yaml                 # 应用 + MySQL 编排
├── VERSION                      # 应用版本
└── VERSION_NOTES.md             # 版本说明，供更新服务读取
```

## 文档

- [文档索引](docs/README.md)
- [开发指南](docs/development/guide.md)
- [前端结构与构建](docs/development/frontend.md) · [前端设计计划](docs/development/frontend-design-plan.md)
- [数据库与迁移](docs/development/migrations.md) · [时区迁移](docs/development/timezone-migration.md)
- [机房设备管理](docs/development/datacenter-management.md) · [设备面板与拓扑](docs/development/device-panel-and-topology.md)
- [机房巡检](docs/development/inspection-management.md) · [机柜视图](docs/development/rack-layout.md)
- [Docker 部署](docs/deployment/docker.md) · [Ubuntu 原生部署](docs/deployment/ubuntu.md) · [更新服务与手动版本更新](docs/deployment/update-service.md)
- [发布流程](docs/releases/github-release.md) · [发布前脱敏检查](docs/development/release-safety.md)
- [安全检查](docs/security/review.md) · [扫描整改记录](docs/security/tscanplus-remediation.md)
- [前端与接口说明](web/README.md) · [GitHub Wiki](https://github.com/freeisme/OMbox/wiki)

## 安全与脱敏

- 仓库**不含**业务数据、数据库备份、账号口令、访问令牌或证书；部署所需的真实取值只放在
  服务器上的 `.env` 或受保护配置文件里。
- 文档、版本说明、测试固定数据一律使用虚拟信息（张三 / 李四 / 测试部门 / IT-PC-01 等），
  不引用真实人员姓名、设备编码、组织与仓库名称。
- 每次发布前运行脱敏扫描，CI 也会执行同一条命令：

  ```bash
  python tools/scan_release_safety.py --rev HEAD
  ```

- 生产环境必须通过 HTTPS 访问并保持 `AUTH_COOKIE_SECURE=true`；
  所有权限与数据范围由服务端校验，隐藏前端菜单不作为授权手段。
- 升级前先备份，迁移后执行校验与权限回归测试。

## 许可

内部使用许可，详见 [LICENSE](LICENSE)。
