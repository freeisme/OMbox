<script setup lang="ts">
/** 共用的「导出」按钮：下拉里选 CSV 或 Excel（xlsx 由后端套用样式模板）。 */
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { downloadTable, type ExportFormat } from "../../api/exports";

const props = withDefaults(
  defineProps<{
    fileName: string;
    header?: string[];
    rows?: string[][];
    /** 导出内容需要现算（例如逐份模板取明细）时给这个函数，选中格式后再调用。 */
    load?: () => Promise<{ header: string[]; rows: string[][]; title?: string[][] }>;
    label?: string;
    sheetName?: string;
    disabled?: boolean;
    size?: "small" | "default" | "large";
  }>(),
  {
    header: () => [],
    rows: () => [],
    label: "导出",
    sheetName: "数据",
    disabled: false,
    size: "small",
  },
);

const busy = ref(false);

async function run(format: string): Promise<void> {
  busy.value = true;
  try {
    const data = props.load
      ? await props.load()
      : { header: props.header, rows: props.rows, title: [] as string[][] };
    if (!data.rows.length) {
      ElMessage.warning("没有可导出的数据。");
      return;
    }
    await downloadTable({
      fileName: props.fileName,
      sheetName: props.sheetName,
      header: data.header,
      rows: data.rows,
      title: data.title,
      format: format as ExportFormat,
    });
    ElMessage.success(format === "csv" ? "已导出 CSV。" : "已导出 Excel。");
  } catch (error) {
    ElMessage.error(`导出失败：${(error as Error).message}`);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <el-dropdown trigger="click" @command="run">
    <el-button :size="size" :disabled="disabled" :loading="busy">
      {{ label }}<span class="caret">▾</span>
    </el-button>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="csv">导出 CSV</el-dropdown-item>
        <el-dropdown-item command="xlsx">导出 Excel（.xlsx）</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.caret {
  margin-left: 2px;
  font-size: 10px;
}
</style>
