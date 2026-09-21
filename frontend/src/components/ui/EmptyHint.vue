<script setup lang="ts">
withDefaults(
  defineProps<{
    description?: string;
    size?: number;
    actionText?: string;
  }>(),
  { description: "暂无数据", size: 70, actionText: "" },
);

defineEmits<{ (event: "action"): void }>();
</script>

<template>
  <el-empty :description="description" :image-size="size">
    <el-button v-if="actionText" @click="$emit('action')">{{ actionText }}</el-button>
  </el-empty>
</template>
