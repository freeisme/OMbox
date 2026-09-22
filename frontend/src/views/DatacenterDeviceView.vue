<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  DATACENTER_STATUS_LABELS as STATUS_LABELS,
  RACK_CATEGORY_LABELS as CATEGORY_LABELS,
  datacenterStatusTagType,
} from "../labels";
import {
  createDatacenterDevice,
  getDeviceType,
  importDatacenterDevices,
  listDatacenterDevices,
  listDeviceTypes,
  removeDatacenterDevice,
  updateDatacenterDevice,
  type DatacenterDeviceSummary,
  type DeviceTypeSummary,
  type ImportSummary,
} from "../api/datacenter";
import { hasPermission } from "../session";


const loading = ref(false);
const devices = ref<DatacenterDeviceSummary[]>([]);
const deviceTypes = ref<DeviceTypeSummary[]>([]);
const statusFilter = ref("");
const keyword = ref("");
const dialog = ref(false);
const editingId = ref("");
/** 复制来源名称：非空时对话框标题显示"复制自…"，并提示补录唯一字段。 */
const copyFromName = ref("");
const form = ref<Record<string, unknown>>({});
const importDialog = ref(false);
const importFileName = ref("");
const importContent = ref("");
const importPreview = ref<ImportSummary | null>(null);
const importMode = ref<"skip" | "update">("skip");
const importBusy = ref(false);

const canCreate = computed(() => hasPermission("rack_layout", "create"));
const canUpdate = computed(() => hasPermission("rack_layout", "update"));
const canDelete = computed(() => hasPermission("rack_layout", "delete"));
const summary = computed(() => {
  const counts: Record<string, number> = { stock: 0, installed: 0, repair: 0, scrapped: 0 };
  devices.value.forEach((item) => {
    counts[item.status] = (counts[item.status] ?? 0) + 1;
  });
  return counts;
});

async function loadDevices(): Promise<void> {
  loading.value = true;
  try {
    const payload = await listDatacenterDevices({
      status: statusFilter.value,
      keyword: keyword.value.trim(),
    });
    devices.value = payload.devices;
  } catch (error) {
    ElMessage.error(`机房设备加载失败：${(error as Error).message}`);
  } finally {
    loading.value = false;
  }
}

async function loadDeviceTypes(): Promise<void> {
  try {
    const payload = await listDeviceTypes();
    deviceTypes.value = payload.deviceTypes;
  } catch {
    deviceTypes.value = [];
  }
}

function openDialog(device: DatacenterDeviceSummary | null): void {
  editingId.value = device?.id ?? "";
  copyFromName.value = "";
  form.value = device
    ? {
        code: device.code,
        name: device.name,
        catalogId: device.catalogId || "",
        brandModel: device.brandModel,
        category: device.category,
        uHeight: device.uHeight,
        serialNumber: device.serialNumber,
        assetCode: device.assetCode,
        ownerLabel: device.ownerLabel,
        status: device.status,
        notes: device.notes ?? "",
      }
    : {
        code: "",
        name: "",
        catalogId: "",
        brandModel: "",
        category: "network",
        uHeight: 1,
        serialNumber: "",
        assetCode: "",
        ownerLabel: "",
        status: "stock",
        notes: "",
      };
  dialog.value = true;
}

/**
 * 复制一台设备：型号库、品牌型号、设备类型、占用高度、使用人与备注都沿用，
 * 只清掉设备编号、名称、SN / ST、固资编码这些唯一值，状态回到"未上架"。
 */
function copyDevice(device: DatacenterDeviceSummary): void {
  editingId.value = "";
  copyFromName.value = device.name || device.code;
  form.value = {
    code: "",
    name: "",
    catalogId: device.catalogId || "",
    brandModel: device.brandModel,
    category: device.category,
    uHeight: device.uHeight,
    serialNumber: "",
    assetCode: "",
    ownerLabel: device.ownerLabel,
    status: "stock",
    notes: device.notes ?? "",
  };
  dialog.value = true;
}

async function applyDeviceType(catalogId: string): Promise<void> {
  if (!catalogId) return;
  try {
    const payload = await getDeviceType(catalogId);
    const detail = payload.deviceType;
    form.value.brandModel = `${detail.manufacturer} ${detail.model}`.trim();
    form.value.category = detail.category;
    form.value.uHeight = Math.max(1, Math.round(Number(detail.uHeight) || 1));
    if (!form.value.name) form.value.name = detail.model;
  } catch (error) {
    ElMessage.error(`型号加载失败：${(error as Error).message}`);
  }
}

