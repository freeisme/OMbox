<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  COMPUTER_STATUS_OPTIONS,
  computersToCsv,
  emptyComputerForm,
  fetchScrapReasons,
  formFromComputer,
  invalidateComputersCache,
  loadComputersData,
  saveComputer,
  scrapComputer,
  type ComputerFormPayload,
  type ScrapReason,
} from "../api/computers";
import { fetchComputerPage } from "../api/lists";
import type { ComputerRow } from "../api/state";
import DataPanel from "../components/ui/DataPanel.vue";
import FilterBar from "../components/ui/FilterBar.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import { confirmAction } from "../composables/useConfirm";
import { deviceTypeLabel, statusLabel, statusTagType } from "../labels";
import { hasPermission } from "../session";

const loading = ref(true);
const saving = ref(false);
const scrapping = ref(false);
// 服务端分页：rows 是当前页，total 是匹配总数。
const rows = ref<ComputerRow[]>([]);
const total = ref(0);
const orgs = ref<Array<{ id: string; code: string; name: string; parentId: string }>>([]);
const employees = ref<Array<{ id: string; name: string; employeeNo: string }>>([]);
const warehouses = ref<Array<{ id: string; name: string; code: string; isActive: unknown }>>([]);
const inventoryModels = ref<Array<{ id: string; name: string; quantity: unknown }>>([]);
const scrapReasons = ref<ScrapReason[]>([]);

const filters = reactive({ keyword: "", status: "", orgId: "" });
const selectedIds = ref<string[]>([]);
const page = ref(1);
const pageSize = ref(50);
/** 已加载过的行，供跨页选择后导出使用。 */
const rowCache = new Map<string, ComputerRow>();
let searchTimer: number | undefined;

const formVisible = ref(false);
const editingId = ref("");
const form = reactive<ComputerFormPayload>(emptyComputerForm());

const scrapVisible = ref(false);
const scrapTarget = ref<ComputerRow | null>(null);
const scrapForm = reactive({ reasonCode: "", notes: "" });

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

const employeeMap = computed(
  () => new Map(employees.value.map((item) => [item.id, item.name] as const)),
);

const orgTree = computed(() => {
  const nodes = new Map<string, { value: string; label: string; children: unknown[] }>();
  orgs.value.forEach((item) =>
    nodes.set(item.id, { value: item.id, label: `${item.name}（${item.code}）`, children: [] }),
  );
  const roots: unknown[] = [];
  orgs.value.forEach((item) => {
    const node = nodes.get(item.id);
    if (!node) return;
    const parent = item.parentId ? nodes.get(item.parentId) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  return roots;
});

const selectedComputers = computed(() =>
  selectedIds.value.map((id) => rowCache.get(id)).filter((row): row is ComputerRow => Boolean(row)),
);

function orgNameOf(orgId: string): string {
  return orgMaps.value.nameOf.get(orgId) ?? "—";
}

function userNameOf(userId: string): string {
  return employeeMap.value.get(userId) ?? "未分配";
}

function hardwareSummary(row: ComputerRow): string {
  return [deviceTypeLabel(row.deviceType), [row.brand, row.model].filter(Boolean).join(" ")]
    .filter(Boolean)
    .join(" · ");
}

async function load(force = false): Promise<void> {
  loading.value = true;
  try {
    const data = await loadComputersData(force);
    orgs.value = data.orgs;
    employees.value = data.employees;
    warehouses.value = data.warehouses;
    inventoryModels.value = data.inventoryModels;
    await loadRows();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "终端数据加载失败。");
  } finally {
    loading.value = false;
  }
}

/** 拉取当前页；过滤条件与分页都由服务端处理，前端不做二次过滤。 */
async function loadRows(): Promise<void> {
  try {
    const payload = await fetchComputerPage({
      page: page.value,
      pageSize: pageSize.value,
      keyword: filters.keyword.trim(),
      status: filters.status,
      orgId: filters.orgId,
    });
    rows.value = payload.items;
    total.value = payload.total;
    payload.items.forEach((row) => rowCache.set(row.id, row));
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "终端列表加载失败。");
  }
}

