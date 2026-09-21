<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  invalidateDirectoryCache,
  loadDirectoryData,
  saveInventoryType,
  saveOrganization,
  type DirectoryEmployeeRow,
  type NonAssetTypeRow,
  type OrgNode,
} from "../api/directory";
import { hasPermission } from "../session";
import DataPanel from "../components/ui/DataPanel.vue";
import FilterBar from "../components/ui/FilterBar.vue";
import PageHeader from "../components/ui/PageHeader.vue";

interface OrgTreeNode extends OrgNode {
  children: OrgTreeNode[];
  label: string;
}

const loading = ref(true);
const saving = ref(false);
const orgs = ref<OrgNode[]>([]);
const types = ref<NonAssetTypeRow[]>([]);
const employees = ref<DirectoryEmployeeRow[]>([]);
const keyword = ref("");
const treeRef = ref();

const orgDialogVisible = ref(false);
const orgEditingId = ref("");
const orgForm = reactive({ code: "", name: "", parentId: "", sortOrder: 1000 });

const typeDialogVisible = ref(false);
const typeEditingId = ref("");
const typeForm = reactive({ code: "", name: "", unit: "件" });

const orgTree = computed<OrgTreeNode[]>(() => {
  const nodes = new Map<string, OrgTreeNode>();
  orgs.value.forEach((item) =>
    nodes.set(item.id, { ...item, label: `${item.name}（${item.code}）`, children: [] }),
  );
  const roots: OrgTreeNode[] = [];
  orgs.value.forEach((item) => {
    const node = nodes.get(item.id);
    if (!node) return;
    const parent = item.parentId ? nodes.get(item.parentId) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  return roots;
});

const typeRows = computed(() => {
  const key = keyword.value.trim().toLowerCase();
  return types.value
    .filter((type) => !key || `${type.code} ${type.name}`.toLowerCase().includes(key))
    .map((type) => ({
      ...type,
      usageCount: employees.value.filter((employee) =>
        [...(employee.monitors ?? []), ...(employee.nonAssetItems ?? [])].some(
          (item) => item.typeId === type.id && Number(item.quantity ?? 0) > 0,
        ),
      ).length,
    }));
});

const visibleOrgCount = computed(() => {
  const key = keyword.value.trim().toLowerCase();
  if (!key) return orgs.value.length;
  return orgs.value.filter((org) => `${org.code} ${org.name}`.toLowerCase().includes(key)).length;
});

function filterOrgNode(value: string, data: OrgTreeNode): boolean {
  const key = String(value ?? "").trim().toLowerCase();
  if (!key) return true;
  return `${data.code} ${data.name}`.toLowerCase().includes(key);
}

async function load(force = false): Promise<void> {
  loading.value = true;
  try {
    const data = await loadDirectoryData(force);
    orgs.value = data.orgs;
    types.value = data.nonAssetTypes;
    employees.value = data.employees;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "字典数据加载失败。");
  } finally {
    loading.value = false;
  }
}

function openOrg(id = "", parentId = ""): void {
  const org = id ? orgs.value.find((item) => item.id === id) : undefined;
  orgEditingId.value = org ? org.id : "";
  orgForm.code = org?.code ?? "";
  orgForm.name = org?.name ?? "";
  orgForm.parentId = org?.parentId ?? parentId;
  orgForm.sortOrder = org?.sortOrder ?? 1000;
  orgDialogVisible.value = true;
}

async function submitOrg(): Promise<void> {
  if (!orgForm.code.trim() || !orgForm.name.trim()) {
    ElMessage.warning("组织编码与名称必填。");
    return;
  }
  saving.value = true;
  try {
    await saveOrganization(
      {
        code: orgForm.code.trim(),
        name: orgForm.name.trim(),
        parentId: orgForm.parentId || "",
        sortOrder: Number(orgForm.sortOrder) || 1000,
      },
      orgEditingId.value,
    );
    ElMessage.success(orgEditingId.value ? "组织已更新。" : "组织已创建。");
    orgDialogVisible.value = false;
    invalidateDirectoryCache();
    await load(true);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败。");
  } finally {
    saving.value = false;
  }
}

function openType(id = ""): void {
  const type = id ? types.value.find((item) => item.id === id) : undefined;
  typeEditingId.value = type ? type.id : "";
  typeForm.code = type?.code ?? "";
  typeForm.name = type?.name ?? "";
  typeForm.unit = type?.unit || "件";
  typeDialogVisible.value = true;
}

async function submitType(): Promise<void> {
  if (!typeForm.code.trim() || !typeForm.name.trim()) {
    ElMessage.warning("类型编码与名称必填。");
    return;
  }
  saving.value = true;
  try {
    await saveInventoryType(
      { code: typeForm.code.trim(), name: typeForm.name.trim(), unit: typeForm.unit.trim() || "件" },
      typeEditingId.value,
    );
    ElMessage.success(typeEditingId.value ? "设备类型已更新。" : "设备类型已创建。");
    typeDialogVisible.value = false;
    invalidateDirectoryCache();
    await load(true);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存失败。");
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await load(false);
});
</script>

<template>
  <PageHeader
    title="基础字典"
    description="组织树结构与人员页面共享同一套层级和排序规则；组织与类型暂不支持删除（与旧版一致）"
  >
    <template #actions>
      <el-button v-if="hasPermission('inventory_catalog', 'create')" @click="openType()">
        ＋ 新增设备类型
      </el-button>
      <el-button v-if="hasPermission('organizations', 'create')" type="primary" @click="openOrg()">
        ＋ 新增根组织
      </el-button>
    </template>
    <template #filters>
      <FilterBar
        :summary="`组织 ${visibleOrgCount} / ${orgs.length} · 设备类型 ${typeRows.length} / ${types.length}`"
        :resettable="Boolean(keyword)"
        @reset="keyword = ''; treeRef?.filter('')"
      >
        <el-input
          v-model="keyword"
          placeholder="搜索组织编码、组织名称或设备类型"
          clearable
          style="max-width: 360px"
          @input="treeRef?.filter(keyword)"
        />
      </FilterBar>
    </template>
  </PageHeader>

  <el-row :gutter="12" class="oa-panel-gap">
    <el-col :xs="24" :md="11">
      <DataPanel title="组织架构树" :loading="loading">
        <el-tree
          ref="treeRef"
          :data="orgTree"
          node-key="id"
          default-expand-all
          :expand-on-click-node="false"
          :filter-node-method="filterOrgNode"
          empty-text="暂无组织"
        >
          <template #default="{ data }">
            <div class="oa-flex-row oa-full-width">
              <span class="oa-flex-1">
                {{ data.name }}
                <span class="oa-cell-sub">
                  {{ data.code }}
                </span>
              </span>
              <el-button
                v-if="hasPermission('organizations', 'create')"
                link
                size="small"
                @click.stop="openOrg('', data.id)"
              >
                新增下级
              </el-button>
              <el-button
                v-if="hasPermission('organizations', 'update')"
                link
                size="small"
                @click.stop="openOrg(data.id)"
              >
                编辑
              </el-button>
            </div>
          </template>
        </el-tree>
      </DataPanel>
    </el-col>
    <el-col :xs="24" :md="13">
      <DataPanel title="非资产设备类型" :loading="loading">
        <el-table :data="typeRows" size="small" border empty-text="暂无符合条件的设备类型">
          <el-table-column prop="code" label="编码" min-width="120" />
          <el-table-column prop="name" label="名称" min-width="140" />
          <el-table-column prop="unit" label="计量单位" width="90" />
          <el-table-column prop="usageCount" label="引用人数" width="90" />
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-button
                v-if="hasPermission('inventory_catalog', 'update')"
                link
                type="primary"
                @click="openType(row.id)"
              >
                编辑
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </DataPanel>
    </el-col>
  </el-row>

  <FormDialog
    v-model="orgDialogVisible"
    :title="orgEditingId ? '编辑组织' : '新增组织'"
    size="sm"
    :loading="saving"
    @confirm="submitOrg"
  >
    <el-form label-position="top">
      <el-form-item label="组织编码" required>
        <el-input v-model="orgForm.code" placeholder="例如 SZNS" />
      </el-form-item>
      <el-form-item label="组织名称" required>
        <el-input v-model="orgForm.name" placeholder="例如 深圳南山" />
      </el-form-item>
      <el-form-item label="上级组织">
        <el-tree-select
          v-model="orgForm.parentId"
          :data="orgTree"
          check-strictly
          clearable
          placeholder="留空表示根组织"
          class="oa-full-width"
        />
      </el-form-item>
      <el-form-item label="排序值">
        <el-input-number v-model="orgForm.sortOrder" :min="0" :step="10" />
      </el-form-item>
    </el-form>
  </FormDialog>

  <FormDialog
    v-model="typeDialogVisible"
    :title="typeEditingId ? '编辑设备类型' : '新增设备类型'"
    size="sm"
    :loading="saving"
    @confirm="submitType"
  >
    <el-form label-position="top">
      <el-form-item label="类型编码" required>
        <el-input v-model="typeForm.code" placeholder="例如 monitor" />
      </el-form-item>
      <el-form-item label="类型名称" required>
        <el-input v-model="typeForm.name" placeholder="例如 显示屏" />
      </el-form-item>
      <el-form-item label="计量单位">
        <el-input v-model="typeForm.unit" placeholder="例如 台" />
      </el-form-item>
    </el-form>
  </FormDialog>
</template>
