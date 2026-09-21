<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  FLOW_DEFINITIONS,
  correctFlowNote,
  flowDefinition,
  flowNoteText,
  flowRecordsToCsv,
  flowStockImpact,
  loadFlowRecords,
  type FlowRecord,
} from "../api/flows";
import { formatDateTimeText } from "../labels";
import { hasPermission } from "../session";
import DataPanel from "../components/ui/DataPanel.vue";
import FilterBar from "../components/ui/FilterBar.vue";
import PageHeader from "../components/ui/PageHeader.vue";

const loading = ref(true);
const saving = ref(false);
const records = ref<FlowRecord[]>([]);
const filters = reactive({
  keyword: "",
  typeName: "",
  action: "",
  category: "",
  dateRange: [] as string[],
});
const page = ref(1);
const pageSize = ref(50);
const noteVisible = ref(false);
const noteTarget = ref<FlowRecord | null>(null);
const noteForm = reactive({ correctedNote: "", correctionReason: "" });

const typeOptions = computed(() =>
  [...new Set(records.value.map((item) => item.typeName).filter(Boolean))].sort(),
);
const actionOptions = computed(() =>
  [...new Set(records.value.map((item) => item.triggerAction).filter(Boolean))].sort(),
);
const categoryOptions = computed(() =>
  [...new Set(Object.values(FLOW_DEFINITIONS).map((item) => item.category))].sort(),
);

const filtered = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase();
  const [start, end] = filters.dateRange ?? [];
  return records.value.filter((record) => {
    if (filters.typeName && record.typeName !== filters.typeName) return false;
    if (filters.action && record.triggerAction !== filters.action) return false;
    if (filters.category && flowDefinition(record).category !== filters.category) return false;
    if (start && String(record.occurredAt).slice(0, 10) < start) return false;
    if (end && String(record.occurredAt).slice(0, 10) > end) return false;
    if (!keyword) return true;
    return [
      record.typeName,
      record.brandName,
      record.modelName,
      record.sourceLabel,
      record.targetLabel,
      record.relatedEmployeeName,
      record.relatedEmployeeNo,
      flowNoteText(record),
    ]
      .join(" ")
      .toLowerCase()
      .includes(keyword);
  });
});

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return filtered.value.slice(start, start + pageSize.value);
});

function impactTagType(record: FlowRecord): "success" | "danger" | "info" {
  const impact = flowStockImpact(record);
  if (impact === "增加") return "success";
  if (impact === "减少") return "danger";
  return "info";
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    records.value = await loadFlowRecords(true);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "流转记录加载失败。");
  } finally {
    loading.value = false;
  }
}

function openNote(record: FlowRecord): void {
  noteTarget.value = record;
  noteForm.correctedNote = flowNoteText(record);
  noteForm.correctionReason = "";
  noteVisible.value = true;
}

async function submitNote(): Promise<void> {
  const target = noteTarget.value;
  if (!target) return;
  if (!noteForm.correctedNote.trim() || !noteForm.correctionReason.trim()) {
    ElMessage.warning("请填写更正后的备注与更正原因。");
    return;
  }
  saving.value = true;
  try {
    await correctFlowNote(target.id, {
      correctedNote: noteForm.correctedNote.trim(),
      correctionReason: noteForm.correctionReason.trim(),
    });
    ElMessage.success("备注更正已记录。");
    noteVisible.value = false;
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更正失败。");
  } finally {
    saving.value = false;
  }
}

