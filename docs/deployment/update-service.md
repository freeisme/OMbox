# 更新服务与手动版本更新

应用内「设置 → 版本更新」通过宿主机上的一个独立小服务工作：它按配置的 Git 仓库地址
读取已发布的 SemVer 标签，把管理员选定的版本排进部署队列，再由部署脚本拉取、构建并重启
应用容器。

```text
浏览器（设置 → 版本更新）
        |
        +-- 应用容器 --(HTTPS + 控制令牌)--> 宿主机更新服务（只监听本机/管理网段）
                                                  |
                                                  +-- 读取 Git 仓库的标签与版本说明
                                                  +-- 排队执行部署脚本（拉取 → 构建 → 迁移 → 重启）
                                                  +-- 失败自动回滚到上一个提交
```

要点：

- **推送不会自动部署**。收到 push 只会记录一条签名事件并返回 `204`，部署必须由管理员在
  页面上选择版本后手动触发。
- Git 仓库可以是 GitHub，也可以是运维单独维护的内网 Git 备份库；本项目不负责搭建那个
  Git 服务，只按地址读取。仓库地址、账号、口令、令牌都不写进本仓库。
- 更新控制服务与部署脚本、配置文件都由宿主机管理，容器里只有运行时需要的 CA 文件。

## 1. 服务器准备

Ubuntu 服务器上安装 Docker Compose v2、Git、Python 3 与 curl：

```bash
sudo apt update
sudo apt install -y ca-certificates curl git python3
```

按 Docker 官方文档安装 Docker Engine 与 Compose 插件，然后确认：

```bash
docker --version
docker compose version
```

创建部署账号并授予 Docker 权限：

```bash
sudo useradd --create-home --shell /bin/bash officeasset-deploy || true
sudo usermod -aG docker officeasset-deploy
sudo mkdir -p /opt/office-asset-mgmt /etc/office-asset-mgmt
sudo chown -R officeasset-deploy:officeasset-deploy /opt/office-asset-mgmt
```

改完 Docker 组后需要重新登录。

## 2. 准备部署检出

在应用服务器上把仓库克隆到部署目录（地址用你们团队实际使用的 Git 远端）：

```bash
sudo -u officeasset-deploy git clone <仓库地址> /opt/office-asset-mgmt
```

按 `.env.example` 创建 `/opt/office-asset-mgmt/.env`，设置生产数据库口令等运行时配置，
先跑一次确认应用可用：

```bash
cd /opt/office-asset-mgmt
docker compose --env-file .env up -d --build
curl --fail http://127.0.0.1:8000/api/health
```

## 3. 给部署账号读取权限

在应用服务器上生成密钥：

```bash
sudo -u officeasset-deploy mkdir -p /home/officeasset-deploy/.ssh
sudo -u officeasset-deploy ssh-keygen -t ed25519 \
  -f /home/officeasset-deploy/.ssh/id_ed25519 \
  -N "" \
  -C "officeasset-deploy"
sudo cat /home/officeasset-deploy/.ssh/id_ed25519.pub
```

把公钥加到 Git 服务上作为**只读部署密钥**（只给读权限，不给写权限），记录主机指纹并验证拉取：

```bash
sudo -u officeasset-deploy ssh-keyscan -p <SSH 端口> <Git 主机> \
  >> /home/officeasset-deploy/.ssh/known_hosts
sudo chmod 700 /home/officeasset-deploy/.ssh
sudo chmod 600 /home/officeasset-deploy/.ssh/id_ed25519
sudo chmod 644 /home/officeasset-deploy/.ssh/known_hosts
sudo -u officeasset-deploy git -C /opt/office-asset-mgmt fetch origin main
```

确认部署目录的 `origin` 指向同一个主机与端口。

## 4. 启用手动部署控制

先创建一个专用控制令牌（与任何 Webhook 密钥都不同）：

```bash
openssl rand -hex 32
```

准备一张证书，SAN 要与应用容器访问服务时使用的主机名一致（常见是
`host.docker.internal` 或内部 DNS 名）。证书与密钥放在仓库之外：

```bash
sudo install -d -m 750 -o root -g officeasset-deploy /etc/office-asset-mgmt/tls
sudo install -m 640 -o root -g officeasset-deploy update-control.crt \
  /etc/office-asset-mgmt/tls/update-control.crt
sudo install -m 640 -o root -g officeasset-deploy update-control.key \
  /etc/office-asset-mgmt/tls/update-control.key
sudo install -d -m 700 -o officeasset-deploy -g officeasset-deploy \
  /opt/office-asset-mgmt/secrets/update-service
sudo install -m 600 -o officeasset-deploy -g officeasset-deploy update-control-ca.pem \
  /opt/office-asset-mgmt/secrets/update-service/update-control-ca.pem
```

创建 `/etc/office-asset-mgmt/gitea-webhook.env`（权限 `600`）——文件名沿用服务启动时读取的
固定路径，内容如下：

```dotenv
DEPLOY_CONTROL_TOKEN=replace-with-a-different-generated-secret
WEBHOOK_BIND=0.0.0.0
WEBHOOK_PORT=9000
DEPLOY_REPO=OWNER/REPO
DEPLOY_BRANCH=main
DEPLOY_VERSION_LIST_LIMIT=30
APP_DIR=/opt/office-asset-mgmt
DEPLOY_TLS_CERT_FILE=/etc/office-asset-mgmt/tls/update-control.crt
DEPLOY_TLS_KEY_FILE=/etc/office-asset-mgmt/tls/update-control.key
DEPLOY_ALLOW_INSECURE_HTTP=false
# 可选：把内网 Git 的 HTTP 地址映射为部署账号可读的 SSH 地址（两个必须成对设置，
# 只填协议、主机与端口，不要写用户名、口令、令牌、路径或结尾斜杠）。
DEPLOY_LOCAL_GITEA_HTTP_ORIGIN=http://<Git 主机>:<HTTP 端口>
DEPLOY_LOCAL_GITEA_SSH_ORIGIN=ssh://git@<Git 主机>:<SSH 端口>
```

