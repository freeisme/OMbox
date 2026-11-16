<script setup lang="ts">
/** 换下设备状况补录：现象 / 根因 / 处理 / 结论。 */
import { reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { addCondition, type LgDevice } from "../../api/lineguard";

const props = defineProps<{ modelValue: boolean; device: LgDevice | null }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void; (e: "done"): void }>();

const busy = ref(false);
const form = reactive({ condition: "", symptom: "", root_cause: "", resolution: "", result: "pending", technician: "" });

watch(() => props.modelValue, (open) => {
  if (!open) return;
  form.condition = "换下";
  form.symptom = "";
  form.root_cause = "";
  form.resolution = "";
  form.result = "pending";
  form.technician = "";
});

async function submit(): Promise<void> {
  if (!props.device) return;
  if (!form.condition.trim()) { ElMessage.warning("请填写状况类型。"); return; }
  busy.value = true;
  try {
    await addCondition(props.device.id, { ...form });
    ElMessage.success("状况已登记。");
    emit("update:modelValue", false);
    emit("done");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "登记失败。");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="登记设备状况" width="560px"
             @update:model-value="emit('update:modelValue', $event)">
    <el-form label-width="90px">
      <el-form-item label="设备">
        <span>{{ device?.asset_no }} · {{ device?.hostname }}</span>
      </el-form-item>
      <el-form-item label="状况类型" required>
        <el-input v-model="form.condition" placeholder="换下 / 故障 / 返修" />
      </el-form-item>
      <el-form-item label="现象">
        <el-input v-model="form.symptom" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="根因">
        <el-input v-model="form.root_cause" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="处理">
        <el-input v-model="form.resolution" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="结论">
        <el-select v-model="form.result" class="oa-full-width">
          <el-option label="待处理" value="pending" />
          <el-option label="已修复" value="repaired" />
          <el-option label="备用" value="standby" />
          <el-option label="报废" value="scrapped" />
        </el-select>
      </el-form-item>
      <el-form-item label="技术员">
        <el-input v-model="form.technician" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="busy" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>
