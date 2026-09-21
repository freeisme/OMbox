# 发布前脱敏检查

本仓库可能被公开访问，任何提交到远程或打包发布的内容都必须先通过脱敏检查。

## 检查命令

```bash
python tools/scan_release_safety.py --rev HEAD
```

脚本从 git 对象库读取指定版本的受跟踪文件，命中任意规则时返回退出码 `1` 并列出文件、行号和规则名。
CI 的 `Verify source` 工作流已包含该步骤，未通过时不会执行后续检查。

还可以附带一份**内部数据词表**，把正则覆盖不到的真实取值（人员姓名、工号、设备名、SN、
组织与仓库名称）一起比对。词表必须放在仓库之外，例如从生产库临时导出到 `/tmp`：

```bash
mysql -h 127.0.0.1 -u root -p -N -B office_asset_mgmt -e "
  SELECT employee_name FROM employee
  UNION SELECT employee_no FROM employee
  UNION SELECT device_name FROM computer_asset
  UNION SELECT sn_st FROM computer_asset
  UNION SELECT org_name FROM org_unit
  UNION SELECT warehouse_name FROM inventory_warehouse;" > /tmp/om-wordlist.txt

python tools/scan_release_safety.py --rev HEAD --wordlist /tmp/om-wordlist.txt
rm -f /tmp/om-wordlist.txt
```

命中任意一项就是泄漏。词表里的 `NULL`、`admin`、`test` 这类通用值会被自动忽略
（需要时用 `--wordlist-min-length` 调整最短长度）。这条检查不进 CI——CI 不该拿到生产数据，
发布前在本地手工跑一次即可。

## 检查规则

| 规则 | 说明 |
| --- | --- |
| `cloud-or-personal-access-token` | 常见云平台与个人访问令牌前缀 |
| `private-key-material` | 私钥文件正文 |
| `ssh-key-material` | SSH 公钥正文 |
| `internal-hostname` | 内网域名与内部主机名（`host.docker.internal` 等容器内通用名称除外） |
| `internal-ipv4` | 内网 IPv4 网段 |
| `local-machine-path` | 本机用户目录、盘符路径和项目工作目录 |
| `local-mysql-path` | 本机 MySQL 客户端安装路径 |
| `hardcoded-credential` | 直接写在代码或文档中的口令、令牌与密钥赋值 |
| `business-employee-number` | 企业工号等业务编号格式 |
| `internal-account-name` | 内网服务器账号、部署密钥文件名等标识 |
| `china-mobile-number` | 手机号 |
| `china-id-card-number` | 身份证号 |
| `email-address` | 邮箱地址（`example.*` / `*.invalid` 与 token、user 等占位本地部分除外） |
| `internal-asset-code` | 本部署的资产编码（前缀见脚本注释），防止文档与表单示例引用真实设备 |

另外禁止提交 `.env`、数据库导出、压缩备份、业务表格、运行日志和内部交接文档。

## 编写规则

- 文档、示例和测试数据统一使用保留地址或占位符，不写真实主机、账号、口令和路径；
- 需要真实取值时，通过环境变量或服务器上的受保护配置文件提供，并在文档里写成 `<占位符>`；
- 不要为了通过扫描而把敏感内容改写成分散拼接的字符串；应直接删除。
- 扫描规则本身在 `tools/scan_release_safety.py`，新增生产环境标识时同步补充规则。

## 文档与更新公告

上面列出的只是「模式可枚举」的内容；**人员姓名、设备编码、组织与仓库名称、客户名称无法用
正则覆盖**，靠的是纪律：

- 仓库里的任何文件（含 `VERSION_NOTES.md`、`docs/wiki/`、测试固定数据）都不得引用真实业务数据；
  示例与测试数据一律用虚拟信息，例如人员用「张三 / 李四」、部门用「测试部门」、
  设备用「IT-PC-01」、公用人员用「<组织名>公用」；
- 验证结论只写「验证了什么、结果如何」，不要把界面上的真实取值抄进文档；
- `VERSION_NOTES.md` 的条目只写变更、影响、验证与回滚，**保持简洁**；根因分析与实现要点
  写到 `docs/development/` 下对应的文档；
- 发布前用内部数据反查一遍：把生产库的人员姓名、工号、设备名、SN、组织与仓库名导出成词表，
  在受跟踪文件里搜一遍，命中即为泄漏（这一步补正则的空白）。

新部署的「全新系统」验收：按 `deploy/docker/init_database.sh` 的流程建一个空库，
确认除权限字典与参考数据（组织根节点、默认仓库、物资类型、巡检模板等）外，
人员、终端、账号、日志等业务表都应为 0 条。

## 本地预检查（可选）

把下面内容保存为 `.git/hooks/pre-push` 并赋予执行权限，可以在本机推送前自动运行检查：

```bash
#!/usr/bin/env bash
set -e
python tools/scan_release_safety.py --rev HEAD
```
