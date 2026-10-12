<script setup lang="ts">
/** 通用 xlsx / csv 批量导入弹窗：选文件 → 预览（dryRun）→ 确认导入 → 结果。
 *
 * 后端接口约定见 office_asset 里的 import_* 方法：入参
 * `{ fileName, contentBase64, dryRun, mode }`，返回 ImportSummary。
 */
import { ref, watch } from "vue";
import { ElMessage } from "element-plus";
import type { ImportSummary } from "../../api/datacenter";
import FormDialog from "./FormDialog.vue";

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    title: string;
    /** 字段名 → 中文列名，用于展示"识别到的列"。 */
    fieldLabels: Record<string, string>;
    templateHeader: string[];
    templateSample: string[];
    templateFileName: string;
    hint?: string;
    importFn: (payload: {
      fileName: string;
      contentBase64: string;
      dryRun: boolean;
      mode: "skip" | "update";
    }) => Promise<ImportSummary>;
  }>(),
  { hint: "" },
);

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
  (event: "imported"): void;
}>();

const busy = ref(false);
const mode = ref<"skip" | "update">("skip");
const fileName = ref("");
const content = ref("");
const preview = ref<ImportSummary | null>(null);

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    // 每次打开都是干净的一次导入
    fileName.value = "";
    content.value = "";
    preview.value = null;
    mode.value = "skip";
  },
);

function close(): void {
  emit("update:modelValue", false);
}

function downloadTemplate(): void {
  const csv = `\ufeff${props.templateHeader.join(",")}\n${props.templateSample
    .map((cell) => `"${cell}"`)
    .join(",")}\n`;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  link.download = props.templateFileName;
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
  busy.value = true;
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    bytes.forEach((byte) => {
      binary += String.fromCharCode(byte);
    });
    content.value = window.btoa(binary);
    fileName.value = file.name;
    preview.value = await props.importFn({
      fileName: file.name,
      contentBase64: content.value,
      dryRun: true,
      mode: mode.value,
    });
  } catch (error) {
    ElMessage.error(`文件解析失败：${(error as Error).message}`);
  } finally {
    busy.value = false;
    input.value = "";
  }
}

async function runImport(): Promise<void> {
  if (!content.value) {
    ElMessage.warning("请先选择文件。");
    return;
  }
  busy.value = true;
  try {
    const result = await props.importFn({
      fileName: fileName.value,
      contentBase64: content.value,
      dryRun: false,
      mode: mode.value,
    });
    preview.value = result;
    ElMessage.success(
      `导入完成：新增 ${result.created}，更新 ${result.updated}，跳过 ${result.skipped}，` +
        `错误 ${result.errorCount}${result.warningCount ? `，提示 ${result.warningCount}` : ""}。`,
    );
    emit("imported");
  } catch (error) {
    ElMessage.error(`导入失败：${(error as Error).message}`);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <FormDialog
    :model-value="modelValue"
    :title="title"
    size="lg"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #footer>
      <el-button @click="close">关闭</el-button>
      <el-button
        type="primary"
        :loading="busy"
        :disabled="!preview || preview.dryRun === false"
        @click="runImport"
      >
        确认导入
      </el-button>
    </template>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="支持 .xlsx / .xlsm / .csv，从第一个工作表读取。"
    />
    <div class="import-row">
      <input type="file" accept=".xlsx,.xlsm,.csv" @change="onFileChange" />
      <el-button size="small" @click="downloadTemplate">下载模板</el-button>
      <el-switch
        v-model="mode"
        active-value="update"
        inactive-value="skip"
        active-text="更新已存在的记录"
        inactive-text="跳过已存在的记录"
        @change="preview = null"
      />
    </div>
    <div v-if="hint" class="hint">{{ hint }}</div>

    <template v-if="preview">
      <el-descriptions :column="3" border size="small" class="oa-mt-3">
        <el-descriptions-item label="文件">{{ preview.fileName || fileName }}</el-descriptions-item>
        <el-descriptions-item label="数据行">{{ preview.totalRows }}</el-descriptions-item>
        <el-descriptions-item :label="preview.dryRun ? '预览结果' : '导入结果'">
          新增 {{ preview.created }} / 更新 {{ preview.updated }} / 跳过 {{ preview.skipped }} /
          错误 {{ preview.errorCount }}
        </el-descriptions-item>
      </el-descriptions>
      <div class="hint">
        识别到的列：
        <span v-for="(header, field) in preview.sheetHeaders" :key="field" class="chip">
          {{ fieldLabels[field] ?? field }} ← {{ header }}
        </span>
      </div>
      <el-table
        v-if="preview.warnings?.length"
        :data="preview.warnings"
        size="small"
        class="oa-mt-2"
      >
        <el-table-column prop="row" label="行号" width="80" />
        <el-table-column prop="code" label="标识" width="160" />
        <el-table-column prop="message" label="提示" />
      </el-table>
      <el-table
        v-if="preview.errors.length"
        :data="preview.errors"
        size="small"
        height="200"
        class="oa-mt-2"
      >
        <el-table-column prop="row" label="行号" width="80" />
        <el-table-column prop="code" label="标识" width="160" />
        <el-table-column prop="message" label="问题" />
      </el-table>
    </template>
  </FormDialog>
</template>

<style scoped>
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
