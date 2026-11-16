<script setup lang="ts">
/** 网段扫描：先探测存活，再勾选批量入库（按 IP 幂等）。 */
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { bulkCreate, scanNetwork, type LgLine, type LgScanCandidate, type LgStation } from "../../api/lineguard";

const props = defineProps<{ modelValue: boolean; lines: LgLine[]; stations: LgStation[] }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void; (e: "done"): void }>();

const cidr = ref("");
const ports = ref("445,3389,5985,22");
const busy = ref(false);
const result = ref<{ cidr: string; total: number; alive_count: number; candidates: LgScanCandidate[] } | null>(null);
const selected = ref<string[]>([]);
const lineId = ref("");
const stationId = ref("");

const stationOptions = computed(() => props.stations.filter((item) => String(item.line_id) === lineId.value));
const addable = computed(() => (result.value?.candidates || []).filter((item) => item.alive && !item.known_device_id));

async function run(): Promise<void> {
  if (!cidr.value.trim()) { ElMessage.warning("请填写网段，例如 192.168.10.0/24"); return; }
  busy.value = true;
  try {
    const payload = await scanNetwork({
      cidr: cidr.value.trim(),
      ports: ports.value.split(",").map((item) => Number(item.trim())).filter((n) => n > 0),
    });
    result.value = payload;
    selected.value = addable.value.map((item) => item.ip);
    ElMessage.success("扫描完成：存活 " + payload.alive_count + " 台，可新增 " + addable.value.length + " 台。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "扫描失败。");
  } finally {
    busy.value = false;
  }
}

async function commit(): Promise<void> {
  if (!selected.value.length) { ElMessage.warning("请先勾选要入库的主机。"); return; }
  busy.value = true;
  try {
    const candidates = addable.value.filter((item) => selected.value.includes(item.ip));
    const payload = await bulkCreate({
      candidates,
      line_id: lineId.value ? Number(lineId.value) : null,
      station_id: stationId.value ? Number(stationId.value) : null,
      probe_mode: "probe",
    });
    ElMessage.success("新增 " + payload.created.length + " 台，跳过 " + payload.skipped.length + " 台。");
    emit("update:modelValue", false);
    emit("done");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "入库失败。");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="扫描网段添加设备" width="820px"
             @update:model-value="emit('update:modelValue', $event)">
    <el-form label-width="90px">
      <el-form-item label="网段">
        <el-input v-model="cidr" placeholder="192.168.10.0/24，或 192.168.10.10-192.168.10.60" class="oa-full-width" />
      </el-form-item>
      <el-form-item label="探测端口">
        <el-input v-model="ports" placeholder="逗号分隔；留空则用 ICMP" />
      </el-form-item>
      <el-form-item label="入库到">
        <div class="oa-flex-row">
          <el-select v-model="lineId" clearable filterable placeholder="产线（可不选）" style="width: 220px"
                     @change="stationId = ''">
            <el-option v-for="item in lines" :key="item.id" :label="item.name" :value="String(item.id)" />
          </el-select>
          <el-select v-model="stationId" clearable filterable placeholder="工位（可不选）" style="width: 220px">
            <el-option v-for="item in stationOptions" :key="item.id" :label="item.name" :value="String(item.id)" />
          </el-select>
        </div>
      </el-form-item>
    </el-form>

    <div class="oa-flex-row oa-mb-2">
      <el-button type="primary" :loading="busy" @click="run">开始扫描</el-button>
      <span v-if="result" class="oa-hint">
        共 {{ result.total }} 个地址，存活 {{ result.alive_count }}，可新增 {{ addable.length }}
      </span>
    </div>

    <el-table v-if="result" :data="result.candidates" size="small" border max-height="320"
              @selection-change="(rows: LgScanCandidate[]) => selected = rows.filter(r => r.alive && !r.known_device_id).map(r => r.ip)">
      <el-table-column type="selection" width="46" :selectable="(row: LgScanCandidate) => row.alive && !row.known_device_id" />
      <el-table-column prop="ip" label="IP" width="140" />
      <el-table-column prop="hostname" label="主机名" min-width="140" />
      <el-table-column prop="mac" label="MAC" width="140" />
      <el-table-column label="时延" width="90">
        <template #default="{ row }">{{ row.latency_ms != null ? row.latency_ms + " ms" : "-" }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.known_device_id" type="info" size="small">台账已存在</el-tag>
          <el-tag v-else-if="row.alive" type="success" size="small">存活</el-tag>
          <el-tag v-else type="warning" size="small">不可达</el-tag>
        </template>
      </el-table-column>
    </el-table>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
      <el-button type="primary" :disabled="!selected.length" :loading="busy" @click="commit">
        入库选中（{{ selected.length }}）
      </el-button>
    </template>
  </el-dialog>
</template>
