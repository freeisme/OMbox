<script setup lang="ts">
import { computed } from "vue";
import {
  INSPECTION_TASK_STATUS_LABELS,
  statusLabel,
  statusTagType,
  ticketStatusLabel,
  ticketStatusTagType,
} from "../../labels";

const props = withDefaults(
  defineProps<{
    /** 状态原始值 */
    value: string;
    /** 状态所属对象：决定文案与颜色映射 */
    kind?: "computer" | "employee" | "ticket" | "inspection";
    size?: "small" | "default" | "large";
  }>(),
  { kind: "computer", size: "small" },
);

const label = computed(() => {
  if (props.kind === "ticket") return ticketStatusLabel(props.value);
  if (props.kind === "inspection") {
    return INSPECTION_TASK_STATUS_LABELS[props.value] || props.value || "—";
  }
  return statusLabel(props.value);
});

const tagType = computed<"success" | "info" | "warning" | "danger">(() => {
  if (props.kind === "ticket") return ticketStatusTagType(props.value);
  if (props.kind === "inspection") {
    if (props.value === "submitted") return "success";
    if (props.value === "running") return "warning";
    return "info";
  }
  return statusTagType(props.value);
});
</script>

<template>
  <el-tag :size="size" :type="tagType">{{ label }}</el-tag>
</template>
