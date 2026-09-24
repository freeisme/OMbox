import { api } from "./client";

export interface RackSummary {
  id: string;
  code: string;
  name: string;
  heightU: number;
  siteId: string;
  siteName: string;
  siteType?: string;
  usedUnits: number;
  deviceCount: number;
}

export interface Placement {
  id: string;
  rackId: string;
  sourceKind: "computer" | "custom";
  computerId?: string;
  inventoryModelId?: string;
  name: string;
  brandModel: string;
  category: string;
  positionU: number;
  uHeight: number;
  face: "front" | "rear" | "both";
  status?: string;
  assetCode?: string;
  serialNumber?: string;
  ownerLabel?: string;
  notes?: string;
}

export interface RackDetail extends RackSummary {
  placements: Placement[];
  freeUnits: number;
}

export interface DatacenterDeviceSummary {
  id: string;
  code: string;
  name: string;
  catalogId: string;
  catalogSlug?: string;
  brandModel: string;
  category: string;
  uHeight: number;
  serialNumber: string;
  assetCode: string;
  ownerLabel: string;
  /** 用途、远程访问地址与硬件配置（台账补充字段）。 */
  purpose?: string;
  remoteAccess?: string;
  cpu?: string;
  memory?: string;
  disk?: string;
  status: string;
  siteId?: string;
  siteName?: string;
  rackId?: string;
  rackName?: string;
  notes?: string;
}

export interface RackPaletteDevice {
  deviceId: string;
  code: string;
  name: string;
  catalogId: string;
  brandModel: string;
  category: string;
  uHeight: number;
  serialNumber: string;
  assetCode: string;
  ownerLabel: string;
  status: string;
}

export interface RackPort {
  id: string;
  name: string;
  type: string;
  kind: "network" | "fiber" | "power" | "console" | "other";
  face: "front" | "rear";
  rowIndex: number;
  positionIndex: number;
  direction: string;
  speed: string;
  status: "up" | "down" | "disabled" | "unknown";
  /** 可选：端口上的 IP/掩码或管理地址。 */
  ipAddress?: string;
  /** 可选：端口所属 VLAN。 */
  vlan?: string;
  notes: string;
  cableId?: string;
  cableLabel?: string;
  cableMedium?: string;
  cableStatus?: string;
  peerPlacementId?: string;
  peerPlacementName?: string;
  peerPortName?: string;
}

export interface RackPortDevice {
  placementId: string;
  name: string;
  brandModel: string;
  category: string;
  positionU: number;
  uHeight: number;
  face: string;
  catalogSlug: string;
  ports: RackPort[];
}

export interface RackPortsPayload {
  id: string;
  name: string;
  code: string;
  heightU: number;
  siteName: string;
  placements: RackPortDevice[];
  portCount: number;
}

export interface Cable {
  id: string;
  medium: string;
  lengthM: number | null;
  label: string;
  status: string;
  notes: string;
  aPortId: string;
  bPortId: string;
  aPortName: string;
  bPortName: string;
  aPlacementId: string;
  bPlacementId: string;
  aPlacementName: string;
  bPlacementName: string;
  aRackName: string;
  bRackName: string;
  aSiteName: string;
  bSiteName: string;
}

export interface DeviceTypeSummary {
  id: string;
  slug: string;
  manufacturer: string;
  model: string;
  partNumber: string;
  uHeight: number;
  category: string;
  frontImage: number;
  rearImage: number;
  imageFrontPath: string;
  imageRearPath: string;
  source: string;
  portCount: number;
}

export interface DeviceTypePort {
  name: string;
  type: string;
  kind: RackPort["kind"];
  face: "front" | "rear";
  rowIndex: number;
  positionIndex: number;
}

export interface DeviceTypeDetail extends DeviceTypeSummary {
  ports: DeviceTypePort[];
}

export interface TopologyNode {
  id: string;
  name: string;
  brandModel: string;
  category: string;
  status: string;
  positionU: number;
  uHeight: number;
  rackId: string;
  rackName: string;
  siteId: string;
  siteName: string;
  portCount: number;
  linkedPortCount: number;
}

export interface TopologyPosition {
  nodeId: string;
  x: number;
  y: number;
}

