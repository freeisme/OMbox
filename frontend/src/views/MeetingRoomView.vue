<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  addSiteDevice,
  deleteInspectionSite,
  fetchInspectionSites,
  fetchSiteDevices,
  removeSiteDevice,
  saveInspectionSite,
  type InspectionSite,
  type SiteDevice,
} from "../api/governance";
import { loadInventoryData, type InventoryData } from "../api/inventory";
import { hasPermission } from "../session";
import { confirmAction } from "../composables/useConfirm";
import DataPanel from "../components/ui/DataPanel.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import ToolbarActions from "../components/ui/ToolbarActions.vue";

const loading = ref(true);
const saving = ref(false);
const sites = ref<InspectionSite[]>([]);
const keyword = ref("");

const roomVisible = ref(false);
const roomEditingId = ref("");
const roomForm = reactive({ code: "", name: "", location: "", remarks: "" });

const deviceVisible = ref(false);
const deviceRoom = ref<InspectionSite | null>(null);
const roomDevices = ref<SiteDevice[]>([]);
const deviceLoading = ref(false);
const inventory = ref<InventoryData | null>(null);
const deviceForm = reactive({
  source: "inventory" as "inventory" | "custom",
  modelId: "",
  warehouseId: "",
  name: "",
  deviceType: "",
  brand: "",
  model: "",
  quantity: 1,
  notes: "",
});

const canCreate = computed(() => hasPermission("inspection_management", "create"));
const canUpdate = computed(() => hasPermission("inspection_management", "update"));
const canDelete = computed(() => hasPermission("inspection_management", "delete"));

/** 只显示会议室（机房、弱电间在巡检中心的「巡检对象」里维护）。 */
const rooms = computed(() => {
  const key = keyword.value.trim().toLowerCase();
  return sites.value
    .filter((item) => (item.siteType ?? "") === "meeting_room")
    .filter((item) =>
      key
        ? `${item.name} ${item.code} ${item.location ?? ""} ${item.remarks ?? ""}`
            .toLowerCase()
            .includes(key)
        : true,
    );
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    sites.value = await fetchInspectionSites();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "会议室加载失败。");
  } finally {
    loading.value = false;
  }
}

function openRoomDialog(row?: InspectionSite): void {
  roomEditingId.value = row?.id ?? "";
  roomForm.code = row?.code ?? "";
  roomForm.name = row?.name ?? "";
  roomForm.location = row?.location ?? "";
  roomForm.remarks = row?.remarks ?? "";
  roomVisible.value = true;
}

async function submitRoom(): Promise<void> {
  if (!roomForm.name.trim()) {
    ElMessage.warning("会议室名称必填。");
    return;
  }
  const code = roomForm.code.trim() || `MR-${Date.now().toString(36).toUpperCase().slice(-6)}`;
  saving.value = true;
  try {
    await saveInspectionSite(
      {
        code,
        name: roomForm.name.trim(),
        siteType: "meeting_room",
        location: roomForm.location.trim(),
        remarks: roomForm.remarks.trim(),
      },
      roomEditingId.value,
    );
    ElMessage.success(roomEditingId.value ? "会议室已更新。" : "会议室已新增。");
    roomVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存会议室失败。");
  } finally {
    saving.value = false;
  }
}

async function removeRoom(row: InspectionSite): Promise<void> {
  const confirmed = await confirmAction(
    `删除会议室「${row.name}」？会议室里还有设备记录或已有巡检任务时不能删除。`,
    { title: "删除会议室", confirmText: "删除", danger: true },
  );
  if (!confirmed) return;
  try {
    await deleteInspectionSite(row.id, "会议室模块删除");
    ElMessage.success("会议室已删除。");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除会议室失败。");
  }
}

// --------------------------------------------------------------- 会议室内设备

async function openDevices(row: InspectionSite): Promise<void> {
  deviceRoom.value = row;
  deviceVisible.value = true;
  resetDeviceForm();
  await loadDevices();
  if (!inventory.value) {
    try {
      inventory.value = await loadInventoryData();
    } catch {
      inventory.value = null;
    }
  }
}

async function loadDevices(): Promise<void> {
  const room = deviceRoom.value;
  if (!room) return;
  deviceLoading.value = true;
  try {
    const payload = await fetchSiteDevices(room.id);
    roomDevices.value = payload.devices;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "读取会议室内设备失败。");
  } finally {
    deviceLoading.value = false;
  }
}

