import { computed, ref } from "vue";

/** 四档断点，与 docs/development/frontend-design-plan.md 的表格一致。 */
export type Breakpoint = "s" | "m" | "l" | "xl";

export function resolveBreakpoint(width: number): Breakpoint {
  if (width >= 1200) return "xl";
  if (width >= 992) return "l";
  if (width >= 768) return "m";
  return "s";
}

export const viewportWidth = ref(typeof window === "undefined" ? 1440 : window.innerWidth);

export const breakpoint = computed<Breakpoint>(() => resolveBreakpoint(viewportWidth.value));

/** 小屏（<768）下弹窗占满宽度、抽屉全宽，避免内容被裁切。 */
export const isNarrowScreen = computed(() => breakpoint.value === "s" || breakpoint.value === "m");

if (typeof window !== "undefined") {
  window.addEventListener("resize", () => {
    viewportWidth.value = window.innerWidth;
  });
}

export function useBreakpoint() {
  return { viewportWidth, breakpoint, isNarrowScreen };
}