function scheduleReload(): void {
  if (searchTimer) window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    page.value = 1;
    void loadRows();
  }, 250);
}

watch(
  () => filters.keyword,
  () => scheduleReload(),
);

watch(
  () => [filters.status, filters.orgId] as const,
  () => {
    page.value = 1;
    void loadRows();
  },
);

watch(
  () => [page.value, pageSize.value] as const,
  () => {
    void loadRows();
  },
);

function openCreate(): void {
  editingId.value = "";
  Object.assign(form, emptyComputerForm());
  formVisible.value = true;
}

function openEdit(row: ComputerRow): void {
  editingId.value = row.id;
  Object.assign(form, formFromComputer(row));
  formVisible.value = true;
}

async function submitForm(): Promise<void> {
  if (!form.deviceName.trim()) {
    ElMessage.warning("请填写设备名。");
    return;
  }
  if (!form.orgId) {
    ElMessage.warning("请选择所属组织。");
    return;
  }
  if (!editingId.value && form.registrationMode === "warehouse") {
    if (!form.inventoryModelId || !form.warehouseId) {
      ElMessage.warning("从库存登记需要选择库存型号与入库仓库。");
      return;
    }
  }
  saving.value = true;
  try {
    await saveComputer({ ...form, deviceName: form.deviceName.trim() }, editingId.value);
    ElMessage.success(editingId.value ? "办公终端已更新。" : "办公终端已创建。");
    formVisible.value = false;
    invalidateComputersCache();
    await load(true);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败。");
  } finally {
    saving.value = false;
  }
}

async function openScrap(row: ComputerRow): Promise<void> {
  scrapTarget.value = row;
  scrapForm.reasonCode = scrapReasons.value[0]?.code ?? "";
  scrapForm.notes = "";
  if (!scrapReasons.value.length) {
    try {
      scrapReasons.value = await fetchScrapReasons();
      scrapForm.reasonCode = scrapReasons.value[0]?.code ?? "";
    } catch {
      // 原因列表拉取失败时仍允许填写说明后提交
    }
  }
  scrapVisible.value = true;
}

async function submitScrap(): Promise<void> {
  const target = scrapTarget.value;
  if (!target) return;
  if (!scrapForm.reasonCode && !scrapForm.notes.trim()) {
    ElMessage.warning("请选择报废原因或填写说明。");
    return;
  }
  const confirmed = await confirmAction(
    `确认报废「${target.deviceName}」？该设备不会回收库存，但会保留审计记录。`,
    { title: "报废确认", confirmText: "确认报废", danger: true },
  );
  if (!confirmed) return;
  scrapping.value = true;
  try {
    await scrapComputer(target.id, {
      reasonCode: scrapForm.reasonCode,
      notes: scrapForm.notes.trim(),
    });
    ElMessage.success("已完成报废登记。");
    scrapVisible.value = false;
    invalidateComputersCache();
    await load(true);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "报废失败。");
  } finally {
    scrapping.value = false;
  }
}

