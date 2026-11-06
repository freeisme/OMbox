import { computed, reactive } from "vue";
import { loadMyCompanies, type Company } from "./api/company";

/**
 * 全局「公司视图」状态：顶栏右上角切换，组织架构等公司相关页面共用。
 * companyId 为空表示「整个集团」或「全部（我的公司）」。
 */
export const companyScope = reactive({
  loaded: false,
  companies: [] as Company[],
  canViewGroup: false,
  companyId: "",
});

export async function loadCompanyScope(): Promise<void> {
  try {
    const payload = await loadMyCompanies();
    companyScope.companies = payload.companies;
    companyScope.canViewGroup = payload.canViewGroup;
    if (
      companyScope.companyId &&
      !payload.companies.some((item) => item.id === companyScope.companyId)
    ) {
      companyScope.companyId = "";
    }
  } catch {
    companyScope.companies = [];
    companyScope.canViewGroup = false;
    companyScope.companyId = "";
  } finally {
    companyScope.loaded = true;
  }
}

/** 只有能看集团，或任职多家公司时才显示切换器。 */
export const canSwitchCompany = computed(
  () => companyScope.canViewGroup || companyScope.companies.length > 1,
);

/** 顶栏当前显示的视图名称。 */
export const companyScopeLabel = computed(() => {
  if (!companyScope.companyId) {
    if (companyScope.canViewGroup) return "整个集团";
    if (companyScope.companies.length > 1) return "全部（我的公司）";
    return companyScope.companies[0]?.name ?? "未绑定公司";
  }
  return companyScope.companies.find((item) => item.id === companyScope.companyId)?.name ?? "—";
});

/** 下拉里「全部」这一项的文案。 */
export const companyScopeAllLabel = computed(() =>
  companyScope.canViewGroup ? "整个集团" : "全部（我的公司）",
);

export function setCompanyScope(companyId: string): void {
  companyScope.companyId = companyId;
}
