# 组织与权限优化方案（v4.0.6 候选）

> 基于 2026-11-06 的全量逻辑检查结论。按优先级执行，全部落到本地测试环境验证。

## 一、高危（数据正确性）

### P1 组织树环
- 后端 `_save_organization`：保存前校验「新父级不能是当前组织自身或其后代」。
- 前端 `buildOrgSubtree`：递归增加 visited 保护，遇到重复 id 直接截断。

### P2 删除组织静默清空关联数据
`org_unit` 的外键多为 `ON DELETE SET NULL`。
- `_delete_organization` 增加校验：`asset_site`、`asset_rack`、`datacenter_device`、`user_org_scope`。
- 有引用时返回明确提示，不再静默孤儿。

### P3 跨公司修改组织
- `_save_organization`：编辑已存在组织时，若 `companyId` 与当前不同 → 拒绝，提示走「转移组织」。

## 二、中危

### P4 组织编码重复
- `_save_organization`：同父级下同编码已存在时拒绝（根级父级按 0 处理，避免 NULL 绕过唯一索引）。

### P5 停用公司仍出现在切换器
- `list_companies` 只返回 `is_active=1` 的公司。

### P6 退出未清空公司视图
- `clearSession()` 同步重置全局 `companyScope`。

### P7 离职人员删除按钮未门控
- 按钮 `v-if="hasPermission('employees','delete')"`。

### P8 审计缺口
- 补齐：公司新增/修改/删除、组织新增。

## 三、低危 / 体验

- P9 组织树停用节点加「停用」标记；编辑时公司只读展示。
- P10 `hasPermission` 去掉 `canView ?? true` 兜底。
- P11 组织树搜索忽略大小写。
- P12 `/api/updates/status` 服务端缓存 30 分钟，避免每次页面加载都 git fetch。
- P13 顶栏切换器加 title 说明「影响组织架构视图」。

## 四、暂不实施（记录）

- 角色删除、离职排序持久化、软删公司恢复入口 → 需要新表字段/交互设计，留待下一轮。

## 五、验收

- 244 项单元测试通过；
- 前端 `vue-tsc` + `vite build` 通过；
- 本地服务 HTTP 冒烟：组织环/跨公司/重复编码/删除引用 均应被拒绝；停用公司不再返回。