export interface TopologyPayload {
  nodes: TopologyNode[];
  links: Cable[];
  positions: TopologyPosition[];
}

export function listRacks(): Promise<{ racks: RackSummary[] }> {
  return api<{ racks: RackSummary[] }>("/api/rack-layout/racks");
}

export function getRack(rackId: string): Promise<{ rack: RackDetail }> {
  return api<{ rack: RackDetail }>(`/api/rack-layout/racks/${encodeURIComponent(rackId)}`);
}

/** 未上架设备只来自机房设备台账，不含办公终端与 IT 物资。 */
export function availableDevices(keyword = ""): Promise<{ devices: RackPaletteDevice[] }> {
  const query = keyword ? `?keyword=${encodeURIComponent(keyword)}` : "";
  return api<{ devices: RackPaletteDevice[] }>(`/api/rack-layout/available${query}`);
}

export function listDatacenterDevices(
  params: { status?: string; keyword?: string; siteId?: string } = {},
): Promise<{ devices: DatacenterDeviceSummary[] }> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.keyword) query.set("keyword", params.keyword);
  if (params.siteId) query.set("siteId", params.siteId);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return api<{ devices: DatacenterDeviceSummary[] }>(`/api/datacenter-devices${suffix}`);
}

export function createDatacenterDevice(payload: Record<string, unknown>): Promise<{ id: string }> {
  return api("/api/datacenter-devices", { method: "POST", body: payload });
}

export function updateDatacenterDevice(
  deviceId: string,
  payload: Record<string, unknown>,
): Promise<unknown> {
  return api(`/api/datacenter-devices/${encodeURIComponent(deviceId)}`, {
    method: "PUT",
    body: payload,
  });
}

export function removeDatacenterDevice(deviceId: string, reason: string): Promise<unknown> {
  return api(`/api/datacenter-devices/${encodeURIComponent(deviceId)}/remove`, {
    method: "POST",
    body: { reason },
  });
}

export interface ImportSummary {
  fileName: string;
  sheetHeaders: Record<string, string>;
  totalRows: number;
  created: number;
  updated: number;
  skipped: number;
  errors: { row: number; code: string; message: string }[];
  errorCount: number;
  dryRun: boolean;
}

/** 上传 xlsx / csv 导入机房设备；dryRun=true 时只解析不写库。 */
export function importDatacenterDevices(payload: {
  fileName: string;
  contentBase64: string;
  dryRun?: boolean;
  mode?: "skip" | "update";
}): Promise<ImportSummary> {
  return api<ImportSummary>("/api/datacenter-devices/import", { method: "POST", body: payload });
}

export function saveDeviceType(payload: Record<string, unknown>): Promise<{ catalogId: string }> {
  return api("/api/device-types", { method: "POST", body: payload });
}

export function placeDevice(rackId: string, payload: Record<string, unknown>): Promise<{ id: string }> {
  return api(`/api/rack-layout/racks/${encodeURIComponent(rackId)}/placements`, {
    method: "POST",
    body: payload,
  });
}

export function updatePlacement(placementId: string, payload: Record<string, unknown>): Promise<unknown> {
  return api(`/api/rack-layout/placements/${encodeURIComponent(placementId)}`, {
    method: "PUT",
    body: payload,
  });
}

export function removePlacement(placementId: string, reason: string): Promise<unknown> {
  return api(`/api/rack-layout/placements/${encodeURIComponent(placementId)}/remove`, {
    method: "POST",
    body: { reason },
  });
}

export function listRackPorts(rackId: string): Promise<{ rack: RackPortsPayload }> {
  return api<{ rack: RackPortsPayload }>(
    `/api/rack-layout/racks/${encodeURIComponent(rackId)}/ports`,
  );
}

export function importPortsFromTemplate(
  placementId: string,
  payload: { catalogId?: string; slug?: string; applyHeight?: boolean; uHeight?: number },
): Promise<{ created: number; skipped: number }> {
  return api(`/api/rack-layout/placements/${encodeURIComponent(placementId)}/ports/import`, {
    method: "POST",
    body: payload,
  });
}

