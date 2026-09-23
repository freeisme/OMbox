<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  EMPLOYEE_STATUS_OPTIONS,
  OFFBOARD_ACTIONS,
  emptyEmployeeForm,
  employeeUsageLabel,
  employeesToCsv,
  fetchOffboardingPreview,
  formFromEmployee,
  invalidateEmployeesCache,
  loadEmployeesData,
  offboardEmployee,
  allocateInventoryToEmployee,
  assignComputerToEmployee,
  releaseComputerFromEmployee,
  returnEmployeeUsage,
  saveEmployee,
  type EmployeeDetailRow,
  type EmployeeFormPayload,
  type OffboardItem,
  type OffboardPreview,
} from "../api/employees";
import type { ComputerRow } from "../api/state";
import { loadInventoryData, type InventoryData, type InventoryModelRow } from "../api/inventory";
import {
  fetchComputerBriefs,
  fetchComputerPage,
  type ComputerBriefRow,
} from "../api/lists";
import { statusLabel, statusTagType } from "../labels";
import { hasPermission } from "../session";
import { confirmAction } from "../composables/useConfirm";

interface OrgNode {
  id: string;
  code: string;
  name: string;
  parentId: string;
  sortOrder: number;
  children: OrgNode[];
  label: string;
}

interface OffboardRow {
  item: OffboardItem;
  action: string;
  targetEmployeeId: string;
  recoveryWarehouseId: string;
  note: string;
}

const loading = ref(true);
const saving = ref(false);
const employees = ref<EmployeeDetailRow[]>([]);
const orgs = ref<Array<{ id: string; code: string; name: string; parentId: string; sortOrder: number }>>([]);
/** 员工 → 名下终端（精简行：设备名 + 品牌型号）。不再整包下载全部终端。 */
const computerBriefsByEmployee = ref<Map<string, ComputerBriefRow[]>>(new Map());
/** 设备弹窗用的两个列表：打开弹窗时按需拉取。 */
const deviceComputers = ref<ComputerRow[]>([]);
const assignableComputers = ref<ComputerRow[]>([]);
const warehouses = ref<Array<{ id: string; name: string; code: string }>>([]);
const treeRef = ref();

const filters = reactive({
  keyword: "",
  assetKeyword: "",
  status: "",
  orgId: "",
});
const selectedIds = ref<string[]>([]);
const page = ref(1);
const pageSize = ref(50);

const formVisible = ref(false);
const editingId = ref("");
const form = reactive<EmployeeFormPayload>(emptyEmployeeForm());

const offboardVisible = ref(false);
const offboardingEmployeeId = ref("");
const offboardingName = ref("");
const offboardRows = ref<OffboardRow[]>([]);
const offboardForm = reactive({ leaveDate: "", leaveReason: "", leaveRemark: "" });

const orgTree = computed<OrgNode[]>(() => {
  const nodes = new Map<string, OrgNode>();
  orgs.value.forEach((item) =>
    nodes.set(item.id, { ...item, children: [], label: `${item.name}（${item.code}）` }),
  );
  const roots: OrgNode[] = [];
  orgs.value.forEach((item) => {
    const node = nodes.get(item.id);
    if (!node) return;
    const parent = item.parentId ? nodes.get(item.parentId) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  return roots;
});

const orgMaps = computed(() => {
  const nameOf = new Map<string, string>();
  const children = new Map<string, string[]>();
  orgs.value.forEach((item) => {
    nameOf.set(item.id, item.name);
    const parent = item.parentId || "";
    children.set(parent, [...(children.get(parent) ?? []), item.id]);
  });
  return { nameOf, children };
});

function deviceBriefsOf(employeeId: string): ComputerBriefRow[] {
  return computerBriefsByEmployee.value.get(employeeId) ?? [];
}

function collectOrgIds(rootId: string): Set<string> {
  const collected = new Set<string>();
  const walk = (id: string) => {
    if (collected.has(id)) return;
    collected.add(id);
    (orgMaps.value.children.get(id) ?? []).forEach(walk);
  };
  if (rootId) walk(rootId);
  return collected;
}

const filtered = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase();
  const assetKeyword = filters.assetKeyword.trim().toLowerCase();
  const scope = filters.orgId ? collectOrgIds(filters.orgId) : null;
  return employees.value.filter((row) => {
    if (filters.status && row.status !== filters.status) return false;
    if (scope && !scope.has(row.orgId)) return false;
    if (keyword) {
      const haystack = [row.name, row.employeeNo, row.department, orgNameOf(row.orgId)]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(keyword)) return false;
    }
    if (assetKeyword) {
      const assets = [...(row.monitors ?? []), ...(row.nonAssetItems ?? [])]
        .map((item) => `${item.typeName ?? ""} ${item.brand ?? ""} ${item.model ?? ""}`)
        .join(" ")
        .toLowerCase();
      const devices = deviceBriefsOf(row.id)
        .map((item) => `${item.deviceName} ${item.brand} ${item.model}`)
        .join(" ")
        .toLowerCase();
      if (!`${assets} ${devices}`.includes(assetKeyword)) return false;
    }
    return true;
  });
});

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return filtered.value.slice(start, start + pageSize.value);
});

