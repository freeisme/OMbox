<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import FormDialog from "../components/ui/FormDialog.vue";
import { confirmAction } from "../composables/useConfirm";
import { RACK_CATEGORY_LABELS as CATEGORY_LABELS } from "../labels";
import {
  copyPortsFromPlacement,
  createCable,
  createPort,
  generatePlacementPorts,
  importPortsFromTemplate,
  listDeviceTypes,
  listRackPorts,
  listRacks,
  loadTopology,
  removeCable,
  removePort,
  saveTopologyPositions,
  updateCable,
  updatePort,
  type Cable,
  type DeviceTypeSummary,
  type RackPort,
  type RackPortDevice,
  type RackSummary,
  type TopologyNode,
  type TopologyPosition,
} from "../api/datacenter";
import { hasPermission } from "../session";

interface PlacedNode {
  node: TopologyNode;
  x: number;
  y: number;
  level: number;
}

const NODE_W = 168;
const NODE_H = 46;
const LEVEL_GAP = 230;
const ROW_GAP = 84;
const MARGIN = { left: 80, top: 56 };
const GRID = 8;

const KIND_LABELS: Record<string, string> = {
  network: "电口",
  fiber: "光口",
  power: "电源",
  console: "Console",
  other: "其他",
};
const MEDIUM_OPTIONS = [
  { value: "cat5e", label: "超五类" },
  { value: "cat6", label: "六类" },
  { value: "fiber-om3", label: "多模光纤 OM3" },
  { value: "fiber-os2", label: "单模光纤 OS2" },
  { value: "dac", label: "DAC 高速线" },
  { value: "power", label: "电源线" },
  { value: "console", label: "Console 线" },
  { value: "other", label: "其他" },
];
const CABLE_STATUS_OPTIONS = [
  { value: "connected", label: "已连接" },
  { value: "planned", label: "计划中" },
  { value: "disconnected", label: "已断开" },
  { value: "fault", label: "故障" },
];
const PORT_STATUS_OPTIONS = [
  { value: "unknown", label: "未知" },
  { value: "up", label: "正常" },
  { value: "down", label: "断开" },
  { value: "disabled", label: "停用" },
];
/** 介质配色：同一条链路在画布、导出与打印里颜色一致。 */
const MEDIUM_COLORS: Record<string, string> = {
  cat5e: "#909399",
  cat6: "#5b8cff",
  "fiber-om3": "#e6a23c",
  "fiber-os2": "#f2c037",
  dac: "#67c23a",
  power: "#f56c6c",
  console: "#b37feb",
  other: "#a8abb2",
};

const loading = ref(false);
const racks = ref<RackSummary[]>([]);
const siteId = ref("");
const rackId = ref("");
const onlyLinked = ref(false);
const showLabels = ref(true);
const focusSelected = ref(false);
const routeMode = ref<"orthogonal" | "direct">("orthogonal");
const snapGrid = ref(true);
const nodes = ref<TopologyNode[]>([]);
const links = ref<Cable[]>([]);
const savedPositions = ref<Record<string, TopologyPosition>>({});
const localPositions = ref<Record<string, { x: number; y: number }>>({});
const selectedId = ref("");
const selectedLinkId = ref("");
const dirty = ref(false);
/** 多选：参与整体拖动的节点（单击=单选，Shift/Ctrl+单击=加减，框选=批量）。 */
const groupIds = ref<string[]>([]);
/** 布局改动的撤销 / 重做栈（只回退节点坐标，端口与链路属于服务端数据，不进这个栈）。 */
const undoStack = ref<Array<Record<string, { x: number; y: number }>>>([]);
const redoStack = ref<Array<Record<string, { x: number; y: number }>>>([]);
const marquee = ref<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
/** 从节点上的连线手柄拖到另一台设备时的橡皮筋。 */
const connectDrag = ref<{ fromId: string; x: number; y: number; overId: string } | null>(null);

/** 机柜端口缓存：端口列表、占用情况与对端都在这里取，点开弹窗时按机柜懒加载。 */
const rackPorts = ref<Record<string, RackPortDevice[]>>({});
const deviceTypes = ref<DeviceTypeSummary[]>([]);

type WizardStep = "" | "aDevice" | "bDevice";
const wizard = reactive({
  step: "" as WizardStep,
  aDeviceId: "",
  aPortId: "",
  bDeviceId: "",
  bPortId: "",
});
const portDialog = reactive({
  open: false,
  side: "" as "" | "a" | "b",
  deviceId: "",
  mode: "list" as "list" | "model" | "batch" | "manual",
  loading: false,
});
const portForm = reactive({
  name: "",
  kind: "network",
  type: "",
  face: "front",
  rowIndex: 1,
  positionIndex: 1,
  direction: "bidi",
  speed: "",
  status: "unknown",
  ipAddress: "",
  vlan: "",
  notes: "",
});
const portEditingId = ref("");
const batchForm = reactive({
  pattern: "GE1/0/{n}",
  start: 1,
  end: 24,
  step: 1,
  perRow: 24,
  kind: "network",
  face: "front",
  type: "",
  speed: "",
});
const modelForm = reactive({
  source: "template" as "template" | "device",
  catalogId: "",
  sourcePlacementId: "",
});
const cableDialog = reactive({ open: false, saving: false });
/** 拖拽连线：松手后在这两个下拉里确认两端的端口，链路属性与点选式共用同一套字段。 */
const connectDialog = reactive({
  open: false,
  saving: false,
  aDeviceId: "",
  bDeviceId: "",
  aPortId: "",
  bPortId: "",
});
const cableForm = reactive({
  medium: "cat6",
  lengthM: 3,
  label: "",
  status: "connected",
  notes: "",
});
const linkForm = reactive({ medium: "cat6", lengthM: 0, label: "", status: "connected", notes: "" });
const linkSaving = ref(false);

const canUpdate = computed(() => hasPermission("rack_layout", "update"));
const sites = computed(() => {
  const map = new Map<string, string>();
  racks.value.forEach((item) => map.set(item.siteId, item.siteName));
  return [...map.entries()].map(([value, label]) => ({ value, label }));
});
const rackOptions = computed(() =>
  racks.value.filter((item) => !siteId.value || item.siteId === siteId.value),
);

/** 聚焦模式：只保留选中设备与它的一跳邻居。 */
const focusIds = computed<Set<string> | null>(() => {
  if (!focusSelected.value || !selectedId.value) return null;
  const ids = new Set<string>([selectedId.value]);
  links.value.forEach((link) => {
    if (link.aPlacementId === selectedId.value) ids.add(link.bPlacementId);
    if (link.bPlacementId === selectedId.value) ids.add(link.aPlacementId);
  });
  return ids;
});
const visibleNodes = computed(() =>
  focusIds.value ? nodes.value.filter((item) => focusIds.value?.has(item.id)) : nodes.value,
);
const visibleLinks = computed(() =>
  focusIds.value
    ? links.value.filter(
        (link) => focusIds.value?.has(link.aPlacementId) && focusIds.value?.has(link.bPlacementId),
      )
    : links.value,
);

const levels = computed(() => {
  const adjacency = new Map<string, Set<string>>();
  visibleNodes.value.forEach((item) => adjacency.set(item.id, new Set()));
  visibleLinks.value.forEach((link) => {
    adjacency.get(link.aPlacementId)?.add(link.bPlacementId);
    adjacency.get(link.bPlacementId)?.add(link.aPlacementId);
  });
  const degree = (id: string) => adjacency.get(id)?.size ?? 0;
  const root = [...visibleNodes.value].sort((a, b) => degree(b.id) - degree(a.id))[0];
  const result = new Map<string, number>();
  if (!root) return result;
  result.set(root.id, 0);
  const queue: string[] = [root.id];
  while (queue.length) {
    const current = queue.shift() as string;
    const next = result.get(current) ?? 0;
    adjacency.get(current)?.forEach((neighbour) => {
      if (result.has(neighbour)) return;
      result.set(neighbour, next + 1);
      queue.push(neighbour);
    });
  }
  let fallback = Math.max(0, ...[...result.values()], 0);
  visibleNodes.value.forEach((item) => {
    if (!result.has(item.id)) {
      fallback += 1;
      result.set(item.id, fallback);
    }
  });
  return result;
});

