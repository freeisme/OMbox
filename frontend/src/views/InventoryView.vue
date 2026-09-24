<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  adjustInventory,
  buildInventoryTree,
  deleteWarehouse,
  invalidateInventoryCache,
  loadInventoryData,
  receiveInventory,
  saveInventoryBrand,
  saveInventoryModel,
  saveInventoryType,
  saveWarehouse,
  transferInventory,
  type InventoryData,
  type InventoryModelRow,
  type InventoryModelPayload,
  type WarehouseRow,
} from "../api/inventory";
import { hasPermission } from "../session";
import { confirmAction } from "../composables/useConfirm";

interface OrgNode {
  id: string;
  code: string;
  name: string;
  parentId: string;
  children: OrgNode[];
  label: string;
  /** el-tree-select 需要 value 才能选中节点。 */
  value: string;
}

const loading = ref(true);
const saving = ref(false);
const data = ref<InventoryData>({
  warehouses: [],
  types: [],
  brands: [],
  models: [],
  stocks: [],
  purchaseLogs: [],
  orgs: [],
});
const warehouseId = ref("");
const keyword = ref("");
const typeFilter = ref("");
const brandFilter = ref("");
const expandedKeys = ref<string[]>([]);
const page = ref(1);
const pageSize = ref(20);

const receiveVisible = ref(false);
const receiveForm = reactive({
  modelId: "",
  warehouseId: "",
  quantity: 1,
  inboundDate: new Date().toISOString().slice(0, 10),
  sourceLabel: "",
  note: "",
});

const transferVisible = ref(false);
const transferForm = reactive({
  modelId: "",
  sourceWarehouseId: "",
  targetWarehouseId: "",
  quantity: 1,
  note: "",
});

const warehouseDialogVisible = ref(false);
const warehouseEditingId = ref("");
const warehouseForm = reactive({
  code: "",
  name: "",
  orgId: "",
  managerEmployeeId: "",
  contactPhone: "",
  address: "",
  remarks: "",
});

const typeVisible = ref(false);
const typeEditingId = ref("");
const typeForm = reactive({ code: "", name: "", unit: "件" });

const brandVisible = ref(false);
const brandEditingId = ref("");
const brandForm = reactive({ typeId: "", name: "", sortOrder: 1000 });

const modelVisible = ref(false);
const modelEditingId = ref("");
const modelForm = reactive({
  typeId: "",
  brandId: "",
  name: "",
  warehouseId: "",
  quantity: 0,
  batchKey: "",
  inboundDate: "",
  cpu: "",
  memory: "",
  storage: "",
  gpu: "",
  sortOrder: 1000,
});

