<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  deleteCompany,
  deleteOrganization,
  loadOrgTree,
  saveCompany,
  saveOrganization,
  transferOrgSubtree,
  type Company,
  type OrgNode,
} from "../api/company";
import { companyScope } from "../companyScope";
import { hasPermission, session } from "../session";

interface TreeNode {
  id: string;
  label: string;
  kind: "group" | "company" | "org";
  companyId?: string;
  parentId?: string;
  orgId?: string;
  isActive?: boolean | number;
  children?: TreeNode[];
}

const loading = ref(false);
const companies = ref<Company[]>([]);
const organizations = ref<OrgNode[]>([]);
const selectedKey = ref("__group__");
const searchText = ref("");
const treeRef = ref<{ filter: (value: string) => void } | null>(null);
/** 公司视图由顶栏右上角的全局切换器控制。 */
const scopeCompanyId = computed(() => companyScope.companyId);

const companyDialog = reactive({ visible: false, id: "", code: "", name: "", sortOrder: 1000 });
const orgDialog = reactive({
  visible: false,
  id: "",
  code: "",
  name: "",
  parentId: "",
  companyId: "",
  sortOrder: 1000,
  isActive: true,
});
const transferDialog = reactive({ visible: false, targetCompanyId: "", orgUnitIds: [] as string[] });
const transferAll = reactive({ employees: true, computers: true, warehouses: true, datacenter: true });

const isSuperAdmin = computed(() => session.isSuperAdmin);
/** 有集团级数据范围（超管，或组织模块 dataScope=all）才能看「整个集团」并切换公司。 */
const canManageGroup = computed(() => session.isSuperAdmin || companyScope.canViewGroup);
const canEditOrg = computed(
  () =>
    session.isSuperAdmin ||
    hasPermission("organizations", "create") ||
    hasPermission("organizations", "update"),
);
const canDeleteOrg = computed(
  () => session.isSuperAdmin || hasPermission("organizations", "delete"),
);
const myCompanyId = computed(() => String(session.user?.companyId ?? ""));

/** 集团管理员可用任意公司；无集团权限时只能在其任职公司之间切换。 */
const effectiveCompanyId = computed(() => {
  if (canManageGroup.value) return scopeCompanyId.value;
  if (scopeCompanyId.value && companies.value.some((item) => item.id === scopeCompanyId.value)) {
    return scopeCompanyId.value;
  }
  // 多公司任职：默认展示其全部公司；单公司则只有一家
  return "";
});
const visibleCompanies = computed(() =>
  effectiveCompanyId.value
    ? companies.value.filter((item) => item.id === effectiveCompanyId.value)
    : companies.value,
);
const companyOptions = computed(() => companies.value);

function buildOrgSubtree(parentId: string, companyId: string): TreeNode[] {
  return organizations.value
    .filter((org) => org.parentId === parentId && org.companyId === companyId)
    .map((org) => ({
      id: "org:" + org.id,
      label: org.name,
      kind: "org" as const,
      companyId: org.companyId,
      parentId: org.parentId,
      orgId: org.id,
      isActive: org.isActive,
      children: buildOrgSubtree(org.id, companyId),
    }));
}

function buildOrgChildren(companyId: string): TreeNode[] {
  const direct = organizations.value.filter(
    (org) =>
      org.companyId === companyId &&
      !organizations.value.some((p) => p.id === org.parentId && p.companyId === companyId),
  );
  return direct.map((org) => ({
    id: "org:" + org.id,
    label: org.name,
    kind: "org" as const,
    companyId: org.companyId,
    parentId: org.parentId,
    orgId: org.id,
    isActive: org.isActive,
    children: buildOrgSubtree(org.id, companyId),
  }));
}

function buildTree(): TreeNode[] {
  const root: TreeNode[] = [];
  const companyNode = (company: Company): TreeNode => ({
    id: "company:" + company.id,
    label: company.name,
    kind: "company",
    companyId: company.id,
    children: buildOrgChildren(company.id),
  });
  if (effectiveCompanyId.value) {
    const company = visibleCompanies.value[0];
    if (company) root.push(companyNode(company));
  } else if (canManageGroup.value) {
    root.push({
      id: "__group__",
      label: session.groupName || "集团",
      kind: "group",
      children: visibleCompanies.value.map(companyNode),
    });
  } else {
    // 多公司任职（无集团权限）：并列展示其可管理的公司
    root.push(...visibleCompanies.value.map(companyNode));
  }
  return root;
}

