<script setup lang="ts">
/** 工控机台账：手工录入 / 网段扫描 / Excel 导入 / 换线 / 状况补录 / 状态维护。 */
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  LG_PROBE_LABELS, LG_STATUS_LABELS,
  createDevice, createLine, createStation, createWorkshop, deleteDevice, exportDevices,
  getOptions, importDevices, listDevices, setDeviceStatus,
  type LgDevice, type LgLine, type LgStation, type LgWorkshop,
} from "../api/lineguard";
import ImportExcelDialog from "../components/ui/ImportExcelDialog.vue";
import ConditionDialog from "../components/lineguard/ConditionDialog.vue";
import DeviceDrawer from "../components/lineguard/DeviceDrawer.vue";
import ScanDialog from "../components/lineguard/ScanDialog.vue";
import TransferDialog from "../components/lineguard/TransferDialog.vue";

const loading = ref(false);
const rows = ref<LgDevice[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(50);
const filters = reactive({ q: "", status: "", workshopId: "", lineId: "" });

const workshops = ref<LgWorkshop[]>([]);
const lines = ref<LgLine[]>([]);
const stations = ref<LgStation[]>([]);

const lineOptions = computed(() =>
  filters.workshopId ? lines.value.filter((item) => String(item.workshop_id) === filters.workshopId) : lines.value);

const drawerOpen = ref(false);
const drawerId = ref<number | null>(null);
const transferOpen = ref(false);
const conditionOpen = ref(false);
const scanOpen = ref(false);
const importOpen = ref(false);
const formOpen = ref(false);
const orgOpen = ref(false);
const current = ref<LgDevice | null>(null);
const editing = ref<LgDevice | null>(null);

const form = reactive({
  asset_no: "", hostname: "", ip: "", mac: "", model: "", os_version: "", serial_no: "",
  line_id: "", station_id: "", probe_mode: "probe", probe_port: "", probe_interval: "60",
  owner: "", remark: "", status: "offline",
});
const orgForm = reactive({ wsCode: "", wsName: "", lineWorkshop: "", lineCode: "", lineName: "",
  stationLine: "", stationCode: "", stationName: "" });

async function loadOptions(): Promise<void> {
  const data = await getOptions();
  workshops.value = data.workshops;
  lines.value = data.lines;
  stations.value = data.stations;
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const data = await listDevices({ ...filters, page: page.value, size: size.value });
    rows.value = data.items;
    total.value = data.total;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载失败。");
  } finally {
    loading.value = false;
  }
}

function resetForm(): void {
  Object.assign(form, {
    asset_no: "", hostname: "", ip: "", mac: "", model: "", os_version: "", serial_no: "",
    line_id: "", station_id: "", probe_mode: "probe", probe_port: "", probe_interval: "60",
    owner: "", remark: "", status: "offline",
  });
}

function openCreate(): void {
  editing.value = null;
  resetForm();
  formOpen.value = true;
}

function openEdit(row: LgDevice): void {
  editing.value = row;
  Object.assign(form, {
    asset_no: row.asset_no, hostname: row.hostname, ip: row.ip, mac: row.mac, model: row.model,
    os_version: row.os_version, serial_no: row.serial_no,
    line_id: row.line_id ? String(row.line_id) : "", station_id: row.station_id ? String(row.station_id) : "",
    probe_mode: row.probe_mode, probe_port: row.probe_port ? String(row.probe_port) : "",
    probe_interval: String(row.probe_interval || 60), owner: row.owner, remark: row.remark, status: row.status,
  });
  formOpen.value = true;
}

