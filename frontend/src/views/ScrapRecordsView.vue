<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  fetchScrapRecords,
  scrapKindLabel,
  scrapRecordSubtitle,
  scrapRecordTitle,
  scrapRecordsToCsv,
  type ScrapRecord,
} from "../api/scrap";
import DataPanel from "../components/ui/DataPanel.vue";
import FilterBar from "../components/ui/FilterBar.vue";
import PageHeader from "../components/ui/PageHeader.vue";

const loading = ref(true);
const records = ref<ScrapRecord[]>([]);
const keyword = ref("");
const kind = ref("");
const page = ref(1);
const pageSize = ref(50);
const detail = ref<ScrapRecord | null>(null);
const detailVisible = ref(false);

const filtered = computed(() => {
  const key = keyword.value.trim().toLowerCase();
  if (!key) return records.value;
  return records.value.filter((record) =>
    [
      scrapRecordTitle(record),
      scrapRecordSubtitle(record),
      record.reason,
      record.notes,
      record.employeeName,
      record.employeeNo,
      record.operatedByName,
    ]
      .join(" ")
      .toLowerCase()
      .includes(key),
  );
});

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return filtered.value.slice(start, start + pageSize.value);
});

async function load(): Promise<void> {
  loading.value = true;
  try {
    records.value = await fetchScrapRecords(kind.value, 500);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "报废记录加载失败。");
  } finally {
    loading.value = false;
  }
}

function exportCsv(): void {
  if (!filtered.value.length) {
    ElMessage.warning("当前没有可导出的记录。");
    return;
  }
  const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
  const blob = new Blob([`\ufeff${scrapRecordsToCsv(filtered.value)}`], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `报废记录-${stamp}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function openDetail(record: ScrapRecord): void {
  detail.value = record;
  detailVisible.value = true;
}

onMounted(load);
</script>

<template>
  <PageHeader
    title="报废记录"
    description="报废物资不回收、不回补库存，办公终端报废后软归档并保留追溯"
  >
    <template #actions>
      <el-button @click="load">刷新</el-button>
      <el-button :disabled="!filtered.length" @click="exportCsv">导出当前结果</el-button>
    </template>
    <template #filters>
      <FilterBar
        :summary="`显示 ${filtered.length} / ${records.length} 条`"
        :resettable="Boolean(keyword || kind)"
        @reset="keyword = ''; kind = ''; load()"
      >
        <el-input
          v-model="keyword"
          placeholder="物品、型号、人员、报废原因或备注"
          clearable
          style="max-width: 360px"
        />
        <el-select v-model="kind" placeholder="全部类型" clearable style="width: 160px" @change="load">
          <el-option label="IT物资" value="inventory" />
          <el-option label="办公终端" value="asset" />
        </el-select>
      </FilterBar>
    </template>
  </PageHeader>

  <DataPanel class="oa-panel-gap" :loading="loading">
    <el-table
      :data="paged"
      size="small"
      border
      stripe
      empty-text="暂无符合条件的报废记录"
    >
      <el-table-column prop="scrapAt" label="报废时间" width="150" />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.kind === 'asset' ? 'warning' : 'info'" effect="plain">
            {{ scrapKindLabel(row.kind) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="物品" min-width="200">
        <template #default="{ row }">
          <div>{{ scrapRecordTitle(row) }}</div>
          <div class="oa-cell-sub">
            {{ scrapRecordSubtitle(row) }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="数量" width="80">
        <template #default="{ row }">{{ Number(row.quantity || 0) || 1 }} 件</template>
      </el-table-column>
      <el-table-column label="使用人" width="130">
        <template #default="{ row }">
          <template v-if="row.employeeName">
            <div>{{ row.employeeName }}</div>
            <div class="oa-cell-sub">
              {{ row.employeeNo }}
            </div>
          </template>
          <span v-else class="oa-muted">未登记</span>
        </template>
      </el-table-column>
      <el-table-column prop="reason" label="报废原因" min-width="140">
        <template #default="{ row }">{{ row.reason || "未填写" }}</template>
      </el-table-column>
      <el-table-column prop="operatedByName" label="操作人" width="110" />
      <el-table-column label="库存影响" width="150">
        <template #default="{ row }">
          <span class="oa-muted">
            {{ Number(row.stockAdjusted) === 1 ? "已扣库存 · 不返还" : "未扣库存 · 无变化" }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
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
    v-model="detailVisible"
    title="报废记录详情"
    size="md"
  >
    <template #footer>
      <el-button @click="detailVisible = false">关闭</el-button>
    </template>
    <el-descriptions v-if="detail" :column="1" border>
      <el-descriptions-item label="报废时间">{{ detail.scrapAt || "—" }}</el-descriptions-item>
      <el-descriptions-item label="类型">{{ scrapKindLabel(detail.kind) }}</el-descriptions-item>
      <el-descriptions-item label="物品">{{ scrapRecordTitle(detail) }}</el-descriptions-item>
      <el-descriptions-item label="品牌型号">{{ scrapRecordSubtitle(detail) }}</el-descriptions-item>
      <el-descriptions-item label="数量">{{ Number(detail.quantity || 0) || 1 }} 件</el-descriptions-item>
      <el-descriptions-item label="使用人">
        {{ detail.employeeName || "—" }} {{ detail.employeeNo }}
      </el-descriptions-item>
      <el-descriptions-item label="报废原因">{{ detail.reason || "—" }}</el-descriptions-item>
      <el-descriptions-item label="说明">{{ detail.notes || "—" }}</el-descriptions-item>
      <el-descriptions-item label="操作人">{{ detail.operatedByName || "—" }}</el-descriptions-item>
      <el-descriptions-item label="库存影响">
        {{ Number(detail.stockAdjusted) === 1 ? "已扣库存 · 不返还" : "未扣库存 · 无变化" }}
      </el-descriptions-item>
    </el-descriptions>
  </FormDialog>
</template>
