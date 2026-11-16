<script setup lang="ts">
/** 换线/迁移：设备是唯一实体，换线只改"当前位置"，履历与告警跟着设备走。 */
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { transferDevice, type LgDevice, type LgLine, type LgStation } from "../../api/lineguard";

const props = defineProps<{
  modelValue: boolean;
  device: LgDevice | null;
  lines: LgLine[];
  stations: LgStation[];
}>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void; (e: "done"): void }>();

const busy = ref(false);
const form = reactive({ toLineId: "", toStationId: "", status: "", reason: "", note: "",
  conditionType: "", symptom: "", resolution: "", result: "pending" });

const stationOptions = computed(() => props.stations.filter((item) => String(item.line_id) === form.toLineId));

watch(() => props.modelValue, (open) => {
  if (!open) return;
  form.toLineId = props.device?.line_id ? String(props.device.line_id) : "";
  form.toStationId = props.device?.station_id ? String(props.device.station_id) : "";
  form.status = "";
  form.reason = "";
  form.note = "";
  form.conditionType = "";
  form.symptom = "";
  form.resolution = "";
  form.result = "pending";
});

async function submit(): Promise<void> {
  if (!props.device) return;
  if (!form.toLineId) { ElMessage.warning("请选择目标产线。"); return; }
  busy.value = true;
  try {
    await transferDevice(props.device.id, {
      to_line_id: Number(form.toLineId),
      to_station_id: form.toStationId ? Number(form.toStationId) : null,
      status: form.status || undefined,
      reason: form.reason,
      note: form.note,
      condition: form.conditionType
        ? { condition: form.conditionType, symptom: form.symptom, resolution: form.resolution, result: form.result }
        : undefined,
    });
    ElMessage.success("换线完成，履历已记录。");
    emit("update:modelValue", false);
    emit("done");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "换线失败。");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="换线 / 迁移" width="560px"
             @update:model-value="emit('update:modelValue', $event)">
    <el-form label-width="96px">
      <el-form-item label="设备">
        <span>{{ device?.asset_no }} · {{ device?.hostname }}</span>
      </el-form-item>
      <el-form-item label="当前位置">
        <span class="oa-hint">{{ device?.workshop_name }} / {{ device?.line_name }} / {{ device?.station_name || "未分工位" }}</span>
      </el-form-item>
      <el-form-item label="目标产线" required>
        <el-select v-model="form.toLineId" filterable class="oa-full-width" placeholder="选择产线"
                   @change="form.toStationId = ''">
          <el-option v-for="item in lines" :key="item.id" :label="item.name" :value="String(item.id)" />
        </el-select>
      </el-form-item>
      <el-form-item label="目标工位">
        <el-select v-model="form.toStationId" clearable filterable class="oa-full-width" placeholder="可不选">
          <el-option v-for="item in stationOptions" :key="item.id" :label="item.name" :value="String(item.id)" />
        </el-select>
      </el-form-item>
      <el-form-item label="换后状态">
        <el-select v-model="form.status" clearable class="oa-full-width" placeholder="保持当前状态">
          <el-option label="在线" value="online" />
          <el-option label="离线" value="offline" />
          <el-option label="故障" value="fault" />
          <el-option label="检修中" value="maintenance" />
          <el-option label="已下线" value="retired" />
        </el-select>
      </el-form-item>
      <el-form-item label="换线原因">
        <el-input v-model="form.reason" placeholder="如：产能调整 / 工位改造" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.note" type="textarea" :rows="2" />
      </el-form-item>
      <el-divider content-position="left">同时登记换下状况（可选）</el-divider>
      <el-form-item label="状况类型">
        <el-input v-model="form.conditionType" placeholder="如：换下 / 故障 / 返修" />
      </el-form-item>
      <el-form-item label="现象">
        <el-input v-model="form.symptom" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="处理结论">
        <el-select v-model="form.result" class="oa-full-width">
          <el-option label="待处理" value="pending" />
          <el-option label="已修复" value="repaired" />
          <el-option label="备用" value="standby" />
          <el-option label="报废" value="scrapped" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="busy" @click="submit">确认换线</el-button>
    </template>
  </el-dialog>
</template>
