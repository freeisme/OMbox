# 机房「文件库」方案（待确认）

> 目标：为机房/弱电间的网络设备与服务器提供配置文件归档，按「机房 → 设备」两级文件夹组织，
> 并与机柜视图、设备清单打通跳转。

## 一、组织方式

```
文件库
├── 一号机房（asset_site, site_type=server_room）
│   ├── 核心交换机-A（datacenter_device）
│   │   ├── running-config-20261118.txt
│   │   └── vlan-plan.xlsx
│   └── 防火墙-01
└── 三楼弱电间（site_type=weak_room）
    └── 接入交换机-3F
```

- 一级目录 = 机房/弱电间（来自 `asset_site`）
- 二级目录 = 该机房下的机房设备（来自 `datacenter_device.site_id`）
- 设备建档时自动生成对应文件夹；已有设备在首次打开文件库时惰性补齐（另可跑一次性回填）

## 二、数据表（3 张，同库）

| 表 | 作用 | 关键字段 |
| --- | --- | --- |
| `file_folder` | 虚拟文件夹 | `folder_id`、`folder_type(site/device)`、`site_id`、`device_id`、`display_path` |
| `file_object` | 文件元数据 | `file_id`、`folder_id`、`file_name`、`stored_name`、`size_bytes`、`sha256`、`description`、`uploaded_by`、`deleted_at` |
| `file_event` | 操作记录 | `file_id`、`folder_id`、`action(upload/download/rename/delete)`、`actor`、`detail`、`created_at` |

文件本体存磁盘卷（`FILE_LIBRARY_ROOT`，compose 挂 `file-library-data`），DB 只存元数据；
磁盘目录用 `site-<id>/device-<id>/<sha前8位>/<原名>`，避免中文与特殊字符问题。

## 三、接口（沿用机房模块权限）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/file-library/tree` | 机房 → 设备两级树（带文件数、总大小） |
| GET | `/api/file-library/files?folderId=` | 当前文件夹的文件列表 |
| POST | `/api/file-library/files` | 上传（文件名、base64、描述） |
| GET | `/api/file-library/files/{id}/download` | 下载（带审计） |
| PUT | `/api/file-library/files/{id}` | 改名 / 改描述 |
| DELETE | `/api/file-library/files/{id}` | 删除（软删 + 审计） |
| GET | `/api/file-library/events?deviceId=` | 该设备的操作记录 |

## 四、界面

1. 机房页面（`/datacenter`）新增第 5 个页签 **文件库**；
2. 左侧树：机房（含类型标识）→ 设备，支持按名称搜索；右侧文件表格（名称/大小/上传人/时间/描述/操作）；
3. 文件表格上方：上传、刷新、记录；
4. 机柜视图右侧「设备属性」栏增加按钮 **配置文件**；
5. 网络设备/服务器（`DatacenterDeviceView`）操作列增加 **配置文件**；
6. 两个按钮都跳到 `/datacenter?tab=files&device=<id>`，自动展开并选中该设备。

## 五、待定项（问答确认）

1. 文件存储位置：磁盘卷 / 数据库
2. 同名文件策略：保留历史版本 / 直接覆盖 / 自动改名
3. 权限：新建 `file_library` 模块 / 复用机房权限
4. 单文件上限与类型：沿用 8MB 请求体（实际约 6MB）/ 扩容到 50–100MB（需流式上传）/ 只允许白名单后缀
5. 机房级共享文件：允许 / 不允许
6. 删除设备时：文件夹与文件保留归档 / 一并删除

## 六、影响面

- 迁移 1 个（3 张表 + 权限）；
- 后端新增 1 个服务 + 7 个接口，`create_datacenter_device` 加一行建文件夹；
- 前端新增 1 个页签视图 + 2 处按钮；
- 部署需新增一个数据卷挂载。
