<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  deleteCompany,
  loadOrgTree,
  saveCompany,
  transferOrgSubtree,
  type Company,
  type OrgNode,
} from "../api/company";
import { canViewPage, session } from "../session";

interface TreeNode {
  id: string;
  label: string;
  kind: "group" | "company" | "org";
  companyId?: string;
  parentId?: string;
  children?: TreeNode[];
}

const loading = ref(false);
const companies = ref<Company[]>([]);
const organizations = ref<OrgNode[]>([]);
const viewCompanyId = ref("");

const companyDialog = reactive({ visible: false, id: "", code: "", name: "", sortOrder: 1000 });
const transferDialog = reactive({ visible: false, targetCompanyId: "", orgUnitIds: [] as string[] });
const transferAll = reactive({ employees: true, computers: true, warehouses: true, datacenter: true });

const isSuperAdmin = computed(() => session.isSuperAdmin);

function buildOrgSubtree(parentId: string): TreeNode[] {
  return organizations.value
    .filter((org) => org.parentId === parentId)
    .map((org) => ({
      id: org.id,
      label: org.name,
      kind: "org" as const,
      companyId: org.companyId,
      parentId: org.parentId,
      children: buildOrgSubtree(org.id),
    }));
}

function buildOrgChildren(companyId: string): TreeNode[] {
  const direct = organizations.value.filter(
    (org) =>
      org.companyId === companyId &&
      !organizations.value.some((p) => p.id === org.parentId && p.companyId === companyId),
  );
  return direct.map((org) => ({
    id: org.id,
    label: org.name,
    kind: "org" as const,
    companyId: org.companyId,
    parentId: org.parentId,
    children: buildOrgSubtree(org.id),
  }));
}

function buildTree(): TreeNode[] {
  const root: TreeNode[] = [
    { id: "__group__", label: session.groupName || "集团", kind: "group", children: [] },
  ];
  for (const company of companies.value) {
    root[0].children!.push({
      id: company.id,
      label: company.name,
      kind: "company",
      companyId: company.id,
      children: buildOrgChildren(company.id),
    });
  }
  return root;
}

const treeData = computed(() => buildTree());

async function reload(): Promise<void> {
  loading.value = true;
  try {
    const tree = await loadOrgTree(viewCompanyId.value);
    companies.value = tree.companies;
    organizations.value = tree.organizations;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载组织架构失败。");
  } finally {
    loading.value = false;
  }
}

function openCompanyCreate(): void {
  companyDialog.id = "";
  companyDialog.code = "";
  companyDialog.name = "";
  companyDialog.sortOrder = 1000;
  companyDialog.visible = true;
}

function openCompanyEdit(company: Company): void {
  companyDialog.id = company.id;
  companyDialog.code = company.code;
  companyDialog.name = company.name;
  companyDialog.sortOrder = company.sortOrder;
  companyDialog.visible = true;
}

async function submitCompany(): Promise<void> {
  if (!companyDialog.name.trim()) {
    ElMessage.warning("公司名称不能为空。");
    return;
  }
  try {
    await saveCompany(
      { code: companyDialog.code.trim(), name: companyDialog.name.trim(), sortOrder: companyDialog.sortOrder },
      companyDialog.id,
    );
    companyDialog.visible = false;
    ElMessage.success("公司已保存。");
    await reload();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存公司失败。");
  }
}

async function removeCompany(company: Company): Promise<void> {
  try {
    await ElMessageBox.confirm("确定停用公司「" + company.name + "」吗？", "停用公司", { type: "warning" });
    await deleteCompany(company.id);
    ElMessage.success("公司已停用。");
    await reload();
  } catch (error) {
    if (error === "cancel" || error === "close") return;
    ElMessage.error(error instanceof Error ? error.message : "停用公司失败。");
  }
}

function openTransfer(): void {
  transferDialog.targetCompanyId = "";
  transferDialog.orgUnitIds = [];
  transferDialog.visible = true;
}

async function submitTransfer(): Promise<void> {
  if (!transferDialog.targetCompanyId) {
    ElMessage.warning("请选择目标公司。");
    return;
  }
  if (transferDialog.orgUnitIds.length === 0) {
    ElMessage.warning("请选择要转移的组织。");
    return;
  }
  try {
    await transferOrgSubtree({
      targetCompanyId: transferDialog.targetCompanyId,
      orgUnitIds: transferDialog.orgUnitIds,
      moveEmployees: transferAll.employees,
      moveComputers: transferAll.computers,
      moveWarehouses: transferAll.warehouses,
      moveDatacenter: transferAll.datacenter,
    });
    transferDialog.visible = false;
    ElMessage.success("组织已转移。");
    await reload();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "转移组织失败。");
  }
}

onMounted(reload);
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="oa-flex-between">
        <span class="oa-card-title">组织架构（集团 → 公司 → 部门）</span>
        <div>
          <el-button v-if="isSuperAdmin" type="primary" @click="openCompanyCreate">新增公司</el-button>
          <el-button v-if="isSuperAdmin" @click="openTransfer">转移组织</el-button>
        </div>
      </div>
    </template>

    <el-tree
      :data="treeData"
      node-key="id"
      default-expand-all
      :props="{ label: 'label', children: 'children' }"
      :expand-on-click-node="false"
    >
      <template #default="{ data }">
        <div class="oa-flex-between oa-tree-row">
          <span>
            <el-tag v-if="data.kind === 'group'" size="small" effect="plain" type="info">集团</el-tag>
            <el-tag v-else-if="data.kind === 'company'" size="small" type="primary">公司</el-tag>
            <el-tag v-else size="small" effect="plain">部门</el-tag>
            <span class="oa-ml-2">{{ data.label }}</span>
          </span>
          <span v-if="data.kind === 'company' && isSuperAdmin">
            <el-button size="small" text @click="openCompanyEdit(data)">编辑</el-button>
            <el-button size="small" text type="danger" @click="removeCompany(data)">停用</el-button>
          </span>
        </div>
      </template>
    </el-tree>

    <el-dialog v-model="companyDialog.visible" :title="companyDialog.id ? '编辑公司' : '新增公司'" width="440px">
      <el-form label-position="top">
        <el-form-item label="公司编码" required>
          <el-input v-model="companyDialog.code" placeholder="例如 CMP-002" />
        </el-form-item>
        <el-form-item label="公司名称" required>
          <el-input v-model="companyDialog.name" placeholder="例如 示例公司" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="companyDialog.sortOrder" :min="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="companyDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitCompany">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="transferDialog.visible" title="转移组织架构" width="520px">
      <el-form label-position="top">
        <el-form-item label="目标公司" required>
          <el-select v-model="transferDialog.targetCompanyId" placeholder="选择要转入的公司">
            <el-option v-for="c in companies" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="要转移的组织（可多选，含其子组织）">
          <el-tree-select
            v-model="transferDialog.orgUnitIds"
            :data="treeData"
            node-key="id"
            multiple
            show-checkbox
            check-strictly
            :props="{ label: 'label', children: 'children' }"
            placeholder="选择组织"
          />
        </el-form-item>
        <el-form-item label="连同转移">
          <el-checkbox v-model="transferAll.employees">其下员工</el-checkbox>
          <el-checkbox v-model="transferAll.computers">办公终端</el-checkbox>
          <el-checkbox v-model="transferAll.warehouses">IT 物资仓库</el-checkbox>
          <el-checkbox v-model="transferAll.datacenter">机房设备</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="transferDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitTransfer">转移</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>