把同一个 `DEPLOY_CONTROL_TOKEN` 写进 `/opt/office-asset-mgmt/.env` 的
`UPDATE_CONTROL_TOKEN`，并配置：

```dotenv
UPDATE_SERVICE_URL=https://host.docker.internal:9000
UPDATE_SERVICE_CA_FILE=/run/office-asset-mgmt/update-service/update-control-ca.pem
UPDATE_SERVICE_CERTS_DIR=./secrets/update-service
UPDATE_SERVICE_ALLOW_HTTP=false
```

应用只用这个令牌读取可用版本并排队一次手动更新，令牌不会下发到浏览器；CA 文件由
`compose.yaml` 只读挂进应用容器，且必须留在 Git 之外。

安装并启动接收端：

```bash
sudo cp deploy/gitea/office-asset-gitea-webhook.service \
  /etc/systemd/system/office-asset-gitea-webhook.service
sudo chmod 600 /etc/office-asset-mgmt/gitea-webhook.env
sudo systemctl daemon-reload
sudo systemctl enable --now office-asset-gitea-webhook
sudo systemctl status office-asset-gitea-webhook
curl --fail --cacert /opt/office-asset-mgmt/secrets/update-service/update-control-ca.pem \
  --resolve host.docker.internal:9000:127.0.0.1 \
  https://host.docker.internal:9000/healthz
```

推送 Webhook 是可选能力：启用后只记录一条签名 push 并返回 `204`，不会触发部署。
Webhook 端口（默认 `9000`）必须由主机防火墙限制在 Docker 网桥与必要的管理来源，
**不要暴露到公网**；证书 SAN 必须与应用容器访问时使用的主机名一致（如
`host.docker.internal`）。

## 5. 更新来源怎么选

「设置 → 版本更新」有两个来源：

| 来源 | 行为 | 适用 |
| --- | --- | --- |
| 内置 GitHub 地址 | 更新服务直接 `git fetch https://github.com/<owner>/<repo>.git` | 服务器能访问 github.com |
| 使用部署目录 `origin` | 从部署检出的远端取版本 | 服务器走内网 Git 备份库 |

服务器不能直连 github.com 时（部分内网只放通 `api.github.com`，`github.com` 本身不通，
`git ls-remote` 会报 `Empty reply from server`），请选择 `origin`，或在
「设置 → 系统设置」把 `update_repository_url` 指向内网 Git 仓库地址——这两处都是运行时
配置，不需要改代码。

管理员在页面上可以选择**发行版**或 **Beta 版**通道：发行版只显示稳定的
`vMAJOR.MINOR.PATCH` 标签，Beta 版只显示 `vMAJOR.MINOR.PATCH-beta.N` 之类的预发布标签，
默认 Beta 版。更新控制服务会校验所选标签是注释标签、属于目标仓库 `main` 历史、
在 `VERSION_NOTES.md` 里有同名小节，并且版本号高于当前版本。HTTP 项目地址只接受内网、
本机或私有网络主机，且不能包含账号、口令或令牌。GitHub 这类 HTTPS 仓库固定使用 HTTP/1.1，
遇到连接重置等短暂传输失败会自动重试三次（可用 `DEPLOY_GIT_FETCH_ATTEMPTS=1-5` 与
`DEPLOY_GIT_FETCH_RETRY_SECONDS=1-30` 调整），最终失败会给出明确的仓库读取失败提示。

若在页面填写的项目地址与 `DEPLOY_LOCAL_GITEA_HTTP_ORIGIN` 精确匹配，更新服务与部署脚本
会仅在服务器内部改用 `DEPLOY_LOCAL_GITEA_SSH_ORIGIN` 读取同一路径，页面、数据库与审计日志
仍保留原始 HTTP 地址，也不会保存任何账号或令牌；两个变量必须同时设置，且 `.env` 里不得
写入账号、口令或访问令牌。

## 6. 发布与回滚

每次发布都要在 `VERSION_NOTES.md` 增加同名小节（数据库影响、配置变更、验证与回滚），
再打注释标签：

```bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

查看部署日志：

```bash
sudo journalctl -u office-asset-gitea-webhook -f
docker compose -f /opt/office-asset-mgmt/compose.yaml ps
docker compose -f /opt/office-asset-mgmt/compose.yaml logs --tail=100 app
```

涉及结构变更的版本，先用部署账号备份数据库（生成 `.sql.gz` 与同名 `.sha256`）：

```bash
sudo -u officeasset-deploy -H bash \
  /opt/office-asset-mgmt/deploy/scripts/backup_compose_database.sh
```

部署脚本会在替换应用容器前以一次性 `migrate` 容器执行受跟踪迁移作为闸门。已有库没有
`schema_migration` 时，只有在备份并确认历史基线之后，才临时在
`/opt/office-asset-mgmt/.env` 里设置 `MIGRATION_ADOPT_BASELINE=legacy-20260813`，
迁移成功后再删掉该设置。迁移、构建、启动或健康检查任一步失败，脚本会恢复到上一个 Git 提交
并重新启动旧应用。
