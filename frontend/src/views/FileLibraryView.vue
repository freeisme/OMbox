<script setup lang="ts">
/** 机房文件库：左侧「机房 → 设备」目录树，右侧配置文件与操作记录。 */
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  deleteFile,
  downloadUrl,
  getFileTree,
  listEvents,
  listFiles,
  updateFile,
  uploadFile,
  type FileDevice,
  type FileEvent,
  type FileItem,
  type FileSite,
} from "../api/fileLibrary";

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const sites = ref<FileSite[]>([]);
const devices = ref<FileDevice[]>([]);
const files = ref<FileItem[]>([]);
const events = ref<FileEvent[]>([]);
const keyword = ref("");
const activeKey = ref("");
const eventsVisible = ref(false);
const uploading = ref(false);
const uploadInput = ref<HTMLInputElement | null>(null);
const uploadForm = reactive({ description: "" });

const siteName = computed(() => new Map(sites.value.map((item) => [item.id, item.name])));
const filteredDevices = computed(() => {
  const term = keyword.value.trim().toLowerCase();
  if (!term) return devices.value;
  return devices.value.filter((item) =>
    (item.name + " " + item.code).toLowerCase().includes(term),
  );
});
/** 未归属机房的设备单独一组。 */
const deviceGroups = computed(() => {
  const groups: Array<{ key: string; label: string; items: FileDevice[] }> = [];
  const bySite = new Map<string, FileDevice[]>();
  filteredDevices.value.forEach((item) => {
    const key = item.siteId && item.siteId !== "0" ? item.siteId : "0";
    bySite.set(key, [...(bySite.get(key) ?? []), item]);
  });
  sites.value.forEach((site) => {
    const items = bySite.get(site.id) ?? [];
    if (items.length) groups.push({ key: site.id, label: site.name, items });
    bySite.delete(site.id);
  });
  const orphan = bySite.get("0") ?? [];
  if (orphan.length) groups.push({ key: "0", label: "未分配机房", items: orphan });
  return groups;
});
const currentDevice = computed(() => devices.value.find((item) => item.id === activeKey.value) ?? null);

function folderOf(key: string): string {
  const device = devices.value.find((item) => item.id === key);
  return device?.folderId ?? "";
}

async function loadTree(): Promise<void> {
  loading.value = true;
  try {
    const data = await getFileTree();
    sites.value = data.sites ?? [];
    devices.value = data.devices ?? [];
    const wanted = String(route.query.device ?? "").trim();
    if (wanted && devices.value.some((item) => item.id === wanted)) activeKey.value = wanted;
    if (!activeKey.value && devices.value.length) activeKey.value = devices.value[0].id;
    await loadFiles();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "目录加载失败。");
  } finally {
    loading.value = false;
  }
}

async function loadFiles(): Promise<void> {
  const folderId = folderOf(activeKey.value);
  if (!folderId || folderId === "0") { files.value = []; events.value = []; return; }
  try {
    const data = await listFiles(folderId);
    files.value = data.files ?? [];
  } catch (error) {
    files.value = [];
    ElMessage.error(error instanceof Error ? error.message : "文件加载失败。");
  }
}

async function loadEvents(): Promise<void> {
  const folderId = folderOf(activeKey.value);
  if (!folderId || folderId === "0") { events.value = []; return; }
  try {
    const data = await listEvents(folderId);
    events.value = data.events ?? [];
  } catch {
    events.value = [];
  }
}

function pickDevice(key: string): void {
  activeKey.value = key;
  void router.replace({ query: { ...route.query, tab: "files", device: key } });
}

function sizeText(value: number | string): string {
  const size = Number(value || 0);
  if (size >= 1024 * 1024) return (size / (1024 * 1024)).toFixed(1) + " MB";
  if (size >= 1024) return (size / 1024).toFixed(1) + " KB";
  return size + " B";
}

function triggerUpload(): void {
  if (!currentDevice.value) { ElMessage.warning("请先选择一台设备。"); return; }
  uploadInput.value?.click();
}

async function onFilePicked(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || !currentDevice.value) return;
  const folderId = folderOf(activeKey.value);
  uploading.value = true;
  try {
    const result = await uploadFile({ folderId, file, description: uploadForm.description });
    ElMessage.success("已上传 " + result.name + "（v" + result.version + "）");
    uploadForm.description = "";
    await loadFiles();
    await loadTree();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "上传失败。");
  } finally {
    uploading.value = false;
  }
}

function download(row: FileItem): void {
  window.location.href = downloadUrl(row.id);
}

