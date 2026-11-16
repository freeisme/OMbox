<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import DatacenterDeviceView from "./DatacenterDeviceView.vue";
import RackLayoutView from "./RackLayoutView.vue";
import DevicePanelView from "./DevicePanelView.vue";
import TopologyView from "./TopologyView.vue";

/** 机房四合一：四个原页面各自独立取数，这里只负责页签与地址同步。 */
const TABS = [
  { key: "devices", label: "网络设备/服务器", component: DatacenterDeviceView },
  { key: "racks", label: "机柜视图", component: RackLayoutView },
  { key: "panel", label: "设备面板", component: DevicePanelView },
  { key: "topology", label: "网络拓扑", component: TopologyView },
];

const route = useRoute();
const router = useRouter();

function normalizeTab(value: unknown): string {
  const key = String(value ?? "").trim();
  return TABS.some((tab) => tab.key === key) ? key : "devices";
}

const activeTab = ref(normalizeTab(route.query.tab));
const current = computed(() => TABS.find((tab) => tab.key === activeTab.value) ?? TABS[0]);

watch(
  () => route.query.tab,
  (value) => {
    const next = normalizeTab(value);
    if (next !== activeTab.value) activeTab.value = next;
  },
);

watch(activeTab, (value) => {
  if (String(route.query.tab ?? "") === value) return;
  void router.replace({ query: { ...route.query, tab: value } });
});
</script>

<template>
  <div class="oa-hub">
    <el-tabs v-model="activeTab" class="oa-hub-tabs">
      <el-tab-pane v-for="tab in TABS" :key="tab.key" :label="tab.label" :name="tab.key" />
    </el-tabs>
    <div class="oa-hub-body">
      <KeepAlive>
        <component :is="current.component" :key="current.key" />
      </KeepAlive>
    </div>
  </div>
</template>
