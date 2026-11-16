<script setup lang="ts">
/** 工控机告警中心 + 阈值配置。 */
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { getSettings, listAlerts, resolveAlert, saveSettings, type LgAlertRow } from "../api/lineguard";

const loading = ref(false);
const rows = ref<LgAlertRow[]>([]);
const onlyOpen = ref(true);
const settings = reactive<Record<string, string>>({ alert_cpu: "90", alert_mem: "90", alert_disk: "90" });

async function load(): Promise<void> {
  loading.value = true;
  try {
    const data = await listAlerts();
    rows.value = data.alerts;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载失败。");
  } finally {
    loading.value = false;
  }
}

async function loadSettings(): Promise<void> {
  try {
    const data = await getSettings();
    for (const key of ["alert_cpu", "alert_mem", "alert_disk"]) {
      if (data.settings[key]) settings[key] = data.settings[key];
    }
  } catch {
    // 未配置时用默认阈值
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

async function save(): Promise<void> {
  try {
    await saveSettings({ ...settings });
    ElMessage.success("阈值已保存。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败。");
  }
}

const visible = () => (onlyOpen.value ? rows.value.filter((item) => !item.resolved_at) : rows.value);

onMounted(async () => { await load(); await loadSettings(); });
</script>

<template>
  <section class="oa-page">
    <header class="oa-flex-between oa-mb-3">
      <h2 class="oa-page-title">工控机告警</h2>
      <div class="oa-flex-row">
        <el-switch v-model="onlyOpen" active-text="只看未处理" />
        <el-button @click="load">刷新</el-button>
      </div>
    </header>

    <el-card shadow="never" class="oa-mb-3">
      <span class="oa-hint">资源阈值（%）：</span>
      <div class="oa-flex-row oa-mt-2">
        <el-input v-model="settings.alert_cpu" placeholder="CPU" style="width: 110px" />
        <el-input v-model="settings.alert_mem" placeholder="内存" style="width: 110px" />
        <el-input v-model="settings.alert_disk" placeholder="磁盘" style="width: 110px" />
        <el-button type="primary" @click="save">保存阈值</el-button>
      </div>
    </el-card>

    <el-table v-loading="loading" :data="visible()" size="small" border>
      <el-table-column label="级别" width="90">
        <template #default="{ row }">
          <el-tag :type="row.level === 'critical' ? 'danger' : 'warning'" size="small">
            {{ row.level === 'critical' ? '严重' : row.level === 'warning' ? '警告' : '提示' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="asset_no" label="资产编号" width="130" />
      <el-table-column prop="hostname" label="主机名" width="140" />
      <el-table-column prop="message" label="内容" min-width="260" show-overflow-tooltip />
      <el-table-column prop="created_at" label="产生时间" width="160" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.resolved_at" type="info" size="small">已处理</el-tag>
          <el-tag v-else type="warning" size="small">未处理</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button v-if="!row.resolved_at" link type="primary" @click="resolve(row.id)">处理</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!visible().length" description="暂无告警" :image-size="70" />
  </section>
</template>
