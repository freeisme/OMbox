<script setup lang="ts">
defineProps<{
  /** 已选/总数等结果提示，显示在右下角 */
  summary?: string;
  /** 是否显示重置按钮 */
  resettable?: boolean;
}>();

defineEmits<{ (event: "reset"): void }>();
</script>

<template>
  <div class="oa-filter-bar">
    <div class="oa-filter-bar__fields">
      <slot />
    </div>
    <div class="oa-filter-bar__footer">
      <slot name="actions" />
      <el-button v-if="resettable" @click="$emit('reset')">清除筛选</el-button>
      <span v-if="summary" class="oa-filter-bar__summary">{{ summary }}</span>
    </div>
  </div>
</template>

<style scoped>
.oa-filter-bar__fields {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oa-space-3);
  align-items: flex-end;
}

.oa-filter-bar__fields :deep(.el-form-item) {
  margin-bottom: 0;
}

.oa-filter-bar__footer {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oa-space-2);
  align-items: center;
  justify-content: flex-end;
  margin-top: var(--oa-space-3);
}

.oa-filter-bar__summary {
  color: var(--oa-text-secondary);
  font-size: var(--oa-font-sm);
}
</style>
