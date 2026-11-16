<script setup lang="ts">
/** 设备详情：基本信息 + 换线履历 + 换下状况 + 事件时间线 + 探测记录。 */
import { ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { getDevice, LG_PROBE_LABELS, LG_STATUS_LABELS, type LgDevice } from "../../api/lineguard";

const props = defineProps<{ modelValue: boolean; deviceId: number | null }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void }>();

const loading = ref(false);
const detail = ref<{ device: LgDevice; transfers: any[]; conditions: any[]; events: any[]; checks: any[] } | null>(null);

watch(() => props.modelValue, async (open) => {
  if (!open || !props.deviceId) return;
  loading.value = true;
  try {
    detail.value = await getDevice(props.deviceId);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载详情失败。");
  } finally {
    loading.value = false;
  }
});

function statusType(status: string): "success" | "danger" | "warning" | "info" {
  if (status === "online") return "success";
  if (status === "offline") return "danger";
  if (status === "fault") return "warning";
  return "info";
}
</script>

<template>
  <el-drawer :model-value="modelValue" size="720px" :title="detail?.device?.asset_no || '设备详情'"
             @update:model-value="emit('update:modelValue', $event)">
    <div v-loading="loading">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="资产编号">{{ detail.device.asset_no }}</el-descriptions-item>
          <el-descriptions-item label="主机名">{{ detail.device.hostname }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusType(detail.device.status)" size="small">
              {{ LG_STATUS_LABELS[detail.device.status] || detail.device.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="IP">{{ detail.device.ip || "-" }}</el-descriptions-item>
          <el-descriptions-item label="位置">
            {{ detail.device.workshop_name || "-" }} / {{ detail.device.line_name || "-" }} /
            {{ detail.device.station_name || "未分工位" }}
          </el-descriptions-item>
          <el-descriptions-item label="检测方式">
            {{ LG_PROBE_LABELS[detail.device.probe_mode] || detail.device.probe_mode }}
            <span v-if="detail.device.probe_port"> · 端口 {{ detail.device.probe_port }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="型号">{{ detail.device.model || "-" }}</el-descriptions-item>
          <el-descriptions-item label="操作系统">{{ detail.device.os_version || "-" }}</el-descriptions-item>
          <el-descriptions-item label="责任人">{{ detail.device.owner || "-" }}</el-descriptions-item>
          <el-descriptions-item label="最近心跳">{{ detail.device.last_heartbeat_at || "-" }}</el-descriptions-item>
          <el-descriptions-item label="CPU / 内存 / 磁盘">
            {{ detail.device.cpu_percent ?? "-" }}% / {{ detail.device.mem_percent ?? "-" }}% / {{ detail.device.disk_percent ?? "-" }}%
          </el-descriptions-item>
          <el-descriptions-item label="备注">{{ detail.device.remark || "-" }}</el-descriptions-item>
        </el-descriptions>

        <el-tabs class="oa-mt-3">
          <el-tab-pane label="换线履历（{{ detail.transfers.length }}）">
            <el-table :data="detail.transfers" size="small" border max-height="260">
              <el-table-column label="时间" width="150"><template #default="{ row }">{{ row.created_at }}</template></el-table-column>
              <el-table-column label="从" min-width="150"><template #default="{ row }">{{ row.from_line_name || "未分配" }}</template></el-table-column>
              <el-table-column label="到" min-width="150"><template #default="{ row }">{{ row.to_line_name || "未分配" }}</template></el-table-column>
              <el-table-column prop="reason" label="原因" min-width="120" />
              <el-table-column prop="operator" label="操作人" width="100" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="换下状况（{{ detail.conditions.length }}）">
            <el-table :data="detail.conditions" size="small" border max-height="260">
              <el-table-column prop="created_at" label="时间" width="150" />
              <el-table-column prop="cond_type" label="类型" width="100" />
              <el-table-column prop="symptom" label="现象" min-width="150" />
              <el-table-column prop="resolution" label="处理" min-width="150" />
              <el-table-column prop="result" label="结论" width="90" />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="事件（{{ detail.events.length }}）">
            <el-timeline>
              <el-timeline-item v-for="item in detail.events" :key="item.id" :timestamp="item.created_at" placement="top">
                <strong>{{ item.title }}</strong>
                <div class="oa-hint">{{ item.detail }}</div>
              </el-timeline-item>
            </el-timeline>
          </el-tab-pane>
          <el-tab-pane label="探测记录">
            <el-table :data="detail.checks" size="small" border max-height="260">
              <el-table-column prop="checked_at" label="时间" width="150" />
              <el-table-column prop="source" label="来源" width="90" />
              <el-table-column prop="status" label="结果" width="80" />
              <el-table-column prop="latency_ms" label="时延(ms)" width="90" />
              <el-table-column prop="detail" label="说明" min-width="160" />
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </template>
      <el-empty v-else description="暂无数据" />
    </div>
  </el-drawer>
</template>
