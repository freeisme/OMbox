<script setup lang="ts">
withDefaults(
  defineProps<{
    hint?: string;
  }>(),
  { hint: "" },
);
</script>

<template>
  <div class="oa-toolbar">
    <div class="oa-toolbar__actions">
      <slot />
    </div>
    <span v-if="hint" class="oa-toolbar__hint">{{ hint }}</span>
    <slot name="hint" />
  </div>
</template>

<style scoped>
.oa-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oa-space-2);
  align-items: center;
  justify-content: space-between;
}

.oa-toolbar__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oa-space-2);
  align-items: center;
}

.oa-toolbar__hint {
  color: var(--oa-text-secondary);
  font-size: var(--oa-font-sm);
}
</style>