const orgEmployeeCounts = computed(() => {
  const counts = new Map<string, number>();
  employees.value.forEach((row) => {
    const ids = collectOrgIds(row.orgId);
    ids.forEach((id) => counts.set(id, (counts.get(id) ?? 0) + 1));
  });
  return counts;
});

const receiverOptions = computed(() =>
  employees.value
    .filter((row) => ["active", "shared"].includes(row.status) && row.id !== offboardingEmployeeId.value)
    .map((row) => ({ value: row.id, label: `${row.name}（${row.employeeNo}）` })),
);

function orgNameOf(orgId: string): string {
  return orgMaps.value.nameOf.get(orgId) ?? "未分配";
}

function filterOrgNode(value: string, data: OrgNode): boolean {
  const key = String(value ?? "").trim().toLowerCase();
  if (!key) return true;
  return `${data.code} ${data.name}`.toLowerCase().includes(key);
}

async function load(force = false): Promise<void> {
  loading.value = true;
  try {
    const [data, deviceBriefs] = await Promise.all([
      loadEmployeesData(force),
      fetchComputerBriefs(),
    ]);
    employees.value = data.employees;
    orgs.value = data.orgs;
    warehouses.value = data.warehouses;
    computerBriefsByEmployee.value = deviceBriefs;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "人员数据加载失败。");
  } finally {
    loading.value = false;
  }
}

function openCreate(): void {
  editingId.value = "";
  Object.assign(form, emptyEmployeeForm(), { orgId: filters.orgId || "" });
  formVisible.value = true;
}

function openEdit(row: EmployeeDetailRow): void {
  editingId.value = row.id;
  Object.assign(form, formFromEmployee(row));
  formVisible.value = true;
}

async function submitForm(): Promise<void> {
  if (!form.name.trim() || !form.employeeNo.trim()) {
    ElMessage.warning("工号与姓名必填。");
    return;
  }
  if (!form.orgId) {
    ElMessage.warning("请选择所属组织。");
    return;
  }
  saving.value = true;
  try {
    await saveEmployee(
      {
        ...form,
        name: form.name.trim(),
        employeeNo: form.employeeNo.trim(),
      },
      editingId.value,
    );
    ElMessage.success(editingId.value ? "人员已更新。" : "人员已创建。");
    formVisible.value = false;
    invalidateEmployeesCache();
    await load(true);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败。");
  } finally {
    saving.value = false;
  }
}

async function openOffboard(row: EmployeeDetailRow): Promise<void> {
  try {
    const preview: OffboardPreview = await fetchOffboardingPreview(row.id);
    offboardingEmployeeId.value = row.id;
    offboardingName.value = `${row.name}（${row.employeeNo}）`;
    offboardRows.value = preview.items.map((item) => ({
      item,
      action: item.itemType === "computer" ? "" : "recover",
      targetEmployeeId: "",
      recoveryWarehouseId: warehouses.value[0]?.id ?? "",
      note: "",
    }));
    offboardForm.leaveDate = new Date().toISOString().slice(0, 10);
    offboardForm.leaveReason = "";
    offboardForm.leaveRemark = "";
    offboardVisible.value = true;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "无法获取离职预览。");
  }
}

async function submitOffboard(): Promise<void> {
  if (!offboardForm.leaveDate || !offboardForm.leaveReason.trim() || !offboardForm.leaveRemark.trim()) {
    ElMessage.warning("离职日期、离职原因和备注不能为空。");
    return;
  }
  for (const row of offboardRows.value) {
    if (!row.action) {
      ElMessage.warning(`请为「${row.item.label}」选择处理方式。`);
      return;
    }
    if (row.action === "recover" && !row.recoveryWarehouseId) {
      ElMessage.warning(`「${row.item.label}」选择回收时必须指定回收目标仓库。`);
      return;
    }
    if (row.action === "transfer" && !row.targetEmployeeId) {
      ElMessage.warning(`「${row.item.label}」选择转交他人时必须选择接收人员。`);
      return;
    }
    if (row.action === "exception" && !row.note.trim()) {
      ElMessage.warning(`「${row.item.label}」异常待处理必须填写说明。`);
      return;
    }
  }
  const confirmed = await confirmAction(
    `确认为 ${offboardingEmployeeId.value ? offboardingName.value : ""} 办理离职？名下资产与物资将按上面的清单处理。`,
    { title: "离职确认", confirmText: "确认办理", danger: true },
  );
  if (!confirmed) return;
  saving.value = true;
  try {
    await offboardEmployee(offboardingEmployeeId.value, {
      leaveDate: offboardForm.leaveDate,
      leaveReason: offboardForm.leaveReason.trim(),
      leaveRemark: offboardForm.leaveRemark.trim(),
      items: offboardRows.value.map((row) => ({
        itemType: row.item.itemType,
        itemId: row.item.id,
        action: row.action,
        note: row.note.trim(),
        targetEmployeeId: row.action === "transfer" ? row.targetEmployeeId : "",
        recoveryWarehouseId: row.action === "recover" ? row.recoveryWarehouseId : "",
      })),
    });
    ElMessage.success("已完成离职办理。");
    offboardVisible.value = false;
    invalidateEmployeesCache();
    await load(true);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "办理离职失败。");
  } finally {
    saving.value = false;
  }
}

