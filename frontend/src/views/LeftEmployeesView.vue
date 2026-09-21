<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  loadDirectoryData,
  offboardDeviceActionText,
  type LeftDeviceRow,
  type LeftEmployeeRow,
} from "../api/directory";
import DataPanel from "../components/ui/DataPanel.vue";
import FilterBar from "../components/ui/FilterBar.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import { formatDateTimeText } from "../labels";

const router = useRouter();
const loading = ref(true);
const rows = ref<LeftEmployeeRow[]>([]);
const keyword = ref("");
const detail = ref<LeftEmployeeRow | null>(null);
const detailVisible = ref(false);
const page = ref(1);
const pageSize = ref(50);

const filtered = computed(() => {
  const key = keyword.value.trim().toLowerCase();
  if (!key) return rows.value;
  return rows.value.filter((row) =>
    [row.name, row.employeeNo, row.orgPath, row.department, row.leaveInfo, row.leaveRemark]
      .join(" ")
      .toLowerCase()
      .includes(key),
  );
});

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return filtered.value.slice(start, start + pageSize.value);
});

const summary = computed(() => `显示 ${filtered.value.length} / ${rows.value.length} 人`);

function deviceSummary(devices: LeftDeviceRow[] | undefined): string {
  const list = devices ?? [];
  if (!list.length) return "暂无离职设备快照";
  return list
    .map((device) => {
      const extra = [
        device.detail,
        Number(device.quantity ?? 0) > 1 ? `x${device.quantity}` : "",
        offboardDeviceActionText(device),
      ]
        .filter(Boolean)
        .join(" · ");
      return extra ? `${device.label ?? "设备"}（${extra}）` : device.label ?? "设备";
    })
    .join("；");
}

function openDetail(row: LeftEmployeeRow): void {
  detail.value = row;
  detailVisible.value = true;
}

function resetFilters(): void {
  keyword.value = "";
}

onMounted(async () => {
  loading.value = true;
  try {
    const data = await loadDirectoryData();
    rows.value = data.leftEmployees;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "离职人员数据加载失败。");
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <PageHeader
    title="离职人员"
    description="离职人员已从组织树移出，保留离职时间、说明、备注与离职时设备快照"
  >
    <template #actions>
      <el-button @click="router.push('/employees')">返回使用人员</el-button>
    </template>
    <template #filters>
      <FilterBar :summary="summary" :resettable="Boolean(keyword)" @reset="resetFilters">
        <el-input
          v-model="keyword"
          placeholder="搜索姓名、编号、组织、部门或离职说明"
          clearable
          style="max-width: 360px"
        />
      </FilterBar>
    </template>
  </PageHeader>

  <DataPanel class="oa-panel-gap" :loading="loading">
    <el-table :data="paged" size="small" border stripe empty-text="暂无离职人员记录">
      <el-table-column label="人员" min-width="150">
        <template #default="{ row }">
          <div>{{ row.name }}</div>
          <div class="oa-cell-sub">{{ row.employeeNo }}</div>
        </template>
      </el-table-column>
      <el-table-column label="原组织 / 部门" min-width="220">
        <template #default="{ row }">
          <div>{{ row.orgPath || "—" }}</div>
          <div class="oa-cell-sub">{{ row.department || "未填写部门" }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="position" label="岗位" width="110" />
      <el-table-column prop="leaveDate" label="离职日期" width="115" />
      <el-table-column label="离职设备快照" min-width="280" show-overflow-tooltip>
        <template #default="{ row }">{{ deviceSummary(row.devices) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">查看详情</el-button>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100, 200]"
        :total="filtered.length"
        layout="total, sizes, prev, pager, next"
        class="oa-pagination"
      />
    </template>
  </DataPanel>

  <DetailDrawer v-model="detailVisible" :title="`${detail?.name ?? ''} · 离职人员档案`" size="md">
    <el-descriptions v-if="detail" :column="1" border>
      <el-descriptions-item label="人员编号">{{ detail.employeeNo || "—" }}</el-descriptions-item>
      <el-descriptions-item label="人员姓名">{{ detail.name || "—" }}</el-descriptions-item>
      <el-descriptions-item label="原组织路径">{{ detail.orgPath || "—" }}</el-descriptions-item>
      <el-descriptions-item label="部门">{{ detail.department || "—" }}</el-descriptions-item>
      <el-descriptions-item label="岗位">{{ detail.position || "—" }}</el-descriptions-item>
      <el-descriptions-item label="离职日期">{{ detail.leaveDate || "—" }}</el-descriptions-item>
      <el-descriptions-item label="归档时间">
        {{ formatDateTimeText(detail.archivedAt) }}
      </el-descriptions-item>
      <el-descriptions-item label="手机号">{{ detail.mobile || "—" }}</el-descriptions-item>
      <el-descriptions-item label="离职信息">{{ detail.leaveInfo || "—" }}</el-descriptions-item>
      <el-descriptions-item label="备注">{{ detail.leaveRemark || "—" }}</el-descriptions-item>
    </el-descriptions>
    <div class="oa-drawer-section">
      <h4>离职时设备快照（{{ (detail?.devices ?? []).length }} 条）</h4>
      <el-descriptions v-if="(detail?.devices ?? []).length" :column="1" border size="small">
        <el-descriptions-item
          v-for="(device, index) in detail?.devices ?? []"
          :key="index"
          :label="device.label || `设备 ${index + 1}`"
        >
          {{ [device.detail, Number(device.quantity ?? 0) > 1 ? `x${device.quantity}` : "", offboardDeviceActionText(device)].filter(Boolean).join(" · ") || "—" }}
        </el-descriptions-item>
      </el-descriptions>
      <el-empty v-else description="暂无离职设备快照" :image-size="60" />
    </div>
  </DetailDrawer>
</template>