async function submit(): Promise<void> {
  const payload = { ...form.value };
  if (!String(payload.code ?? "").trim() || !String(payload.name ?? "").trim()) {
    ElMessage.warning("设备编号与名称不能为空。");
    return;
  }
  try {
    if (editingId.value) {
      await updateDatacenterDevice(editingId.value, payload);
      ElMessage.success("机房设备已更新。");
    } else {
      await createDatacenterDevice(payload);
      ElMessage.success("机房设备已新增。");
    }
    dialog.value = false;
    await loadDevices();
  } catch (error) {
    ElMessage.error(`保存失败：${(error as Error).message}`);
  }
}

async function changeStatus(device: DatacenterDeviceSummary, status: string): Promise<void> {
  if (status === device.status) return;
  try {
    await updateDatacenterDevice(device.id, { status });
    ElMessage.success(`「${device.name}」状态已改为${STATUS_LABELS[status]}。`);
    await loadDevices();
  } catch (error) {
    ElMessage.error(`状态更新失败：${(error as Error).message}`);
  }
}

async function removeDevice(device: DatacenterDeviceSummary): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt(
      `删除「${device.name}」的原因（会写入操作日志）`,
      "删除机房设备",
      { confirmButtonText: "确认删除", cancelButtonText: "取消" },
    );
    await removeDatacenterDevice(device.id, String(value ?? ""));
    ElMessage.success("机房设备已删除。");
    await loadDevices();
  } catch (error) {
    if (error !== "cancel") ElMessage.error(`删除失败：${String(error)}`);
  }
}

function downloadTemplate(): void {
  const header = [
    "设备编号",
    "设备名称",
    "品牌型号",
    "设备类型",
    "占用高度",
    "SN/ST",
    "固资编码",
    "使用人",
    "状态",
    "备注",
  ];
  const sample = [
    "SW-A01",
    "核心交换机",
    "华为 S5731-H48T4XC",
    "网络设备",
    "1",
    "2102351XHT10N6000123",
    "FA-2026-0201",
    "机房公用",
    "未上架",
    "A 列 1 号柜 39U",
  ];
  const csv = `\ufeff${header.join(",")}\n${sample.map((cell) => `"${cell}"`).join(",")}\n`;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  link.download = "机房设备导入模板.csv";
  link.click();
  URL.revokeObjectURL(link.href);
}

async function onFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const name = file.name.toLowerCase();
  if (!name.endsWith(".xlsx") && !name.endsWith(".xlsm") && !name.endsWith(".csv")) {
    ElMessage.warning("只支持 .xlsx、.xlsm 或 .csv 文件。");
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    ElMessage.warning("文件过大，请控制在 8MB 以内。");
    return;
  }
  importBusy.value = true;
  try {
    const buffer = await file.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = "";
    bytes.forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    importContent.value = window.btoa(binary);
    importFileName.value = file.name;
    importPreview.value = await importDatacenterDevices({
      fileName: file.name,
      contentBase64: importContent.value,
      dryRun: true,
      mode: importMode.value,
    });
  } catch (error) {
    ElMessage.error(`文件解析失败：${(error as Error).message}`);
  } finally {
    importBusy.value = false;
    input.value = "";
  }
}

async function runImport(): Promise<void> {
  if (!importContent.value) {
    ElMessage.warning("请先选择文件。");
    return;
  }
  importBusy.value = true;
  try {
    const result = await importDatacenterDevices({
      fileName: importFileName.value,
      contentBase64: importContent.value,
      dryRun: false,
      mode: importMode.value,
    });
    importPreview.value = result;
    ElMessage.success(
      `导入完成：新增 ${result.created}，更新 ${result.updated}，跳过 ${result.skipped}，错误 ${result.errorCount}。`,
    );
    await loadDevices();
  } catch (error) {
    ElMessage.error(`导入失败：${(error as Error).message}`);
  } finally {
    importBusy.value = false;
  }
}

const IMPORT_FIELD_LABELS: Record<string, string> = {
  code: "设备编号",
  name: "设备名称",
  brandModel: "品牌型号",
  category: "设备类型",
  uHeight: "占用高度",
  serialNumber: "SN/ST",
  assetCode: "固资编码",
  ownerLabel: "使用人",
  status: "状态",
  notes: "备注",
};