async function rename(row: FileItem): Promise<void> {
  try {
    const result = await ElMessageBox.prompt("新的文件名", "重命名", { inputValue: row.name });
    await updateFile(row.id, { name: result.value });
    ElMessage.success("已重命名。");
    await loadFiles();
  } catch (error) {
    if (error === "cancel" || error === "close") return;
    ElMessage.error(error instanceof Error ? error.message : "重命名失败。");
  }
}

async function remove(row: FileItem): Promise<void> {
  try {
    await ElMessageBox.confirm("删除后该版本不再显示（记录保留），确定删除？", "删除文件", { type: "warning" });
  } catch {
    return;
  }
  try {
    await deleteFile(row.id);
    ElMessage.success("已删除。");
    await loadFiles();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除失败。");
  }
}

async function openEvents(): Promise<void> {
  await loadEvents();
  eventsVisible.value = true;
}

watch(() => route.query.device, (value) => {
  const key = String(value ?? "").trim();
  if (key && key !== activeKey.value) { activeKey.value = key; void loadFiles(); }
});

onMounted(loadTree);
</script>

<template>
  <section class="oa-file-library" v-loading="loading">
    <aside class="oa-file-tree">
      <el-input v-model="keyword" placeholder="搜索设备名称或编号" clearable class="oa-mb-2" />
      <el-scrollbar height="calc(100vh - 320px)">
        <div v-for="group in deviceGroups" :key="group.key" class="oa-file-group">
          <div class="oa-file-group-title">{{ group.label }}</div>
          <div
            v-for="device in group.items"
            :key="device.id"
            class="oa-file-device"
            :class="{ 'is-active': device.id === activeKey }"
            @click="pickDevice(device.id)"
          >
            <span class="oa-file-device-name">{{ device.name }}</span>
            <span class="oa-hint">{{ device.fileCount }} 个文件</span>
          </div>
        </div>
        <el-empty v-if="!deviceGroups.length" description="还没有机房设备" :image-size="60" />
      </el-scrollbar>
    </aside>

    <div class="oa-file-main">
      <header class="oa-flex-between oa-mb-2">
        <div>
          <strong>{{ currentDevice?.name || "请选择设备" }}</strong>
          <span class="oa-hint" v-if="currentDevice">
            {{ siteName.get(currentDevice.siteId) || "未分配机房" }} · {{ currentDevice.code }}
          </span>
        </div>
        <div class="oa-flex-row">
          <el-input v-model="uploadForm.description" placeholder="本次上传说明（可选）" style="width: 220px" />
          <el-button type="primary" :loading="uploading" :disabled="!currentDevice" @click="triggerUpload">
            上传配置文件
          </el-button>
          <el-button :disabled="!currentDevice" @click="openEvents">操作记录</el-button>
          <el-button :disabled="!currentDevice" @click="loadFiles">刷新</el-button>
        </div>
      </header>

      <input ref="uploadInput" type="file" style="display: none" @change="onFilePicked" />

      <el-table :data="files" size="small" border v-if="currentDevice">
        <el-table-column prop="name" label="文件名" min-width="220" show-overflow-tooltip />
        <el-table-column label="版本" width="80" align="center">
          <template #default="{ row }">
            <el-tag v-if="Number(row.isCurrent) === 1" type="success" size="small">v{{ row.version }} 当前</el-tag>
            <span v-else class="oa-hint">v{{ row.version }} 历史</span>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ sizeText(row.size) }}</template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="160" show-overflow-tooltip />
        <el-table-column prop="uploadedBy" label="上传人" width="100" />
        <el-table-column prop="createdAt" label="时间" width="160" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="download(row)">下载</el-button>
            <el-button v-if="Number(row.isCurrent) === 1" link type="primary" @click="rename(row)">重命名</el-button>
            <el-button v-if="Number(row.isCurrent) === 1" link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="从左侧选择一台设备查看配置文件" :image-size="80" />
    </div>

    <el-drawer v-model="eventsVisible" title="操作记录" size="520px">
      <el-timeline>
        <el-timeline-item v-for="item in events" :key="item.id" :timestamp="item.createdAt" placement="top">
          <strong>{{ item.action }}</strong> · {{ item.actor }}
          <div class="oa-hint">{{ JSON.stringify(item.detail) }}</div>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!events.length" description="暂无记录" :image-size="60" />
    </el-drawer>
  </section>
</template>

<style scoped>
.oa-file-library {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
}
.oa-file-tree {
  border-right: 1px solid var(--el-border-color-lighter);
  padding-right: 12px;
}
.oa-file-group-title {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 10px 0 4px;
}
.oa-file-device {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
}
.oa-file-device:hover { background: var(--el-fill-color-light); }
.oa-file-device.is-active { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.oa-file-device-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
