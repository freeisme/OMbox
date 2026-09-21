<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  PRIORITY_OPTIONS,
  TICKET_TRANSITIONS,
  TICKET_TYPE_OPTIONS,
  addTicketNote,
  createTicket,
  fetchTicket,
  fetchTickets,
  transitionTicket,
  type TicketDetail,
  type TicketRow,
} from "../api/service";
import { formatDateTimeText, ticketStatusLabel, ticketStatusTagType } from "../labels";
import { hasPermission } from "../session";
import DataPanel from "../components/ui/DataPanel.vue";
import FilterBar from "../components/ui/FilterBar.vue";
import PageHeader from "../components/ui/PageHeader.vue";

const loading = ref(true);
const saving = ref(false);
const tickets = ref<TicketRow[]>([]);
const filters = reactive({ keyword: "", status: "", mine: "" });
const page = ref(1);
const pageSize = ref(20);

const createVisible = ref(false);
const createForm = reactive({
  title: "",
  description: "",
  type: "incident",
  impact: "medium",
  urgency: "medium",
  priority: "medium",
});

const detailVisible = ref(false);
const detail = ref<TicketDetail | null>(null);
const noteText = ref("");
const transitionTarget = ref("");
const resolutionText = ref("");

const filtered = computed(() => tickets.value);
const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return filtered.value.slice(start, start + pageSize.value);
});
const availableTransitions = computed(() =>
  detail.value ? TICKET_TRANSITIONS[detail.value.status] ?? [] : [],
);

async function load(): Promise<void> {
  loading.value = true;
  try {
    tickets.value = await fetchTickets({
      keyword: filters.keyword.trim(),
      status: filters.status,
      mine: filters.mine,
    });
    page.value = 1;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "工单加载失败。");
  } finally {
    loading.value = false;
  }
}

async function submitCreate(): Promise<void> {
  if (!createForm.title.trim()) {
    ElMessage.warning("请填写工单标题。");
    return;
  }
  saving.value = true;
  try {
    await createTicket({
      title: createForm.title.trim(),
      description: createForm.description.trim(),
      type: createForm.type,
      impact: createForm.impact,
      urgency: createForm.urgency,
      priority: createForm.priority,
    });
    ElMessage.success("工单已创建。");
    createVisible.value = false;
    createForm.title = "";
    createForm.description = "";
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "创建失败。");
  } finally {
    saving.value = false;
  }
}

async function openDetail(row: TicketRow): Promise<void> {
  try {
    detail.value = await fetchTicket(row.id);
    noteText.value = "";
    transitionTarget.value = "";
    resolutionText.value = "";
    detailVisible.value = true;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "工单详情加载失败。");
  }
}

async function submitTransition(): Promise<void> {
  if (!detail.value || !transitionTarget.value) {
    ElMessage.warning("请选择要流转到的状态。");
    return;
  }
  if (transitionTarget.value === "resolved" && !resolutionText.value.trim()) {
    ElMessage.warning("标记为已解决需要填写处理结果。");
    return;
  }
  saving.value = true;
  try {
    await transitionTicket(detail.value.id, {
      status: transitionTarget.value,
      resolution: resolutionText.value.trim(),
    });
    ElMessage.success("工单状态已更新。");
    detail.value = await fetchTicket(detail.value.id);
    transitionTarget.value = "";
    resolutionText.value = "";
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "流转失败。");
  } finally {
    saving.value = false;
  }
}