function deviceSummary(row: EmployeeDetailRow): string {
  const parts = [
    ...deviceBriefsOf(row.id).map((item) => item.deviceName),
    ...(row.monitors ?? []).map(employeeUsageLabel),
    ...(row.nonAssetItems ?? []).map(employeeUsageLabel),
  ];
  return parts.length ? parts.join("；") : "暂无设备";
}

// ---------------------------------------------------------------- 人员设备清单

const deviceVisible = ref(false);
const deviceEmployee = ref<EmployeeDetailRow | null>(null);
const deviceSaving = ref(false);
const inventoryData = ref<InventoryData | null>(null);
const assignComputerId = ref("");

/** 领用表单：类型用真实物资类型（显示屏 / 鼠标 / 键盘…），型号可选库存型号或自定义。 */
const usageForm = reactive({
  typeId: "",
  modelId: "",
  customMode: false,
  brand: "",
  model: "",
  quantity: 1,
  warehouseId: "",
  notes: "",
});

/** 回收弹窗：选中某条物资点「回收」时才弹出，仓库必选（自定义物资也在这里选入库仓库）。 */
const recoverVisible = ref(false);
const recoverTarget = ref<{
  allocationType: "monitor" | "non_asset";
  usageId: string;
  label: string;
} | null>(null);
const recoverForm = reactive({ warehouseId: "", notes: "" });

const CUSTOM_MODEL_VALUE = "__custom__";

/**
 * 当前人员名下的办公终端 / 可分配的办公终端。
 * 这两份数据只在设备弹窗里用得到，打开弹窗时按需向服务端要，不再随页面整包加载。
 */
async function refreshDeviceComputers(): Promise<void> {
  const employee = deviceEmployee.value;
  if (!employee) {
    deviceComputers.value = [];
    assignableComputers.value = [];
    return;
  }
  try {
    const [owned, idle] = await Promise.all([
      fetchComputerPage({ userId: employee.id, pageSize: 0 }),
      // 可分配 = 没有使用人，且不是报废 / 丢失状态。
      fetchComputerPage({ unassigned: true, pageSize: 0 }),
    ]);
    deviceComputers.value = owned.items;
    assignableComputers.value = idle.items.filter(
      (item) => !["retired", "lost"].includes(item.status),
    );
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "终端列表加载失败。");
  }
}

const warehouseOptions = computed(() => inventoryData.value?.warehouses ?? []);

/** 是否还能给该人员分配 / 领用设备（离职、停用人员不行，与后端校验一致）。 */
const canAssignDevice = computed(() =>
  ["active", "shared"].includes(deviceEmployee.value?.status ?? ""),
);

function inventoryModelLabel(model: InventoryModelRow): string {
  const brand = inventoryData.value?.brands.find((item) => item.id === model.brandId)?.name ?? "";
  return [brand, model.name].filter(Boolean).join(" ") || model.name;
}

/** 显示屏类型在台账里存在非资产类型表，用类型编码而不是主键判断。 */
const monitorTypeIds = computed(
  () =>
    new Set(
      (inventoryData.value?.types ?? [])
        .filter((type) => String(type.code).toLowerCase() === "monitor")
        .map((type) => String(type.id)),
    ),
);

/** 领用类型下拉：台账里全部物资类型（显示屏 / 鼠标 / 键盘 / 拓展坞…），类型编码用于区分显示屏。 */
const usageTypeOptions = computed(() => inventoryData.value?.types ?? []);

/** 该类型是否属于"显示屏"——显示屏按单台登记，且发放走 monitor 通道。 */
const usageIsMonitor = computed(() => monitorTypeIds.value.has(String(usageForm.typeId)));

/** 领用提交时的 allocationType：显示屏走 monitor，其余都算 non_asset。 */
const usageAllocationType = computed<"monitor" | "non_asset">(() =>
  usageIsMonitor.value ? "monitor" : "non_asset",
);