const placed = computed<PlacedNode[]>(() => {
  const byLevel = new Map<number, TopologyNode[]>();
  visibleNodes.value.forEach((item) => {
    const level = levels.value.get(item.id) ?? 0;
    const list = byLevel.get(level) ?? [];
    list.push(item);
    byLevel.set(level, list);
  });
  const result: PlacedNode[] = [];
  [...byLevel.keys()]
    .sort((a, b) => a - b)
    .forEach((level) => {
      (byLevel.get(level) ?? [])
        .sort((a, b) => `${a.rackName}-${a.name}`.localeCompare(`${b.rackName}-${b.name}`))
        .forEach((node, index) => {
          const override = localPositions.value[node.id] ?? savedPositions.value[node.id];
          result.push({
            node,
            level,
            x: override?.x ?? MARGIN.left + level * LEVEL_GAP,
            y: override?.y ?? MARGIN.top + index * ROW_GAP,
          });
        });
    });
  return result;
});

const canvas = computed(() => {
  const maxX = Math.max(NODE_W + MARGIN.left, ...placed.value.map((item) => item.x + NODE_W));
  const maxY = Math.max(NODE_H + MARGIN.top, ...placed.value.map((item) => item.y + NODE_H));
  return { width: maxX + 40, height: maxY + 40 };
});

const selected = computed(() => nodes.value.find((item) => item.id === selectedId.value) ?? null);
const selectedLink = computed(
  () => links.value.find((item) => item.id === selectedLinkId.value) ?? null,
);
const selectedLinks = computed(() =>
  links.value.filter(
    (link) => link.aPlacementId === selectedId.value || link.bPlacementId === selectedId.value,
  ),
);
const levelLabels = computed(() => {
  const seen = new Set<number>();
  placed.value.forEach((item) => seen.add(item.level));
  return [...seen]
    .sort((a, b) => a - b)
    .map((level, index) => ({
      level,
      label: index === 0 ? "边界 / 核心" : index === 1 ? "汇聚" : index === 2 ? "接入" : "末端",
    }));
});

/** 同一对设备之间的多条链路（堆叠 / LACP）横向错开，避免叠成一条线。 */
const linkOffsets = computed<Record<string, number>>(() => {
  const groups = new Map<string, Cable[]>();
  visibleLinks.value.forEach((link) => {
    const key = [link.aPlacementId, link.bPlacementId].sort().join("|");
    const list = groups.get(key) ?? [];
    list.push(link);
    groups.set(key, list);
  });
  const result: Record<string, number> = {};
  groups.forEach((list) => {
    const sorted = [...list].sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
    sorted.forEach((link, index) => {
      result[link.id] = (index - (sorted.length - 1) / 2) * 18;
    });
  });
  return result;
});

const wizardHint = computed(() =>
  wizard.step === "aDevice" ? "请点击 A 端设备" : wizard.step === "bDevice" ? "请点击 B 端设备" : "",
);
const wizardSummary = computed(() => {
  const a = wizard.aPortId ? portLabel(wizard.aPortId) : "";
  const b = wizard.bPortId ? portLabel(wizard.bPortId) : "";
  return [a ? `A 端：${a}` : "", b ? `B 端：${b}` : ""].filter(Boolean).join("　");
});
const portDialogDevice = computed(
  () => nodes.value.find((item) => item.id === portDialog.deviceId) ?? null,
);
const portDialogTitle = computed(() => {
  const side = portDialog.side === "a" ? "A 端" : portDialog.side === "b" ? "B 端" : "端口管理";
  return `${side} · ${portDialogDevice.value?.name ?? "设备"}`;
});
const portDialogPorts = computed<RackPort[]>(() => {
  const device = portDialogDevice.value;
  if (!device) return [];
  const placements = rackPorts.value[device.rackId] ?? [];
  return placements.find((item) => item.placementId === device.id)?.ports ?? [];
});
/** 已配好端口的设备可以直接当"复制端口配置"的来源。 */
const copySourceOptions = computed(() =>
  nodes.value
    .filter((item) => item.portCount > 0 && item.id !== portDialog.deviceId)
    .map((item) => ({
      value: item.id,
      label: `${item.name}（${item.brandModel || "未填型号"} · ${item.portCount} 口）`,
    })),
);

function portLabel(portId: string): string {
  for (const placements of Object.values(rackPorts.value)) {
    for (const device of placements) {
      const port = device.ports.find((item) => item.id === portId);
      if (port) return `${device.name} / ${port.name}`;
    }
  }
  return "";
}

function rackIdOfPort(portId: string): string {
  for (const [targetRackId, placements] of Object.entries(rackPorts.value)) {
    for (const device of placements) {
      if (device.ports.some((item) => item.id === portId)) return targetRackId;
    }
  }
  return "";
}

function positionOf(nodeId: string): { x: number; y: number } {
  return placed.value.find((item) => item.node.id === nodeId) ?? { x: 0, y: 0 };
}

/** 鼠标位置换算成画布坐标（画布用 viewBox 缩放，必须按比例换算）。 */
function toCanvasPoint(event: PointerEvent | MouseEvent): { x: number; y: number } {
  const svg = document.querySelector<SVGSVGElement>(".topology-canvas");
  const rect = svg?.getBoundingClientRect();
  if (!rect) return { x: 0, y: 0 };
  const scaleX = canvas.value.width / rect.width;
  const scaleY = canvas.value.height / rect.height;
  return { x: (event.clientX - rect.left) * scaleX, y: (event.clientY - rect.top) * scaleY };
}

function snap(value: number): number {
  const grid = snapGrid.value ? GRID : 1;
  return Math.max(0, Math.round(value / grid) * grid);
}

function clonePositions(): Record<string, { x: number; y: number }> {
  return Object.fromEntries(Object.entries(localPositions.value).map(([key, value]) => [key, { ...value }]));
}

/** 拖动开始前先记一份坐标，松手时压入撤销栈。 */
function pushHistory(snapshot: Record<string, { x: number; y: number }>): void {
  undoStack.value = [...undoStack.value, snapshot].slice(-50);
  redoStack.value = [];
}

function undoLayout(): void {
  if (!undoStack.value.length) {
    ElMessage.info("没有可撤销的布局改动。");
    return;
  }
  const previous = undoStack.value[undoStack.value.length - 1];
  redoStack.value = [...redoStack.value, clonePositions()];
  undoStack.value = undoStack.value.slice(0, -1);
  localPositions.value = previous;
  dirty.value = true;
}

function redoLayout(): void {
  if (!redoStack.value.length) {
    ElMessage.info("没有可重做的布局改动。");
    return;
  }
  const next = redoStack.value[redoStack.value.length - 1];
  undoStack.value = [...undoStack.value, clonePositions()];
  redoStack.value = redoStack.value.slice(0, -1);
  localPositions.value = next;
  dirty.value = true;
}

