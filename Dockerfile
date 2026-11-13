# 构建新版前端（Vue + Vite）。产物落到 /web/app，由运行阶段复制进镜像。
FROM node:22-alpine AS frontend

WORKDIR /frontend

# 服务器/内网环境常无法直连 registry.npmjs.org（构建时会 ETIMEDOUT），
# 默认走国内镜像；需要官方源时用 --build-arg NPM_REGISTRY=https://registry.npmjs.org 覆盖。
ARG NPM_REGISTRY=https://registry.npmmirror.com
ENV COREPACK_NPM_REGISTRY=${NPM_REGISTRY} \
    npm_config_registry=${NPM_REGISTRY}

RUN corepack enable

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./
COPY VERSION /VERSION
RUN mkdir -p /web/app
RUN pnpm build

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

COPY server.py ./
COPY office_asset ./office_asset
COPY database/migrations ./database/migrations
COPY tools/migration_runner.py ./tools/migration_runner.py
COPY web ./web
COPY --from=frontend /web/app ./web/app
COPY VERSION ./

# 再分发合规：镜像内保留自有许可与第三方组件许可清单
COPY LICENSE THIRD_PARTY_NOTICES.md ./

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MYSQL_BIN=/usr/bin/mysql \
    MYSQLDUMP_BIN=/usr/bin/mysqldump \
    BACKUP_DIR=/app/backups \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000

EXPOSE 8000

CMD ["python", "server.py"]