const treeData = computed(() => buildTree());

const filterNode = (value: string, data: TreeNode): boolean => {
  if (!value) return true;
  return String(data.label ?? "")
    .toLowerCase()
    .includes(value.trim().toLowerCase());
};

const selectedOrg = computed<OrgNode | null>(() => {
  if (!selectedKey.value.startsWith("org:")) return null;
  const id = selectedKey.value.slice(4);
  return organizations.value.find((item) => item.id === id) ?? null;
});

const selectedCompany = computed<Company | null>(() => {
  if (selectedKey.value.startsWith("company:")) {
    const id = selectedKey.value.slice(8);
    return companies.value.find((item) => item.id === id) ?? null;
  }
  if (selectedOrg.value?.companyId) {
    return companies.value.find((item) => item.id === selectedOrg.value!.companyId) ?? null;
  }
  return null;
});

const orgPath = computed<string[]>(() => {
  const path: string[] = [];
  let current: OrgNode | null = selectedOrg.value;
  let guard = 0;
  while (current && guard < 20) {
    path.unshift(current.name);
    const parentId: string = current.parentId;
    current = parentId ? organizations.value.find((item) => item.id === parentId) ?? null : null;
    guard += 1;
  }
  if (selectedCompany.value) path.unshift(selectedCompany.value.name);
  return path;
});

const childCount = computed(() => {
  const org = selectedOrg.value;
  if (!org) return 0;
  return organizations.value.filter((item) => item.parentId === org.id).length;
});

async function reload(): Promise<void> {
  loading.value = true;
  try {
    const tree = await loadOrgTree(effectiveCompanyId.value);
    companies.value = tree.companies;
    organizations.value = tree.organizations;
    if (!treeData.value.some((node) => nodeContains(node, selectedKey.value))) {
      selectedKey.value = treeData.value[0]?.id ?? "__group__";
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "加载组织架构失败。");
  } finally {
    loading.value = false;
  }
}

function nodeContains(node: TreeNode, key: string): boolean {
  if (node.id === key) return true;
  return (node.children ?? []).some((child) => nodeContains(child, key));
}

function selectNode(data: TreeNode): void {
  selectedKey.value = data.id;
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
  companyDialog.sortOrder = company.sortOrder ?? 1000;
  companyDialog.visible = true;
}