async function submitForm(): Promise<void> {
  if (!form.asset_no.trim() || !form.hostname.trim()) {
    ElMessage.warning("资产编号与主机名必填。");
    return;
  }
  const payload = {
    ...form,
    line_id: form.line_id ? Number(form.line_id) : null,
    station_id: form.station_id ? Number(form.station_id) : null,
    probe_port: form.probe_port ? Number(form.probe_port) : 0,
    probe_interval: Number(form.probe_interval || 60),
  };
  try {
    if (editing.value) {
      await updateDevice(editing.value.id, payload);
      ElMessage.success("已保存。");
    } else {
      const created = await createDevice(payload);
      ElMessage.success("设备已入库，令牌：" + created.agent_token);
    }
    formOpen.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败。");
  }
}

async function updateDevice(id: number, payload: Record<string, unknown>): Promise<void> {
  const { updateDevice: fn } = await import("../api/lineguard");
  await fn(id, payload);
}

async function removeRow(row: LgDevice): Promise<void> {
  try {
    await ElMessageBox.confirm("删除后该设备的履历与告警一并删除，确定继续？", "删除设备", { type: "warning" });
  } catch {
    return;
  }
  try {
    await deleteDevice(row.id);
    ElMessage.success("已删除。");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除失败。");
  }
}

async function changeStatus(row: LgDevice, status: string): Promise<void> {
  try {
    await setDeviceStatus(row.id, { status, detail: "台账手工调整" });
    ElMessage.success("状态已更新。");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新失败。");
  }
}

function openTransfer(row: LgDevice): void { current.value = row; transferOpen.value = true; }
function openCondition(row: LgDevice): void { current.value = row; conditionOpen.value = true; }
function openDrawer(row: LgDevice): void { drawerId.value = row.id; drawerOpen.value = true; }

async function downloadCsv(): Promise<void> {
  try {
    const data = await exportDevices();
    const blob = new Blob([data.content], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = data.fileName || "工控机台账.csv";
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "导出失败。");
  }
}

async function submitWorkshop(): Promise<void> {
  if (!orgForm.wsCode.trim() || !orgForm.wsName.trim()) { ElMessage.warning("车间编码与名称必填。"); return; }
  await createWorkshop({ code: orgForm.wsCode.trim(), name: orgForm.wsName.trim() });
  ElMessage.success("车间已创建。");
  await loadOptions();
}

async function submitLine(): Promise<void> {
  if (!orgForm.lineWorkshop || !orgForm.lineCode.trim() || !orgForm.lineName.trim()) {
    ElMessage.warning("请选择车间并填写产线编码与名称。");
    return;
  }
  await createLine({ workshop_id: Number(orgForm.lineWorkshop), code: orgForm.lineCode.trim(), name: orgForm.lineName.trim() });
  ElMessage.success("产线已创建。");
  await loadOptions();
}

async function submitStation(): Promise<void> {
  if (!orgForm.stationLine || !orgForm.stationCode.trim() || !orgForm.stationName.trim()) {
    ElMessage.warning("请选择产线并填写工位编码与名称。");
    return;
  }
  await createStation({ line_id: Number(orgForm.stationLine), code: orgForm.stationCode.trim(), name: orgForm.stationName.trim() });
  ElMessage.success("工位已创建。");
  await loadOptions();
}

function statusType(status: string): "success" | "danger" | "warning" | "info" {
  if (status === "online") return "success";
  if (status === "offline") return "danger";
  if (status === "fault") return "warning";
  return "info";
}

onMounted(async () => {
  await loadOptions();
  await load();
});
</script>