/** 复制另一台已上架设备的端口配置（跳过同名端口）。 */
export function copyPortsFromPlacement(
  placementId: string,
  sourcePlacementId: string,
): Promise<{ created: number; skipped: number }> {
  return api(`/api/rack-layout/placements/${encodeURIComponent(placementId)}/ports/copy`, {
    method: "POST",
    body: { sourcePlacementId },
  });
}

/** 按命名模板批量生成端口，例如 GE1/0/{n} 生成 1-24。 */
export function generatePlacementPorts(
  placementId: string,
  payload: {
    pattern: string;
    start: number;
    end: number;
    step?: number;
    perRow?: number;
    kind?: string;
    face?: string;
    type?: string;
    speed?: string;
  },
): Promise<{ created: number; skipped: number }> {
  return api(`/api/rack-layout/placements/${encodeURIComponent(placementId)}/ports/batch`, {
    method: "POST",
    body: payload,
  });
}

export function createPort(placementId: string, payload: Record<string, unknown>): Promise<{ id: string }> {
  return api(`/api/rack-layout/placements/${encodeURIComponent(placementId)}/ports`, {
    method: "POST",
    body: payload,
  });
}

export function updatePort(portId: string, payload: Record<string, unknown>): Promise<unknown> {
  return api(`/api/rack-layout/ports/${encodeURIComponent(portId)}`, {
    method: "PUT",
    body: payload,
  });
}

export function removePort(portId: string, reason: string): Promise<unknown> {
  return api(`/api/rack-layout/ports/${encodeURIComponent(portId)}/remove`, {
    method: "POST",
    body: { reason },
  });
}

export function listCables(params: { rackId?: string; siteId?: string } = {}): Promise<{ cables: Cable[] }> {
  const query = new URLSearchParams();
  if (params.rackId) query.set("rackId", params.rackId);
  if (params.siteId) query.set("siteId", params.siteId);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return api<{ cables: Cable[] }>(`/api/rack-layout/cables${suffix}`);
}

export function createCable(payload: Record<string, unknown>): Promise<{ id: string }> {
  return api("/api/rack-layout/cables", { method: "POST", body: payload });
}

export function updateCable(cableId: string, payload: Record<string, unknown>): Promise<unknown> {
  return api(`/api/rack-layout/cables/${encodeURIComponent(cableId)}`, {
    method: "PUT",
    body: payload,
  });
}

export function removeCable(cableId: string, reason: string): Promise<unknown> {
  return api(`/api/rack-layout/cables/${encodeURIComponent(cableId)}/remove`, {
    method: "POST",
    body: { reason },
  });
}

export function listDeviceTypes(keyword = ""): Promise<{ deviceTypes: DeviceTypeSummary[] }> {
  const query = keyword ? `?keyword=${encodeURIComponent(keyword)}` : "";
  return api<{ deviceTypes: DeviceTypeSummary[] }>(`/api/device-types${query}`);
}

export function getDeviceType(catalogId: string): Promise<{ deviceType: DeviceTypeDetail }> {
  return api<{ deviceType: DeviceTypeDetail }>(`/api/device-types/${encodeURIComponent(catalogId)}`);
}

export function uploadDeviceTypeImage(
  catalogId: string,
  payload: { face: "front" | "rear"; fileName: string; contentBase64: string },
): Promise<{ path: string }> {
  return api(`/api/device-types/${encodeURIComponent(catalogId)}/image`, {
    method: "POST",
    body: payload,
  });
}

export function removeDeviceTypeImage(
  catalogId: string,
  face: "front" | "rear",
): Promise<{ path: string }> {
  return api(`/api/device-types/${encodeURIComponent(catalogId)}/image/remove`, {
    method: "POST",
    body: { face },
  });
}

export function loadTopology(params: {
  siteId?: string;
  rackId?: string;
  onlyLinked?: boolean;
}): Promise<TopologyPayload> {
  const query = new URLSearchParams();
  if (params.siteId) query.set("siteId", params.siteId);
  if (params.rackId) query.set("rackId", params.rackId);
  if (params.onlyLinked) query.set("onlyLinked", "1");
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return api<TopologyPayload>(`/api/rack-layout/topology${suffix}`);
}

export function saveTopologyPositions(
  nodes: TopologyPosition[],
): Promise<{ saved: number }> {
  return api("/api/rack-layout/topology/positions", { method: "POST", body: { nodes } });
}
