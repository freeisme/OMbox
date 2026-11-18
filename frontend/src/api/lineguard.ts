/** 产线工控机（LineGuard）接口封装。 */
import { api } from "./client";
import { withCompanyQuery } from "../companyScope";
import type { ImportSummary } from "./datacenter";

export const LG_STATUS_LABELS: Record<string, string> = {
  online: "在线",
  offline: "离线",
  fault: "故障",
  maintenance: "检修中",
  retired: "已下线",
};

export const LG_PROBE_LABELS: Record<string, string> = {
  heartbeat: "心跳",
  probe: "主动探测",
  hybrid: "混合",
};

export interface LgWorkshop { id: number; code: string; name: string; company_id?: number; description?: string }
export interface LgLine { id: number; workshop_id: number; code: string; name: string }
export interface LgStation { id: number; line_id: number; code: string; name: string }

export interface LgDevice {
  id: number;
  asset_no: string;
  hostname: string;
  ip: string;
  mac: string;
  model: string;
  os_version: string;
  serial_no: string;
  status: string;
  probe_mode: string;
  probe_port: number;
  probe_interval: number;
  cpu_percent: number | null;
  mem_percent: number | null;
  disk_percent: number | null;
  last_heartbeat_at: string | null;
  last_seen_at: string | null;
  last_probe_ok: number | null;
  owner: string;
  source: string;
  result?: string;
  line_id: number | null;
  station_id: number | null;
  remark: string;
  line_name?: string;
  workshop_name?: string;
  station_name?: string;
  workshop_id?: number;
  agent_token_masked?: string;
  company_id?: number;
}

export interface LgDeviceList { total: number; page: number; size: number; items: LgDevice[] }
export interface LgOverview {
  summary: { online: number; offline: number; fault: number; maintenance: number; retired: number; total: number; health: number };
  by_workshop: { id: number; name: string; stats: Record<string, number> }[];
  alerts: LgAlertRow[];
  unassigned: number;
}
export interface LgAlertRow {
  id: number;
  device_id: number;
  level: string;
  alert_type: string;
  message: string;
  created_at: string;
  resolved_at: string | null;
  asset_no?: string;
  hostname?: string;
}
export interface LgTreeStation extends LgStation { devices: LgDevice[] }
export interface LgTreeLine extends LgLine { stations: LgTreeStation[]; unassigned: LgDevice[]; stats: Record<string, number>; device_count: number }
export interface LgTreeWorkshop extends LgWorkshop { lines: LgTreeLine[] }
export interface LgScanCandidate { ip: string; alive: boolean; latency_ms: number | null; mac: string; hostname: string; open_ports: number[]; known_device_id: number | null; reason: string }
export interface LgScanResult {
  cidr: string;
  total: number;
  alive_count: number;
  may_add_count: number;
  /** 当前环境能否执行 ICMP 探测；false 时只能靠 TCP 端口发现主机。 */
  icmp_available?: boolean;
  icmp_note?: string;
  candidates: LgScanCandidate[];
}

export function getMeta(): Promise<{ statuses: Record<string, string>; offline_seconds: number; probe_interval_seconds: number; probe_modes: Record<string, string> }> {
  return api(withCompanyQuery("/api/lineguard/meta"));
}

export function getOverview(): Promise<LgOverview> {
  return api(withCompanyQuery("/api/lineguard/overview"));
}

export function getTree(): Promise<{ workshops: LgTreeWorkshop[] }> {
  return api(withCompanyQuery("/api/lineguard/tree"));
}

export function getOptions(): Promise<{ workshops: LgWorkshop[]; lines: LgLine[]; stations: LgStation[] }> {
  return api(withCompanyQuery("/api/lineguard/options"));
}

export function listDevices(query: {
  q?: string; status?: string; workshopId?: string; lineId?: string; page?: number; size?: number;
}): Promise<LgDeviceList> {
  const search = new URLSearchParams();
  if (query.q) search.set("q", query.q);
  if (query.status) search.set("status", query.status);
  if (query.workshopId) search.set("workshopId", query.workshopId);
  if (query.lineId) search.set("lineId", query.lineId);
  search.set("page", String(query.page ?? 1));
  search.set("size", String(query.size ?? 50));
  return api(withCompanyQuery("/api/lineguard/devices?" + search.toString()));
}

