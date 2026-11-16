# 产线工控机（LineGuard）

管理车间产线上工控机的台账、换线履历与在线状态。数据表以 `lg_` 前缀与其它资产表同库共存。

## 能做什么

| 场景 | 入口 |
| --- | --- |
| 汇总在线率、各车间分布、待处理告警 | 工控机总览 |
| 手工录入 / 网段扫描入库 / Excel 导入 | 工控机台账 |
| 换线、换下状况登记、人工改状态、查看履历 | 工控机台账 → 行操作 |
| 查看与处理离线/阈值告警、设置阈值 | 工控机告警 |

## 关键概念

- **设备是唯一实体**：`line_id` / `station_id` 只是「当前位置」，换线只改位置，履历、告警、探测记录都挂在设备上，不随产线搬移。
- **状态来源**：`probe_mode` 决定判定方式。
  - `probe`：服务端主动探测（推荐，300 台规模的主力方式），按 `probe_interval` 到期执行；
  - `heartbeat`：只认设备上报（需要 Agent，本项目默认不部署）；
  - `hybrid`：两者取并集。
- **人工状态不被覆盖**：`故障 / 检修中 / 已下线` 由人工标记后，探测不会自动改回在线。
- **公司隔离**：车间与设备都带 `company_id`，列表按当前公司（顶栏公司切换）过滤；跨公司访问直接 403。

## 数据表（12 张，`lg_` 前缀）

`lg_workshop` 车间、`lg_line` 产线、`lg_station` 工位、`lg_device` 设备、`lg_device_event` 事件、
`lg_device_transfer` 换线履历、`lg_device_condition` 换下状况、`lg_health_check` 探测采样、
`lg_alert` 告警、`lg_scan_task` 扫描任务、`lg_setting` 阈值配置、`lg_host_link` 与办公资产弱关联。

## 权限

模块 `lineguard`，动作 `view / create / update / delete / approve / export`。
在「设置 → 角色权限」里给角色勾选后，左侧「产线设备」分组才会出现。

## 网段扫描

1. 工控机台账 → 扫描网段；
2. 填网段（`192.0.2.0/24`，或 `192.0.2.10-192.0.2.60`，示例地址段），单次上限 4096 个地址；
3. 探测端口留空用 ICMP，也可填 `445,3389` 之类的 TCP 端口；
4. 勾选存活主机 → 入库（按 IP 幂等，重复扫描不会重复建）。

> 容器默认没有 `NET_RAW`，ICMP 可能不可用；此时请填写 TCP 探测端口，或给容器加 `cap_add: [NET_RAW]`。

## 探测与状态判定

- 探测循环每 5 秒检查一次到期设备，按 `probe_interval`（默认 60 秒）轮转；
- `probe` 模式连续 2 次失败判离线，`hybrid` 需要心跳也超时且连续 3 次失败；
- 探测不可用（如没装 ping）只记录，不判离线，避免误报；
- 采样记录默认保留 30 天（`LINEGUARD_CHECK_RETENTION_DAYS`）。

## 配置项（环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LINEGUARD_PROBE_INTERVAL_SECONDS` | 30 | 新设备默认探测周期 |
| `LINEGUARD_PROBE_TIMEOUT_MS` | 2000 | 单次探测超时 |
| `LINEGUARD_PROBE_CONCURRENCY` | 64 | 探测并发 |
| `LINEGUARD_OFFLINE_SECONDS` | 90 | 心跳超时判离线 |
| `LINEGUARD_SCAN_TIMEOUT_MS` | 800 | 扫描单地址超时 |
| `LINEGUARD_SCAN_CONCURRENCY` | 256 | 扫描并发 |
| `LINEGUARD_CHECK_RETENTION_DAYS` | 30 | 采样保留天数 |

## 常见问题

**菜单里看不到「产线设备」？** 当前角色没有被授予 `lineguard` 权限。

**设备一直显示离线？** 先在「检测方式」里确认是 `probe` 且填了 IP；端口探测要填对端口；
容器内 ping 不可用时只能靠端口探测。

**换线后历史丢了吗？** 不会。履历、状况、探测记录都按 `device_id` 关联，换线只写一条 `lg_device_transfer`。

**和办公终端的资产编号怎么对应？** 二者是不同台账。需要关联时在 `lg_host_link` 里登记 `host_asset_no`（当前版本给接口留位，未做界面）。