function resetDeviceForm(): void {
  Object.assign(deviceForm, {
    source: "inventory",
    modelId: "",
    warehouseId: "",
    name: "",
    deviceType: "",
    brand: "",
    model: "",
    quantity: 1,
    notes: "",
  });
}

/** 所选仓库里还有库存的 IT 物资型号。 */
const modelOptions = computed(() => {
  const data = inventory.value;
  if (!data) return [];
  const stockOf = new Map<string, number>();
  data.stocks.forEach((item) => {
    if (!item.warehouseId || !item.modelId) return;
    if (deviceForm.warehouseId && item.warehouseId !== deviceForm.warehouseId) return;
    stockOf.set(item.modelId, (stockOf.get(item.modelId) ?? 0) + Number(item.quantity ?? 0));
  });
  return data.models
    .map((model) => {
      const brand = data.brands.find((item) => item.id === model.brandId);
      const type = data.types.find((item) => item.id === model.typeId);
      return {
        value: model.id,
        label: `${type?.name ?? ""} ${brand?.name ?? ""} ${model.name}`.trim(),
        stock: stockOf.get(model.id) ?? 0,
      };
    })
    .filter((item) => !deviceForm.warehouseId || item.stock > 0)
    .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
});

async function submitDevice(): Promise<void> {
  const room = deviceRoom.value;
  if (!room) return;
  if (deviceForm.source === "custom" && !deviceForm.name.trim()) {
    ElMessage.warning("自定义设备必须填写设备名称。");
    return;
  }
  if (deviceForm.source === "inventory" && (!deviceForm.modelId || !deviceForm.warehouseId)) {
    ElMessage.warning("从 IT 物资分配时必须选择仓库与型号。");
    return;
  }
  deviceLoading.value = true;
  try {
    await addSiteDevice(room.id, {
      source: deviceForm.source,
      modelId: deviceForm.modelId,
      warehouseId: deviceForm.warehouseId,
      name: deviceForm.name.trim(),
      deviceType: deviceForm.deviceType.trim(),
      brand: deviceForm.brand.trim(),
      model: deviceForm.model.trim(),
      quantity: Number(deviceForm.quantity) || 1,
      notes: deviceForm.notes.trim(),
    });
    ElMessage.success("设备已登记到会议室。");
    resetDeviceForm();
    await loadDevices();
    await load();
    // 从 IT 物资分配会扣库存，下次打开时重新拉最新库存。
    inventory.value = null;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "登记设备失败。");
  } finally {
    deviceLoading.value = false;
  }
}

