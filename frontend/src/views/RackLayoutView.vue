<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  availableDevices,
  getRack,
  listRacks,
  placeDevice,
  removePlacement,
  updatePlacement,
  type Placement,
  type RackPaletteDevice,
  type RackDetail,
  type RackSummary,
} from "../api/datacenter";
import { RACK_CATEGORY_LABELS as CATEGORY_LABELS, rackCategoryLabel, statusLabel } from "../labels";
import { hasPermission } from "../session";

const router = useRouter();

const FACE_LABELS: Record<string, string> = { front: "前面板", rear: "后面板", both: "整机深度" };

interface ArmedDevice {
  key: string;
  sourceKind: "datacenter";
  datacenterDeviceId: string;
  name: string;
  brandModel: string;
  category: string;
  uHeight: number;
}

interface PaletteRow {
  key: string;
  sourceKind: "datacenter";
  datacenterDeviceId: string;
  name: string;
  brandModel: string;
  category: string;
  uHeight: number;
  note: string;
}

const loading = ref(false);
const viewMode = ref<"single" | "side">("single");
const sideRacks = ref<RackDetail[]>([]);
const racks = ref<RackSummary[]>([]);
const rack = ref<RackDetail | null>(null);
const selectedId = ref("");
const face = ref<"front" | "rear">("front");
const showLabels = ref(true);
const rowHeight = ref(22);
const paletteKeyword = ref("");
const palette = ref<{ devices: RackPaletteDevice[] }>({ devices: [] });
const armed = ref<ArmedDevice | null>(null);
const dragging = ref<{ id: string; startY: number; candidate: number; moved: boolean } | null>(null);
const form = ref<Record<string, unknown>>({});

const canCreate = computed(() => hasPermission("rack_layout", "create"));
const canUpdate = computed(() => hasPermission("rack_layout", "update"));
const canDelete = computed(() => hasPermission("rack_layout", "delete"));
const height = computed(() => Number(rack.value?.heightU ?? 42));
const placements = computed<Placement[]>(() => rack.value?.placements ?? []);
const selected = computed<Placement | null>(
  () => placements.value.find((item) => item.id === selectedId.value) ?? null,
);
const occupiedUnits = computed(() => {
  const map = new Map<number, Placement>();
  placements.value.forEach((item) => {
    for (let unit = item.positionU; unit < item.positionU + item.uHeight; unit += 1) {
      map.set(unit, item);
    }
  });
  return map;
});
const unitRows = computed(() =>
  Array.from({ length: height.value }, (_, index) => height.value - index),
);
const usedUnits = computed(() => occupiedUnits.value.size);
const paletteRows = computed<PaletteRow[]>(() => {
  const keyword = paletteKeyword.value.trim().toLowerCase();
  const rows: PaletteRow[] = palette.value.devices.map((item) => ({
    key: `device:${item.deviceId}`,
    sourceKind: "datacenter",
    datacenterDeviceId: item.deviceId,
    name: item.name,
    brandModel: item.brandModel,
    category: item.category,
    uHeight: item.uHeight || 1,
    note: `${item.code} ｜ ${rackCategoryLabel(item.category)}${
      item.serialNumber ? ` ｜ SN ${item.serialNumber}` : ""
    }`,
  }));
  if (!keyword) return rows;
  return rows.filter((row) => `${row.name} ${row.brandModel}`.toLowerCase().includes(keyword));
});

function deviceTop(placement: Placement): number {
  return (height.value - (placement.positionU + placement.uHeight - 1)) * rowHeight.value + 1;
}

function deviceTopOf(rackHeight: number, placement: Placement): number {
  return (rackHeight - (placement.positionU + placement.uHeight - 1)) * rowHeight.value + 1;
}

function unitRowsOf(rackHeight: number): number[] {
  return Array.from({ length: rackHeight }, (_, index) => rackHeight - index);
}

/** 并排视图：同机房的机柜各占一列，只读显示，点设备回到单柜编辑。 */
async function loadSideBySide(): Promise<void> {
  const siteId = rack.value?.siteId ?? "";
  const list = racks.value.filter((item) => !siteId || item.siteId === siteId);
  loading.value = true;
  try {
    sideRacks.value = await Promise.all(
      list.map(async (item) => (await getRack(item.id)).rack),
    );
  } catch (error) {
    ElMessage.error(`并排视图加载失败：${(error as Error).message}`);
  } finally {
    loading.value = false;
  }
}