async function submitNote(): Promise<void> {
  if (!detail.value || !noteText.value.trim()) {
    ElMessage.warning("请填写处理记录。");
    return;
  }
  saving.value = true;
  try {
    await addTicketNote(detail.value.id, noteText.value.trim());
    noteText.value = "";
    detail.value = await fetchTicket(detail.value.id);
    ElMessage.success("处理记录已保存。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败。");
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <PageHeader title="工单" description="统一受理故障与服务请求，记录处理过程与 SLA 状态">
    <template #actions>
      <el-button @click="load">刷新</el-button>
      <el-button v-if="hasPermission('tickets', 'create')" type="primary" @click="createVisible = true">
        新建工单
      </el-button>
    </template>
    <template #filters>
      <FilterBar :summary="`共 ${tickets.length} 条`">
        <el-input
          v-model="filters.keyword"
          placeholder="标题、编号或描述"
          clearable
          style="max-width: 280px"
          @keyup.enter="load"
        />
        <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 150px">
          <el-option
            v-for="status in Object.keys(TICKET_TRANSITIONS)"
            :key="status"
            :label="ticketStatusLabel(status)"
            :value="status"
          />
        </el-select>
        <el-select v-model="filters.mine" placeholder="全部工单" clearable style="width: 150px">
          <el-option label="只看我负责的" value="1" />
        </el-select>
        <template #actions>
          <el-button type="primary" @click="load">查询</el-button>
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
      empty-text="暂无工单"
    >
      <el-table-column label="编号" width="140">
        <template #default="{ row }">{{ row.number || row.id }}</template>
      </el-table-column>
      <el-table-column prop="title" label="标题" min-width="220" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="ticketStatusTagType(row.status)">
            {{ ticketStatusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="优先级" width="90">
        <template #default="{ row }">
          {{ PRIORITY_OPTIONS.find((item) => item.value === row.priority)?.label || row.priority || "—" }}
        </template>
      </el-table-column>
      <el-table-column label="SLA" width="130">
        <template #default="{ row }">
          <el-tag v-if="row.slaState === 'breached'" size="small" type="danger">已超时</el-tag>
          <span v-else-if="row.slaState === 'running'" class="oa-muted">
            剩余 {{ row.slaRemainingMinutes ?? "—" }} 分钟
          </span>
          <span v-else class="oa-muted">未配置</span>
        </template>
      </el-table-column>
      <el-table-column prop="assignedToName" label="负责人" width="110" />
      <el-table-column prop="requesterName" label="报障人" width="110" />
      <el-table-column label="创建时间" width="150">
        <template #default="{ row }">{{ formatDateTimeText(row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">处理</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :page-sizes="[10, 20, 50]"
      :total="filtered.length"
      layout="total, sizes, prev, pager, next"
      class="oa-pagination"
    />
  </DataPanel>

  <FormDialog
    v-model="createVisible"
    title="新建工单"
    size="md"
    confirm-text="创建"
    :loading="saving"
    @confirm="submitCreate"
  >
    <el-form label-position="top">
      <el-form-item label="标题" required><el-input v-model="createForm.title" /></el-form-item>
      <el-form-item label="描述">
        <el-input v-model="createForm.description" type="textarea" :rows="3" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :xs="12" :sm="6">
          <el-form-item label="类型">
            <el-select v-model="createForm.type" class="oa-full-width">
              <el-option v-for="item in TICKET_TYPE_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-form-item label="影响">
            <el-select v-model="createForm.impact" class="oa-full-width">
              <el-option v-for="item in PRIORITY_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-form-item label="紧急度">
            <el-select v-model="createForm.urgency" class="oa-full-width">
              <el-option v-for="item in PRIORITY_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :xs="12" :sm="6">
          <el-form-item label="优先级">
            <el-select v-model="createForm.priority" class="oa-full-width">
              <el-option v-for="item in PRIORITY_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>
  </FormDialog>

  <DetailDrawer
    v-model="detailVisible"
    :title="detail ? `${detail.number || detail.id} · ${detail.title}` : '工单详情'"
    size="lg"
  >
    <template v-if="detail">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="状态">
          <el-tag size="small" :type="ticketStatusTagType(detail.status)">
            {{ ticketStatusLabel(detail.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="SLA">
          {{ detail.slaState === "breached" ? "已超时" : detail.slaState || "未配置" }}
        </el-descriptions-item>
        <el-descriptions-item label="负责人">{{ detail.assignedToName || "未分配" }}</el-descriptions-item>
        <el-descriptions-item label="报障人">{{ detail.requesterName || "—" }}</el-descriptions-item>
        <el-descriptions-item label="关联终端">{{ detail.relatedComputerName || "—" }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">
          {{ formatDateTimeText(detail.createdAt) }}
        </el-descriptions-item>
        <el-descriptions-item label="描述" :span="2">
          {{ detail.description || detail.summary || "—" }}
        </el-descriptions-item>
        <el-descriptions-item label="处理结果" :span="2">
          {{ detail.resolution || "—" }}
        </el-descriptions-item>
      </el-descriptions>

      <el-divider content-position="left">处理记录</el-divider>
      <el-table :data="detail.notes ?? []" size="small" border empty-text="暂无处理记录">
        <el-table-column prop="createdByName" label="记录人" width="100" />
        <el-table-column prop="content" label="内容" min-width="200" />
        <el-table-column label="时间" width="140">
          <template #default="{ row }">{{ formatDateTimeText(row.createdAt) }}</template>
        </el-table-column>
      </el-table>
      <el-input
        v-model="noteText"
        type="textarea"
        :rows="2"
        placeholder="填写处理记录"
        class="oa-mt-2"
      />
      <div class="oa-text-right oa-mt-2">
        <el-button :loading="saving" @click="submitNote">保存记录</el-button>
      </div>

      <el-divider content-position="left">状态流转</el-divider>
      <el-select v-model="transitionTarget" placeholder="选择要流转到的状态" class="oa-full-width">
        <el-option
          v-for="status in availableTransitions"
          :key="status"
          :label="ticketStatusLabel(status)"
          :value="status"
        />
      </el-select>
      <el-input
        v-if="transitionTarget === 'resolved'"
        v-model="resolutionText"
        type="textarea"
        :rows="2"
        placeholder="处理结果（标记已解决时必填）"
        class="oa-mt-2"
      />
      <div class="oa-text-right oa-mt-2">
        <el-button
          type="primary"
          :disabled="!transitionTarget"
          :loading="saving"
          @click="submitTransition"
        >
          提交流转
        </el-button>
      </div>
    </template>
  </DetailDrawer>
</template>