/** 当前类型下、所选仓库有库存的型号；另提供"自定义（无库存记录）"这一项。 */
const usageModelOptions = computed(() => {
  const models = inventoryData.value?.models ?? [];
  const stocks = inventoryData.value?.stocks ?? [];
  const warehouseId = usageForm.warehouseId;
  return models
    .filter((model) => String(model.typeId) === String(usageForm.typeId))
    .map((model: InventoryModelRow) => {
      const available = warehouseId
        ? stocks.find(
            (stock) =>
              String(stock.modelId) === String(model.id) &&
              String(stock.warehouseId) === String(warehouseId),
          )?.quantity ?? 0
        : model.quantity;
      return { model, available: Number(available) || 0 };
    })
    .filter((entry) => entry.available > 0);
});

/** 切换类型后，原先选中的型号不再适用，清空避免提交错型号。 */
watch(
  () => usageForm.typeId,
  () => {
    usageForm.modelId = "";
    usageForm.customMode = false;
    usageForm.brand = "";
    usageForm.model = "";
    usageForm.quantity = 1;
  },
);

/** 型号下拉选到"自定义"时切到手工填写品牌型号。 */
watch(
  () => usageForm.modelId,
  (value) => {
    usageForm.customMode = value === CUSTOM_MODEL_VALUE;
  },
);

async function openDeviceManager(row: EmployeeDetailRow): Promise<void> {
  deviceEmployee.value = row;
  assignComputerId.value = "";
  recoverTarget.value = null;
  Object.assign(usageForm, {
    typeId: "",
    modelId: "",
    customMode: false,
    brand: "",
    model: "",
    quantity: 1,
    warehouseId: "",
    notes: "",
  });
  deviceVisible.value = true;
  try {
    if (!inventoryData.value) inventoryData.value = await loadInventoryData();
    Object.assign(usageForm, {
      typeId: inventoryData.value?.types[0]?.id ?? "",
      warehouseId: warehouseOptions.value[0]?.id ?? "",
    });
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "库存数据加载失败。");
  }
  await refreshDeviceComputers();
}

async function reloadEmployees(employeeId: string): Promise<void> {
  invalidateEmployeesCache();
  await load(true);
  const refreshed = employees.value.find((item) => item.id === employeeId);
  if (refreshed) deviceEmployee.value = refreshed;
  await refreshDeviceComputers();
}

async function submitAssignComputer(): Promise<void> {
  const employee = deviceEmployee.value;
  if (!employee || !assignComputerId.value) {
    ElMessage.warning("请选择要分配的办公终端。");
    return;
  }
  deviceSaving.value = true;
  try {
    await assignComputerToEmployee(assignComputerId.value, employee.id, "人员设备清单分配");
    ElMessage.success("办公终端已分配。");
    assignComputerId.value = "";
    await reloadEmployees(employee.id);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "分配失败。");
  } finally {
    deviceSaving.value = false;
  }
}

async function releaseComputer(row: ComputerRow): Promise<void> {
  const employee = deviceEmployee.value;
  if (!employee) return;
  const confirmed = await confirmAction(`解除「${row.deviceName}」与 ${employee.name} 的分配？`, {
    title: "解除分配",
    confirmText: "解除",
  });
  if (!confirmed) return;
  deviceSaving.value = true;
  try {
    await releaseComputerFromEmployee(row.id, "人员设备清单解除");
    ElMessage.success("已解除分配，设备回到闲置。");
    await reloadEmployees(employee.id);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "解除失败。");
  } finally {
    deviceSaving.value = false;
  }
}

async function submitAllocate(): Promise<void> {
  const employee = deviceEmployee.value;
  if (!employee) return;
  if (!usageForm.typeId) {
    ElMessage.warning("请选择物资类型。");
    return;
  }
  const custom = usageForm.modelId === CUSTOM_MODEL_VALUE;
  if (custom) {
    if (!usageForm.brand.trim() || !usageForm.model.trim()) {
      ElMessage.warning("自定义物资需要填写品牌与型号。");
      return;
    }
  } else if (!usageForm.modelId || !usageForm.warehouseId) {
    ElMessage.warning("请选择库存型号与出库仓库。");
    return;
  }
  deviceSaving.value = true;
  try {
    await allocateInventoryToEmployee({
      allocationType: usageAllocationType.value,
      employeeId: employee.id,
      // 显示屏按单台登记，后端也会拒绝 quantity !== 1。
      quantity: usageIsMonitor.value ? 1 : Number(usageForm.quantity) || 1,
      notes: usageForm.notes.trim(),
      ...(custom
        ? {
            // 自定义物资不扣库存；回收时按品牌型号自动补进目录并入库
            typeId: usageForm.typeId,
            brand: usageForm.brand.trim(),
            model: usageForm.model.trim(),
            displayName: usageForm.brand.trim(),
            stockAdjusted: false,
          }
        : { modelId: usageForm.modelId, warehouseId: usageForm.warehouseId }),
    });
    ElMessage.success(
      custom ? "自定义物资已登记（未扣库存，回收时入库）。" : "领用已登记。",
    );
    Object.assign(usageForm, {
      modelId: "",
      customMode: false,
      brand: "",
      model: "",
      quantity: 1,
      notes: "",
    });
    await reloadEmployees(employee.id);
    inventoryData.value = await loadInventoryData(true);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "领用失败。");
  } finally {
    deviceSaving.value = false;
  }
}

