<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
}>();
</script>

<template>
  <el-card class="oa-page-header" shadow="never">
    <div class="oa-page-header__row">
      <div class="oa-page-header__text">
        <h2>{{ title }}</h2>
        <p v-if="description">{{ description }}</p>
      </div>
      <div class="oa-page-header__actions">
        <slot name="actions" />
      </div>
    </div>
    <div v-if="$slots.filters" class="oa-page-header__filters">
      <slot name="filters" />
    </div>
  </el-card>
</template>

<style scoped>
.oa-page-header__row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oa-space-3);
  align-items: center;
  justify-content: space-between;
}

.oa-page-header__text {
  min-width: 0;
}

.oa-page-header__text h2 {
  margin: 0;
  font-size: var(--oa-font-xl);
  line-height: var(--oa-line-tight);
}

.oa-page-header__text p {
  margin: var(--oa-space-1) 0 0;
  color: var(--oa-text-secondary);
  font-size: var(--oa-font-sm);
}

.oa-page-header__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--oa-space-2);
}

.oa-page-header__filters {
  margin-top: var(--oa-space-3);
}
</style>
