<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "../api/client";
import { session } from "../session";
import {
  issueMyCredential,
  listMyCredentials,
  listMyTickets,
  revokeMyCredential,
  type ApiCredentialRow,
  type MyTicketRow,
} from "../api/me";

interface ComputerRow {
  id: string;
  deviceName?: string;
  deviceType?: string;
  status?: string;
  userId?: string;
  brandName?: string;
  modelName?: string;
}

interface EmployeeRow {
  id: string;
  name?: string;
  employeeNo?: string;
  department?: string;
  position?: string;
  email?: string;
  mobile?: string;
  orgId?: string;
}

const loading = ref(true);
const employees = ref<EmployeeRow[]>([]);
const computers = ref<ComputerRow[]>([]);
const tickets = ref<MyTicketRow[]>([]);
const credentials = ref<ApiCredentialRow[]>([]);
const tokenDialogVisible = ref(false);
const tokenName = ref("");
const issuedToken = ref("");
const issuing = ref(false);

const employeeId = computed(() => String(session.user?.employeeId || ""));
const me = computed<EmployeeRow | undefined>(() =>
  employees.value.find((row) => String(row.id) === employeeId.value),
);
const myDevices = computed(() =>
  computers.value.filter((row) => String(row.userId || "") === employeeId.value),
);

async function load(): Promise<void> {
  loading.value = true;
  try {
    const [state, myTicketRows, creds] = await Promise.all([
      api<{ employees?: EmployeeRow[]; computers?: ComputerRow[] }>(
        "/api/state?include=employees,computers",
      ),
      listMyTickets(),
      listMyCredentials(),
    ]);
    employees.value = state.employees ?? [];
    computers.value = state.computers ?? [];
    tickets.value = myTicketRows;
    credentials.value = creds;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "个人数据加载失败。");
  } finally {
    loading.value = false;
  }
}

function openTokenDialog(): void {
  tokenName.value = "";
  issuedToken.value = "";
  tokenDialogVisible.value = true;
}

async function createToken(): Promise<void> {
  issuing.value = true;
  try {
    const result = await issueMyCredential(tokenName.value.trim() || "我的令牌");
    issuedToken.value = result.token;
    credentials.value = await listMyCredentials();
    ElMessage.success("令牌已创建，请立即复制保存。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "令牌创建失败。");
  } finally {
    issuing.value = false;
  }
}

async function copyToken(): Promise<void> {
  try {
    await navigator.clipboard.writeText(issuedToken.value);
    ElMessage.success("已复制到剪贴板。");
  } catch {
    ElMessage.warning("复制失败，请手动选择文本。");
  }
}

async function removeToken(row: ApiCredentialRow): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定吊销令牌「${row.name}」吗？吊销后使用它的客户端会立即失效。`, "吊销令牌", {
      type: "warning",
      confirmButtonText: "吊销",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await revokeMyCredential(row.id);
    credentials.value = await listMyCredentials();
    ElMessage.success("令牌已吊销。");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "吊销失败。");
  }
}

onMounted(load);
</script>

<template>
  <PageHeader title="我的工作台" description="我的信息、名下设备、我提交的工单，以及供 AI 客户端使用的个人 API 令牌">
    <template #actions>
      <el-button @click="load">刷新</el-button>
      <el-button type="primary" @click="openTokenDialog">新建 API 令牌</el-button>
    </template>
  </PageHeader>

  <DataPanel :loading="loading" class="oa-panel-gap">
    <el-descriptions title="我的信息" :column="3" border size="small">
      <el-descriptions-item label="姓名">{{ me?.name || session.user?.displayName || "—" }}</el-descriptions-item>
      <el-descriptions-item label="工号">{{ me?.employeeNo || "—" }}</el-descriptions-item>
      <el-descriptions-item label="部门">{{ me?.department || "—" }}</el-descriptions-item>
      <el-descriptions-item label="岗位">{{ me?.position || "—" }}</el-descriptions-item>
      <el-descriptions-item label="邮箱">{{ me?.email || "—" }}</el-descriptions-item>
      <el-descriptions-item label="手机">{{ me?.mobile || "—" }}</el-descriptions-item>
    </el-descriptions>
  </DataPanel>

  <DataPanel :loading="loading" class="oa-panel-gap" title="我名下的设备">
    <el-table :data="myDevices" size="small" empty-text="当前没有分配给你的设备">
      <el-table-column prop="deviceName" label="设备名称" min-width="180" />
      <el-table-column prop="deviceType" label="类型" width="120" />
      <el-table-column label="品牌型号" min-width="160">
        <template #default="{ row }">{{ [row.brandName, row.modelName].filter(Boolean).join(" ") || "—" }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="110" />
    </el-table>
  </DataPanel>

  <DataPanel :loading="loading" class="oa-panel-gap" title="我提交的工单">
    <el-table :data="tickets" size="small" empty-text="还没有提交过工单">
      <el-table-column prop="number" label="工单号" width="170" />
      <el-table-column prop="title" label="标题" min-width="220" />
      <el-table-column prop="status" label="状态" width="110" />
      <el-table-column prop="createdAt" label="提交时间" width="170" />
    </el-table>
  </DataPanel>

  <DataPanel :loading="loading" class="oa-panel-gap" title="个人 API 令牌">
    <el-alert type="info" :closable="false" show-icon class="oa-mb-2"
      title="令牌仅用于你的 AI 客户端连接 MCP 网关，权限与你的账号完全一致；令牌只在创建时显示一次。" />
    <el-table :data="credentials" size="small" empty-text="还没有创建令牌">
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="prefix" label="前缀" width="150" />
      <el-table-column prop="createdAt" label="创建时间" width="170" />
      <el-table-column prop="lastUsedAt" label="最近使用" width="170">
        <template #default="{ row }">{{ row.lastUsedAt || "未使用" }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.revoked ? 'info' : 'success'" size="small">{{ row.revoked ? "已吊销" : "有效" }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button v-if="!row.revoked" link type="danger" @click="removeToken(row)">吊销</el-button>
        </template>
      </el-table-column>
    </el-table>
  </DataPanel>

  <FormDialog v-model="tokenDialogVisible" title="新建 API 令牌" size="sm" :loading="issuing" @confirm="createToken">
    <el-form label-width="80px">
      <el-form-item label="名称">
        <el-input v-model="tokenName" maxlength="64" placeholder="例如：办公室 AI 助手" />
      </el-form-item>
      <el-form-item v-if="issuedToken" label="令牌">
        <div style="width: 100%">
          <el-input :model-value="issuedToken" type="textarea" :rows="3" readonly />
          <el-button class="oa-mt-1" size="small" @click="copyToken">复制令牌</el-button>
          <div class="oa-hint">关闭此窗口后无法再次查看，请妥善保存。</div>
        </div>
      </el-form-item>
    </el-form>
  </FormDialog>
</template>