function openInSingleView(rackId: string, placementId: string): void {
  viewMode.value = "single";
  selectedId.value = placementId;
  void loadRack(rackId);
}

function deviceHeight(placement: Placement): number {
  return placement.uHeight * rowHeight.value - 2;
}

function slotTop(unit: number): number {
  return (height.value - unit) * rowHeight.value + 1;
}

function faceVisible(placement: Placement): boolean {
  if (face.value === "front" && placement.face === "rear") return false;
  return true;
}

async function loadRacks(): Promise<void> {
  loading.value = true;
  try {
    const payload = await listRacks();
    racks.value = payload.racks;
    const current = racks.value.find((item) => item.id === selectedId.value) ?? racks.value[0];
    if (current) {
      selectedId.value = current.id;
      await loadRack(current.id);
    } else {
      rack.value = null;
    }
  } catch (error) {
    ElMessage.error(`机柜列表加载失败：${(error as Error).message}`);
  } finally {
    loading.value = false;
  }
}

async function loadRack(rackId: string): Promise<void> {
  const payload = await getRack(rackId);
  rack.value = payload.rack;
  syncForm(payload.rack.placements.find((item) => item.id === selectedId.value) ?? null);
}

async function loadPalette(keyword = ""): Promise<void> {
  try {
    palette.value = await availableDevices(keyword);
  } catch (error) {
    ElMessage.error(`未上架设备加载失败：${(error as Error).message}`);
  }
}

function syncForm(placement: Placement | null): void {
  form.value = placement
    ? {
        displayName: placement.name,
        brandModel: placement.brandModel,
        category: placement.category,
        positionU: placement.positionU,
        uHeight: placement.uHeight,
        face: placement.face,
        notes: placement.notes ?? "",
      }
    : {};
}

function selectPlacement(placement: Placement): void {
  selectedId.value = placement.id;
  syncForm(placement);
}

function armDevice(row: (typeof paletteRows.value)[number]): void {
  armed.value = {
    key: row.key,
    sourceKind: row.sourceKind,
    datacenterDeviceId: row.datacenterDeviceId,
    name: row.name,
    brandModel: row.brandModel,
    category: row.category,
    uHeight: row.uHeight,
  };
  ElMessage.info(`已选中「${row.name}」，点击机柜空位即可上架。`);
}

async function placeAt(unit: number): Promise<void> {
  if (!armed.value || !rack.value) {
    ElMessage.warning("先在右侧未上架设备里选一台设备。");
    return;
  }
  try {
    await placeDevice(rack.value.id, {
      sourceKind: armed.value.sourceKind,
      datacenterDeviceId: armed.value.datacenterDeviceId,
      displayName: armed.value.name,
      brandModel: armed.value.brandModel,
      category: armed.value.category,
      positionU: unit,
      uHeight: armed.value.uHeight,
      face: "front",
    });
    ElMessage.success(`已上架到 U${unit}。`);
    armed.value = null;
    await loadRack(rack.value.id);
    await loadPalette(paletteKeyword.value);
  } catch (error) {
    ElMessage.error(`上架失败：${(error as Error).message}`);
  }
}

async function savePlacement(): Promise<void> {
  const placement = selected.value;
  if (!placement || !rack.value) return;
  try {
    await updatePlacement(placement.id, { rackId: rack.value.id, ...form.value });
    ElMessage.success("机柜位置已保存。");
    await loadRack(rack.value.id);
  } catch (error) {
    ElMessage.error(`保存失败：${(error as Error).message}`);
    await loadRack(rack.value.id);
  }
}

async function unlinkPlacement(): Promise<void> {
  const placement = selected.value;
  if (!placement || !rack.value) return;
  try {
    const { value } = await ElMessageBox.prompt(
      `下架「${placement.name}」的原因（会写入操作日志）`,
      "下架设备",
      { confirmButtonText: "确认下架", cancelButtonText: "取消", inputPlaceholder: "例如：搬迁到 A 列 2 号柜" },
    );
    await removePlacement(placement.id, String(value ?? ""));
    ElMessage.success("设备已下架。");
    selectedId.value = "";
    await loadRack(rack.value.id);
    await loadPalette(paletteKeyword.value);
  } catch (error) {
    if (error !== "cancel") ElMessage.error(`下架失败：${String(error)}`);
  }
}

