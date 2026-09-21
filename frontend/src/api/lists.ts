import { api } from "./client";
import type { ComputerRow } from "./state";

export interface ListPage<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface ListQuery {
  page?: number;
  /** 0 表示取全部，用于导出与"全选当前结果"。 */
  pageSize?: number;
  keyword?: string;
  status?: string;
  orgId?: string;
  /** 只看某位使用人名下的终端（设备弹窗用）。 */
  userId?: string;
  /** 只看没有使用人的终端（分配下拉用）。 */
  unassigned?: boolean;
  /** fields=names 只回 id / userId / deviceName / brand / model，用于「名下设备」这类场景。 */
  fields?: "names";
}

function toSearchParams(query: ListQuery): string {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    params.set(key, typeof value === "boolean" ? (value ? "1" : "0") : String(value));
  });
  return params.toString();
}

/**
 * 服务端分页列表：过滤与分页都在服务端完成，返回当前页与匹配总数。
 * 权限与数据范围由服务端按会话裁剪，前端不需要再过滤一遍。
 */
export async function fetchComputerPage(query: ListQuery = {}): Promise<ListPage<ComputerRow>> {
  const search = toSearchParams(query);
  const payload = await api<Partial<ListPage<ComputerRow>>>(`/api/list/computers?${search}`);
  return {
    items: Array.isArray(payload.items) ? payload.items : [],
    total: Number(payload.total ?? 0),
    page: Number(payload.page ?? 1),
    pageSize: Number(payload.pageSize ?? 0),
  };
}

/** fields=names 的精简行：够「名下设备」列、关键字过滤与 CSV 导出用，不含硬件明细。 */
export type ComputerBriefRow = Pick<
  ComputerRow,
  "id" | "userId" | "deviceName" | "brand" | "model"
>;

/**
 * 使用人员页只要设备名与品牌型号：一次拿全量、每行回 5 个字段
 * （约 24 KB，完整行是 144 KB），按使用人分组返回。
 */
export async function fetchComputerBriefs(): Promise<Map<string, ComputerBriefRow[]>> {
  const payload = await api<Partial<ListPage<ComputerBriefRow>>>(
    "/api/list/computers?pageSize=0&fields=names",
  );
  const byEmployee = new Map<string, ComputerBriefRow[]>();
  (payload.items ?? []).forEach((row) => {
    const ownerId = String(row.userId ?? "");
    if (!ownerId) return;
    byEmployee.set(ownerId, [...(byEmployee.get(ownerId) ?? []), row]);
  });
  return byEmployee;
}