function exportCsv(): void {
  if (!filtered.value.length) {
    ElMessage.warning("当前没有可导出的记录。");
    return;
  }
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  const blob = new Blob([`\ufeff${flowRecordsToCsv(filtered.value)}`], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `物资流转记录-${stamp}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function clearFilters(): void {
  filters.keyword = "";
  filters.typeName = "";
  filters.action = "";
  filters.category = "";
  filters.dateRange = [];
}

onMounted(load);
</script>

<template>
  <PageHeader
    title="物资流转记录"
    description="按物品、关联人员、业务类型、来源去向和时间区间查看自动登记的物资流转信息"
  >
    <template #actions>
      <el-button :disabled="!filtered.length" @click="exportCsv">导出当前结果</el-button>
    </template>
    <template #filters>
      <FilterBar :summary="`显示 ${filtered.length} / ${records.length} 条`">
        <el-form label-position="top" class="oa-filter-form">
      <el-row :gutter="12">
        <el-col :xs="24" :sm="12" :md="6">
          <el-form-item label="关键字">
            <el-input v-model="filters.keyword" placeholder="物品、品牌、型号或备注" clearable />
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6" :md="3">
          <el-form-item label="物资类型">
            <el-select v-model="filters.typeName" placeholder="全部" clearable class="oa-full-width">
              <el-option v-for="item in typeOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6" :md="3">
          <el-form-item label="业务类型">
            <el-select v-model="filters.action" placeholder="全部" clearable filterable class="oa-full-width">
              <el-option
                v-for="item in actionOptions"
                :key="item"
                :label="FLOW_DEFINITIONS[item]?.label ?? item"
                :value="item"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6" :md="3">
          <el-form-item label="业务分类">
            <el-select v-model="filters.category" placeholder="全部" clearable class="oa-full-width">
              <el-option v-for="item in categoryOptions" :key="item" :label="item" :value="item" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="24" :sm="12" :md="5">
          <el-form-item label="时间区间">
            <el-date-picker
              v-model="filters.dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始"
              end-placeholder="结束"
              class="oa-full-width"
            />
          </el-form-item>
        </el-col>
      </el-row>
        </el-form>
        <template #actions>
          <el-button @click="clearFilters">清除筛选</el-button>
        </template>
      </FilterBar>
    </template>
  </PageHeader>

  <DataPanel class="oa-panel-gap" :loading="loading">
    <el-table
      :data="paged"
      size="small"
      border
      stripe
      empty-text="暂无物资流转记录"
    >
      <el-table-column label="时间" width="150">
        <template #default="{ row }">{{ formatDateTimeText(row.occurredAt) }}</template>
      </el-table-column>
      <el-table-column label="业务类型" width="120">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ flowDefinition(row).label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="业务分类" width="110">
        <template #default="{ row }">{{ flowDefinition(row).category }}</template>
      </el-table-column>
      <el-table-column prop="typeName" label="物资类型" width="110" />
      <el-table-column label="品牌 / 型号" min-width="170">
        <template #default="{ row }">
          <div>{{ row.brandName || "未登记品牌" }}</div>
          <div class="oa-cell-sub">
            {{ row.modelName || "未登记型号" }}
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="quantity" label="数量" width="70" />
      <el-table-column label="库存影响" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="impactTagType(row)">{{ flowStockImpact(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="sourceLabel" label="调出方" min-width="120" />
      <el-table-column prop="targetLabel" label="接收方" min-width="140" />
      <el-table-column label="关联人员" width="120">
        <template #default="{ row }">
          {{ [row.relatedEmployeeName, row.relatedEmployeeNo].filter(Boolean).join(" / ") || "—" }}
        </template>
      </el-table-column>
      <el-table-column label="备注" min-width="200">
        <template #default="{ row }">
          <div>{{ flowNoteText(row) || "—" }}</div>
          <div
            v-if="(row.noteCorrections ?? []).length"
            class="oa-warn-text"
          >
            已修正 {{ row.noteCorrections.length }} 次
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="hasPermission('inventory_operations', 'update')"
            link
            type="primary"
            @click="openNote(row)"
          >
            修正
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

  <FormDialog
    v-model="noteVisible"
    title="修正流转备注"
    size="md"
    confirm-text="保存更正"
    :loading="saving"
    @confirm="submitNote"
  >
    <p class="oa-hint">
      更正不会覆盖原始记录，系统会保留原始备注、更正内容与更正原因。
    </p>
    <el-form label-position="top">
      <el-form-item label="更正后的备注" required>
        <el-input v-model="noteForm.correctedNote" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item label="更正原因" required>
        <el-input v-model="noteForm.correctionReason" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
  </FormDialog>
</template>