function onPointerDown(event: PointerEvent, placement: Placement): void {
  if (!canUpdate.value) return;
  selectPlacement(placement);
  dragging.value = { id: placement.id, startY: event.clientY, candidate: placement.positionU, moved: false };
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
}

function onPointerMove(event: PointerEvent): void {
  const drag = dragging.value;
  const placement = selected.value;
  if (!drag || !placement) return;
  const delta = Math.round((event.clientY - drag.startY) / rowHeight.value);
  const candidate = Math.min(
    height.value - placement.uHeight + 1,
    Math.max(1, placement.positionU - delta),
  );
  if (candidate !== drag.candidate) drag.moved = true;
  drag.candidate = candidate;
}

async function onPointerUp(): Promise<void> {
  window.removeEventListener("pointermove", onPointerMove);
  const drag = dragging.value;
  dragging.value = null;
  const placement = selected.value;
  if (!drag || !placement || !rack.value || !drag.moved || drag.candidate === placement.positionU) {
    return;
  }
  try {
    await updatePlacement(placement.id, {
      rackId: rack.value.id,
      positionU: drag.candidate,
      uHeight: placement.uHeight,
      face: placement.face,
      displayName: placement.name,
      brandModel: placement.brandModel,
      category: placement.category,
      notes: placement.notes ?? "",
    });
    ElMessage.success(`「${placement.name}」已移动到 U${drag.candidate}。`);
  } catch (error) {
    ElMessage.error(`移动失败：${(error as Error).message}`);
  }
  await loadRack(rack.value.id);
}

