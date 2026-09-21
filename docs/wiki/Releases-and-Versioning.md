# 发布与版本

## 版本号

* 唯一来源是仓库根目录的 `VERSION`（SemVer，例如 `2.17.0`）；
* 后端启动时读取，通过 `GET /api/meta` 返回 `version` / `serverTime` / `timeZone`；
* 前端构建时注入版本与构建时间，设置页与登录页会显示。

## 版本说明

每个可部署版本在 `VERSION_NOTES.md` 里有同名段落（`## vX.Y.Z`），记录：
功能变更、数据库影响、配置要求、验证结果与回滚提示。
结构回归会检查「`VERSION` 与版本说明里最新的标题一致」，避免两者漂移。

## 发布流程

1. 改动合并到主分支，跑结构回归与相关端到端回归；
2. 前端 `vue-tsc --noEmit` 与 `vite build` 通过；
3. **推送前必须跑脱敏扫描**：

   ```bash
   python tools/scan_release_safety.py --rev HEAD
   ```

   命中敏感内容会以非零退出码失败，CI 里也包含该步骤；
4. 打 SemVer 注释标签（标签内容与 `VERSION_NOTES.md` 段落一致）；
5. 推送主分支与标签。

除非明确要求，发布只推代码仓库，不自动部署到生产、不同步内网镜像。

## 数据库迁移

* 所有结构变更都是 `database/migrations/` 下的新文件，命名 `YYYYMMDD_NNN_描述.sql`；
* 迁移只增不改：已应用的迁移文件不得再编辑（runner 校验 SHA-256 校验和）；
* 迁移必须幂等（`CREATE TABLE IF NOT EXISTS`、`information_schema` 判断后 `ALTER`）；
* 新表要同步更新健康检查里的必需表数量，否则 `/api/health` 会返回 503。

## 回滚

* 只新增表/列的版本可以直接回退代码，数据保留；
* 涉及健康检查表数量的版本，代码与数据库必须一起回退；
* 回滚前先备份数据库，并按 `VERSION_NOTES.md` 里该版本的「回滚提示」执行。
