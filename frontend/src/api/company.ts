import { api } from "./client";

export interface Company {
  id: string;
  code: string;
  name: string;
  sortOrder: number;
  isActive: boolean | number;
}

export interface OrgNode {
  id: string;
  code: string;
  name: string;
  parentId: string;
  companyId: string;
  sortOrder: number;
  isActive: boolean | number;
}

export interface OrgTree {
  companies: Company[];
  organizations: OrgNode[];
}

export interface Position {
  id?: string;
  companyId: string;
  companyName?: string;
  orgUnitId: string;
  orgName?: string;
  department: string;
  positionName: string;
  isPrimary: boolean;
  isActive?: boolean | number;
}

export async function listCompanies(): Promise<Company[]> {
  const payload = await api<{ companies?: Company[] }>("/api/companies");
  return payload.companies ?? [];
}

export async function saveCompany(
  payload: Partial<Company> & { name: string },
  companyId = "",
): Promise<Company | null> {
  const result = companyId
    ? await api<{ company?: Company }>(`/api/companies/${encodeURIComponent(companyId)}`, {
        method: "PUT",
        body: payload,
      })
    : await api<{ company?: Company }>("/api/companies", { method: "POST", body: payload });
  return result.company ?? null;
}

export async function deleteCompany(companyId: string): Promise<void> {
  await api(`/api/companies/${encodeURIComponent(companyId)}`, { method: "DELETE" });
}

export interface MyCompanies {
  companies: Company[];
  canViewGroup: boolean;
  companyId: string;
}

/** 当前账号可切换的公司范围（顶栏切换用）。 */
export async function loadMyCompanies(): Promise<MyCompanies> {
  const payload = await api<Partial<MyCompanies>>("/api/my-companies");
  return {
    companies: payload.companies ?? [],
    canViewGroup: Boolean(payload.canViewGroup),
    companyId: String(payload.companyId ?? ""),
  };
}

export async function loadOrgTree(companyId = ""): Promise<OrgTree> {
  const query = companyId ? `?companyId=${encodeURIComponent(companyId)}` : "";
  const payload = await api<Partial<OrgTree>>(`/api/org-tree${query}`);
  return { companies: payload.companies ?? [], organizations: payload.organizations ?? [] };
}

export async function saveOrganization(
  payload: Partial<OrgNode> & { code: string; name: string },
  orgId = "",
): Promise<OrgNode | null> {
  const result = orgId
    ? await api<{ organization?: OrgNode }>(
        "/api/resources/organization/" + encodeURIComponent(orgId),
        { method: "PUT", body: payload },
      )
    : await api<{ organization?: OrgNode }>("/api/resources/organization", {
        method: "POST",
        body: payload,
      });
  return result.organization ?? null;
}

export async function deleteOrganization(orgId: string): Promise<void> {
  await api("/api/resources/organization/" + encodeURIComponent(orgId), { method: "DELETE" });
}

export async function transferOrgSubtree(payload: {
  targetCompanyId: string;
  orgUnitIds: string[];
  moveEmployees?: boolean;
  moveComputers?: boolean;
  moveWarehouses?: boolean;
  moveDatacenter?: boolean;
}): Promise<OrgTree> {
  return api<OrgTree>("/api/organizations/transfer", { method: "POST", body: payload });
}

export async function listPositions(employeeId: string): Promise<Position[]> {
  const payload = await api<{ positions?: Position[] }>(
    `/api/employees/${encodeURIComponent(employeeId)}/positions`,
  );
  return payload.positions ?? [];
}

export async function savePositions(employeeId: string, positions: Position[]): Promise<Position[]> {
  const payload = await api<{ positions?: Position[] }>(
    `/api/employees/${encodeURIComponent(employeeId)}/positions`,
    { method: "PUT", body: { positions } },
  );
  return payload.positions ?? [];
}

export async function transferAsset(payload: {
  assetKind: "computer" | "datacenter_device";
  assetId: string;
  targetCompanyId: string;
  targetOrgUnitId?: string;
  note?: string;
}): Promise<{ transferNo: string }> {
  return api<{ transferNo: string }>("/api/asset-transfers", { method: "POST", body: payload });
}

export async function completeGroupSetup(payload: {
  groupName: string;
  companyName: string;
  moduleDatacenterEnabled: boolean;
  moduleInspectionEnabled: boolean;
}): Promise<void> {
  await api("/api/auth/group-setup", { method: "POST", body: payload });
}

export interface NavLink {
  id: string;
  title: string;
  url: string;
  icon?: string;
  sortOrder: number;
  openMode: "new_tab" | "same_tab";
  isActive?: boolean | number;
}

export async function listNavLinks(): Promise<NavLink[]> {
  const payload = await api<{ links?: NavLink[] }>("/api/nav-links");
  return payload.links ?? [];
}

export async function listAllNavLinks(): Promise<NavLink[]> {
  const payload = await api<{ links?: NavLink[] }>("/api/nav-links/all");
  return payload.links ?? [];
}

export async function saveNavLink(payload: Partial<NavLink> & { title: string; url: string }, linkId = ""): Promise<void> {
  if (linkId) {
    await api(`/api/nav-links/${encodeURIComponent(linkId)}`, { method: "PUT", body: payload });
  } else {
    await api("/api/nav-links", { method: "POST", body: payload });
  }
}

export async function deleteNavLink(linkId: string): Promise<void> {
  await api(`/api/nav-links/${encodeURIComponent(linkId)}`, { method: "DELETE" });
}