function exportCsv(): void {
  if (!rack.value || !placements.value.length) {
    ElMessage.warning("当前机柜还没有上架设备。");
    return;
  }
  const header = ["起始U", "占用", "安装面", "设备名称", "品牌型号", "类型", "状态", "固资编码", "SN/ST", "使用人", "备注"];
  const rows = [...placements.value]
    .sort((a, b) => b.positionU - a.positionU)
    .map((item) =>
      [
        item.positionU,
        `${item.uHeight}U`,
        FACE_LABELS[item.face] ?? item.face,
        item.name,
        item.brandModel,
        rackCategoryLabel(item.category),
        statusLabel(item.status ?? ""),
        item.assetCode ?? "",
        item.serialNumber ?? "",
        item.ownerLabel ?? "",
        item.notes ?? "",
      ]
        .map((cell) => `"${String(cell).replace(/"/g, '""')}"`)
        .join(","),
    );
  const csv = `\ufeff${header.join(",")}\n${rows.join("\n")}`;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  link.download = `机柜设备清单-${rack.value.name}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function printRack(): void {
  if (!rack.value) return;
  const rows = unitRows.value
    .map((unit) => {
      const placement = occupiedUnits.value.get(unit);
      const isStart = placement && placement.positionU === unit;
      const text = placement
        ? isStart
          ? `${placement.name} <small>${placement.brandModel} · ${FACE_LABELS[placement.face] ?? placement.face} · ${placement.uHeight}U</small>`
          : ""
        : "";
      return `<tr><td class="u">${unit}U</td><td>${text}</td></tr>`;
    })
    .join("");
  const win = window.open("", "_blank");
  if (!win) {
    ElMessage.warning("浏览器拦截了打印窗口，请允许弹出窗口后重试。");
    return;
  }
  win.document.write(
    `<html><head><meta charset="utf-8" /><title>${rack.value.name} 机柜图</title>
      <style>body{font-family:"Microsoft YaHei",Arial,sans-serif;font-size:12px;margin:24px}
      h1{font-size:18px;margin:0 0 6px}p.meta{color:#555;margin:0 0 12px}
      table{border-collapse:collapse;width:460px}td{border:1px solid #999;padding:4px 6px;height:18px}
      td.u{width:48px;text-align:right;color:#555;background:#f2f2f2}small{color:#555}</style></head>
      <body><h1>${rack.value.name}</h1>
      <p class="meta">${rack.value.siteName} ｜ ${height.value}U ｜ 设备 ${placements.value.length} 台</p>
      <table>${rows}</table></body></html>`,
  );
  win.document.close();
  win.focus();
  win.print();
}

function startInspection(): void {
  if (!rack.value) return;
  void router.push({ path: "/inspection", query: { rack: rack.value.code } });
}

onMounted(async () => {
  await loadRacks();
  await loadPalette();
});
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div class="rack-toolbar">
        <el-select v-model="selectedId" style="width: 320px" @change="loadRack">
          <el-option
            v-for="item in racks"
            :key="item.id"
            :value="item.id"
            :label="`${item.siteName} / ${item.name}（${item.heightU}U，已用 ${item.usedUnits}U）`"
          />
        </el-select>
        <el-radio-group v-model="face" size="small">
          <el-radio-button value="front">前面板</el-radio-button>
          <el-radio-button value="rear">后面板</el-radio-button>
        </el-radio-group>
        <el-radio-group v-model="viewMode" size="small" @change="viewMode === 'side' && loadSideBySide()">
          <el-radio-button value="single">单柜</el-radio-button>
          <el-radio-button value="side">并排</el-radio-button>
        </el-radio-group>
        <el-switch v-model="showLabels" active-text="标签" />
        <el-radio-group v-model="rowHeight" size="small">
          <el-radio-button :value="18">紧凑</el-radio-button>
          <el-radio-button :value="22">标准</el-radio-button>
          <el-radio-button :value="28">放大</el-radio-button>
        </el-radio-group>
        <div class="spacer" />
        <el-button size="small" @click="printRack">打印机柜图</el-button>
        <el-button size="small" @click="exportCsv">导出清单</el-button>
        <el-button size="small" @click="startInspection">发起巡检</el-button>
      </div>
    </template>

    <div v-if="viewMode === 'side'" class="side-by-side">
      <div v-for="(item, index) in sideRacks" :key="item.id" class="side-rack">
        <div class="side-head">
          <strong>{{ item.name }}</strong>
          <span>{{ item.siteName }} ｜ {{ item.heightU }}U ｜ 已用 {{ item.usedUnits }}U</span>
        </div>
        <div class="rack-frame">
          <div v-if="index === 0" class="rack-units">
            <div v-for="unit in unitRowsOf(Number(item.heightU))" :key="unit" class="unit" :style="{ height: `${rowHeight}px` }">
              {{ unit }}
            </div>
          </div>
          <div
            class="rack-body"
            :style="{ height: `${Number(item.heightU) * rowHeight + 2}px`, '--rack-row': `${rowHeight}px` }"
          >
            <div
              v-for="placement in item.placements"
              :key="placement.id"
              class="device"
              :class="[`status-${placement.status ?? 'other'}`]"
              :style="{
                top: `${deviceTopOf(Number(item.heightU), placement)}px`,
                height: `${placement.uHeight * rowHeight - 2}px`,
                cursor: 'pointer',
              }"
              :title="`${placement.name} · ${placement.brandModel}`"
              @click="openInSingleView(item.id, placement.id)"
            >
              <span class="device-name">{{ showLabels ? placement.name : (CATEGORY_LABELS[placement.category] ?? "设备") }}</span>
              <span class="device-tag">{{ placement.uHeight }}U</span>
            </div>
          </div>
        </div>
      </div>
      <div v-if="!sideRacks.length" class="empty-hint">该机房还没有机柜。</div>
      <div class="legend"><span>点任意设备回到单柜视图编辑它</span></div>
    </div>
    <div v-else-if="!rack" class="empty-hint">还没有机柜，请先在“机房巡检 → 机房与机柜”里维护。</div>
    <div v-else class="rack-grid">
      <section>
        <div class="rack-meta">
          <strong>{{ rack.name }}</strong>
          <span>{{ rack.siteName }} ｜ {{ height }}U ｜ 已用 {{ usedUnits }}U / 空闲 {{ height - usedUnits }}U</span>
        </div>
        <div class="rack-frame">
          <div class="rack-units">
            <div v-for="unit in unitRows" :key="unit" class="unit" :style="{ height: `${rowHeight}px` }">
              {{ unit }}
            </div>
          </div>
          <div class="rack-body" :style="{ height: `${height * rowHeight + 2}px`, '--rack-row': `${rowHeight}px` }">
            <div
              v-for="unit in unitRows"
              v-show="!occupiedUnits.get(unit)"
              :key="`slot-${unit}`"
              class="slot"
              :style="{ top: `${slotTop(unit)}px`, height: `${rowHeight - 1}px` }"
              @click="placeAt(unit)"
            />
            <div
              v-for="item in placements"
              :key="item.id"
              class="device"
              :class="[
                `status-${item.status ?? 'other'}`,
                { selected: item.id === selectedId, dimmed: !faceVisible(item) },
              ]"
              :style="{
                top: `${deviceTop(item)}px`,
                height: `${deviceHeight(item)}px`,
                cursor: canUpdate ? 'grab' : 'default',
              }"
              :title="`${item.name} · ${item.brandModel}`"
              @pointerdown="onPointerDown($event, item)"
            >
              <span class="device-name">{{ showLabels ? item.name : (rackCategoryLabel(item.category)) }}</span>
              <span v-if="item.uHeight >= 2" class="device-model">{{ item.brandModel }}</span>
              <span class="device-tag">{{ item.uHeight }}U</span>
            </div>
          </div>
          <div class="rack-units">
            <div v-for="unit in unitRows" :key="`r-${unit}`" class="unit right" :style="{ height: `${rowHeight}px` }">
              {{ unit }}
            </div>
          </div>
        </div>
        <div class="legend">
          <span>拖动设备改 U 位，冲突会提示并回退</span>
          <span>点右侧未上架设备，再点机柜空位即可上架</span>
        </div>
      </section>

      <aside>
        <el-card shadow="never" class="side-card">
          <template #header>
            <div class="side-head">
              <strong>设备属性</strong>
              <el-button
                v-if="selected && canDelete"
                link
                type="danger"
                size="small"
                @click="unlinkPlacement"
              >
                下架
              </el-button>
            </div>
          </template>
          <div v-if="!selected" class="empty-hint">点击机柜里的设备查看或调整。</div>
          <el-form v-else label-position="top" size="small">
            <el-form-item label="显示名称">
              <el-input v-model="form.displayName" :disabled="!canUpdate" />
            </el-form-item>
            <el-form-item label="品牌型号">
              <el-input v-model="form.brandModel" :disabled="!canUpdate" />
            </el-form-item>
            <el-form-item label="起始 U 位 / 占用高度">
              <el-input-number v-model="form.positionU" :min="1" :max="height" :disabled="!canUpdate" />
              <el-select v-model="form.uHeight" class="oa-w-96 oa-ml-2" :disabled="!canUpdate">
                <el-option v-for="value in [1, 2, 3, 4, 6, 8]" :key="value" :value="value" :label="`${value}U`" />
              </el-select>
            </el-form-item>
            <el-form-item label="设备类型">
              <el-select v-model="form.category" class="oa-full-width" :disabled="!canUpdate">
                <el-option v-for="(label, value) in CATEGORY_LABELS" :key="value" :value="value" :label="label" />
              </el-select>
            </el-form-item>
            <el-form-item label="安装面板">
              <el-select v-model="form.face" class="oa-full-width" :disabled="!canUpdate">
                <el-option v-for="(label, value) in FACE_LABELS" :key="value" :value="value" :label="label" />
              </el-select>
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="form.notes" :disabled="!canUpdate" />
            </el-form-item>
            <el-descriptions :column="1" size="small" border>
              <el-descriptions-item label="固资编码">{{ selected.assetCode || "—" }}</el-descriptions-item>
              <el-descriptions-item label="SN / ST">{{ selected.serialNumber || "—" }}</el-descriptions-item>
              <el-descriptions-item label="使用人">{{ selected.ownerLabel || "未分配" }}</el-descriptions-item>
              <el-descriptions-item label="台账状态">
                {{ statusLabel(selected.status ?? "") }}
              </el-descriptions-item>
            </el-descriptions>
            <div class="form-actions">
              <el-button v-if="canUpdate" type="primary" size="small" @click="savePlacement">保存属性</el-button>
            </div>
          </el-form>
        </el-card>

        <el-card v-if="canCreate" shadow="never" class="side-card">
          <template #header><strong>未上架设备</strong></template>
          <el-input v-model="paletteKeyword" placeholder="搜索设备名或型号" clearable size="small" @change="loadPalette(paletteKeyword)" />
          <div class="palette">
            <button
              v-for="row in paletteRows"
              :key="row.key"
              type="button"
              class="palette-item"
              :class="{ armed: armed?.key === row.key }"
              @click="armDevice(row)"
            >
              <strong>{{ row.name }}</strong>
              <small>{{ row.brandModel }} ｜ {{ rackCategoryLabel(row.category) }} ｜ {{ row.note }}</small>
            </button>
            <div v-if="!paletteRows.length" class="empty-hint">没有匹配的未上架设备。</div>
          </div>
        </el-card>
      </aside>
    </div>
  </el-card>
</template>

<style scoped>
.rack-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.spacer {
  flex: 1;
}
.rack-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 340px);
  gap: 16px;
  align-items: start;
}
.rack-meta {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 8px;
}
.rack-meta span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.rack-frame {
  display: flex;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  background: var(--el-bg-color);
}
.rack-units {
  display: flex;
  flex-direction: column;
  width: 26px;
  flex: 0 0 26px;
}
.unit {
  display: flex;
  align-items: center;
  justify-content: center;
  border-right: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: 10px;
}
.unit.right {
  border-right: 0;
  border-left: 1px solid var(--el-border-color-lighter);
}
.rack-body {
  position: relative;
  flex: 1;
  min-width: 0;
  border: 2px solid var(--el-border-color);
  background: repeating-linear-gradient(
    to bottom,
    var(--el-bg-color) 0,
    var(--el-bg-color) calc(var(--rack-row, 22px) - 1px),
    var(--el-border-color-lighter) calc(var(--rack-row, 22px) - 1px),
    var(--el-border-color-lighter) var(--rack-row, 22px)
  );
}
.slot {
  position: absolute;
  left: 0;
  right: 0;
  cursor: pointer;
}
.slot:hover {
  background: var(--el-color-primary-light-9);
  outline: 1px dashed var(--el-color-primary);
}
.device {
  position: absolute;
  left: 0;
  right: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 8px;
  overflow: hidden;
  border: 1px solid var(--el-border-color);
  border-left-width: 3px;
  background: var(--el-bg-color);
  user-select: none;
  touch-action: none;
}
.device.selected {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}
.device.dimmed {
  opacity: 0.35;
}
.status-in_use { border-left-color: var(--el-text-color-primary); }
.status-idle { border-left-color: var(--el-border-color-darker); }
.status-repair { border-left-color: var(--el-color-danger); }
.status-retired { border-left-color: var(--el-text-color-disabled); }
.status-shared { border-left-style: dotted; border-left-color: var(--el-color-primary); }
.device-name {
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.device-model {
  color: var(--el-text-color-secondary);
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.device-tag {
  margin-left: auto;
  padding: 0 6px;
  border: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: 10px;
}
.legend,
.empty-hint {
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.legend {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.side-by-side {
  display: flex;
  gap: 14px;
  overflow-x: auto;
  padding-bottom: 8px;
}
.side-rack {
  flex: 0 0 auto;
  min-width: 220px;
}
.side-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 6px;
}
.side-head span {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.side-by-side .rack-frame {
  padding: 6px;
}
.side-by-side .device-model {
  display: none;
}
.side-card {
  margin-bottom: 12px;
}
.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.palette {
  display: grid;
  gap: 8px;
  margin-top: 8px;
  max-height: 280px;
  overflow: auto;
}
.palette-item {
  display: grid;
  gap: 2px;
  padding: 8px 10px;
  text-align: left;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background: var(--el-bg-color);
  color: var(--el-text-color-primary);
  cursor: pointer;
}
.palette-item:hover {
  border-color: var(--el-color-primary);
}
.palette-item.armed {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.palette-item small {
  color: var(--el-text-color-secondary);
}
.form-actions {
  margin-top: 12px;
}
@media (max-width: 1100px) {
  .rack-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
