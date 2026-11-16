<script setup lang="ts">
/** 工控机总览：在线率、各车间分布、待处理告警、未分配设备。 */
import { onMounted, onUnmounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getMeta, getOverview, getTree, LG_STATUS_LABELS, resolveAlert, type LgOverview, type LgTreeWorkshop } from "../api/lineguard";

const loading = ref(false);
const overview = ref<LgOverview | null>(null);
const tree = ref<LgTreeWorkshop[]>([]);
const meta = ref<{ offline_seconds: number; probe_interval_seconds: number } | null>(null);
let timer: number | undefined;

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [data, treeData, metaData] = await Promise.all([getOverview(), getTree(), getMeta()]);
    overview.value = data;
    tree.value = treeData.workshops;
    meta.value = metaData;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载失败。");
  } finally {
    loading.value = false;
  }
}

async function resolve(id: number): Promise<void> {
  try {
    await resolveAlert(id);
    ElMessage.success("已标记处理。");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "操作失败。");
  }
}

function percent(value: number, total: number): number {
  return total ? Math.round((value / total) * 100) : 0;
}

onMounted(async () => {
  await load();
  timer = window.setInterval(load, 60_000);
});
onUnmounted(() => { if (timer) window.clearInterval(timer); });
</script>

<template>
  <section class="oa-page" v-loading="loading">
    <header class="oa-flex-between oa-mb-3">
      <h2 class="oa-page-title">工控机总览</h2>
      <span class="oa-hint" v-if="meta">
        离线判定 {{ meta.offline_seconds }} 秒 · 默认探测周期 {{ meta.probe_interval_seconds }} 秒
      </span>
    </header>

    <div class="oa-metric-grid oa-mb-3" v-if="overview">
      <el-card shadow="never" class="oa-metric-card">
        <div class="oa-hint">在线率</div>
        <div class="oa-metric-value">{{ overview.summary.health }}%</div>
        <el-progress :percentage="overview.summary.health" :show-text="false" />
      </el-card>
      <el-card shadow="never" class="oa-metric-card">
        <div class="oa-hint">在线 / 离线</div>
        <div class="oa-metric-value">
          <span style="color: var(--el-color-success)">{{ overview.summary.online }}</span>
          <span class="oa-hint"> / </span>
          <span style="color: var(--el-color-danger)">{{ overview.summary.offline }}</span>
        </div>
        <div class="oa-hint">共 {{ overview.summary.total }} 台</div>
      </el-card>
      <el-card shadow="never" class="oa-metric-card">
        <div class="oa-hint">故障 / 检修中</div>
        <div class="oa-metric-value">
          {{ overview.summary.fault }} <span class="oa-hint">/</span> {{ overview.summary.maintenance }}
        </div>
        <div class="oa-hint">已下线 {{ overview.summary.retired }}</div>
      </el-card>
      <el-card shadow="never" class="oa-metric-card">
        <div class="oa-hint">未分配产线</div>
        <div class="oa-metric-value">{{ overview.unassigned }}</div>
        <div class="oa-hint">待处理告警 {{ overview.alerts.length }}</div>
      </el-card>
    </div>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>各车间状态</template>
          <el-table :data="overview?.by_workshop || []" size="small" border>
            <el-table-column prop="name" label="车间" min-width="140" />
            <el-table-column label="在线" width="80" align="center">
              <template #default="{ row }">{{ row.stats.online || 0 }}</template>
            </el-table-column>
            <el-table-column label="离线" width="80" align="center">
              <template #default="{ row }">{{ row.stats.offline || 0 }}</template>
            </el-table-column>
            <el-table-column label="故障/检修" width="100" align="center">
              <template #default="{ row }">{{ (row.stats.fault || 0) + (row.stats.maintenance || 0) }}</template>
            </el-table-column>
            <el-table-column label="合计" width="80" align="center">
              <template #default="{ row }">
                {{ Object.values(row.stats).reduce((sum: number, item: any) => sum + Number(item), 0) as number }}
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!overview?.by_workshop?.length" description="还没有车间数据" :image-size="60" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>待处理告警</template>
          <el-table :data="overview?.alerts || []" size="small" border max-height="320">
            <el-table-column label="级别" width="80">
              <template #default="{ row }">
                <el-tag :type="row.level === 'critical' ? 'danger' : 'warning'" size="small">
                  {{ row.level === 'critical' ? '严重' : row.level === 'warning' ? '警告' : '提示' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="asset_no" label="资产编号" width="120" />
            <el-table-column prop="message" label="内容" min-width="200" show-overflow-tooltip />
            <el-table-column label="操作" width="80">
              <template #default="{ row }"><el-button link type="primary" @click="resolve(row.id)">处理</el-button></template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!overview?.alerts?.length" description="没有待处理告警" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="oa-mt-3">
      <template #header>车间 / 产线分布</template>
      <el-table :data="tree" size="small" border row-key="id">
        <el-table-column prop="name" label="车间" width="160" />
        <el-table-column label="产线">
          <template #default="{ row }">
            <div v-for="line in row.lines" :key="line.id" class="oa-flex-row oa-mb-1">
              <strong style="min-width: 140px">{{ line.name }}</strong>
              <span class="oa-hint">
                {{ line.device_count }} 台 ·
                <span v-for="(count, status) in line.stats" :key="status" style="margin-right: 8px">
                  {{ LG_STATUS_LABELS[status] || status }} {{ count }}
                </span>
              </span>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!tree.length" description="还没有车间与产线" :image-size="60" />
    </el-card>
  </section>
</template>
