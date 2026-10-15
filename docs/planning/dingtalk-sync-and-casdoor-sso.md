# 规划：钉钉组织架构同步与 Casdoor + 钉钉扫码登录

> 状态：**方案留档，尚未实施**（2026-10-15 整理）。
> 本文只写方案与约束，不含任何真实 AppKey / Secret / 内网地址。

## 0. 共同前提

- 本项目**零第三方依赖**：所有出站 HTTP 用标准库 `urllib.request`（现有更新服务就是这么做的），
  新增外呼不能引入 `requests` / 钉钉 SDK。
- 现有可复用的链路：`sync_source` / `sync_run` / `sync_staging_record` / `sync_entity_mapping`
  以及「同步与质量」页面的「暂存 → 人工审核 → 应用」，见 `office_asset/operations.py`。
- 权限与账号完全由本系统决定：`user_account`（`role_code` + `employee_id`）与
  `auth_role` / `auth_role_permission` / `auth_user_permission`；外部系统只提供身份与组织事实。

## 1. 方案 A：钉钉组织架构同步

### 1.1 目标与边界

钉钉通讯录（部门 + 成员）单向同步进 `org_unit` / `employee`；**不回写钉钉**，
不同步资产，不建登录账号（登录见方案 B）。

### 1.2 流程

```
定时（默认每天 06:30）/ 手动触发
  → 取 access_token（缓存 2 小时，提前 5 分钟刷新）
  → 拉部门（/topapi/v2/department/listsub、/topapi/v2/department/get）
  → 按部门拉成员（/topapi/v2/user/list，分页 size=100）
  → 规范化成 stage 记录：{entityType: organization|employee, externalId, action: upsert|disable, data}
  → SyncService.stage() → sync_run(status=validated)
  → 管理员在「同步与质量」页看统计（新增 / 更新 / 停用 / 错误）后点「应用」
  → apply 写 org_unit / employee，并写 sync_entity_mapping + 审计
```

### 1.3 增量策略（重要取舍）

钉钉的通讯录变更事件回调要对报文做 AES-256-CBC 解密，而标准库没有 AES。
**阶段 1、2 采用「全量拉取 + 本地 diff」**（几百人规模，一天 1–2 次足够）；
将来要准实时，再评估独立回调小程序或破例引入加密依赖。

### 1.4 字段映射

| 钉钉 | 本系统 | 规则 |
| --- | --- | --- |
| `dept_id` | `sync_entity_mapping.external_id` | 不改写 `org_code`；新建组织 `org_code = DT-<dept_id>` |
| `name` | `org_unit.org_name` | 钉钉非空才覆盖 |
| `parent_id` | `org_unit.parent_org_unit_id` | 按映射解析；父级缺失该条标 invalid |
| `order` | `org_unit.sort_order` | 直接覆盖 |
| `userid` | `sync_entity_mapping.external_id` | 人员优先按工号匹配 |
| `job_number` | `employee.employee_no` | 有工号用工号，否则 `DT-<userid>`（要求钉钉维护工号） |
| `dept_id_list[0]` | `employee.org_unit_id` | 取主部门 |
| `title` / `mobile` / `email` | 同名业务字段 | 覆盖，手机号可开关 |
| 离职 / 停用 | `action=disable` → `employment_status='inactive'` | **不直接置 left**，离职仍走本系统离职办理 |

### 1.5 冲突与优先级

- `sync_source.priority_rank`：manual 10 > hr 20 > **dingtalk 30（新增）** > excel 50；
- 已存在工号只更新组织 / 岗位 / 联系方式，不覆盖资产关系与使用状态；
- 手工标记 `left` 的人员不因钉钉还在而被重新激活；
- 钉钉里消失的部门先 `is_active=0` 停用，不删除。

### 1.6 配置项

```
DINGTALK_SYNC_ENABLED=false
DINGTALK_APP_KEY=
DINGTALK_APP_SECRET=
DINGTALK_ROOT_DEPT_ID=1
DINGTALK_SYNC_SCHEDULE=06:30
DINGTALK_SYNC_MOBILE=true
HTTPS_PROXY=            # 内网无直连外网时使用
```