function onShortcut(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null;
  const typing =
    target &&
    (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
  if (typing || !canUpdate.value) return;
  if (!(event.ctrlKey || event.metaKey)) return;
  const key = event.key.toLowerCase();
  if (key === "z" && !event.shiftKey) {
    event.preventDefault();
    undoLayout();
  } else if (key === "y" || (key === "z" && event.shiftKey)) {
    event.preventDefault();
    redoLayout();
  }
}

function mediumColor(medium: string): string {
  return MEDIUM_COLORS[medium] ?? MEDIUM_COLORS.other;
}

function mediumLabel(medium: string): string {
  return MEDIUM_OPTIONS.find((item) => item.value === medium)?.label ?? medium;
}

function linkPath(link: Cable): string {
  const from = positionOf(link.aPlacementId);
  const to = positionOf(link.bPlacementId);
  if (!from || !to) return "";
  const x1 = from.x + NODE_W;
  const y1 = from.y + NODE_H / 2;
  const x2 = to.x;
  const y2 = to.y + NODE_H / 2;
  const offset = linkOffsets.value[link.id] ?? 0;
  if (routeMode.value === "direct") {
    const length = Math.hypot(x2 - x1, y2 - y1) || 1;
    const midX = (x1 + x2) / 2 - ((y2 - y1) / length) * offset;
    const midY = (y1 + y2) / 2 + ((x2 - x1) / length) * offset;
    return `M ${x1} ${y1} L ${midX} ${midY} L ${x2} ${y2}`;
  }
  const midX = (x1 + x2) / 2 + offset;
  return `M ${x1} ${y1} L ${midX} ${y1} L ${midX} ${y2} L ${x2} ${y2}`;
}

function linkLabelPoint(link: Cable): { x: number; y: number } {
  const from = positionOf(link.aPlacementId);
  const to = positionOf(link.bPlacementId);
  const offset = linkOffsets.value[link.id] ?? 0;
  const x1 = from.x + NODE_W;
  const y1 = from.y + NODE_H / 2;
  const x2 = to.x;
  const y2 = to.y + NODE_H / 2;
  if (routeMode.value === "direct") {
    const length = Math.hypot(x2 - x1, y2 - y1) || 1;
    return {
      x: (x1 + x2) / 2 - ((y2 - y1) / length) * offset,
      y: (y1 + y2) / 2 + ((x2 - x1) / length) * offset,
    };
  }
  return { x: (x1 + x2) / 2 + offset, y: (y1 + y2) / 2 };
}

function linkLabel(link: Cable): string {
  return link.label || `${link.aPortName} → ${link.bPortName}`;
}

function isHighlighted(link: Cable): boolean {
  if (link.id === selectedLinkId.value) return true;
  return link.aPlacementId === selectedId.value || link.bPlacementId === selectedId.value;
}

async function loadData(): Promise<void> {
  loading.value = true;
  try {
    const payload = await loadTopology({
      siteId: siteId.value,
      rackId: rackId.value,
      onlyLinked: onlyLinked.value,
    });
    nodes.value = payload.nodes;
    links.value = payload.links;
    savedPositions.value = Object.fromEntries(
      payload.positions.map((item) => [item.nodeId, item]),
    );
    localPositions.value = {};
    dirty.value = false;
    undoStack.value = [];
    redoStack.value = [];
    groupIds.value = [];
    marquee.value = null;
    connectDrag.value = null;
    if (selectedId.value && !nodes.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = "";
    }
    if (selectedLinkId.value && !links.value.some((item) => item.id === selectedLinkId.value)) {
      selectedLinkId.value = "";
    }
  } catch (error) {
    ElMessage.error(`拓扑加载失败：${(error as Error).message}`);
  } finally {
    loading.value = false;
  }
}

async function ensureRackPorts(targetRackId: string, force = false): Promise<void> {
  if (!targetRackId || (!force && rackPorts.value[targetRackId])) return;
  try {
    const payload = await listRackPorts(targetRackId);
    rackPorts.value = { ...rackPorts.value, [targetRackId]: payload.rack.placements ?? [] };
  } catch (error) {
    ElMessage.error(`端口加载失败：${(error as Error).message}`);
  }
}

/** 端口或链路变更后：刷新受影响的机柜端口缓存，再重新拉一次拓扑。 */
async function refreshAfterEdit(...changedRackIds: string[]): Promise<void> {
  for (const id of changedRackIds) {
    if (id) await ensureRackPorts(id, true);
  }
  await loadData();
}

/** 拖动上下文：整体拖动的每个节点记录它与鼠标的相对偏移；框选与连线拖动共用一套监听。 */
let dragGroup: { nodes: Array<{ id: string; offsetX: number; offsetY: number }>; before: Record<string, { x: number; y: number }> } | null =
  null;

function onNodePointerDown(event: PointerEvent, item: PlacedNode): void {
  if (wizard.step === "aDevice" || wizard.step === "bDevice") {
    void pickWizardDevice(item.node);
    return;
  }
  selectedLinkId.value = "";
  if (event.shiftKey || event.ctrlKey) {
    groupIds.value = groupIds.value.includes(item.node.id)
      ? groupIds.value.filter((id) => id !== item.node.id)
      : [...groupIds.value, item.node.id];
  } else if (!groupIds.value.includes(item.node.id) || groupIds.value.length <= 1) {
    groupIds.value = [item.node.id];
  }
  selectedId.value = item.node.id;
  if (!canUpdate.value || !groupIds.value.includes(item.node.id)) return;
  const point = toCanvasPoint(event);
  const members = placed.value.filter((entry) => groupIds.value.includes(entry.node.id));
  dragGroup = {
    nodes: members.map((entry) => ({
      id: entry.node.id,
      offsetX: entry.x - point.x,
      offsetY: entry.y - point.y,
    })),
    before: clonePositions(),
  };
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
}

/** 空白处按下：清空选择并开始框选。 */
function onCanvasPointerDown(event: PointerEvent): void {
  if (event.target !== event.currentTarget) return;
  selectedId.value = "";
  selectedLinkId.value = "";
  groupIds.value = [];
  if (!canUpdate.value) return;
  const point = toCanvasPoint(event);
  marquee.value = { x1: point.x, y1: point.y, x2: point.x, y2: point.y };
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
}

/** 节点右边缘的连线手柄：按住往另一台设备拖。 */
function onConnectHandleDown(event: PointerEvent, item: PlacedNode): void {
  if (!canUpdate.value) return;
  event.stopPropagation();
  const from = positionOf(item.node.id);
  connectDrag.value = { fromId: item.node.id, x: from.x + NODE_W, y: from.y + NODE_H / 2, overId: "" };
  selectedId.value = item.node.id;
  groupIds.value = [item.node.id];
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
}

function onPointerMove(event: PointerEvent): void {
  if (marquee.value) {
    const point = toCanvasPoint(event);
    marquee.value = { ...marquee.value, x2: point.x, y2: point.y };
    return;
  }
  if (connectDrag.value) {
    const point = toCanvasPoint(event);
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    const container = hit?.closest("[data-node-id]") as HTMLElement | null;
    const overId = container?.dataset.nodeId ?? "";
    connectDrag.value = {
      ...connectDrag.value,
      x: point.x,
      y: point.y,
      overId: overId === connectDrag.value.fromId ? "" : overId,
    };
    return;
  }
  if (!dragGroup) return;
  const point = toCanvasPoint(event);
  const next = { ...localPositions.value };
  dragGroup.nodes.forEach((entry) => {
    next[entry.id] = { x: snap(point.x + entry.offsetX), y: snap(point.y + entry.offsetY) };
  });
  localPositions.value = next;
  dirty.value = true;
}

function onPointerUp(): void {
  window.removeEventListener("pointermove", onPointerMove);
  if (marquee.value) {
    const { x1, y1, x2, y2 } = marquee.value;
    const left = Math.min(x1, x2);
    const right = Math.max(x1, x2);
    const top = Math.min(y1, y2);
    const bottom = Math.max(y1, y2);
    // 拖出的框太小就当成"点空白清空选择"，避免误触。
    if (right - left > 6 || bottom - top > 6) {
      const picked = placed.value.filter(
        (entry) =>
          entry.x + NODE_W >= left &&
          entry.x <= right &&
          entry.y + NODE_H >= top &&
          entry.y <= bottom,
      );
      groupIds.value = picked.map((entry) => entry.node.id);
      selectedId.value = groupIds.value[0] ?? "";
      if (groupIds.value.length > 1) {
        ElMessage.info(`已框选 ${groupIds.value.length} 台设备，拖动其中任意一台会整体移动。`);
      }
    }
    marquee.value = null;
  }
  if (connectDrag.value) {
    const { fromId, overId } = connectDrag.value;
    connectDrag.value = null;
    if (overId && overId !== fromId) openConnectDialog(fromId, overId);
  }
  if (dragGroup) {
    const changed = JSON.stringify(dragGroup.before) !== JSON.stringify(localPositions.value);
    if (changed) pushHistory(dragGroup.before);
    dragGroup = null;
  }
}

/** 拖拽连线的落点弹窗：两端各选一条空闲端口。 */
async function openConnectDialog(aDeviceId: string, bDeviceId: string): Promise<void> {
  connectDialog.aDeviceId = aDeviceId;
  connectDialog.bDeviceId = bDeviceId;
  connectDialog.aPortId = "";
  connectDialog.bPortId = "";
  const aNode = nodes.value.find((item) => item.id === aDeviceId);
  const bNode = nodes.value.find((item) => item.id === bDeviceId);
  await ensureRackPorts(aNode?.rackId ?? "");
  await ensureRackPorts(bNode?.rackId ?? "");
  const aFree = freePorts(aDeviceId);
  const bFree = freePorts(bDeviceId);
  connectDialog.aPortId = aFree[0]?.id ?? "";
  connectDialog.bPortId = bFree[0]?.id ?? "";
  Object.assign(cableForm, {
    medium: "cat6",
    lengthM: 3,
    label: "",
    status: "connected",
    notes: "",
  });
  connectDialog.open = true;
}

/** 某台设备上还没连线的端口，用于拖拽连线时直接预选。 */
function freePorts(deviceId: string): RackPort[] {
  const node = nodes.value.find((item) => item.id === deviceId);
  if (!node) return [];
  const placements = rackPorts.value[node.rackId] ?? [];
  const ports = placements.find((item) => item.placementId === deviceId)?.ports ?? [];
  return ports.filter((port) => !port.cableId);
}

async function submitConnectDialog(): Promise<void> {
  if (!connectDialog.aPortId || !connectDialog.bPortId) {
    ElMessage.warning("两端都要选一条空闲端口。");
    return;
  }
  connectDialog.saving = true;
  try {
    const aRack = rackIdOfPort(connectDialog.aPortId);
    const bRack = rackIdOfPort(connectDialog.bPortId);
    await createCable({
      aPortId: connectDialog.aPortId,
      bPortId: connectDialog.bPortId,
      medium: cableForm.medium,
      lengthM: cableForm.lengthM || undefined,
      label: cableForm.label,
      status: cableForm.status,
      notes: cableForm.notes,
    });
    ElMessage.success("链路已建立。");
    connectDialog.open = false;
    await refreshAfterEdit(aRack, bRack);
  } catch (error) {
    ElMessage.error(`建立链路失败：${(error as Error).message}`);
  } finally {
    connectDialog.saving = false;
  }
}

function selectLink(link: Cable): void {
  selectedLinkId.value = link.id;
  selectedId.value = "";
  groupIds.value = [];
  linkForm.medium = link.medium;
  linkForm.lengthM = link.lengthM ?? 0;
  linkForm.label = link.label;
  linkForm.status = link.status;
  linkForm.notes = link.notes;
}

// ------------------------------------------------------------------ 连线向导

function resetWizard(): void {
  wizard.step = "";
  wizard.aDeviceId = "";
  wizard.aPortId = "";
  wizard.bDeviceId = "";
  wizard.bPortId = "";
  cableDialog.open = false;
}

/** 交互：选连线 → 点 A 设备 → 选或新建端口 → 点 B 设备 → 选或新建端口。 */
function startConnect(deviceId = ""): void {
  if (!canUpdate.value) {
    ElMessage.warning("没有机柜视图的修改权限。");
    return;
  }
  resetWizard();
  wizard.step = "aDevice";
  if (deviceId) {
    void pickWizardDevice(nodes.value.find((item) => item.id === deviceId));
    return;
  }
  ElMessage.info("请点击 A 端设备；随时可以点“取消连线”。");
}

async function pickWizardDevice(node: TopologyNode | undefined): Promise<void> {
  if (!node) return;
  if (wizard.step === "aDevice") {
    wizard.aDeviceId = node.id;
    await openPortDialog(node.id, "a");
    return;
  }
  if (wizard.step === "bDevice") {
    if (node.id === wizard.aDeviceId) {
      ElMessage.warning("B 端不能选同一台设备。");
      return;
    }
    wizard.bDeviceId = node.id;
    await openPortDialog(node.id, "b");
  }
}

// ------------------------------------------------------------------ 端口弹窗

function resetPortForm(): void {
  portEditingId.value = "";
  Object.assign(portForm, {
    name: "",
    kind: "network",
    type: "",
    face: "front",
    rowIndex: 1,
    positionIndex: 1,
    direction: "bidi",
    speed: "",
    status: "unknown",
    ipAddress: "",
    vlan: "",
    notes: "",
  });
}

async function openPortDialog(deviceId: string, side: "" | "a" | "b" = ""): Promise<void> {
  const node = nodes.value.find((item) => item.id === deviceId);
  if (!node) return;
  portDialog.deviceId = deviceId;
  portDialog.side = side;
  portDialog.mode = "list";
  portDialog.open = true;
  resetPortForm();
  await ensureRackPorts(node.rackId);
}

function closePortDialog(): void {
  portDialog.open = false;
  if (wizard.step === "aDevice") resetWizard();
}

function choosePort(port: RackPort): void {
  if (port.cableId) {
    ElMessage.warning(`端口「${port.name}」已经连接，请先断开或换一个端口。`);
    return;
  }
  if (portDialog.side === "a") {
    wizard.aPortId = port.id;
    portDialog.open = false;
    wizard.step = "bDevice";
    ElMessage.info(`A 端已选：${portLabel(port.id)}，请点击 B 端设备。`);
    return;
  }
  if (portDialog.side === "b") {
    if (port.id === wizard.aPortId) {
      ElMessage.warning("两端不能是同一条端口。");
      return;
    }
    wizard.bPortId = port.id;
    portDialog.open = false;
    openCableDialog();
  }
}

function editPort(port: RackPort): void {
  portEditingId.value = port.id;
  Object.assign(portForm, {
    name: port.name,
    kind: port.kind,
    type: port.type,
    face: port.face,
    rowIndex: port.rowIndex,
    positionIndex: port.positionIndex,
    direction: port.direction || "bidi",
    speed: port.speed,
    status: port.status,
    ipAddress: port.ipAddress ?? "",
    vlan: port.vlan ?? "",
    notes: port.notes ?? "",
  });
  portDialog.mode = "manual";
}

/** 手工新增：清空表单并切到手工页签。 */
function startManualPort(): void {
  resetPortForm();
  portDialog.mode = "manual";
}

async function submitManualPort(): Promise<void> {
  const device = portDialogDevice.value;
  if (!device) return;
  if (!portForm.name.trim()) {
    ElMessage.warning("端口名称不能为空。");
    return;
  }
  portDialog.loading = true;
  try {
    if (portEditingId.value) {
      await updatePort(portEditingId.value, { ...portForm });
      ElMessage.success("端口已更新。");
    } else {
      await createPort(device.id, { ...portForm });
      ElMessage.success("端口已新增。");
    }
    resetPortForm();
    portDialog.mode = "list";
    await refreshAfterEdit(device.rackId);
  } catch (error) {
    ElMessage.error(`保存端口失败：${(error as Error).message}`);
  } finally {
    portDialog.loading = false;
  }
}

async function submitBatchPorts(): Promise<void> {
  const device = portDialogDevice.value;
  if (!device) return;
  if (!batchForm.pattern.includes("{n}")) {
    ElMessage.warning("端口名模板必须包含 {n} 占位符，例如 GE1/0/{n}。");
    return;
  }
  portDialog.loading = true;
  try {
    const result = await generatePlacementPorts(device.id, { ...batchForm });
    ElMessage.success(`批量生成完成：新增 ${result.created} 个，跳过 ${result.skipped} 个。`);
    portDialog.mode = "list";
    await refreshAfterEdit(device.rackId);
  } catch (error) {
    ElMessage.error(`批量生成失败：${(error as Error).message}`);
  } finally {
    portDialog.loading = false;
  }
}

async function submitModelPorts(): Promise<void> {
  const device = portDialogDevice.value;
  if (!device) return;
  if (modelForm.source === "template" && !modelForm.catalogId) {
    ElMessage.warning("请选择型号。");
    return;
  }
  if (modelForm.source === "device" && !modelForm.sourcePlacementId) {
    ElMessage.warning("请选择要复制端口配置的来源设备。");
    return;
  }
  portDialog.loading = true;
  try {
    const result =
      modelForm.source === "template"
        ? await importPortsFromTemplate(device.id, { catalogId: modelForm.catalogId })
        : await copyPortsFromPlacement(device.id, modelForm.sourcePlacementId);
    ElMessage.success(`生成端口完成：新增 ${result.created} 个，跳过 ${result.skipped} 个。`);
    portDialog.mode = "list";
    await refreshAfterEdit(device.rackId);
  } catch (error) {
    ElMessage.error(`生成端口失败：${(error as Error).message}`);
  } finally {
    portDialog.loading = false;
  }
}

async function deletePortRow(port: RackPort): Promise<void> {
  const device = portDialogDevice.value;
  const confirmed = await confirmAction(
    `删除端口「${port.name}」会同时删除它的链路，确认删除？`,
    { title: "删除端口", confirmText: "删除", danger: true },
  );
  if (!confirmed) return;
  try {
    const result = (await removePort(port.id, "拓扑图删除端口")) as { removedCables?: number };
    const removed = Number(result?.removedCables ?? 0);
    ElMessage.success(removed > 0 ? `端口已删除，同时移除 ${removed} 条链路。` : "端口已删除。");
    if (device) await refreshAfterEdit(device.rackId);
  } catch (error) {
    ElMessage.error(`删除端口失败：${(error as Error).message}`);
  }
}

// ------------------------------------------------------------------ 链路弹窗与属性

function openCableDialog(): void {
  Object.assign(cableForm, {
    medium: "cat6",
    lengthM: 3,
    label: "",
    status: "connected",
    notes: "",
  });
  cableDialog.open = true;
}

async function submitCable(): Promise<void> {
  if (!wizard.aPortId || !wizard.bPortId) return;
  cableDialog.saving = true;
  try {
    const aRack = rackIdOfPort(wizard.aPortId);
    const bRack = rackIdOfPort(wizard.bPortId);
    await createCable({
      aPortId: wizard.aPortId,
      bPortId: wizard.bPortId,
      medium: cableForm.medium,
      lengthM: cableForm.lengthM || undefined,
      label: cableForm.label,
      status: cableForm.status,
      notes: cableForm.notes,
    });
    ElMessage.success("链路已建立。");
    resetWizard();
    await refreshAfterEdit(aRack, bRack);
  } catch (error) {
    ElMessage.error(`建立链路失败：${(error as Error).message}`);
  } finally {
    cableDialog.saving = false;
  }
}

async function saveLink(): Promise<void> {
  const link = selectedLink.value;
  if (!link) return;
  linkSaving.value = true;
  try {
    await updateCable(link.id, {
      medium: linkForm.medium,
      status: linkForm.status,
      lengthM: linkForm.lengthM || undefined,
      label: linkForm.label,
      notes: linkForm.notes,
    });
    ElMessage.success("链路已更新。");
    await refreshAfterEdit(rackIdOfPort(link.aPortId), rackIdOfPort(link.bPortId));
  } catch (error) {
    ElMessage.error(`保存链路失败：${(error as Error).message}`);
  } finally {
    linkSaving.value = false;
  }
}

async function deleteLink(link: Cable): Promise<void> {
  const confirmed = await confirmAction(
    `删除链路「${link.aPlacementName}/${link.aPortName} ↔ ${link.bPlacementName}/${link.bPortName}」？`,
    { title: "删除链路", confirmText: "删除", danger: true },
  );
  if (!confirmed) return;
  try {
    const aRack = rackIdOfPort(link.aPortId);
    const bRack = rackIdOfPort(link.bPortId);
    await removeCable(link.id, "拓扑图删除链路");
    ElMessage.success("链路已删除。");
    selectedLinkId.value = "";
    await refreshAfterEdit(aRack, bRack);
  } catch (error) {
    ElMessage.error(`删除链路失败：${(error as Error).message}`);
  }
}

// ------------------------------------------------------------------ 布局与导出

async function savePositions(): Promise<void> {
  const payload: TopologyPosition[] = placed.value.map((item) => ({
    nodeId: item.node.id,
    x: item.x,
    y: item.y,
  }));
  if (!payload.length) return;
  try {
    const result = await saveTopologyPositions(payload);
    ElMessage.success(`已保存 ${result.saved} 个节点坐标。`);
    dirty.value = false;
    await loadData();
  } catch (error) {
    ElMessage.error(`保存布局失败：${(error as Error).message}`);
  }
}

function resetLayout(): void {
  if (Object.keys(localPositions.value).length) pushHistory(clonePositions());
  localPositions.value = {};
  dirty.value = false;
  ElMessage.info("已按端口连接重新分层，未保存的拖动已清除。");
}

function buildExportSvg(): string {
  const nodesMarkup = placed.value
    .map(
      (item) => `<g transform="translate(${item.x},${item.y})">
        <rect width="${NODE_W}" height="${NODE_H}" fill="#ffffff" stroke="${
          item.node.id === selectedId.value ? "#409eff" : "#8a8a8a"
        }"></rect>
        <text x="10" y="20" font-size="12" fill="#111111">${escapeXml(item.node.name)}</text>
        <text x="10" y="35" font-size="10" fill="#666666">${escapeXml(
          `${item.node.brandModel} · ${CATEGORY_LABELS[item.node.category] ?? item.node.category}`,
        )}</text>
      </g>`,
    )
    .join("");
  const linksMarkup = visibleLinks.value
    .map((link) => {
      const path = linkPath(link);
      if (!path) return "";
      const point = linkLabelPoint(link);
      const label = showLabels.value
        ? `<text x="${point.x}" y="${point.y}" font-size="9" fill="#666666">${escapeXml(
            linkLabel(link),
          )}</text>`
        : "";
      return `<path d="${path}" fill="none" stroke="${mediumColor(
        link.medium,
      )}" stroke-width="1.5"></path>${label}`;
    })
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${canvas.value.width} ${
    canvas.value.height
  }" width="${canvas.value.width}" height="${canvas.value.height}">
    <rect width="100%" height="100%" fill="#ffffff"></rect>${linksMarkup}${nodesMarkup}</svg>`;
}

function escapeXml(value: string): string {
  return value.replace(/[<>&"]/g, (char) =>
    char === "<" ? "&lt;" : char === ">" ? "&gt;" : char === "&" ? "&amp;" : "&quot;",
  );
}

function downloadBlob(blob: Blob, fileName: string): void {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(link.href);
}

function downloadCsv(fileName: string, header: string[], rows: string[][]): void {
  const escape = (value: string) =>
    /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
  const content = [header, ...rows].map((row) => row.map(escape).join(",")).join("\r\n");
  downloadBlob(new Blob([`\ufeff${content}\r\n`], { type: "text/csv;charset=utf-8" }), fileName);
}

function exportSvg(): void {
  if (!placed.value.length) {
    ElMessage.warning("当前筛选条件下没有节点。");
    return;
  }
  downloadBlob(new Blob([buildExportSvg()], { type: "image/svg+xml" }), "网络拓扑.svg");
}

function exportPng(): void {
  if (!placed.value.length) return;
  const svg = buildExportSvg();
  const image = new Image();
  image.onload = () => {
    const canvasEl = document.createElement("canvas");
    canvasEl.width = canvas.value.width * 2;
    canvasEl.height = canvas.value.height * 2;
    const context = canvasEl.getContext("2d");
    if (!context) return;
    context.scale(2, 2);
    context.drawImage(image, 0, 0);
    canvasEl.toBlob((blob) => {
      if (blob) downloadBlob(blob, "网络拓扑.png");
    }, "image/png");
  };
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** 链路清单：A/B 两端设备与端口、介质、长度、标签、状态，便于交付布线资料。 */
function exportLinkList(): void {
  if (!visibleLinks.value.length) {
    ElMessage.warning("当前没有可导出的链路。");
    return;
  }
  const rows = visibleLinks.value.map((link, index) => [
    String(index + 1),
    link.aPlacementName,
    link.aPortName,
    link.bPlacementName,
    link.bPortName,
    mediumLabel(link.medium),
    link.lengthM === null || link.lengthM === undefined ? "" : String(link.lengthM),
    link.label,
    CABLE_STATUS_OPTIONS.find((item) => item.value === link.status)?.label ?? link.status,
    link.notes,
  ]);
  downloadCsv(
    "链路清单.csv",
    ["序号", "A 端设备", "A 端端口", "B 端设备", "B 端端口", "介质", "长度(米)", "标签", "状态", "备注"],
    rows,
  );
}

/** 节点清单：设备、型号、位置、端口使用与层级。 */
function exportNodeList(): void {
  if (!placed.value.length) {
    ElMessage.warning("当前没有可导出的节点。");
    return;
  }
  const rows = placed.value.map((item, index) => [
    String(index + 1),
    item.node.name,
    item.node.brandModel,
    CATEGORY_LABELS[item.node.category] ?? item.node.category,
    item.node.siteName,
    item.node.rackName,
    `${item.node.positionU}U`,
    String(item.node.portCount),
    String(item.node.linkedPortCount),
    String(item.level + 1),
  ]);
  downloadCsv(
    "拓扑节点清单.csv",
    ["序号", "设备", "型号", "类别", "机房", "机柜", "起始 U 位", "端口数", "已连端口", "层级"],
    rows,
  );
}

function printTopology(): void {
  const win = window.open("", "_blank");
  if (!win) {
    ElMessage.warning("浏览器拦截了打印窗口，请允许弹出窗口后重试。");
    return;
  }
  win.document.write(
    `<html><head><meta charset="utf-8" /><title>网络拓扑</title>
      <style>body{margin:16px;font-family:"Microsoft YaHei",Arial,sans-serif}
      h1{font-size:16px;margin:0 0 8px}p{color:#666;font-size:12px;margin:0 0 12px}</style></head>
      <body><h1>网络拓扑</h1><p>节点 ${placed.value.length} 个，链路 ${
        visibleLinks.value.length
      } 条</p>${buildExportSvg()}</body></html>`,
  );
  win.document.close();
  win.focus();
  win.print();
}

onMounted(async () => {
  window.addEventListener("keydown", onShortcut);
  try {
    const payload = await listRacks();
    racks.value = payload.racks;
  } catch {
    racks.value = [];
  }
  if (canUpdate.value) {
    try {
      const payload = await listDeviceTypes();
      deviceTypes.value = payload.deviceTypes;
    } catch {
      deviceTypes.value = [];
    }
  }
  await loadData();
});

onUnmounted(() => {
  window.removeEventListener("keydown", onShortcut);
  window.removeEventListener("pointermove", onPointerMove);
});
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div class="topo-toolbar">
        <el-select v-model="siteId" placeholder="全部机房" clearable style="width: 180px" @change="loadData">
          <el-option v-for="item in sites" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
        <el-select v-model="rackId" placeholder="全部机柜" clearable style="width: 220px" @change="loadData">
          <el-option
            v-for="item in rackOptions"
            :key="item.id"
            :value="item.id"
            :label="`${item.siteName} / ${item.name}`"
          />
        </el-select>
        <el-switch v-model="onlyLinked" active-text="只看有链路的设备" @change="loadData" />
        <el-switch v-model="showLabels" active-text="链路标签" />
        <el-switch v-model="focusSelected" active-text="只看选中设备相关" />
        <el-select v-model="routeMode" style="width: 124px">
          <el-option value="orthogonal" label="正交走线" />
          <el-option value="direct" label="直线走线" />
        </el-select>
        <el-switch v-model="snapGrid" active-text="网格吸附" />
        <div class="spacer" />
        <el-tag v-if="dirty" type="warning" effect="plain" size="small">有未保存的拖动</el-tag>
        <el-button
          v-if="canUpdate"
          size="small"
          type="primary"
          :disabled="!!wizard.step"
          @click="startConnect()"
        >
          新建链路
        </el-button>
        <el-button size="small" @click="resetLayout">{{ dirty ? "丢弃未保存" : "重新布局" }}</el-button>
        <el-button
          v-if="canUpdate"
          size="small"
          :disabled="!undoStack.length"
          title="撤销布局拖动（Ctrl+Z）"
          @click="undoLayout"
        >
          撤销
        </el-button>
        <el-button
          v-if="canUpdate"
          size="small"
          :disabled="!redoStack.length"
          title="重做布局拖动（Ctrl+Y）"
          @click="redoLayout"
        >
          重做
        </el-button>
        <el-button v-if="canUpdate" size="small" :disabled="!dirty" @click="savePositions">
          保存布局
        </el-button>
        <el-button size="small" @click="exportSvg">导出 SVG</el-button>
        <el-button size="small" @click="exportPng">导出 PNG</el-button>
        <el-button size="small" @click="exportLinkList">导出链路清单</el-button>
        <el-button size="small" @click="exportNodeList">导出节点清单</el-button>
        <el-button size="small" @click="printTopology">打印</el-button>
      </div>
    </template>

    <div v-if="!nodes.length" class="empty-hint">
      当前筛选条件下没有设备。请先在“机柜视图”上架设备，再回到这里给设备加端口、连链路。
    </div>
    <div v-else class="topo-grid">
      <section>
        <div v-if="wizard.step" class="wizard-bar">
          <el-tag type="primary" effect="plain" size="small">{{ wizardHint }}</el-tag>
          <span v-if="wizardSummary" class="wizard-summary">{{ wizardSummary }}</span>
          <el-button size="small" text @click="resetWizard">取消连线</el-button>
        </div>
        <svg
          class="topology-canvas"
          :viewBox="`0 0 ${canvas.width} ${canvas.height}`"
          :style="{ minHeight: `${Math.min(680, canvas.height)}px` }"
          role="img"
          aria-label="由端口连接自动生成的网络拓扑图"
          @pointerdown="onCanvasPointerDown"
        >
          <rect
            v-if="marquee"
            class="marquee"
            :x="Math.min(marquee.x1, marquee.x2)"
            :y="Math.min(marquee.y1, marquee.y2)"
            :width="Math.abs(marquee.x2 - marquee.x1)"
            :height="Math.abs(marquee.y2 - marquee.y1)"
          />
          <text
            v-for="item in levelLabels"
            :key="`tier-${item.level}`"
            :x="MARGIN.left + item.level * LEVEL_GAP - 60"
            y="30"
            class="tier-label"
          >
            {{ item.label }}
          </text>
          <g v-for="link in visibleLinks" :key="`link-${link.id}`">
            <path
              :d="linkPath(link)"
              class="link"
              :class="{ highlight: isHighlighted(link), picked: link.id === selectedLinkId }"
              :stroke="mediumColor(link.medium)"
              @pointerdown.stop="selectLink(link)"
            />
            <text
              v-if="showLabels"
              :x="linkLabelPoint(link).x"
              :y="linkLabelPoint(link).y"
              class="link-label"
            >
              {{ linkLabel(link) }}
            </text>
          </g>
          <g
            v-for="item in placed"
            :key="item.node.id"
            :data-node-id="item.node.id"
            class="node"
            :class="{
              selected: item.node.id === selectedId,
              picked: item.node.id === wizard.aDeviceId || item.node.id === wizard.bDeviceId,
              grouped: groupIds.length > 1 && groupIds.includes(item.node.id),
              dropTarget: connectDrag?.overId === item.node.id,
            }"
            :transform="`translate(${item.x},${item.y})`"
            @pointerdown="onNodePointerDown($event, item)"
          >
            <rect :width="NODE_W" :height="NODE_H" rx="3" />
            <text x="10" y="20">{{ item.node.name }}</text>
            <text x="10" y="35" class="sub">
              {{ CATEGORY_LABELS[item.node.category] ?? item.node.category }} ·
              {{ item.node.linkedPortCount }}/{{ item.node.portCount }} 端口
            </text>
            <circle
              v-if="canUpdate"
              class="connect-handle"
              :cx="NODE_W - 8"
              :cy="NODE_H / 2"
              r="6"
              @pointerdown="onConnectHandleDown($event, item)"
            >
              <title>拖到另一台设备建立链路</title>
            </circle>
          </g>
          <line
            v-if="connectDrag"
            class="rubber-band"
            :x1="positionOf(connectDrag.fromId).x + NODE_W"
            :y1="positionOf(connectDrag.fromId).y + NODE_H / 2"
            :x2="connectDrag.overId ? positionOf(connectDrag.overId).x : connectDrag.x"
            :y2="connectDrag.overId ? positionOf(connectDrag.overId).y + NODE_H / 2 : connectDrag.y"
          />
        </svg>
      </section>

      <aside>
        <el-card v-if="selectedLink" shadow="never">
          <template #header><strong>链路属性</strong></template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="A 端">
              {{ selectedLink.aPlacementName }} / {{ selectedLink.aPortName }}
            </el-descriptions-item>
            <el-descriptions-item label="B 端">
              {{ selectedLink.bPlacementName }} / {{ selectedLink.bPortName }}
            </el-descriptions-item>
          </el-descriptions>
          <el-form label-position="top" size="small" class="oa-mt-3">
            <el-form-item label="介质">
              <el-select v-model="linkForm.medium" :disabled="!canUpdate" class="oa-full-width">
                <el-option
                  v-for="item in MEDIUM_OPTIONS"
                  :key="item.value"
                  :value="item.value"
                  :label="item.label"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="长度（米）">
              <el-input-number
                v-model="linkForm.lengthM"
                :disabled="!canUpdate"
                :min="0"
                :max="10000"
                :step="0.5"
              />
            </el-form-item>
            <el-form-item label="标签">
              <el-input
                v-model="linkForm.label"
                :disabled="!canUpdate"
                placeholder="例如：SW-A01-GE24 → SRV-A01-NIC1"
              />
            </el-form-item>
            <el-form-item label="状态">
              <el-select v-model="linkForm.status" :disabled="!canUpdate" class="oa-full-width">
                <el-option
                  v-for="item in CABLE_STATUS_OPTIONS"
                  :key="item.value"
                  :value="item.value"
                  :label="item.label"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="linkForm.notes" :disabled="!canUpdate" type="textarea" :rows="2" />
            </el-form-item>
          </el-form>
          <div v-if="canUpdate" class="panel-actions">
            <el-button size="small" type="primary" :loading="linkSaving" @click="saveLink">
              保存链路
            </el-button>
            <el-button size="small" type="danger" plain @click="deleteLink(selectedLink)">
              删除链路
            </el-button>
          </div>
        </el-card>

        <el-card shadow="never">
          <template #header><strong>节点详情</strong></template>
          <el-descriptions v-if="selected" :column="1" size="small" border>
            <el-descriptions-item label="设备">{{ selected.name }}</el-descriptions-item>
            <el-descriptions-item label="型号">{{ selected.brandModel || "—" }}</el-descriptions-item>
            <el-descriptions-item label="位置">
              {{ selected.siteName }} / {{ selected.rackName }} / 第 {{ selected.positionU }}U
            </el-descriptions-item>
            <el-descriptions-item label="端口">
              已连 {{ selected.linkedPortCount }} / 共 {{ selected.portCount }}
            </el-descriptions-item>
            <el-descriptions-item label="层级">
              第 {{ (levels.get(selected.id) ?? 0) + 1 }} 层
            </el-descriptions-item>
          </el-descriptions>
          <div v-else class="empty-hint">
            点击拓扑里的节点查看详情；拖动节点可微调布局，点击连线可改链路属性。
          </div>

          <div v-if="selected && canUpdate" class="panel-actions">
            <el-button size="small" @click="openPortDialog(selected.id)">端口管理</el-button>
            <el-button size="small" type="primary" @click="startConnect(selected.id)">
              连接其他设备
            </el-button>
          </div>

          <el-table v-if="selectedLinks.length" :data="selectedLinks" size="small" class="oa-mt-3">
            <el-table-column label="链路" min-width="150">
              <template #default="{ row }">
                {{ row.label || `${row.aPortName} ↔ ${row.bPortName}` }}
              </template>
            </el-table-column>
            <el-table-column label="对端" min-width="150">
              <template #default="{ row }">
                {{ row.aPlacementId === selected?.id ? row.bPlacementName : row.aPlacementName }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="selectLink(row)">属性</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </aside>
    </div>

    <FormDialog v-model="portDialog.open" :title="portDialogTitle" size="lg">
      <template #footer>
        <el-button @click="closePortDialog">关闭</el-button>
      </template>
      <div class="port-tabs">
        <el-button-group>
          <el-button
            size="small"
            :type="portDialog.mode === 'list' ? 'primary' : 'default'"
            @click="portDialog.mode = 'list'"
          >
            端口列表
          </el-button>
          <el-button
            size="small"
            :type="portDialog.mode === 'model' ? 'primary' : 'default'"
            @click="portDialog.mode = 'model'"
          >
            按型号生成
          </el-button>
          <el-button
            size="small"
            :type="portDialog.mode === 'batch' ? 'primary' : 'default'"
            @click="portDialog.mode = 'batch'"
          >
            批量生成
          </el-button>
          <el-button
            size="small"
            :type="portDialog.mode === 'manual' ? 'primary' : 'default'"
            @click="startManualPort()"
          >
            手工添加
          </el-button>
        </el-button-group>
      </div>

      <template v-if="portDialog.mode === 'list'">
        <el-table :data="portDialogPorts" size="small" max-height="360">
          <el-table-column label="端口" min-width="110">
            <template #default="{ row }">{{ row.name }}</template>
          </el-table-column>
          <el-table-column label="类型" width="80">
            <template #default="{ row }">{{ KIND_LABELS[row.kind] ?? row.kind }}</template>
          </el-table-column>
          <el-table-column label="速率" width="80">
            <template #default="{ row }">{{ row.speed || "—" }}</template>
          </el-table-column>
          <el-table-column label="IP / VLAN" min-width="130">
            <template #default="{ row }">
              {{ [row.ipAddress, row.vlan].filter(Boolean).join(" / ") || "—" }}
            </template>
          </el-table-column>
          <el-table-column label="对端" min-width="150">
            <template #default="{ row }">
              <span v-if="row.cableId">{{ row.peerPlacementName }} / {{ row.peerPortName }}</span>
              <el-tag v-else size="small" type="success" effect="plain">空闲</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button
                v-if="portDialog.side"
                link
                type="primary"
                size="small"
                :disabled="!!row.cableId"
                @click="choosePort(row)"
              >
                选择
              </el-button>
              <el-button v-if="canUpdate" link size="small" @click="editPort(row)">编辑</el-button>
              <el-button v-if="canUpdate" link type="danger" size="small" @click="deletePortRow(row)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="!portDialogPorts.length" class="empty-hint">
          这台设备还没有端口，用上面的「按型号生成 / 批量生成 / 手工添加」建端口。
        </div>
      </template>

      <el-form v-else-if="portDialog.mode === 'model'" label-position="top" size="small">
        <el-form-item label="端口来源">
          <el-radio-group v-model="modelForm.source">
            <el-radio value="template">型号库模板</el-radio>
            <el-radio value="device">已有设备的端口配置</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="modelForm.source === 'template'" label="型号">
          <el-select v-model="modelForm.catalogId" filterable class="oa-full-width" placeholder="选择型号">
            <el-option
              v-for="item in deviceTypes"
              :key="item.id"
              :value="item.id"
              :label="`${item.manufacturer} ${item.model}（${item.portCount} 个端口）`"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="来源设备">
          <el-select
            v-model="modelForm.sourcePlacementId"
            filterable
            class="oa-full-width"
            placeholder="选择已经配好端口的设备"
          >
            <el-option
              v-for="item in copySourceOptions"
              :key="item.value"
              :value="item.value"
              :label="item.label"
            />
          </el-select>
        </el-form-item>
        <div class="oa-hint">
          按型号生成使用型号库的端口模板；按设备生成会复制对方全部端口（同名端口自动跳过）。
        </div>
        <el-button type="primary" size="small" :loading="portDialog.loading" @click="submitModelPorts">
          生成端口
        </el-button>
      </el-form>

      <el-form v-else-if="portDialog.mode === 'batch'" label-position="top" size="small">
        <el-form-item label="端口名模板">
          <el-input v-model="batchForm.pattern" placeholder="GE1/0/{n}" />
          <div class="oa-hint">用大括号里的 n 作序号占位符，例如 GE1/0/&#123;n&#125;、XGE1/0/&#123;n&#125;。</div>
        </el-form-item>
        <el-form-item label="序号范围 / 步长 / 每行">
          <el-input-number v-model="batchForm.start" :min="0" :max="9999" style="width: 110px" />
          <el-input-number v-model="batchForm.end" :min="1" :max="9999" style="width: 110px; margin: 0 8px" />
          <el-input-number v-model="batchForm.step" :min="1" :max="64" style="width: 100px" />
          <el-input-number v-model="batchForm.perRow" :min="1" :max="64" style="width: 100px; margin-left: 8px" />
        </el-form-item>
        <el-form-item label="类型 / 面板 / 速率">
          <el-select v-model="batchForm.kind" style="width: 120px">
            <el-option v-for="(label, value) in KIND_LABELS" :key="value" :value="value" :label="label" />
          </el-select>
          <el-select v-model="batchForm.face" style="width: 120px; margin-left: 8px">
            <el-option value="front" label="前面板" />
            <el-option value="rear" label="后面板" />
          </el-select>
          <el-input
            v-model="batchForm.speed"
            placeholder="例如 1000M / 10G"
            style="width: 160px; margin-left: 8px"
          />
        </el-form-item>
        <div class="oa-hint">一次最多生成 256 个端口，已存在的同名端口会跳过。</div>
        <el-button type="primary" size="small" :loading="portDialog.loading" @click="submitBatchPorts">
          批量生成
        </el-button>
      </el-form>

      <el-form v-else label-position="top" size="small">
        <el-form-item :label="portEditingId ? '编辑端口' : '新增端口'">
          <el-input v-model="portForm.name" placeholder="例如 GE24" />
        </el-form-item>
        <el-form-item label="类型 / 类型标识">
          <el-select v-model="portForm.kind" style="width: 120px">
            <el-option v-for="(label, value) in KIND_LABELS" :key="value" :value="value" :label="label" />
          </el-select>
          <el-input
            v-model="portForm.type"
            placeholder="例如 1000base-t"
            style="width: 200px; margin-left: 8px"
          />
        </el-form-item>
        <el-form-item label="面板 / 行 / 位">
          <el-select v-model="portForm.face" style="width: 110px">
            <el-option value="front" label="前面板" />
            <el-option value="rear" label="后面板" />
          </el-select>
          <el-input-number v-model="portForm.rowIndex" :min="1" :max="20" style="margin: 0 8px" />
          <el-input-number v-model="portForm.positionIndex" :min="1" :max="48" />
        </el-form-item>
        <el-form-item label="状态 / 速率">
          <el-select v-model="portForm.status" style="width: 120px">
            <el-option
              v-for="item in PORT_STATUS_OPTIONS"
              :key="item.value"
              :value="item.value"
              :label="item.label"
            />
          </el-select>
          <el-input
            v-model="portForm.speed"
            placeholder="例如 1000M"
            style="width: 160px; margin-left: 8px"
          />
        </el-form-item>
        <el-form-item label="IP / 掩码 · VLAN（可选）">
          <el-input v-model="portForm.ipAddress" placeholder="例如 192.0.2.10/24" style="width: 220px" />
          <el-input
            v-model="portForm.vlan"
            placeholder="例如 10 / 10,20"
            style="width: 160px; margin-left: 8px"
          />
        </el-form-item>
        <el-form-item label="备注（可选）">
          <el-input v-model="portForm.notes" type="textarea" :rows="2" />
        </el-form-item>
        <div class="oa-hint">除端口名称外都是可选项；IP / VLAN / 备注可以后补，不填也能先连线。</div>
        <el-button type="primary" size="small" :loading="portDialog.loading" @click="submitManualPort">
          {{ portEditingId ? "保存端口" : "新增端口" }}
        </el-button>
      </el-form>
    </FormDialog>

    <FormDialog
      v-model="connectDialog.open"
      title="连接两台设备"
      size="sm"
      confirm-text="建立链路"
      :loading="connectDialog.saving"
      @confirm="submitConnectDialog"
    >
      <el-form label-position="top" size="small">
        <el-form-item
          :label="`A 端（${nodes.find((item) => item.id === connectDialog.aDeviceId)?.name ?? ''}）`"
        >
          <el-select v-model="connectDialog.aPortId" filterable class="oa-full-width" placeholder="选择空闲端口">
            <el-option
              v-for="port in freePorts(connectDialog.aDeviceId)"
              :key="port.id"
              :value="port.id"
              :label="`${port.name}（${KIND_LABELS[port.kind] ?? port.kind}）`"
            />
          </el-select>
        </el-form-item>
        <el-form-item
          :label="`B 端（${nodes.find((item) => item.id === connectDialog.bDeviceId)?.name ?? ''}）`"
        >
          <el-select v-model="connectDialog.bPortId" filterable class="oa-full-width" placeholder="选择空闲端口">
            <el-option
              v-for="port in freePorts(connectDialog.bDeviceId)"
              :key="port.id"
              :value="port.id"
              :label="`${port.name}（${KIND_LABELS[port.kind] ?? port.kind}）`"
            />
          </el-select>
        </el-form-item>
        <div
          v-if="!freePorts(connectDialog.aDeviceId).length || !freePorts(connectDialog.bDeviceId).length"
          class="oa-hint"
        >
          有一端没有空闲端口：先选中该设备用「端口管理」新建端口，或断开它已连接的链路。
        </div>
        <el-form-item label="介质">
          <el-select v-model="cableForm.medium" class="oa-full-width">
            <el-option
              v-for="item in MEDIUM_OPTIONS"
              :key="item.value"
              :value="item.value"
              :label="item.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="长度（米）">
          <el-input-number v-model="cableForm.lengthM" :min="0.5" :max="10000" :step="0.5" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="cableForm.label" placeholder="例如：SW-A01-GE24 → SRV-A01-NIC1" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="cableForm.status" class="oa-full-width">
            <el-option
              v-for="item in CABLE_STATUS_OPTIONS"
              :key="item.value"
              :value="item.value"
              :label="item.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="cableForm.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
    </FormDialog>

    <FormDialog
      v-model="cableDialog.open"
      title="建立链路"
      size="sm"
      confirm-text="建立链路"
      :loading="cableDialog.saving"
      @confirm="submitCable"
    >
      <el-form label-position="top" size="small">
        <el-form-item label="A 端">
          <el-input :model-value="portLabel(wizard.aPortId)" disabled />
        </el-form-item>
        <el-form-item label="B 端">
          <el-input :model-value="portLabel(wizard.bPortId)" disabled />
        </el-form-item>
        <el-form-item label="介质">
          <el-select v-model="cableForm.medium" class="oa-full-width">
            <el-option
              v-for="item in MEDIUM_OPTIONS"
              :key="item.value"
              :value="item.value"
              :label="item.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="长度（米）">
          <el-input-number v-model="cableForm.lengthM" :min="0.5" :max="10000" :step="0.5" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="cableForm.label" placeholder="例如：SW-A01-GE24 → SRV-A01-NIC1" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="cableForm.status" class="oa-full-width">
            <el-option
              v-for="item in CABLE_STATUS_OPTIONS"
              :key="item.value"
              :value="item.value"
              :label="item.label"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="cableForm.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
    </FormDialog>
  </el-card>
</template>

<style scoped>
.topo-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.spacer {
  flex: 1;
}
.topo-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 340px);
  gap: 16px;
  align-items: start;
}
.wizard-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.wizard-summary {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.topology-canvas {
  width: 100%;
  height: auto;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  touch-action: none;
}
.tier-label {
  fill: var(--el-text-color-secondary);
  font-size: 11px;
}
.link {
  fill: none;
  stroke-width: 1.5;
  cursor: pointer;
}
.link.highlight {
  stroke-width: 3;
}
.link.picked {
  stroke-dasharray: 6 3;
}
.marquee {
  fill: var(--el-color-primary-light-8);
  stroke: var(--el-color-primary);
  stroke-dasharray: 4 3;
  pointer-events: none;
}
.rubber-band {
  stroke: var(--el-color-primary);
  stroke-width: 2;
  stroke-dasharray: 6 4;
  pointer-events: none;
}
.connect-handle {
  fill: var(--el-color-primary-light-3);
  stroke: var(--el-color-primary);
  cursor: crosshair;
  opacity: 0.35;
}
.node:hover .connect-handle,
.node.selected .connect-handle {
  opacity: 1;
}
.link-label {
  fill: var(--el-text-color-secondary);
  font-size: 10px;
}
.node {
  cursor: grab;
}
.node rect {
  fill: var(--el-bg-color);
  stroke: var(--el-border-color-darker);
}
.node.selected rect {
  stroke: var(--el-color-primary);
  stroke-width: 2;
}
.node.picked rect {
  stroke: var(--el-color-warning);
  stroke-width: 2;
}
.node.grouped rect {
  stroke: var(--el-color-primary-light-3);
  stroke-width: 2;
  stroke-dasharray: 5 3;
}
.node.dropTarget rect {
  stroke: var(--el-color-success);
  stroke-width: 3;
}
.node text {
  fill: var(--el-text-color-primary);
  font-size: 12px;
}
.node text.sub {
  fill: var(--el-text-color-secondary);
  font-size: 10px;
}
.port-tabs {
  margin-bottom: 12px;
}
.panel-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.empty-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
@media (max-width: 1200px) {
  .topo-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