/** 点某条物资的「回收」时才弹出回收弹窗：现场选入库仓库（自定义物资也在这里选）。 */
function openRecoverDialog(
  allocationType: "monitor" | "non_asset",
  usageId: string,
  label: string,
): void {
  recoverTarget.value = { allocationType, usageId, label };
  recoverForm.warehouseId = warehouseOptions.value[0]?.id ?? "";
  recoverForm.notes = "";
  recoverVisible.value = true;
}

async function submitRecover(): Promise<void> {
  const employee = deviceEmployee.value;
  const target = recoverTarget.value;
  if (!employee || !target) return;
  if (!recoverForm.warehouseId) {
    ElMessage.warning("请选择回收入库的仓库。");
    return;
  }
  deviceSaving.value = true;
  try {
    await returnEmployeeUsage(
      employee.id,
      target.allocationType,
      target.usageId,
      recoverForm.warehouseId,
      recoverForm.notes.trim(),
    );
    ElMessage.success("已回收并入库。");
    recoverVisible.value = false;
    recoverTarget.value = null;
    await reloadEmployees(employee.id);
    inventoryData.value = await loadInventoryData(true);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "回收失败。");
  } finally {
    deviceSaving.value = false;
  }
}

function exportSelected(): void {
  const rows = employees.value.filter((row) => selectedIds.value.includes(row.id));
  if (!rows.length) {
    ElMessage.warning("请先选择要导出的人员。");
    return;
  }
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  const csv = employeesToCsv(
    rows,
    orgNameOf,
    (employeeId) => deviceBriefsOf(employeeId).map((item) => item.deviceName),
  );
  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `使用人员-${stamp}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function onSelectionChange(rows: EmployeeDetailRow[]): void {
  selectedIds.value = rows.map((row) => row.id);
}

function selectAllFiltered(): void {
  const ids = new Set(selectedIds.value);
  filtered.value.forEach((row) => ids.add(row.id));
  selectedIds.value = [...ids];
}

function clearFilters(): void {
  filters.keyword = "";
  filters.assetKeyword = "";
  filters.status = "";
  filters.orgId = "";
  treeRef.value?.filter("");
}

function expandAll(value: boolean): void {
  const nodes = treeRef.value?.store?.nodesMap ?? {};
  Object.values(nodes).forEach((node: any) => {
    node.expanded = value;
  });
}

onMounted(async () => {
  await load(false);
});
</script>

<template>
  <PageHeader
    title="办公设备使用人员"
    description="按组织架构查看人员，并直接看到名下的办公终端、显示屏与非资产物资"
  >
    <template #actions>
        <el-button @click="selectAllFiltered">全选当前结果</el-button>
        <el-button @click="selectedIds = []">清空选择</el-button>
        <el-button :disabled="!selectedIds.length" @click="exportSelected">
          导出选中 {{ selectedIds.length }}
        </el-button>
        <el-button v-if="hasPermission('employees', 'create')" type="primary" @click="openCreate">
          ＋ 新增人员
        </el-button>
    </template>
    <template #filters>
      <FilterBar
        :summary="`显示 ${filtered.length} / ${employees.length} 人`"
        :resettable="Boolean(filters.keyword || filters.assetKeyword || filters.status || filters.orgId)"
        @reset="clearFilters"
      >
    <el-form label-position="top" class="oa-filter-form" @submit.prevent>
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12" :md="8">
          <el-form-item label="人员关键字">
            <el-input v-model="filters.keyword" placeholder="姓名、工号、部门或组织" clearable />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12" :md="6">
          <el-form-item label="IT 物资">
            <el-input v-model="filters.assetKeyword" placeholder="品牌或型号" clearable />
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <el-form-item label="状态">
            <el-select v-model="filters.status" placeholder="全部" clearable class="oa-full-width">
              <el-option
                v-for="status in EMPLOYEE_STATUS_OPTIONS"
                :key="status"
                :label="statusLabel(status)"
                :value="status"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6" :md="6">
          <el-form-item label="组织">
            <el-tree-select
              v-model="filters.orgId"
              :data="orgTree"
              check-strictly
              clearable
              placeholder="全部组织（含下级）"
              class="oa-full-width"
            />
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>
      </FilterBar>
    </template>
  </PageHeader>

  <el-row :gutter="12" class="oa-panel-gap">
    <el-col :xs="24" :md="8">
      <DataPanel title="组织架构" :loading="loading">
        <template #actions>
          <el-button link size="small" @click="expandAll(true)">全部展开</el-button>
          <el-button link size="small" @click="expandAll(false)">全部收起</el-button>
        </template>
        <el-input
          v-model="filters.keyword"
          placeholder="过滤组织"
          clearable
          class="oa-filter-input"
          @input="treeRef?.filter(filters.keyword)"
        />
        <el-tree
          ref="treeRef"
          :data="orgTree"
          node-key="id"
          default-expand-all
          :expand-on-click-node="false"
          :filter-node-method="filterOrgNode"
          empty-text="暂无组织"
          @node-click="(data: OrgNode) => (filters.orgId = data.id)"
        >
          <template #default="{ data }">
            <span class="oa-flex-between">
              <span>{{ data.name }}</span>
              <span class="oa-cell-sub">
                {{ orgEmployeeCounts.get(data.id) ?? 0 }} 人
              </span>
            </span>
          </template>
        </el-tree>
      </DataPanel>
    </el-col>
    <el-col :xs="24" :md="16">
      <DataPanel title="人员清单" :loading="loading">
        <el-table
          :data="paged"
          row-key="id"
          class="employees-table"
          size="small"
          border
          stripe
          empty-text="暂无符合条件的人员"
          @selection-change="onSelectionChange"
        >
          <el-table-column type="selection" width="48" reserve-selection />
          <el-table-column label="人员" min-width="150">
            <template #default="{ row }">
              <div>{{ row.name }}</div>
              <div class="oa-cell-sub">{{ row.employeeNo }}</div>
            </template>
          </el-table-column>
          <el-table-column label="组织 / 部门" min-width="170">
            <template #default="{ row }">
              <div>{{ orgNameOf(row.orgId) }}</div>
              <div class="oa-cell-sub">{{ row.department || "—" }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="position" label="岗位" width="120" />
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.status)">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="名下设备" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">{{ deviceSummary(row) }}</template>
          </el-table-column>
          <!-- 操作列宽度按实测给足：176px 时「设备 / 编辑 / 办理离职」三个按钮会换行，
               把整行顶到 41px；210px 下单行显示，全表回到 32px 紧凑行高。 -->
          <el-table-column label="操作" width="210" fixed="right" align="center">
            <template #default="{ row }">
              <el-button
                v-if="hasPermission('employees', 'view')"
                link
                @click="openDeviceManager(row)"
              >
                设备
              </el-button>
              <el-button
                v-if="hasPermission('employees', 'update')"
                link
                type="primary"
                @click="openEdit(row)"
              >
                编辑
              </el-button>
              <el-button
                v-if="hasPermission('employees', 'update')"
                link
                type="danger"
                @click="openOffboard(row)"
              >
                {{ row.status === "shared" ? "删除" : "办理离职" }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          :total="filtered.length"
          layout="total, sizes, prev, pager, next"
          class="oa-pagination"
        />
      </DataPanel>
    </el-col>
  </el-row>

  <FormDialog
    v-model="formVisible"
    :title="editingId ? '编辑人员' : '新增人员'"
    size="lg"
    :loading="saving"
    @confirm="submitForm"
  >
    <el-form label-position="top">
      <el-row :gutter="12">
        <el-col :xs="12" :md="8">
          <el-form-item label="工号" required>
            <el-input v-model="form.employeeNo" placeholder="公用人员可留空自动生成" />
          </el-form-item>
        </el-col>
        <el-col :xs="12" :md="8">
          <el-form-item label="姓名" required><el-input v-model="form.name" /></el-form-item>
        </el-col>
        <el-col :xs="12" :md="8">
          <el-form-item label="状态">
            <el-select v-model="form.status" class="oa-full-width">
              <el-option label="在职" value="active" />
              <el-option label="停用" value="inactive" />
              <el-option label="公用" value="shared" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-form-item label="所属组织" required>
            <el-tree-select
              v-model="form.orgId"
              :data="orgTree"
              check-strictly
              placeholder="选择组织"
              class="oa-full-width"
            />
          </el-form-item>
        </el-col>
        <el-col :xs="12" :md="6">
          <el-form-item label="部门"><el-input v-model="form.department" /></el-form-item>
        </el-col>
        <el-col :xs="12" :md="6">
          <el-form-item label="岗位"><el-input v-model="form.position" /></el-form-item>
        </el-col>
        <el-col :xs="12" :md="6">
          <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
        </el-col>
        <el-col :xs="12" :md="6">
          <el-form-item label="手机"><el-input v-model="form.mobile" /></el-form-item>
        </el-col>
      </el-row>
      <el-alert
        v-if="form.status === 'shared'"
        type="info"
        :closable="false"
        show-icon
        title="公用人员用于挂靠非个人使用的设备，不能绑定登录账号，工号留空会按组织自动生成。"
      />
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="offboardVisible"
    :title="`办理离职 · ${offboardingName}`"
    size="xl"
    confirm-text="确认办理离职"
    confirm-type="danger"
    :loading="saving"
    @confirm="submitOffboard"
  >
    <el-form label-position="top">
      <el-row :gutter="12">
        <el-col :xs="24" :md="8">
          <el-form-item label="离职日期" required>
            <el-date-picker v-model="offboardForm.leaveDate" type="date" value-format="YYYY-MM-DD" class="oa-full-width" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="8">
          <el-form-item label="离职原因" required>
            <el-input v-model="offboardForm.leaveReason" placeholder="例如 个人原因" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="8">
          <el-form-item label="备注" required>
            <el-input v-model="offboardForm.leaveRemark" placeholder="补充说明" />
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>
    <el-table :data="offboardRows" size="small" border empty-text="该人员名下没有需要处理的资产或物资">
      <el-table-column label="资产 / 物资" min-width="180">
        <template #default="{ row }">
          <div>{{ row.item.label }}</div>
          <div class="oa-cell-sub">
            {{ row.item.detail || row.item.itemType }} ×{{ row.item.quantity }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="处理方式" width="150">
        <template #default="{ row }">
          <el-select v-model="row.action" placeholder="请选择" class="oa-full-width">
            <el-option
              v-for="action in OFFBOARD_ACTIONS"
              :key="action.value"
              :label="action.label"
              :value="action.value"
            />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="回收仓库 / 接收人" width="220">
        <template #default="{ row }">
          <el-select
            v-if="row.action === 'recover'"
            v-model="row.recoveryWarehouseId"
            placeholder="回收目标仓库"
            class="oa-full-width"
          >
            <el-option
              v-for="warehouse in warehouses"
              :key="warehouse.id"
              :label="warehouse.name"
              :value="warehouse.id"
            />
          </el-select>
          <el-select
            v-else-if="row.action === 'transfer'"
            v-model="row.targetEmployeeId"
            filterable
            placeholder="接收人"
            class="oa-full-width"
          >
            <el-option
              v-for="option in receiverOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <span v-else class="oa-cell-sub">—</span>
        </template>
      </el-table-column>
      <el-table-column label="处理说明" min-width="200">
        <template #default="{ row }">
          <el-input
            v-model="row.note"
            size="small"
            :placeholder="row.action === 'exception' ? '异常待处理必填' : '可选'"
          />
        </template>
      </el-table-column>
    </el-table>
  </FormDialog>

  <FormDialog
    v-model="deviceVisible"
    :title="`设备清单 · ${deviceEmployee?.name ?? ''}`"
    size="xl"
  >
    <p style="margin: 0 0 8px; color: var(--el-text-color-secondary); font-size: 13px">
      {{ deviceEmployee?.employeeNo }} ·
      {{ deviceEmployee ? orgNameOf(deviceEmployee.orgId) : "" }} ·
      {{ deviceEmployee?.department || "未填写部门" }}
    </p>
    <el-alert
      v-if="!canAssignDevice"
      type="info"
      :closable="false"
      show-icon
      title="该人员已离职或停用，只能查看与回收名下设备。"
      class="oa-mb-2"
    />

    <el-divider content-position="left">办公终端 · {{ deviceComputers.length }} 台</el-divider>
    <el-table :data="deviceComputers" size="small" border empty-text="当前没有分配办公终端">
      <el-table-column label="设备" min-width="180">
        <template #default="{ row }">
          <div>{{ row.deviceName }}</div>
          <div class="oa-cell-sub">
            {{ [row.brand, row.model].filter(Boolean).join(" ") || "未填写品牌型号" }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTagType(row.status)">
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button link type="danger" :loading="deviceSaving" @click="releaseComputer(row)">
            解除
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="oa-flex-row oa-mt-2">
      <el-select
        v-model="assignComputerId"
        filterable
        clearable
        :disabled="!canAssignDevice"
        placeholder="选择一台可分配办公终端"
        class="oa-flex-1"
      >
        <el-option
          v-for="item in assignableComputers"
          :key="item.id"
          :label="`${item.deviceName} · ${item.model || '未填写型号'}`"
          :value="item.id"
        />
      </el-select>
      <el-button
        type="primary"
        :disabled="!canAssignDevice"
        :loading="deviceSaving"
        @click="submitAssignComputer"
      >
        分配
      </el-button>
    </div>

    <el-divider content-position="left">
      显示屏 · {{ (deviceEmployee?.monitors ?? []).length }} 项
    </el-divider>
    <el-table
      :data="deviceEmployee?.monitors ?? []"
      size="small"
      border
      empty-text="暂无显示屏"
    >
      <el-table-column label="品牌型号" min-width="220">
        <template #default="{ row }">{{ employeeUsageLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button
            link
            type="danger"
            :loading="deviceSaving"
            @click="openRecoverDialog('monitor', row.id ?? '', employeeUsageLabel(row))"
          >
            回收
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-divider content-position="left">
      非资产设备 · {{ (deviceEmployee?.nonAssetItems ?? []).length }} 项
    </el-divider>
    <el-table
      :data="deviceEmployee?.nonAssetItems ?? []"
      size="small"
      border
      empty-text="无非资产设备"
    >
      <el-table-column label="类型 / 品牌型号" min-width="220">
        <template #default="{ row }">{{ employeeUsageLabel(row) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button
            link
            type="danger"
            :loading="deviceSaving"
            @click="openRecoverDialog('non_asset', row.id ?? '', employeeUsageLabel(row))"
          >
            回收
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-divider content-position="left">领用设备 / 物资</el-divider>
    <el-form label-position="top">
      <el-row :gutter="12">
        <el-col :xs="12" :sm="5">
          <el-form-item label="类型" required>
            <el-select v-model="usageForm.typeId" filterable class="oa-full-width">
              <el-option
                v-for="type in usageTypeOptions"
                :key="type.id"
                :label="type.name"
                :value="type.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col v-if="!usageForm.customMode" :xs="12" :sm="5">
          <el-form-item label="出库仓库">
            <el-select v-model="usageForm.warehouseId" clearable class="oa-full-width">
              <el-option
                v-for="warehouse in warehouseOptions"
                :key="warehouse.id"
                :label="warehouse.name"
                :value="warehouse.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="usageForm.customMode ? 10 : 8">
          <el-form-item label="型号">
            <el-select
              v-model="usageForm.modelId"
              filterable
              clearable
              placeholder="选择库存型号，或选「自定义」手工填写"
              class="oa-full-width"
            >
              <el-option
                v-for="option in usageModelOptions"
                :key="option.model.id"
                :label="`${inventoryModelLabel(option.model)} · 库存 ${option.available}`"
                :value="option.model.id"
              />
              <el-option
                label="自定义（无库存记录，回收时入库）"
                :value="CUSTOM_MODEL_VALUE"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="3">
          <el-form-item label="数量">
            <el-input-number
              v-model="usageForm.quantity"
              :min="1"
              :disabled="usageIsMonitor"
              class="oa-full-width"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row v-if="usageForm.customMode" :gutter="12">
        <el-col :xs="12" :sm="6">
          <el-form-item label="品牌" required>
            <el-input v-model="usageForm.brand" placeholder="例如 罗技" />
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-form-item label="型号" required>
            <el-input v-model="usageForm.model" placeholder="例如 M185" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12">
          <div class="oa-hint">
            自定义物资没有出库记录，不扣库存；回收时按填写的品牌型号自动补进目录并入库到所选仓库。
          </div>
        </el-col>
      </el-row>
      <el-form-item label="备注">
        <el-input v-model="usageForm.notes" placeholder="可选" />
      </el-form-item>
      <el-button
        type="primary"
        :disabled="!canAssignDevice"
        :loading="deviceSaving"
        @click="submitAllocate"
      >
        ＋ 领用
      </el-button>
    </el-form>

    <template #footer>
      <el-button @click="deviceVisible = false">关闭</el-button>
    </template>
  </FormDialog>

  <FormDialog
    v-model="recoverVisible"
    :title="`回收物资 · ${recoverTarget?.label ?? ''}`"
    size="sm"
    confirm-text="确认回收"
    confirm-type="danger"
    :loading="deviceSaving"
    @confirm="submitRecover"
  >
    <el-form label-position="top">
      <el-form-item label="回收入库仓库" required>
        <el-select v-model="recoverForm.warehouseId" class="oa-full-width" placeholder="请选择仓库">
          <el-option
            v-for="warehouse in warehouseOptions"
            :key="warehouse.id"
            :label="warehouse.name"
            :value="warehouse.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="回收备注">
        <el-input v-model="recoverForm.notes" placeholder="例如 离职回收 / 换机回收" />
      </el-form-item>
      <div class="oa-hint">
        回收后物资进入所选仓库库存；自定义物资若目录里没有对应品牌型号，会自动创建。
      </div>
    </el-form>
  </FormDialog>
</template>

<style scoped>
/* 人员清单的单元格里有两行文本，单独放宽左右内边距，行高仍由令牌统一控制。 */
.employees-table :deep(.el-table__cell .cell) {
  padding: 0 14px;
}

.employees-table :deep(.el-table__cell .el-button + .el-button) {
  margin-left: 10px;
}
</style>
