<script setup lang="ts">
defineProps<{
  title?: string;
  hint?: string;
  loading?: boolean;
}>();
</script>

<template>
  <el-card class="oa-panel" shadow="never" v-loading="Boolean(loading)">
    <template v-if="title || hint || $slots.actions" #header>
      <div class="oa-panel__header">
        <span class="oa-panel__title">
          <strong v-if="title">{{ title }}</strong>
          <span v-if="hint" class="oa-panel__hint">{{ hint }}</span>
        </span>
        <span class="oa-panel__actions"><slot name="actions" /></span>
      </div>
    </template>
    <slot />
    <template v-if="$slots.footer" #footer>
      <slot name="footer" />
    </template>
  </el-card>
</template>

<style scoped>
.oa-panel {
  border: var(--oa-border);
}

.oa-panel__header {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oa-space-2);
  align-items: baseline;
  justify-content: space-between;
}

.oa-panel__title {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oa-space-2);
  align-items: baseline;
}

.oa-panel__title strong {
  font-size: var(--oa-font-md);
}

.oa-panel__hint {
  color: var(--oa-text-secondary);
  font-size: var(--oa-font-xs);
}
</style>
