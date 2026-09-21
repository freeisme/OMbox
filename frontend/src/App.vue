<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import AppShell from "./layouts/AppShell.vue";

const route = useRoute();
const isPublicRoute = computed(() => Boolean(route.meta.public));
</script>

<template>
  <el-config-provider :locale="zhCn">
    <router-view v-if="isPublicRoute" />
    <AppShell v-else>
      <router-view />
    </AppShell>
  </el-config-provider>
</template>