async function submitCompany(): Promise<void> {
  if (!companyDialog.name.trim()) {
    ElMessage.warning("公司名称必填。");
    return;
  }
  try {
    await saveCompany(
      {
        code: companyDialog.code.trim() || companyDialog.name.trim().toUpperCase(),
        name: companyDialog.name.trim(),
        sortOrder: companyDialog.sortOrder,
      },
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
  const ok = await ElMessageBox.confirm(
    "确定删除公司「" + company.name + "」吗？公司下必须没有组织和数据。",
    "删除公司",
    { type: "warning" },
  ).catch(() => false);
  if (!ok) return;
  try {
    await deleteCompany(company.id);
    ElMessage.success("公司已删除。");
    await reload();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除公司失败。");
  }
}

function openOrgCreate(parentId = "", companyId = ""): void {
  orgDialog.id = "";
  orgDialog.code = "";
  orgDialog.name = "";
  orgDialog.parentId = parentId;
  orgDialog.companyId = companyId || selectedCompany.value?.id || "";
  orgDialog.sortOrder = 1000;
  orgDialog.isActive = true;
  orgDialog.visible = true;
}

function openOrgEdit(org: OrgNode): void {
  orgDialog.id = org.id;
  orgDialog.code = org.code;
  orgDialog.name = org.name;
  orgDialog.parentId = org.parentId || "";
  orgDialog.companyId = org.companyId || "";
  orgDialog.sortOrder = org.sortOrder ?? 1000;
  orgDialog.isActive = org.isActive === true || Number(org.isActive) === 1;
  orgDialog.visible = true;
}

async function submitOrg(): Promise<void> {
  if (!orgDialog.code.trim() || !orgDialog.name.trim()) {
    ElMessage.warning("组织编码与名称必填。");
    return;
  }
  try {
    await saveOrganization(
      {
        code: orgDialog.code.trim(),
        name: orgDialog.name.trim(),
        parentId: orgDialog.parentId,
        companyId: orgDialog.companyId,
        sortOrder: orgDialog.sortOrder,
        isActive: orgDialog.isActive,
      },
      orgDialog.id,
    );
    orgDialog.visible = false;
    ElMessage.success("组织已保存。");
    await reload();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存组织失败。");
  }
}

async function removeOrg(org: OrgNode): Promise<void> {
  const ok = await ElMessageBox.confirm(
    "确定删除组织「" + org.name + "」吗？有下级、人员或资产时会被拒绝。",
    "删除组织",
    { type: "warning" },
  ).catch(() => false);
  if (!ok) return;
  try {
    await deleteOrganization(org.id);
    ElMessage.success("组织已删除。");
    await reload();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "删除组织失败。");
  }
}

function openTransfer(): void {
  transferDialog.targetCompanyId = "";
  transferDialog.orgUnitIds = selectedOrg.value ? [selectedOrg.value.id] : [];
  transferAll.employees = true;
  transferAll.computers = true;
  transferAll.warehouses = true;
  transferAll.datacenter = true;
  transferDialog.visible = true;
}

async function submitTransfer(): Promise<void> {
  if (!transferDialog.targetCompanyId) {
    ElMessage.warning("请选择目标公司。");
    return;
  }
  if (!transferDialog.orgUnitIds.length) {
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

function orgOptions(companyId: string): OrgNode[] {
  return organizations.value.filter((item) => !companyId || item.companyId === companyId);
}

watch(searchText, (value) => {
  treeRef.value?.filter(value);
});

watch(
  () => companyScope.companyId,
  () => {
    selectedKey.value = "__group__";
    void reload();
  },
);

onMounted(reload);
</script>

<template>
  <el-card v-loading="loading">
    <template #header>
      <div class="oa-flex-between">
        <span class="oa-card-title">组织架构</span>
        <div class="oa-flex-row">
          <el-input
            v-model="searchText"
            clearable
            placeholder="搜索部门"
            style="width: 180px"
          />
          <el-button v-if="isSuperAdmin" type="primary" @click="openCompanyCreate">新增公司</el-button>
          <el-button v-if="isSuperAdmin" @click="openTransfer">转移组织</el-button>
        </div>
      </div>
    </template>

    <el-row :gutter="12">
      <el-col :xs="24" :md="9">
        <el-card shadow="never" class="oa-org-tree-card">
          <el-tree
            ref="treeRef"
            :data="treeData"
            node-key="id"
            default-expand-all
            highlight-current
            :filter-node-method="filterNode"
            :props="{ label: 'label', children: 'children' }"
            :expand-on-click-node="false"
            @node-click="selectNode"
          >
            <template #default="{ data }">
              <div class="oa-flex-between oa-org-tree-row">
                <span>
                  <el-tag v-if="data.kind === 'group'" size="small" effect="plain" type="info">集团</el-tag>
                  <el-tag v-else-if="data.kind === 'company'" size="small" type="primary">公司</el-tag>
                  <span class="oa-ml-2">{{ data.label }}</span>
                  <el-tag
                    v-if="data.kind === 'org' && !(data.isActive === true || Number(data.isActive) === 1)"
                    size="small"
                    type="info"
                    effect="plain"
                    class="oa-ml-2"
                  >
                    停用
                  </el-tag>
                </span>
                <span v-if="data.kind === 'company' && canEditOrg" class="oa-org-tree-actions">
                  <el-button link size="small" @click.stop="openOrgCreate('', data.companyId)">+ 部门</el-button>
                </span>
                <span v-else-if="data.kind === 'org' && canEditOrg" class="oa-org-tree-actions">
                  <el-button link size="small" @click.stop="openOrgCreate(data.orgId, data.companyId)">+</el-button>
                </span>
              </div>
            </template>
          </el-tree>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="15">
        <el-card shadow="never">
          <template #header>
            <div class="oa-flex-between">
              <span>
                <template v-if="selectedOrg">{{ orgPath.join(" / ") }}</template>
                <template v-else-if="selectedCompany">{{ selectedCompany.name }}</template>
                <template v-else>{{ session.groupName || "集团" }}</template>
              </span>
              <div v-if="selectedOrg">
                <el-button v-if="canEditOrg" size="small" @click="openOrgCreate(selectedOrg.id, selectedOrg.companyId)">新增下级</el-button>
                <el-button v-if="canEditOrg" size="small" type="primary" @click="openOrgEdit(selectedOrg)">编辑</el-button>
                <el-button v-if="canDeleteOrg" size="small" type="danger" @click="removeOrg(selectedOrg)">删除</el-button>
              </div>
              <div v-else-if="selectedCompany">
                <el-button v-if="canEditOrg" size="small" type="primary" @click="openOrgCreate('', selectedCompany.id)">新增部门</el-button>
                <el-button v-if="isSuperAdmin" size="small" @click="openCompanyEdit(selectedCompany)">编辑公司</el-button>
                <el-button v-if="isSuperAdmin" size="small" type="danger" @click="removeCompany(selectedCompany)">删除公司</el-button>
              </div>
            </div>
          </template>

          <el-descriptions v-if="selectedOrg" :column="2" border>
            <el-descriptions-item label="组织编码">{{ selectedOrg.code }}</el-descriptions-item>
            <el-descriptions-item label="组织名称">{{ selectedOrg.name }}</el-descriptions-item>
            <el-descriptions-item label="所属公司">{{ selectedCompany?.name || "—" }}</el-descriptions-item>
            <el-descriptions-item label="下级组织">{{ childCount }}</el-descriptions-item>
            <el-descriptions-item label="排序">{{ selectedOrg.sortOrder }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="selectedOrg.isActive === true || Number(selectedOrg.isActive) === 1 ? 'success' : 'info'" size="small">
                {{ selectedOrg.isActive === true || Number(selectedOrg.isActive) === 1 ? "启用" : "停用" }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
          <el-empty v-else description="选择左侧的部门或公司查看详情" />
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="companyDialog.visible" :title="companyDialog.id ? '编辑公司' : '新增公司'" width="440px">
      <el-form label-position="top">
        <el-form-item label="公司编码">
          <el-input v-model="companyDialog.code" placeholder="留空自动用大写名称" />
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

    <el-dialog v-model="orgDialog.visible" :title="orgDialog.id ? '编辑组织' : '新增组织'" width="480px">
      <el-form label-position="top">
        <el-form-item label="上级组织">
          <el-select v-model="orgDialog.parentId" clearable filterable class="oa-full-width" placeholder="留空表示公司根组织">
            <el-option
              v-for="org in orgOptions(orgDialog.companyId).filter((o) => o.id !== orgDialog.id)"
              :key="org.id"
              :label="org.name"
              :value="org.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="所属公司" required>
          <el-select v-model="orgDialog.companyId" class="oa-full-width" :disabled="Boolean(orgDialog.id)">
            <el-option v-for="c in companies" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <div v-if="orgDialog.id" class="oa-hint">跨公司调整请使用「转移组织」。</div>
        </el-form-item>
        <el-form-item label="组织编码" required>
          <el-input v-model="orgDialog.code" placeholder="例如 DEPT-A" />
        </el-form-item>
        <el-form-item label="组织名称" required>
          <el-input v-model="orgDialog.name" placeholder="例如 技术部" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="orgDialog.sortOrder" :min="0" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="orgDialog.isActive" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="orgDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitOrg">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="transferDialog.visible" title="转移组织" width="520px">
      <el-form label-position="top">
        <el-form-item label="目标公司" required>
          <el-select v-model="transferDialog.targetCompanyId" class="oa-full-width">
            <el-option v-for="c in companies" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="要转移的组织" required>
          <el-select v-model="transferDialog.orgUnitIds" multiple filterable class="oa-full-width">
            <el-option v-for="org in organizations" :key="org.id" :label="org.name" :value="org.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-checkbox v-model="transferAll.employees">同时转移人员</el-checkbox>
      <el-checkbox v-model="transferAll.computers">同时转移办公终端</el-checkbox>
      <el-checkbox v-model="transferAll.warehouses">同时转移仓库</el-checkbox>
      <el-checkbox v-model="transferAll.datacenter">同时转移机房设备</el-checkbox>
      <template #footer>
        <el-button @click="transferDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="submitTransfer">确认转移</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.oa-org-tree-card {
  min-height: 520px;
}
.oa-org-tree-row {
  width: 100%;
  padding-right: 6px;
}
.oa-org-tree-actions {
  opacity: 0.6;
}
.oa-org-tree-actions:hover {
  opacity: 1;
}
</style>
