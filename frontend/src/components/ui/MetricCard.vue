<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string;
    value: string | number;
    hint?: string;
    /** 数值强调色：默认主色，可传 success / warning / danger */
    tone?: "" | "success" | "warning" | "danger";
    clickable?: boolean;
  }>(),
  { hint: "", tone: "", clickable: false },
);

defineEmits<{ (event: "click"): void }>();
</script>

<template>
  <el-card class="oa-metric" shadow="never" :class="{ 'is-clickable': clickable }" @click="clickable && $emit('click')">
    <div class="oa-metric__label">{{ label }}</div>
    <div class="oa-metric__value" :class="tone ? `oa-metric__value--${tone}` : ''">{{ value }}</div>
    <div v-if="hint" class="oa-metric__hint">{{ hint }}</div>
  </el-card>
</template>

<style scoped>
.oa-metric {
  border: var(--oa-border);
  height: 100%;
}

.oa-metric.is-clickable {
  cursor: pointer;
}

.oa-metric__label {
  color: var(--oa-text-secondary);
  font-size: var(--oa-font-sm);
}

.oa-metric__value {
  margin: var(--oa-space-1) 0;
  font-size: var(--oa-font-2xl);
  font-weight: 600;
  line-height: var(--oa-line-tight);
}

.oa-metric__value--success { color: var(--el-color-success); }
.oa-metric__value--warning { color: var(--el-color-warning); }
.oa-metric__value--danger { color: var(--el-color-danger); }

.oa-metric__hint {
  color: var(--oa-text-secondary);
  font-size: var(--oa-font-xs);
}
</style>