生产服务器需要能出网访问 `oapi.dingtalk.com:443`，或在钉钉后台把出口 IP 加白名单。

### 1.7 阶段与待确认

| 阶段 | 内容 |
| --- | --- |
| 1 | 拉全量 → 只生成暂存批次（预览、不应用），人工核对映射 |
| 2 | 「同步钉钉」按钮 + 定时线程 + 差异统计 |
| 3 | 冲突策略可配置、事件订阅（如需准实时） |

待确认：工号是否齐全、谁是主数据（钉钉覆盖还是人工优先）、离职是停用还是走离职流程、
是否同步手机号 / 邮箱、多公司与兼职部门怎么取。

## 2. 方案 B：Casdoor + 钉钉扫码登录

### 2.1 为什么经 Casdoor

Casdoor 是标准 OIDC 身份提供方且内置钉钉 provider；本系统只对接一次 OIDC，
以后加企业微信 / 微信 / 邮箱登录都不用改本系统代码。代价是多一个容器，
且 **Casdoor 服务器必须能出网访问钉钉**（扫码二维码由 Casdoor 服务端换取）。

### 2.2 登录流程（授权码 + PKCE）

```
1. 登录页「钉钉扫码登录」→ GET /api/auth/sso/start?redirect=/dashboard
   生成一次性 state + PKCE code_verifier，302 到 Casdoor /login/oauth/authorize
2. Casdoor（钉钉扫码）回调 → GET /api/auth/sso/callback?code=&state=
   - 校验 state（一次性、10 分钟过期）
   - 服务端用 client_secret 换 token；校验 id_token 的 iss/aud/exp/nonce
     （可选：用 Casdoor 证书本地验 RS256，标准库可实现）
   - 取 sub / preferred_username / name / email
3. 绑定本地账号
   - user_account.sso_subject 命中 → 直接用
   - 未命中 → 按工号（其次邮箱前缀）匹配 employee 后建号 / 绑定；
     找不到就拒绝登录（默认不自动建人，防通讯录外的人进入）
4. 建立会话：复用 create_auth_session() + cookie_headers()（HttpOnly + SameSite=Lax + CSRF）
5. 退出：本地清 cookie 并撤销 auth_session（不做全局单点登出）
```

### 2.3 数据结构改动

```sql
ALTER TABLE user_account
  ADD COLUMN sso_subject VARCHAR(128) NULL,
  ADD COLUMN sso_provider VARCHAR(32) NOT NULL DEFAULT '',
  ADD UNIQUE KEY uq_user_account_sso_subject (sso_subject);
```

密码列保留：SSO 账号可以留空并禁止密码登录，也允许两种登录方式并存。

### 2.4 安全要点

- `state` 一次性 + PKCE(S256) + `nonce`，回调地址精确匹配，只走 HTTPS；
- `client_secret` 只放服务器环境变量；自签证书按 `UPDATE_SERVICE_CA_FILE` 的思路显式配 CA；
- 自动绑定只在工号 / 邮箱精确匹配时进行，绑定写审计；失败复用 `enforce_login_rate_limit` 限流；
- 权限不做同步：Casdoor 只回答"你是谁"，角色与数据范围仍由本系统 `role_code` 决定。

### 2.5 部署要点

- Casdoor 独立容器（内置库或复用 MySQL）+ nginx + 证书；用户浏览器要能访问它（内网地址即可）；
- Casdoor 应用回调填 `https://<本系统>/api/auth/sso/callback`；
- 钉钉开放平台建应用拿 AppKey/AppSecret，在 Casdoor 里配 DingTalk provider；
- 需要企业管理员审批（通讯录权限用于方案 A，扫码登录是另一个应用能力）。

### 2.6 待确认

Casdoor 部署位置与域名、是否允许自动建号、绑定键（工号 / 邮箱 / 手机号）、
是否按部门映射默认角色、密码登录是否保留作兜底、后续是否接企业微信 / 微信。
