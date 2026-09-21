<script setup lang="ts">
import { computed } from "vue";
import { isNarrowScreen } from "../../composables/useBreakpoint";

/** 详情抽屉宽度档位；<992px 时全宽，避免表格与描述项被裁切。 */
const SIZE_BY_SIZE = {
  md: "560px",
  lg: "640px",
  xl: "760px",
} as const;

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    title?: string;
    size?: keyof typeof SIZE_BY_SIZE;
    /** 底部按钮区；默认只给一个"关闭"。 */
    closeText?: string;
  }>(),
  { title: "", size: "lg", closeText: "关闭" },
);

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
}>();

const width = computed(() => (isNarrowScreen.value ? "100%" : SIZE_BY_SIZE[props.size]));
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    :title="title"
    :size="width"
    append-to-body
    class="oa-detail-drawer"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
  >
    <slot />
    <template v-if="$slots.footer" #footer>
      <slot name="footer" />
    </template>
    <template v-else #footer>
      <el-button @click="emit('update:modelValue', false)">{{ closeText }}</el-button>
    </template>
  </el-drawer>
</template>