export function getDevice(id: number | string): Promise<{
  device: LgDevice; transfers: any[]; conditions: any[]; events: any[]; checks: any[];
}> {
  return api(withCompanyQuery("/api/lineguard/devices/" + id));
}

export function createDevice(payload: Record<string, unknown>): Promise<{ id: number; agent_token: string }> {
  return api(withCompanyQuery("/api/lineguard/devices"), { method: "POST", body: payload });
}

export function updateDevice(id: number | string, payload: Record<string, unknown>): Promise<{ ok: boolean; changed: string[] }> {
  return api(withCompanyQuery("/api/lineguard/devices/" + id), { method: "PUT", body: payload });
}

export function deleteDevice(id: number | string): Promise<{ ok: boolean }> {
  return api(withCompanyQuery("/api/lineguard/devices/" + id), { method: "DELETE" });
}

export function transferDevice(id: number | string, payload: Record<string, unknown>): Promise<{ ok: boolean; from: string; to: string }> {
  return api(withCompanyQuery("/api/lineguard/devices/" + id + "/transfer"), { method: "POST", body: payload });
}

export function setDeviceStatus(id: number | string, payload: { status: string; detail?: string }): Promise<{ ok: boolean; changed: boolean }> {
  return api(withCompanyQuery("/api/lineguard/devices/" + id + "/status"), { method: "POST", body: payload });
}

export function addCondition(id: number | string, payload: Record<string, unknown>): Promise<{ ok: boolean; id: number }> {
  return api(withCompanyQuery("/api/lineguard/devices/" + id + "/conditions"), { method: "POST", body: payload });
}

export function bulkCreate(payload: { candidates: unknown[]; line_id?: number | null; station_id?: number | null; probe_mode?: string }): Promise<{ created: any[]; skipped: any[] }> {
  return api(withCompanyQuery("/api/lineguard/devices/bulk-create"), { method: "POST", body: payload });
}

export function scanNetwork(payload: { cidr: string; ports?: number[] }): Promise<LgScanResult> {
  return api(withCompanyQuery("/api/lineguard/scan"), { method: "POST", body: payload });
}

export function listAlerts(): Promise<{ alerts: LgAlertRow[] }> {
  return api(withCompanyQuery("/api/lineguard/alerts"));
}

export function resolveAlert(id: number): Promise<{ ok: boolean }> {
  return api(withCompanyQuery("/api/lineguard/alerts/" + id + "/resolve"), { method: "POST", body: {} });
}

export function getSettings(): Promise<{ settings: Record<string, string>; allowed: string[] }> {
  return api(withCompanyQuery("/api/lineguard/settings"));
}

export function saveSettings(payload: Record<string, string>): Promise<{ ok: boolean; settings: Record<string, string> }> {
  return api(withCompanyQuery("/api/lineguard/settings"), { method: "PUT", body: payload });
}

export function exportDevices(): Promise<{ fileName: string; content: string; count: number }> {
  return api(withCompanyQuery("/api/lineguard/reports/export"));
}

export function importDevices(payload: { fileName: string; contentBase64: string; dryRun: boolean; mode: "skip" | "update" }): Promise<ImportSummary> {
  return api(withCompanyQuery("/api/lineguard/reports/import"), { method: "POST", body: payload });
}

export function createWorkshop(payload: { code: string; name: string; description?: string }): Promise<{ id: number }> {
  return api(withCompanyQuery("/api/lineguard/workshops"), { method: "POST", body: payload });
}

export function createLine(payload: { workshop_id: number; code: string; name: string }): Promise<{ id: number }> {
  return api(withCompanyQuery("/api/lineguard/lines"), { method: "POST", body: payload });
}

export function createStation(payload: { line_id: number; code: string; name: string }): Promise<{ id: number }> {
  return api(withCompanyQuery("/api/lineguard/stations"), { method: "POST", body: payload });
}