<template>
  <section class="oa-page">
    <header class="oa-flex-between oa-mb-3">
      <h2 class="oa-page-title">工控机台账</h2>
      <div class="oa-flex-row">
        <el-button @click="orgOpen = true">组织维护</el-button>
        <el-button @click="importOpen = true">导入</el-button>
        <el-button @click="downloadCsv">导出</el-button>
        <el-button @click="scanOpen = true">扫描网段</el-button>
        <el-button type="primary" @click="openCreate">新增设备</el-button>
      </div>
    </header>

    <el-card shadow="never" class="oa-mb-3">
      <div class="oa-flex-row oa-filter-row">
        <el-input v-model="filters.q" placeholder="资产编号 / 主机名 / IP / 型号" clearable style="width: 260px"
                  @keyup.enter="page = 1; load()" />
        <el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 130px" @change="page = 1; load()">
          <el-option v-for="(label, value) in LG_STATUS_LABELS" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select v-model="filters.workshopId" clearable placeholder="全部车间" style="width: 150px"
                   @change="filters.lineId = ''; page = 1; load()">
          <el-option v-for="item in workshops" :key="item.id" :label="item.name" :value="String(item.id)" />
        </el-select>
        <el-select v-model="filters.lineId" clearable filterable placeholder="全部产线" style="width: 150px"
                   @change="page = 1; load()">
          <el-option v-for="item in lineOptions" :key="item.id" :label="item.name" :value="String(item.id)" />
        </el-select>
        <el-button type="primary" @click="page = 1; load()">查询</el-button>
        <el-button @click="filters.q = ''; filters.status = ''; filters.workshopId = ''; filters.lineId = ''; page = 1; load()">重置</el-button>
      </div>
    </el-card>

    <el-table v-loading="loading" :data="rows" size="small" border>
      <el-table-column prop="asset_no" label="资产编号" width="130" fixed />
      <el-table-column prop="hostname" label="主机名" min-width="130" />
      <el-table-column prop="ip" label="IP" width="120" />
      <el-table-column label="位置" min-width="180">
        <template #default="{ row }">
          {{ row.workshop_name || "-" }} / {{ row.line_name || "-" }} / {{ row.station_name || "未分工位" }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="96">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ LG_STATUS_LABELS[row.status] || row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="检测" width="110">
        <template #default="{ row }">
          {{ LG_PROBE_LABELS[row.probe_mode] || row.probe_mode }}<span v-if="row.probe_port">:{{ row.probe_port }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="owner" label="责任人" width="100" />
      <el-table-column label="最近心跳" width="150">
        <template #default="{ row }">{{ row.last_heartbeat_at || "-" }}</template>
      </el-table-column>
      <el-table-column label="操作" width="290" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDrawer(row)">详情</el-button>
          <el-button link type="primary" @click="openTransfer(row)">换线</el-button>
          <el-button link type="primary" @click="openCondition(row)">状况</el-button>
          <el-dropdown trigger="click" @command="(cmd: string) => changeStatus(row, cmd)">
            <el-button link type="primary">状态</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="(label, value) in LG_STATUS_LABELS" :key="value" :command="value">{{ label }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="removeRow(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="oa-flex-between oa-mt-3">
      <span class="oa-hint">共 {{ total }} 台</span>
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
                     :page-sizes="[20, 50, 100, 200]" layout="sizes, prev, pager, next" @current-change="load" @size-change="load" />
    </div>

    <!-- 新增/编辑 -->
    <el-dialog v-model="formOpen" :title="editing ? '编辑设备' : '新增设备'" width="640px">
      <el-form label-width="96px">
        <el-form-item label="资产编号" required><el-input v-model="form.asset_no" :disabled="!!editing" /></el-form-item>
        <el-form-item label="主机名" required><el-input v-model="form.hostname" /></el-form-item>
        <el-form-item label="IP"><el-input v-model="form.ip" placeholder="用于主动探测" /></el-form-item>
        <el-form-item label="MAC"><el-input v-model="form.mac" /></el-form-item>
        <el-form-item label="型号"><el-input v-model="form.model" /></el-form-item>
        <el-form-item label="操作系统"><el-input v-model="form.os_version" /></el-form-item>
        <el-form-item label="序列号"><el-input v-model="form.serial_no" /></el-form-item>
        <el-form-item label="产线">
          <el-select v-model="form.line_id" clearable filterable class="oa-full-width" placeholder="可不选">
            <el-option v-for="item in lines" :key="item.id" :label="item.name" :value="String(item.id)" />
          </el-select>
        </el-form-item>
        <el-form-item label="工位">
          <el-select v-model="form.station_id" clearable filterable class="oa-full-width" placeholder="可不选">
            <el-option v-for="item in stations.filter(s => !form.line_id || String(s.line_id) === form.line_id)"
                       :key="item.id" :label="item.name" :value="String(item.id)" />
          </el-select>
        </el-form-item>
        <el-form-item label="检测方式">
          <el-select v-model="form.probe_mode" class="oa-full-width">
            <el-option label="主动探测" value="probe" />
            <el-option label="心跳" value="heartbeat" />
            <el-option label="混合" value="hybrid" />
          </el-select>
        </el-form-item>
        <el-form-item label="探测端口">
          <el-input v-model="form.probe_port" placeholder="留空用 ICMP；如 445 / 3389" />
        </el-form-item>
        <el-form-item label="探测周期"><el-input v-model="form.probe_interval" placeholder="秒" /></el-form-item>
        <el-form-item label="责任人"><el-input v-model="form.owner" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 组织维护 -->
    <el-dialog v-model="orgOpen" title="车间 / 产线 / 工位" width="720px">
      <el-divider content-position="left">新增车间</el-divider>
      <div class="oa-flex-row oa-mb-3">
        <el-input v-model="orgForm.wsCode" placeholder="编码" style="width: 120px" />
        <el-input v-model="orgForm.wsName" placeholder="名称" style="width: 200px" />
        <el-button @click="submitWorkshop">创建</el-button>
      </div>
      <el-divider content-position="left">新增产线</el-divider>
      <div class="oa-flex-row oa-mb-3">
        <el-select v-model="orgForm.lineWorkshop" placeholder="所属车间" style="width: 160px">
          <el-option v-for="item in workshops" :key="item.id" :label="item.name" :value="String(item.id)" />
        </el-select>
        <el-input v-model="orgForm.lineCode" placeholder="编码" style="width: 120px" />
        <el-input v-model="orgForm.lineName" placeholder="名称" style="width: 200px" />
        <el-button @click="submitLine">创建</el-button>
      </div>
      <el-divider content-position="left">新增工位</el-divider>
      <div class="oa-flex-row oa-mb-3">
        <el-select v-model="orgForm.stationLine" placeholder="所属产线" style="width: 160px">
          <el-option v-for="item in lines" :key="item.id" :label="item.name" :value="String(item.id)" />
        </el-select>
        <el-input v-model="orgForm.stationCode" placeholder="编码" style="width: 120px" />
        <el-input v-model="orgForm.stationName" placeholder="名称" style="width: 200px" />
        <el-button @click="submitStation">创建</el-button>
      </div>
      <template #footer><el-button @click="orgOpen = false">关闭</el-button></template>
    </el-dialog>

    <ScanDialog v-model="scanOpen" :lines="lines" :stations="stations" @done="load" />
    <TransferDialog v-model="transferOpen" :device="current" :lines="lines" :stations="stations" @done="load" />
    <ConditionDialog v-model="conditionOpen" :device="current" @done="load" />
    <DeviceDrawer v-model="drawerOpen" :device-id="drawerId" />
    <ImportExcelDialog
      v-model="importOpen"
      title="导入工控机台账"
      :field-labels="{ asset_no: '资产编号', hostname: '主机名', ip: 'IP地址', model: '型号', workshop: '车间', line: '产线', station: '工位' }"
      :template-header="['资产编号', '主机名', 'IP地址', '型号', '操作系统', '序列号', '车间', '产线', '工位', '责任人']"
      :template-sample="['JG-01-01', 'IPC-01', '192.168.10.11', '研华 610', 'Windows 10 LTSC', 'SN123456', '一车间', 'SMT线', '贴片工位', '张三']"
      template-file-name="工控机台账导入模板.csv"
      hint="列名需与模板一致；资产编号已存在则更新。"
      :import-fn="importDevices"
      @imported="load"
    />
  </section>
</template>