const orgTree = computed<OrgNode[]>(() => {
  const nodes = new Map<string, OrgNode>();
  data.value.orgs.forEach((item) =>
    nodes.set(item.id, {
      ...item,
      value: item.id,
      children: [],
      label: `${item.name}（${item.code}）`,
    }),
  );
  const roots: OrgNode[] = [];
  data.value.orgs.forEach((item) => {
    const node = nodes.get(item.id);
    if (!node) return;
    const parent = item.parentId ? nodes.get(item.parentId) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  return roots;
});

const activeWarehouse = computed<WarehouseRow | undefined>(() =>
  data.value.warehouses.find((item) => item.id === warehouseId.value),
);

const tree = computed(() => buildInventoryTree(data.value, warehouseId.value));

const filteredTree = computed(() => {
  let nodes = tree.value;
  if (typeFilter.value) {
    nodes = nodes.filter((type) => type.id === typeFilter.value);
  }
  if (brandFilter.value) {
    nodes = nodes
      .map((type) => {
        const children = type.children.filter((brand) => brand.id === brandFilter.value);
        return children.length
          ? {
              ...type,
              children,
              quantity: children.reduce((sum, brand) => sum + brand.quantity, 0),
            }
          : null;
      })
      .filter((item): item is (typeof nodes)[number] => Boolean(item));
  }
  const key = keyword.value.trim().toLowerCase();
  if (!key) return nodes;
  return nodes
    .map((type) => {
      const brands = type.children
        .map((brand) => {
          const models = brand.children.filter((model) =>
            `${type.name} ${brand.name} ${model.name} ${model.config}`.toLowerCase().includes(key),
          );
          const brandMatches = `${type.name} ${brand.name}`.toLowerCase().includes(key);
          return { ...brand, children: brandMatches ? brand.children : models };
        })
        .filter((brand) => brand.children.length > 0);
      const typeMatches = `${type.name} ${type.code}`.toLowerCase().includes(key);
      return { ...type, children: typeMatches ? type.children : brands };
    })
    .filter((type) => type.children.length > 0);
});

const brandFilterOptions = computed(() =>
  data.value.brands.filter((brand) => !typeFilter.value || brand.typeId === typeFilter.value),
);

/**
 * 型号行补充说明：只有电脑类物资才有配置、批次和入库日期，
 * 普通物资（鼠标 / 键盘 / 显示屏等）只显示型号和数量，避免行与行参差不齐。
 */
function modelMeta(row: {
  typeId?: string;
  config?: string;
  batchKey?: string;
  inboundDate?: string;
}): string {
  if (!isComputerType(String(row.typeId ?? ""))) return "";
  return [
    row.config,
    row.batchKey ? `批次：${row.batchKey}` : "",
    row.inboundDate ? `入库：${row.inboundDate}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

function typeSummary(row: { children?: Array<{ children?: unknown[] }> }): string {
  const brands = row.children ?? [];
  const models = brands.reduce((sum, brand) => sum + (brand.children?.length ?? 0), 0);
  return `${brands.length} 个品牌 / ${models} 个型号`;
}

function brandSummary(row: { children?: unknown[] }): string {
  return `${(row.children ?? []).length} 个型号`;
}

const totalQuantity = computed(() =>
  filteredTree.value.reduce((sum, type) => sum + type.quantity, 0),
);

/** 表格第一列是树：类型 / 品牌 / 型号三层，用它给每行加一个层级标签。 */
function inventoryRowLevel(row: Record<string, unknown>): "type" | "brand" | "model" {
  const level = String(row.level ?? "");
  if (level === "type" || level === "brand" || level === "model") return level;
  return row.children ? "type" : "model";
}

/** 行样式钩子：类型行加浅色底，让三层关系一眼可辨。 */
function inventoryRowClass({ row }: { row: Record<string, unknown> }): string {
  return `oa-inv-row--${inventoryRowLevel(row)}`;
}

/** 父级行在黑体名称后面补一句下级数量；型号行没有下级，返回空。 */
function nodeSummary(row: Record<string, unknown>): string {
  const level = inventoryRowLevel(row);
  if (level === "type") return typeSummary(row as { children?: Array<{ children?: unknown[] }> });
  if (level === "brand") return brandSummary(row as { children?: unknown[] });
  return "";
}

/** 展开全部时用的 key：类型 + 品牌（型号是最底层，没有子节点）。 */
const allKeys = computed(() => {
  const keys: string[] = [];
  tree.value.forEach((type) => {
    keys.push(type.key);
    type.children.forEach((brand) => keys.push(brand.key));
  });
  return keys;
});

/**
 * 有关键字或类型 / 品牌筛选时强制展开命中的分支，
 * 否则匹配到的型号会被折叠在品牌下面，看起来像"搜不到"。
 */
const effectiveExpandKeys = computed(() =>
  keyword.value.trim() || typeFilter.value || brandFilter.value ? allKeys.value : expandedKeys.value,
);

const purchaseLogs = computed(() =>
  data.value.purchaseLogs.filter(
    (log) => !warehouseId.value || String(log.warehouseId ?? "") === warehouseId.value,
  ),
);

const pagedPurchaseLogs = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return purchaseLogs.value.slice(start, start + pageSize.value);
});

const modelOptions = computed(() =>
  data.value.models.map((model: InventoryModelRow) => {
    const brand = data.value.brands.find((item) => item.id === model.brandId)?.name ?? "";
    const type = data.value.types.find((item) => item.id === model.typeId)?.name ?? "";
    const quantity = warehouseId.value
      ? data.value.stocks.find(
          (row) => String(row.modelId) === model.id && String(row.warehouseId) === warehouseId.value,
        )?.quantity ?? 0
      : model.quantity;
    return {
      value: model.id,
      label: `${type} · ${brand} ${model.name}（库存 ${quantity}）`,
    };
  }),
);

async function load(force = false): Promise<void> {
  loading.value = true;
  try {
    data.value = await loadInventoryData(force);
    if (!warehouseId.value && data.value.warehouses.length) {
      warehouseId.value = data.value.warehouses[0].id;
    }
    // 默认摊开类型与品牌，让「型号挂在其品牌下面」直接可见。
    expandedKeys.value = allKeys.value;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "库存数据加载失败。");
  } finally {
    loading.value = false;
  }
}

async function refresh(): Promise<void> {
  invalidateInventoryCache();
  await load(true);
}

function openReceive(modelId = ""): void {
  receiveForm.modelId = modelId || (data.value.models[0]?.id ?? "");
  receiveForm.warehouseId = warehouseId.value || data.value.warehouses[0]?.id || "";
  receiveForm.quantity = 1;
  receiveForm.inboundDate = new Date().toISOString().slice(0, 10);
  receiveForm.sourceLabel = "";
  receiveForm.note = "";
  receiveVisible.value = true;
}

async function submitReceive(): Promise<void> {
  if (!receiveForm.modelId || !receiveForm.warehouseId || receiveForm.quantity <= 0) {
    ElMessage.warning("请选择库存型号、仓库并填写大于零的数量。");
    return;
  }
  saving.value = true;
  try {
    await receiveInventory({
      modelId: receiveForm.modelId,
      warehouseId: receiveForm.warehouseId,
      quantity: Number(receiveForm.quantity),
      inboundDate: receiveForm.inboundDate,
      sourceLabel: receiveForm.sourceLabel.trim(),
      note: receiveForm.note.trim(),
    });
    ElMessage.success("入库完成。");
    receiveVisible.value = false;
    await refresh();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "入库失败。");
  } finally {
    saving.value = false;
  }
}

function openTransfer(): void {
  transferForm.modelId = data.value.models[0]?.id ?? "";
  transferForm.sourceWarehouseId = warehouseId.value || data.value.warehouses[0]?.id || "";
  transferForm.targetWarehouseId = "";
  transferForm.quantity = 1;
  transferForm.note = "";
  transferVisible.value = true;
}

async function submitTransfer(): Promise<void> {
  if (
    !transferForm.modelId ||
    !transferForm.sourceWarehouseId ||
    !transferForm.targetWarehouseId ||
    transferForm.quantity <= 0
  ) {
    ElMessage.warning("请选择型号、调出与调入仓库，并填写大于零的数量。");
    return;
  }
  if (transferForm.sourceWarehouseId === transferForm.targetWarehouseId) {
    ElMessage.warning("调出仓库和调入仓库不能相同。");
    return;
  }
  saving.value = true;
  try {
    await transferInventory({
      modelId: transferForm.modelId,
      sourceWarehouseId: transferForm.sourceWarehouseId,
      targetWarehouseId: transferForm.targetWarehouseId,
      quantity: Number(transferForm.quantity),
      note: transferForm.note.trim(),
    });
    ElMessage.success("库存调拨完成。");
    transferVisible.value = false;
    await refresh();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "调拨失败。");
  } finally {
    saving.value = false;
  }
}

function openWarehouse(row?: WarehouseRow): void {
  warehouseEditingId.value = row?.id ?? "";
  warehouseForm.code = row?.code ?? "";
  warehouseForm.name = row?.name ?? "";
  warehouseForm.orgId = row?.orgId ?? "";
  warehouseForm.managerEmployeeId = row?.managerEmployeeId ?? "";
  warehouseForm.contactPhone = row?.contactPhone ?? "";
  warehouseForm.address = row?.address ?? "";
  warehouseForm.remarks = row?.remarks ?? "";
  warehouseDialogVisible.value = true;
}

async function submitWarehouse(): Promise<void> {
  if (!warehouseForm.code.trim() || !warehouseForm.name.trim() || !warehouseForm.orgId) {
    ElMessage.warning("仓库编码、名称与所属组织必填。");
    return;
  }
  saving.value = true;
  try {
    await saveWarehouse(
      {
        code: warehouseForm.code.trim(),
        name: warehouseForm.name.trim(),
        orgId: warehouseForm.orgId,
        managerEmployeeId: warehouseForm.managerEmployeeId,
        contactPhone: warehouseForm.contactPhone.trim(),
        address: warehouseForm.address.trim(),
        remarks: warehouseForm.remarks.trim(),
      },
      warehouseEditingId.value,
    );
    ElMessage.success(warehouseEditingId.value ? "仓库已更新。" : "仓库已创建。");
    warehouseDialogVisible.value = false;
    await refresh();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败。");
  } finally {
    saving.value = false;
  }
}

async function removeWarehouse(row: WarehouseRow): Promise<void> {
  const confirmed = await confirmAction(`确认删除仓库「${row.name}」？`, {
    title: "删除确认",
    confirmText: "删除",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await deleteWarehouse(row.id);
    ElMessage.success("仓库已删除。");
    if (warehouseId.value === row.id) warehouseId.value = "";
    await refresh();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除失败。");
  }
}

function openTypeDialog(row?: Record<string, unknown>): void {
  typeEditingId.value = String(row?.id ?? "");
  typeForm.code = String(row?.code ?? "");
  typeForm.name = String(row?.name ?? "");
  typeForm.unit = String(row?.unit ?? "件");
  typeVisible.value = true;
}

async function submitType(): Promise<void> {
  if (!typeForm.code.trim() || !typeForm.name.trim()) {
    ElMessage.warning("类型编码与名称必填。");
    return;
  }
  saving.value = true;
  try {
    await saveInventoryType(
      {
        code: typeForm.code.trim(),
        name: typeForm.name.trim(),
        unit: typeForm.unit.trim() || "件",
      },
      typeEditingId.value,
    );
    ElMessage.success(typeEditingId.value ? "物资类型已更新。" : "物资类型已创建。");
    typeVisible.value = false;
    typeEditingId.value = "";
    await refresh();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败。");
  } finally {
    saving.value = false;
  }
}

function openBrandDialog(row?: Record<string, unknown>, typeId = ""): void {
  brandEditingId.value = String(row?.id ?? "");
  brandForm.typeId = String(row?.typeId ?? typeId);
  brandForm.name = String(row?.name ?? "");
  brandForm.sortOrder = Number(row?.sortOrder ?? 1000) || 1000;
  brandVisible.value = true;
}

async function submitBrand(): Promise<void> {
  if (!brandForm.typeId || !brandForm.name.trim()) {
    ElMessage.warning("请选择物资类型并填写品牌名称。");
    return;
  }
  saving.value = true;
  try {
    await saveInventoryBrand(
      {
        typeId: brandForm.typeId,
        name: brandForm.name.trim(),
        sortOrder: Math.max(0, Number(brandForm.sortOrder) || 1000),
      },
      brandEditingId.value,
    );
    ElMessage.success(brandEditingId.value ? "品牌已更新。" : "品牌已创建。");
    brandVisible.value = false;
    brandEditingId.value = "";
    await refresh();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存品牌失败。");
  } finally {
    saving.value = false;
  }
}

/** 只有电脑类物资需要记录入库日期与配置，与旧前端保持一致。 */
function isComputerType(typeId: string): boolean {
  const type = data.value.types.find((item) => item.id === typeId);
  const code = String(type?.code ?? "").toLowerCase();
  const name = String(type?.name ?? "");
  return ["computer", "pc"].includes(code) || ["电脑", "计算机"].includes(name);
}

function stockOf(modelId: string, targetWarehouseId: string): number {
  return Number(
    data.value.stocks.find(
      (row) =>
        String(row.modelId) === String(modelId) &&
        String(row.warehouseId) === String(targetWarehouseId),
    )?.quantity ?? 0,
  );
}

function openModelDialog(model?: Record<string, unknown>, typeId = "", brandId = ""): void {
  const resolvedTypeId = String(model?.typeId ?? typeId);
  const targetWarehouseId = warehouseId.value || data.value.warehouses[0]?.id || "";
  modelEditingId.value = String(model?.id ?? "");
  modelForm.typeId = resolvedTypeId;
  modelForm.brandId = String(model?.brandId ?? brandId);
  modelForm.name = String(model?.name ?? "");
  modelForm.warehouseId = targetWarehouseId;
  modelForm.quantity = model ? stockOf(String(model.id), targetWarehouseId) : 0;
  modelForm.batchKey = String(model?.batchKey ?? "");
  modelForm.inboundDate = String(
    model?.inboundDate ?? (isComputerType(resolvedTypeId) ? new Date().toISOString().slice(0, 10) : ""),
  );
  modelForm.cpu = String(model?.cpu ?? "");
  modelForm.memory = String(model?.memory ?? "");
  modelForm.storage = String(model?.storage ?? "");
  modelForm.gpu = String(model?.gpu ?? "");
  modelForm.sortOrder = Number(model?.sortOrder ?? 1000) || 1000;
  modelVisible.value = true;
}

async function submitModel(): Promise<void> {
  if (!modelForm.typeId || !modelForm.brandId || !modelForm.name.trim() || !modelForm.warehouseId) {
    ElMessage.warning("请选择仓库、类型、品牌并填写型号名称。");
    return;
  }
  const computerModel = isComputerType(modelForm.typeId);
  const previous = modelEditingId.value ? stockOf(modelEditingId.value, modelForm.warehouseId) : 0;
  const desired = Math.max(0, Number(modelForm.quantity) || 0);
  saving.value = true;
  try {
    const payload: InventoryModelPayload = {
      typeId: modelForm.typeId,
      brandId: modelForm.brandId,
      name: modelForm.name.trim(),
      batchKey: modelForm.batchKey.trim(),
      inboundDate: computerModel ? modelForm.inboundDate : "",
      cpu: computerModel ? modelForm.cpu.trim() : "",
      memory: computerModel ? modelForm.memory.trim() : "",
      storage: computerModel ? modelForm.storage.trim() : "",
      gpu: computerModel ? modelForm.gpu.trim() : "",
      sortOrder: Math.max(0, Number(modelForm.sortOrder) || 1000),
    };
    const saved = await saveInventoryModel(payload, modelEditingId.value);
    const modelId = saved.id || modelEditingId.value;
    const delta = desired - previous;
    if (delta > 0) {
      await receiveInventory({
        modelId,
        warehouseId: modelForm.warehouseId,
        quantity: delta,
        inboundDate: modelForm.inboundDate || new Date().toISOString().slice(0, 10),
        sourceLabel: "库存型号维护入库",
        note: "通过库存型号维护设置当前仓库数量",
      });
    } else if (delta < 0) {
      await adjustInventory({
        modelId,
        warehouseId: modelForm.warehouseId,
        quantityDelta: delta,
        note: "通过库存型号维护调整当前仓库数量",
      });
    }
    ElMessage.success(modelEditingId.value ? "库存型号已更新。" : "库存型号已创建。");
    modelVisible.value = false;
    modelEditingId.value = "";
    await refresh();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存型号失败。");
  } finally {
    saving.value = false;
  }
}

function clearInventoryFilters(): void {
  keyword.value = "";
  typeFilter.value = "";
  brandFilter.value = "";
}

function exportCurrent(): void {
  const rows: string[][] = [];
  filteredTree.value.forEach((type) =>
    type.children.forEach((brand) =>
      brand.children.forEach((model) =>
        rows.push([
          type.name,
          type.unit,
          brand.name,
          model.name,
          String(model.quantity),
          model.inboundDate,
          model.config,
          model.batchKey,
        ]),
      ),
    ),
  );
  if (!rows.length) {
    ElMessage.warning("当前仓库没有可导出的库存。");
    return;
  }
  const header = ["物资类型", "单位", "品牌", "型号", "库存数量", "入库日期", "配置", "批次"];
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const csv = [header, ...rows].map((line) => line.map(escape).join(",")).join("\r\n");
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `IT物资-${activeWarehouse.value?.name ?? "全部"}-${stamp}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

onMounted(() => load(false));
</script>

<template>
  <PageHeader
    title="IT物资"
    :description="`${activeWarehouse ? `${activeWarehouse.name}（${activeWarehouse.code}）` : '全部仓库'} · 库存 ${totalQuantity} 件 · 采购入库 ${purchaseLogs.length} 条`"
  >
    <template #actions>
        <el-button v-if="hasPermission('warehouse_management')" @click="openWarehouse()">
          ＋ 新增仓库
        </el-button>
        <el-button
          v-if="hasPermission('warehouse_management', 'create') && hasPermission('inventory_operations', 'update')"
          @click="openTransfer"
        >
          库存调拨
        </el-button>
        <el-button v-if="hasPermission('inventory_operations', 'create')" @click="openReceive()">
          ＋ 入库
        </el-button>
        <el-button @click="exportCurrent">导出当前仓库</el-button>
        <el-button v-if="hasPermission('inventory_catalog', 'create')" @click="openTypeDialog()">
          新增类型
        </el-button>
    </template>
    <template #filters>
      <FilterBar
        :summary="`当前仓库：${activeWarehouse ? activeWarehouse.name : '全部仓库'}`"
        :resettable="Boolean(keyword || typeFilter || brandFilter)"
        @reset="clearInventoryFilters"
      >
        <el-button
          v-for="warehouse in data.warehouses"
          :key="warehouse.id"
          :type="warehouse.id === warehouseId ? 'primary' : 'default'"
          size="small"
          @click="warehouseId = warehouse.id"
        >
          {{ warehouse.name }}
        </el-button>
        <el-button
          v-if="data.warehouses.length"
          :type="warehouseId === '' ? 'primary' : 'default'"
          size="small"
          @click="warehouseId = ''"
        >
          全部仓库
        </el-button>
        <el-input
          v-model="keyword"
          placeholder="搜索类型、品牌或型号"
          clearable
          class="oa-filter-input"
          style="max-width: 260px"
        />
        <el-select v-model="typeFilter" clearable placeholder="物资类型" style="width: 150px">
          <el-option
            v-for="type in data.types"
            :key="type.id"
            :label="type.name"
            :value="type.id"
          />
        </el-select>
        <el-select
          v-model="brandFilter"
          clearable
          filterable
          placeholder="品牌"
          style="width: 150px"
        >
          <el-option
            v-for="brand in brandFilterOptions"
            :key="brand.id"
            :label="brand.name"
            :value="brand.id"
          />
        </el-select>
        <el-button @click="expandedKeys = allKeys">展开全部</el-button>
        <el-button @click="expandedKeys = []">收起全部</el-button>
      </FilterBar>
    </template>
  </PageHeader>

  <DataPanel class="oa-panel-gap" :loading="loading">
    <el-table
      class="inventory-table"
      :data="filteredTree"
      row-key="key"
      size="small"
      border
      :indent="32"
      :default-expand-all="false"
      :expand-row-keys="effectiveExpandKeys"
      :row-class-name="inventoryRowClass"
      empty-text="暂无符合条件的库存"
    >
      <el-table-column label="类型 / 品牌 / 型号" min-width="300">
        <template #default="{ row }">
          <div class="oa-inv-node" :class="`oa-inv-node--${inventoryRowLevel(row)}`">
            <div class="oa-inv-node__main">
              <span class="oa-inv-node__name">{{ row.name }}</span>
              <span v-if="row.code" class="oa-muted">（{{ row.code }}）</span>
              <span v-if="nodeSummary(row)" class="oa-cell-sub oa-ml-2">
                {{ nodeSummary(row) }}
              </span>
            </div>
            <div v-if="modelMeta(row)" class="oa-cell-sub">{{ modelMeta(row) }}</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="库存数量" width="130" align="right">
        <template #default="{ row }">
          <span v-if="row.children" class="oa-muted">共 </span>
          <strong class="oa-tabular">{{ row.quantity }}</strong>
          <span class="oa-muted"> {{ row.unit || "件" }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="230" fixed="right">
        <template #default="{ row }">
          <template v-if="inventoryRowLevel(row) === 'type'">
            <el-button
              v-if="hasPermission('inventory_catalog', 'update')"
              link
              type="primary"
              @click="openTypeDialog(row)"
            >
              编辑类型
            </el-button>
            <el-button
              v-if="hasPermission('inventory_catalog', 'create')"
              link
              @click="openBrandDialog(undefined, row.id)"
            >
              新增品牌
            </el-button>
          </template>
          <template v-else-if="inventoryRowLevel(row) === 'brand'">
            <el-button
              v-if="hasPermission('inventory_catalog', 'update')"
              link
              type="primary"
              @click="openBrandDialog(row)"
            >
              编辑品牌
            </el-button>
            <el-button
              v-if="hasPermission('inventory_catalog', 'create')"
              link
              @click="openModelDialog(undefined, row.typeId, row.id)"
            >
              新增型号
            </el-button>
          </template>
          <template v-else>
            <el-button
              v-if="hasPermission('inventory_catalog', 'update')"
              link
              type="primary"
              @click="openModelDialog(row)"
            >
              编辑
            </el-button>
            <el-button
              v-if="hasPermission('inventory_operations', 'create')"
              link
              @click="openReceive(row.id)"
            >
              入库
            </el-button>
            <el-button
              v-if="hasPermission('warehouse_management', 'create') && hasPermission('inventory_operations', 'update')"
              link
              @click="transferForm.modelId = row.id; openTransfer()"
            >
              调拨
            </el-button>
          </template>
        </template>
      </el-table-column>
    </el-table>
  </DataPanel>

  <DataPanel class="oa-panel-gap" title="采购入库记录" :hint="`${purchaseLogs.length} 条`">
    <el-table :data="pagedPurchaseLogs" size="small" border empty-text="暂无采购入库记录">
      <el-table-column label="物资" min-width="180">
        <template #default="{ row }">
          {{ [row.typeName, row.brandName, row.modelName].filter(Boolean).join(" · ") || "—" }}
        </template>
      </el-table-column>
      <el-table-column prop="quantity" label="数量" width="80" />
      <el-table-column prop="inboundDate" label="入库日期" width="110" />
      <el-table-column prop="sourceLabel" label="来源" min-width="140" />
      <el-table-column prop="note" label="备注" min-width="160" />
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :page-sizes="[10, 20, 50]"
      :total="purchaseLogs.length"
      layout="total, sizes, prev, pager, next"
      class="oa-pagination"
    />
  </DataPanel>

  <FormDialog
    v-model="receiveVisible"
    title="物资入库"
    size="md"
    confirm-text="确认入库"
    :loading="saving"
    @confirm="submitReceive"
  >
    <el-form label-position="top">
      <el-form-item label="库存型号" required>
        <el-select v-model="receiveForm.modelId" filterable class="oa-full-width">
          <el-option v-for="item in modelOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="入库仓库" required>
        <el-select v-model="receiveForm.warehouseId" class="oa-full-width">
          <el-option
            v-for="warehouse in data.warehouses"
            :key="warehouse.id"
            :label="warehouse.name"
            :value="warehouse.id"
          />
        </el-select>
      </el-form-item>
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12">
          <el-form-item label="数量" required>
            <el-input-number v-model="receiveForm.quantity" :min="1" class="oa-full-width" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12">
          <el-form-item label="入库日期">
            <el-date-picker
              v-model="receiveForm.inboundDate"
              type="date"
              value-format="YYYY-MM-DD"
              class="oa-full-width"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="来源"><el-input v-model="receiveForm.sourceLabel" placeholder="例如 供应商送货" /></el-form-item>
      <el-form-item label="备注"><el-input v-model="receiveForm.note" type="textarea" :rows="2" /></el-form-item>
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="transferVisible"
    title="库存调拨"
    size="md"
    confirm-text="确认调拨"
    :loading="saving"
    @confirm="submitTransfer"
  >
    <el-form label-position="top">
      <el-form-item label="库存型号" required>
        <el-select v-model="transferForm.modelId" filterable class="oa-full-width">
          <el-option v-for="item in modelOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12">
          <el-form-item label="调出仓库" required>
            <el-select v-model="transferForm.sourceWarehouseId" class="oa-full-width">
              <el-option
                v-for="warehouse in data.warehouses"
                :key="warehouse.id"
                :label="warehouse.name"
                :value="warehouse.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12">
          <el-form-item label="调入仓库" required>
            <el-select v-model="transferForm.targetWarehouseId" class="oa-full-width">
              <el-option
                v-for="warehouse in data.warehouses"
                :key="warehouse.id"
                :label="warehouse.name"
                :value="warehouse.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="数量" required>
        <el-input-number v-model="transferForm.quantity" :min="1" />
      </el-form-item>
      <el-form-item label="备注"><el-input v-model="transferForm.note" type="textarea" :rows="2" /></el-form-item>
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="warehouseDialogVisible"
    :title="warehouseEditingId ? '编辑仓库' : '新增仓库'"
    size="md"
  >
    <el-form label-position="top">
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12">
          <el-form-item label="仓库编码" required>
            <el-input v-model="warehouseForm.code" placeholder="大写字母/数字，例如 SZNS" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12">
          <el-form-item label="仓库名称" required><el-input v-model="warehouseForm.name" /></el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="所属组织" required>
        <el-tree-select
          v-model="warehouseForm.orgId"
          :data="orgTree"
          check-strictly
          placeholder="选择组织"
          class="oa-full-width"
        />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12">
          <el-form-item label="联系电话"><el-input v-model="warehouseForm.contactPhone" /></el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12">
          <el-form-item label="地址"><el-input v-model="warehouseForm.address" /></el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="备注"><el-input v-model="warehouseForm.remarks" /></el-form-item>
    </el-form>
    <template #footer>
      <div class="oa-flex-between">
        <el-button
          v-if="warehouseEditingId && hasPermission('warehouse_management', 'delete')"
          type="danger"
          plain
          @click="() => { const row = data.warehouses.find((item) => item.id === warehouseEditingId); if (row) removeWarehouse(row); }"
        >
          删除仓库
        </el-button>
        <div>
          <el-button @click="warehouseDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="submitWarehouse">保存</el-button>
        </div>
      </div>
    </template>
  </FormDialog>

  <FormDialog
    v-model="typeVisible"
    :title="typeEditingId ? '编辑物资类型' : '新增物资类型'"
    size="sm"
    :loading="saving"
    @confirm="submitType"
  >
    <el-form label-position="top">
      <el-form-item label="类型编码" required><el-input v-model="typeForm.code" placeholder="例如 monitor" /></el-form-item>
      <el-form-item label="类型名称" required><el-input v-model="typeForm.name" placeholder="例如 显示屏" /></el-form-item>
      <el-form-item label="计量单位"><el-input v-model="typeForm.unit" /></el-form-item>
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="brandVisible"
    :title="brandEditingId ? '编辑品牌' : '新增品牌'"
    size="sm"
    confirm-text="保存品牌"
    :loading="saving"
    @confirm="submitBrand"
  >
    <el-form label-position="top">
      <el-form-item label="物资类型" required>
        <el-select v-model="brandForm.typeId" class="oa-full-width">
          <el-option v-for="type in data.types" :key="type.id" :label="type.name" :value="type.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="品牌名称" required>
        <el-input v-model="brandForm.name" placeholder="例如 罗技" />
      </el-form-item>
      <el-form-item label="排序">
        <el-input-number v-model="brandForm.sortOrder" :min="0" class="oa-full-width" />
      </el-form-item>
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="modelVisible"
    :title="modelEditingId ? '编辑库存型号' : '新增库存型号'"
    size="lg"
    confirm-text="保存型号"
    :loading="saving"
    @confirm="submitModel"
  >
    <el-form label-position="top">
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12">
          <el-form-item label="库存仓库" required>
            <el-select
              v-model="modelForm.warehouseId"
              :disabled="Boolean(modelEditingId)"
              class="oa-full-width"
            >
              <el-option
                v-for="warehouse in data.warehouses"
                :key="warehouse.id"
                :label="warehouse.name"
                :value="warehouse.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12">
          <el-form-item label="物资类型" required>
            <el-select v-model="modelForm.typeId" class="oa-full-width">
              <el-option v-for="type in data.types" :key="type.id" :label="type.name" :value="type.id" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12">
          <el-form-item label="品牌" required>
            <el-select v-model="modelForm.brandId" filterable class="oa-full-width">
              <el-option
                v-for="brand in data.brands.filter((item) => item.typeId === modelForm.typeId)"
                :key="brand.id"
                :label="brand.name"
                :value="brand.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12">
          <el-form-item label="型号" required>
            <el-input v-model="modelForm.name" placeholder="例如 M332" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12">
          <el-form-item label="当前仓库可用数量" required>
            <el-input-number v-model="modelForm.quantity" :min="0" class="oa-full-width" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12">
          <el-form-item label="排序">
            <el-input-number v-model="modelForm.sortOrder" :min="0" class="oa-full-width" />
          </el-form-item>
        </el-col>
      </el-row>
      <template v-if="isComputerType(modelForm.typeId)">
        <el-row :gutter="12">
          <el-col :xs="24" :sm="12">
            <el-form-item label="入库日期">
              <el-date-picker
                v-model="modelForm.inboundDate"
                type="date"
                value-format="YYYY-MM-DD"
                class="oa-full-width"
              />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="批次">
              <el-input v-model="modelForm.batchKey" placeholder="留空表示不指定批次" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :xs="12" :sm="6">
            <el-form-item label="CPU"><el-input v-model="modelForm.cpu" placeholder="i5-14500HX" /></el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="内存"><el-input v-model="modelForm.memory" placeholder="16G" /></el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="存储"><el-input v-model="modelForm.storage" placeholder="512G" /></el-form-item>
          </el-col>
          <el-col :xs="12" :sm="6">
            <el-form-item label="显卡"><el-input v-model="modelForm.gpu" placeholder="RTX4060TI" /></el-form-item>
          </el-col>
        </el-row>
      </template>
      <el-alert
        v-else
        type="info"
        :closable="false"
        show-icon
        title="普通物资只记录型号与数量，入库日期与配置仅电脑类物资需要填写。"
      />
    </el-form>
  </FormDialog>
</template>

<style scoped>
/* 目录是「类型 → 品牌 → 型号」三层，缩进由 el-table 的树提供，
   这里补字重与底色，让层级和归属一眼可辨（不再给每行挂一个层级标签）。 */
.oa-inv-node {
  /* 关键：el-table 的缩进是 .cell 里的行内元素（indent + placeholder），
     插槽内容必须是行内级才会排在缩进后面；用 div（块级）会另起一行，
     缩进就完全看不到了。 */
  display: inline-flex;
  flex-direction: column;
  vertical-align: top;
}

.oa-inv-node__name {
  margin-right: var(--oa-space-1);
}

.oa-inv-node--type .oa-inv-node__name {
  font-weight: 600;
}

.oa-inv-node--brand .oa-inv-node__name {
  font-weight: 500;
}

.inventory-table :deep(.oa-inv-row--type) {
  --el-table-tr-bg-color: var(--el-fill-color-light);
}
</style>
