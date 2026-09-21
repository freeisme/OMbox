<script setup lang="ts">
import { computed } from "vue";
import { isNarrowScreen } from "../../composables/useBreakpoint";

/** 弹窗宽度档位；<768px 时统一用近满宽，避免窄屏溢出。 */
const WIDTH_BY_SIZE = {
  sm: "420px",
  md: "560px",
  lg: "720px",
  xl: "900px",
} as const;

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    title?: string;
    size?: keyof typeof WIDTH_BY_SIZE;
    /** 是否渲染统一底部按钮区；自定义 footer 时用 #footer 插槽。 */
    footer?: boolean;
    confirmText?: string;
    cancelText?: string;
    confirmType?: "primary" | "danger";
    loading?: boolean;
    confirmDisabled?: boolean;
  }>(),
  {
    title: "",
    size: "md",
    footer: true,
    confirmText: "保存",
    cancelText: "取消",
    confirmType: "primary",
    loading: false,
    confirmDisabled: false,
  },
);

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
  (event: "confirm"): void;
}>();

const width = computed(() => (isNarrowScreen.value ? "92%" : WIDTH_BY_SIZE[props.size]));
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    :width="width"
    destroy-on-close
    append-to-body
    class="oa-form-dialog"
    @update:model-value="(value: boolean) => emit('update:modelValue', value)"
  >
    <slot />
    <template v-if="footer || $slots.footer" #footer>
      <slot name="footer">
        <el-button @click="emit('update:modelValue', false)">{{ cancelText }}</el-button>
        <el-button
          :type="confirmType"
          :loading="loading"
          :disabled="confirmDisabled"
          @click="emit('confirm')"
        >
          {{ confirmText }}
        </el-button>
      </slot>
    </template>
  </el-dialog>
</template>

<style scoped>
.oa-form-dialog :deep(.el-dialog__body) {
  max-height: 68vh;
  overflow: auto;
}
</style>
