<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import InventoryView from "./InventoryView.vue";
import FlowControlView from "./FlowControlView.vue";
import ScrapRecordsView from "./ScrapRecordsView.vue";
import { hasPermission } from "../session";

/** 物资三合一：入口按三个模块的并集显示，页签再按各自模块过滤。 */
const TABS = [
  {
    key: "catalog",
    label: "物资台账",
    modules: ["inventory_catalog", "warehouse_management"],
    component: InventoryView,
  },
  { key: "flow", label: "流转记录", modules: ["inventory_operations"], component: FlowControlView },
  { key: "scrap", label: "报废记录", modules: ["scrap_management"], component: ScrapRecordsView },
];

const route = useRoute();
const router = useRouter();

/** 只保留有权限的页签：没有任何权限时返回空数组，页面给出提示。 */
const allowedTabs = computed(() =>
  TABS.filter((tab) => tab.modules.some((module) => hasPermission(module, "view"))),
);

function normalizeTab(value: unknown): string {
  const key = String(value ?? "").trim();
  return allowedTabs.value.some((tab) => tab.key === key) ? key : (allowedTabs.value[0]?.key ?? "");
}

const activeTab = ref(normalizeTab(route.query.tab));
const current = computed(() => allowedTabs.value.find((tab) => tab.key === activeTab.value) ?? null);

watch(allowedTabs, () => {
  const next = normalizeTab(route.query.tab || activeTab.value);
  if (next && next !== activeTab.value) activeTab.value = next;
});

watch(
  () => route.query.tab,
  (value) => {
    const next = normalizeTab(value);
    if (next && next !== activeTab.value) activeTab.value = next;
  },
);

watch(activeTab, (value) => {
  if (!value || String(route.query.tab ?? "") === value) return;
  void router.replace({ query: { ...route.query, tab: value } });
});
</script>

<template>
  <div class="oa-hub">
    <el-tabs v-if="allowedTabs.length" v-model="activeTab" class="oa-hub-tabs">
      <el-tab-pane v-for="tab in allowedTabs" :key="tab.key" :label="tab.label" :name="tab.key" />
    </el-tabs>
    <div class="oa-hub-body">
      <KeepAlive v-if="current">
        <component :is="current.component" :key="current.key" />
      </KeepAlive>
      <el-empty v-else description="当前账号没有物资相关权限。" />
    </div>
  </div>
</template>