function exportSelected(): void {
  if (!selectedComputers.value.length) {
    ElMessage.warning("请先选择要导出的终端。");
    return;
  }
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  const csv = computersToCsv(selectedComputers.value, orgNameOf, userNameOf);
  const blob = new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `办公终端-${stamp}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

/** 全选"当前筛选结果"：需要全部 id，因此单独向服务端要一次不分页的数据。 */
async function selectAllFiltered(): Promise<void> {
  try {
    const payload = await fetchComputerPage({
      pageSize: 0,
      keyword: filters.keyword.trim(),
      status: filters.status,
      orgId: filters.orgId,
    });
    const ids = new Set(selectedIds.value);
    payload.items.forEach((row) => {
      rowCache.set(row.id, row);
      ids.add(row.id);
    });
    selectedIds.value = [...ids];
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "全选失败。");
  }
}

function clearSelection(): void {
  selectedIds.value = [];
}

function clearFilters(): void {
  filters.keyword = "";
  filters.status = "";
  filters.orgId = "";
  page.value = 1;
}

function onSelectionChange(rows: ComputerRow[]): void {
  selectedIds.value = rows.map((row) => row.id);
}

onMounted(async () => {
  await load(false);
  try {
    scrapReasons.value = await fetchScrapReasons();
  } catch {
    // 报废原因后续在打开弹窗时再取
  }
});
</script>

<template>
  <PageHeader
    title="办公终端台账"
    :description="`按筛选条件统计，共 ${total} 台；列表由服务端分页返回，翻页不会再整包拉取数据`"
  >
    <template #actions>
      <el-button @click="selectAllFiltered">全选当前结果</el-button>
      <el-button @click="clearSelection">清空选择</el-button>
      <el-button :disabled="!selectedIds.length" @click="exportSelected">
        导出选中 {{ selectedIds.length }}
      </el-button>
      <el-button v-if="hasPermission('it_assets', 'create')" type="primary" @click="openCreate">
        ＋ 新增办公终端
      </el-button>
    </template>
    <template #filters>
      <FilterBar :summary="`匹配 ${total} 台 · 本页 ${rows.length} 台`" :resettable="Boolean(filters.keyword || filters.status || filters.orgId)" @reset="clearFilters">
        <el-form label-position="top" class="oa-filter-form" @submit.prevent>
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12" :md="8">
          <el-form-item label="关键字">
            <el-input
              v-model="filters.keyword"
              placeholder="设备名、型号、固资编码、SN/ST、组织或使用人"
              clearable
            />
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6" :md="4">
          <el-form-item label="状态">
            <el-select v-model="filters.status" placeholder="全部状态" clearable class="oa-full-width">
              <el-option
                v-for="status in COMPUTER_STATUS_OPTIONS"
                :key="status"
                :label="statusLabel(status)"
                :value="status"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6" :md="6">
          <el-form-item label="所属组织">
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

  <DataPanel class="oa-panel-gap" :loading="loading">
    <el-table
      :data="rows"
      row-key="id"
      size="small"
      border
      stripe
      empty-text="暂无符合条件的办公终端"
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="44" reserve-selection />
      <el-table-column prop="deviceName" label="设备名" min-width="150" show-overflow-tooltip />
      <el-table-column label="所属组织" min-width="130" show-overflow-tooltip>
        <template #default="{ row }">{{ orgNameOf(row.orgId) }}</template>
      </el-table-column>
      <el-table-column label="设备类型 / 品牌型号" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">{{ hardwareSummary(row) || "—" }}</template>
      </el-table-column>
      <el-table-column prop="fixedAssetCode" label="固资编码" min-width="110" show-overflow-tooltip />
      <el-table-column prop="snSt" label="SN/ST" min-width="110" show-overflow-tooltip />
      <el-table-column prop="location" label="位置" min-width="110" show-overflow-tooltip />
      <el-table-column label="使用用户" width="110" show-overflow-tooltip>
        <template #default="{ row }">{{ userNameOf(row.userId) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button v-if="hasPermission('it_assets', 'update')" link type="primary" @click="openEdit(row)">
            编辑
          </el-button>
          <el-button
            v-if="hasPermission('scrap_management', 'create')"
            link
            type="danger"
            @click="openScrap(row)"
          >
            报废
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :page-sizes="[20, 50, 100, 200]"
      :total="total"
      layout="total, sizes, prev, pager, next"
      class="oa-pagination"
    />
  </DataPanel>

  <FormDialog
    v-model="formVisible"
    :title="editingId ? '编辑办公终端' : '新增办公终端'"
    size="xl"
    :loading="saving"
    @confirm="submitForm"
  >
    <el-form label-position="top">
      <el-row :gutter="12">
        <el-col :xs="24" :md="8">
          <el-form-item label="设备名" required>
            <el-input v-model="form.deviceName" placeholder="例如 IT-PC-01" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="8">
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
        <el-col :xs="12" :md="4">
          <el-form-item label="设备类型">
            <el-select v-model="form.deviceType" class="oa-full-width">
              <el-option label="台式机" value="desktop" />
              <el-option label="笔记本" value="laptop" />
              <el-option label="工作站" value="workstation" />
              <el-option label="迷你主机" value="mini_pc" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="12" :md="4">
          <el-form-item label="状态">
            <el-select v-model="form.status" class="oa-full-width">
              <el-option
                v-for="status in COMPUTER_STATUS_OPTIONS"
                :key="status"
                :label="statusLabel(status)"
                :value="status"
              />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>

      <el-row v-if="!editingId" :gutter="12">
        <el-col :xs="24" :md="8">
          <el-form-item label="登记方式">
            <el-radio-group v-model="form.registrationMode">
              <el-radio-button value="custom">自定义登记</el-radio-button>
              <el-radio-button value="warehouse">从库存登记</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-col>
        <template v-if="form.registrationMode === 'warehouse'">
          <el-col :xs="24" :md="8">
            <el-form-item label="库存型号" required>
              <el-select v-model="form.inventoryModelId" filterable class="oa-full-width">
                <el-option
                  v-for="model in inventoryModels"
                  :key="model.id"
                  :label="`${model.name}（库存 ${model.quantity}）`"
                  :value="model.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="8">
            <el-form-item label="入库仓库" required>
              <el-select v-model="form.warehouseId" filterable class="oa-full-width">
                <el-option
                  v-for="warehouse in warehouses"
                  :key="warehouse.id"
                  :label="warehouse.name"
                  :value="warehouse.id"
                />
              </el-select>
            </el-form-item>
          </el-col>
        </template>
      </el-row>

      <el-row :gutter="12">
        <el-col :xs="12" :md="6"><el-form-item label="品牌"><el-input v-model="form.brand" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="型号"><el-input v-model="form.model" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="固资编码"><el-input v-model="form.fixedAssetCode" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="SN/ST"><el-input v-model="form.snSt" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="CPU"><el-input v-model="form.cpu" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="内存"><el-input v-model="form.memory" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="存储"><el-input v-model="form.storage" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="显卡"><el-input v-model="form.gpu" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="Wifi MAC"><el-input v-model="form.wifiMac" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="网口 MAC"><el-input v-model="form.ethernetMac" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="位置"><el-input v-model="form.location" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="部门"><el-input v-model="form.department" /></el-form-item></el-col>
        <el-col :xs="12" :md="6"><el-form-item label="岗位"><el-input v-model="form.position" /></el-form-item></el-col>
        <el-col :xs="12" :md="6">
          <el-form-item label="购置日期">
            <el-date-picker v-model="form.purchaseDate" type="date" value-format="YYYY-MM-DD" class="oa-full-width" />
          </el-form-item>
        </el-col>
        <el-col :xs="12" :md="6">
          <el-form-item label="注册日期">
            <el-date-picker v-model="form.registeredDate" type="date" value-format="YYYY-MM-DD" class="oa-full-width" />
          </el-form-item>
        </el-col>
        <el-col :xs="24" :md="12">
          <el-form-item label="备注"><el-input v-model="form.remarks" /></el-form-item>
        </el-col>
      </el-row>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="使用人请通过「分配 / 领用」流程绑定，本表单只维护资产属性。"
      />
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="scrapVisible"
    title="报废登记"
    size="sm"
    confirm-text="确认报废"
    confirm-type="danger"
    :loading="scrapping"
    @confirm="submitScrap"
  >
    <p class="oa-mt-0">
      设备：<strong>{{ scrapTarget?.deviceName }}</strong>
      （{{ hardwareSummary(scrapTarget ?? ({} as ComputerRow)) || "—" }}）
    </p>
    <el-form label-position="top">
      <el-form-item label="报废原因">
        <el-select v-model="scrapForm.reasonCode" placeholder="选择报废原因" class="oa-full-width">
          <el-option
            v-for="reason in scrapReasons"
            :key="reason.code"
            :label="reason.name"
            :value="reason.code"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="说明">
        <el-input v-model="scrapForm.notes" type="textarea" :rows="3" placeholder="补充说明（可选）" />
      </el-form-item>
    </el-form>
  </FormDialog>
</template>