async function removeDevice(row: SiteDevice): Promise<void> {
  const tip =
    row.source === "inventory"
      ? `移除「${row.name}」并把 ${row.quantity} 台退回仓库「${row.warehouseName || "原仓库"}」？`
      : `移除自定义设备记录「${row.name}」？`;
  const confirmed = await confirmAction(tip, {
    title: "移除会议室内设备",
    confirmText: "移除",
    danger: true,
  });
  if (!confirmed) return;
  try {
    await removeSiteDevice(row.id, { reason: "会议室模块移除" });
    ElMessage.success("设备记录已移除。");
    await loadDevices();
    await load();
    inventory.value = null;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "移除设备失败。");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader
    title="会议室"
    description="会议室的名称与位置维护，以及会议室内设备登记（可从 IT 物资分配，也可自定义记录）；巡检在「巡检中心」发起"
  >
    <template #actions>
      <el-button @click="load">刷新</el-button>
    </template>
  </PageHeader>

  <DataPanel class="oa-panel-gap" :loading="loading">
    <ToolbarActions class="oa-mb-3" hint="会议室是独立的巡检对象，不挂机柜；设备可从 IT 物资分配（扣库存）或自定义登记">
      <el-input
        v-model="keyword"
        placeholder="搜索名称 / 编码 / 位置"
        clearable
        style="width: 240px"
      />
      <el-button v-if="canCreate" type="primary" @click="openRoomDialog()">
        ＋ 新增会议室
      </el-button>
    </ToolbarActions>

    <el-table :data="rooms" size="small" border empty-text="暂无会议室">
      <el-table-column prop="name" label="会议室" min-width="180" />
      <el-table-column prop="code" label="编码" width="150" />
      <el-table-column prop="location" label="位置" min-width="180" />
      <el-table-column label="设备" width="100">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDevices(row)">
            设备（{{ row.deviceCount ?? 0 }}）
          </el-button>
        </template>
      </el-table-column>
      <el-table-column prop="remarks" label="备注" min-width="160" show-overflow-tooltip />
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canUpdate" link type="primary" @click="openRoomDialog(row)">
            编辑
          </el-button>
          <el-button v-if="canDelete" link type="danger" @click="removeRoom(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </DataPanel>

  <FormDialog
    v-model="roomVisible"
    :title="roomEditingId ? '编辑会议室' : '新增会议室'"
    size="sm"
    :loading="saving"
    @confirm="submitRoom"
  >
    <el-form label-position="top">
      <el-form-item label="会议室名称" required>
        <el-input v-model="roomForm.name" placeholder="例如 3 楼大会议室" />
      </el-form-item>
      <el-form-item label="编码">
        <el-input v-model="roomForm.code" placeholder="留空自动生成，例如 MR-3F-A" />
      </el-form-item>
      <el-form-item label="位置">
        <el-input v-model="roomForm.location" placeholder="例如 A 栋 3 楼东侧 301" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="roomForm.remarks" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="deviceVisible"
    :title="`会议室内设备 · ${deviceRoom?.name ?? ''}`"
    size="lg"
  >
    <template #footer>
      <el-button @click="deviceVisible = false">关闭</el-button>
    </template>
    <el-table :data="roomDevices" size="small" border empty-text="暂无设备" v-loading="deviceLoading">
      <el-table-column label="设备" min-width="180">
        <template #default="{ row }">
          <div>{{ row.name }}</div>
          <div class="oa-cell-sub">
            {{ row.source === "inventory" ? "IT 物资分配" : "自定义登记" }}
            <template v-if="row.brand || row.model"> · {{ row.brand }} {{ row.model }}</template>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="110">
        <template #default="{ row }">{{ row.deviceType || "—" }}</template>
      </el-table-column>
      <el-table-column label="数量" width="70">
        <template #default="{ row }">{{ row.quantity }}</template>
      </el-table-column>
      <el-table-column label="来源仓库" width="140">
        <template #default="{ row }">{{ row.warehouseName || "—" }}</template>
      </el-table-column>
      <el-table-column label="备注" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ row.notes || "—" }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canUpdate" link type="danger" @click="removeDevice(row)">移除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-divider content-position="left">登记设备</el-divider>
    <el-form v-if="canUpdate" label-position="top" size="small">
      <el-form-item label="来源">
        <el-radio-group v-model="deviceForm.source">
          <el-radio value="inventory">从 IT 物资分配</el-radio>
          <el-radio value="custom">自定义设备记录</el-radio>
        </el-radio-group>
      </el-form-item>
      <template v-if="deviceForm.source === 'inventory'">
        <el-form-item label="出库仓库 / 型号">
          <el-select v-model="deviceForm.warehouseId" placeholder="仓库" style="width: 240px">
            <el-option
              v-for="warehouse in inventory?.warehouses ?? []"
              :key="warehouse.id"
              :value="warehouse.id"
              :label="warehouse.name"
            />
          </el-select>
          <el-select
            v-model="deviceForm.modelId"
            filterable
            placeholder="型号（显示当前仓库库存）"
            style="width: 320px; margin-left: 8px"
          >
            <el-option
              v-for="option in modelOptions"
              :key="option.value"
              :value="option.value"
              :label="`${option.label}（库存 ${option.stock}）`"
            />
          </el-select>
        </el-form-item>
        <div class="oa-hint">从 IT 物资分配会按数量扣减所选仓库库存；移除时原路退回仓库。</div>
      </template>
      <template v-else>
        <el-form-item label="设备名称" required>
          <el-input v-model="deviceForm.name" placeholder="例如 会议室电视" />
        </el-form-item>
        <el-form-item label="类型 / 品牌 / 型号">
          <el-input v-model="deviceForm.deviceType" placeholder="类型" style="width: 180px" />
          <el-input v-model="deviceForm.brand" placeholder="品牌" style="width: 180px; margin-left: 8px" />
          <el-input v-model="deviceForm.model" placeholder="型号" style="width: 200px; margin-left: 8px" />
        </el-form-item>
      </template>
      <el-form-item label="数量 / 备注">
        <el-input-number v-model="deviceForm.quantity" :min="1" :max="999" />
        <el-input
          v-model="deviceForm.notes"
          placeholder="备注，可选"
          style="width: 340px; margin-left: 8px"
        />
      </el-form-item>
      <el-button type="primary" size="small" :loading="deviceLoading" @click="submitDevice">
        登记设备
      </el-button>
    </el-form>
  </FormDialog>
</template>