onMounted(async () => {
  await loadDeviceTypes();
  await loadDevices();
});
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div class="ledger-toolbar">
        <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 150px" @change="loadDevices">
          <el-option v-for="(label, value) in STATUS_LABELS" :key="value" :value="value" :label="label" />
        </el-select>
        <el-input
          v-model="keyword"
          placeholder="搜索设备编号、名称、型号或 SN"
          clearable
          style="width: 260px"
          @keyup.enter="loadDevices"
          @clear="loadDevices"
        />
        <el-button size="small" @click="loadDevices">查询</el-button>
        <el-tag type="info" effect="plain">未上架 {{ summary.stock }}</el-tag>
        <el-tag type="success" effect="plain">上架 {{ summary.installed }}</el-tag>
        <el-tag type="warning" effect="plain">维修 {{ summary.repair }}</el-tag>
        <el-tag type="danger" effect="plain">报废 {{ summary.scrapped }}</el-tag>
        <div class="spacer" />
        <el-button v-if="canCreate" size="small" @click="importDialog = true">导入 Excel</el-button>
        <el-button size="small" @click="downloadTemplate">下载模板</el-button>
        <el-button v-if="canCreate" type="primary" size="small" @click="openDialog(null)">
          ＋ 新增网络设备/服务器
        </el-button>
      </div>
    </template>

    <el-table :data="devices" size="small" height="560">
      <el-table-column prop="code" label="设备编号" width="150" />
      <el-table-column prop="name" label="设备名称" min-width="180" />
      <el-table-column prop="brandModel" label="品牌型号" min-width="200" />
      <el-table-column label="类型" width="130">
        <template #default="{ row }">{{ CATEGORY_LABELS[row.category] ?? row.category }}</template>
      </el-table-column>
      <el-table-column label="U 高" width="70">
        <template #default="{ row }">{{ row.uHeight }}U</template>
      </el-table-column>
      <el-table-column prop="serialNumber" label="SN / ST" min-width="150" />
      <el-table-column label="位置" min-width="200">
        <template #default="{ row }">
          {{ row.rackName ? `${row.siteName} / ${row.rackName}` : "—" }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="130">
        <template #default="{ row }">
          <el-tag :type="datacenterStatusTagType(row.status)" effect="plain">
            {{ STATUS_LABELS[row.status] ?? row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="ownerLabel" label="使用人 / 责任人" width="140" />
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button v-if="canUpdate" link size="small" @click="openDialog(row)">编辑</el-button>
          <el-button v-if="canCreate" link size="small" @click="copyDevice(row)">复制</el-button>
          <el-dropdown v-if="canUpdate" @command="(command: string) => changeStatus(row, command)">
            <el-button link size="small">状态<span class="caret">▾</span></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="stock" :disabled="row.status === 'installed'">未上架</el-dropdown-item>
                <el-dropdown-item command="repair">维修</el-dropdown-item>
                <el-dropdown-item command="scrapped">报废</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button v-if="canDelete" link type="danger" size="small" @click="removeDevice(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="hint">
      “上架”状态由机柜视图的上架操作自动写入；已上架设备要改回未上架，需先在机柜视图下架。
      这里只维护机房里的网络设备与服务器，办公终端和 IT 物资仍在各自模块管理。
    </div>

    <FormDialog
      v-model="dialog"
      :title="
        editingId
          ? '编辑机房设备'
          : copyFromName
            ? `复制机房设备（来自 ${copyFromName}）`
            : '新增机房设备'
      "
      size="lg"
      @confirm="submit"
    >
      <el-alert
        v-if="copyFromName && !editingId"
        type="info"
        :closable="false"
        show-icon
        title="已沿用被复制设备的型号、类型、占用高度与备注，请补填设备编号与名称，SN / ST 与固资编码需重新录入。"
        class="oa-mb-2"
      />
      <el-form label-position="top" size="small">
        <el-form-item label="型号库（可选，选中后自动带出型号、类型与 U 高）">
          <el-select
            v-model="form.catalogId"
            filterable
            clearable
            class="oa-full-width"
            @change="applyDeviceType"
          >
            <el-option
              v-for="item in deviceTypes"
              :key="item.id"
              :value="item.id"
              :label="`${item.manufacturer} ${item.model}（${item.uHeight}U，${item.portCount} 口）`"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="设备编号">
          <el-input v-model="form.code" placeholder="例如 SW-A01 / SRV-A01" />
        </el-form-item>
        <el-form-item label="设备名称">
          <el-input v-model="form.name" placeholder="例如 核心交换机" />
        </el-form-item>
        <el-form-item label="品牌型号">
          <el-input v-model="form.brandModel" placeholder="例如 华为 S5731-H48T4XC" />
        </el-form-item>
        <el-form-item label="设备类型">
          <el-select v-model="form.category" class="oa-full-width">
            <el-option v-for="(label, value) in CATEGORY_LABELS" :key="value" :value="value" :label="label" />
          </el-select>
        </el-form-item>
        <el-form-item label="占用高度（U）">
          <el-input-number v-model="form.uHeight" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="SN / ST">
          <el-input v-model="form.serialNumber" />
        </el-form-item>
        <el-form-item label="固资编码">
          <el-input v-model="form.assetCode" />
        </el-form-item>
        <el-form-item label="使用人 / 责任人">
          <el-input v-model="form.ownerLabel" placeholder="例如 机房公用" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status" class="oa-full-width" :disabled="form.status === 'installed'">
            <el-option label="未上架" value="stock" />
            <el-option label="上架（由上架操作设置）" value="installed" disabled />
            <el-option label="维修" value="repair" />
            <el-option label="报废" value="scrapped" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
    </FormDialog>

    <FormDialog v-model="importDialog" title="导入机房设备" size="lg">
      <template #footer>
        <el-button @click="importDialog = false">关闭</el-button>
        <el-button
          type="primary"
          :loading="importBusy"
          :disabled="!importPreview || importPreview.dryRun === false"
          @click="runImport"
        >
          确认导入
        </el-button>
      </template>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="支持 .xlsx / .xlsm / .csv，从第一个工作表读取；表头需包含「设备编号」与「设备名称」。"
      />
      <div class="import-row">
        <input type="file" accept=".xlsx,.xlsm,.csv" @change="onFileChange" />
        <el-switch
          v-model="importMode"
          active-text="更新已存在的设备"
          inactive-text="跳过已存在的设备"
          @change="importPreview = null"
        />
      </div>
      <div class="hint">
        可识别的列：设备编号、设备名称、品牌型号、设备类型、占用高度、SN/ST、固资编码、使用人、状态、备注。
        状态只接受「未上架 / 维修 / 报废」（「上架」由机柜视图的上架操作写入）；设备类型支持中文名，
        如 服务器、网络设备、配线架、UPS、存储。
      </div>

      <template v-if="importPreview">
        <el-descriptions :column="3" border size="small" class="oa-mt-3">
          <el-descriptions-item label="文件">{{ importPreview.fileName || importFileName }}</el-descriptions-item>
          <el-descriptions-item label="数据行">{{ importPreview.totalRows }}</el-descriptions-item>
          <el-descriptions-item :label="importPreview.dryRun ? '预览结果' : '导入结果'">
            新增 {{ importPreview.created }} / 更新 {{ importPreview.updated }} / 跳过
            {{ importPreview.skipped }} / 错误 {{ importPreview.errorCount }}
          </el-descriptions-item>
        </el-descriptions>
        <div class="hint">
          识别到的列：
          <span v-for="(header, field) in importPreview.sheetHeaders" :key="field" class="chip">
            {{ IMPORT_FIELD_LABELS[field] ?? field }} ← {{ header }}
          </span>
        </div>
        <el-table
          v-if="importPreview.errors.length"
          :data="importPreview.errors"
          size="small"
          height="200"
          class="oa-mt-2"
        >
          <el-table-column prop="row" label="行号" width="80" />
          <el-table-column prop="code" label="设备编号" width="160" />
          <el-table-column prop="message" label="问题" />
        </el-table>
      </template>
      <div v-else class="hint">选择文件后会先解析并显示将要新增/更新/跳过的数量，确认无误再导入。</div>

    </FormDialog>
  </el-card>
</template>

<style scoped>
.ledger-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.spacer {
  flex: 1;
}
.caret {
  margin-left: 2px;
  font-size: 10px;
}
.import-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin: 12px 0 4px;
  flex-wrap: wrap;
}
.chip {
  display: inline-block;
  margin: 2px 6px 2px 0;
  padding: 1px 6px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 3px;
  background: var(--el-fill-color-lighter);
}
.hint {
  margin-top: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.7;
}
</style>
