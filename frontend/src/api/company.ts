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

export async function loadOrgTree(companyId = ""): Promise<OrgTree> {
  const query = companyId ? `?companyId=${encodeURIComponent(companyId)}` : "";
  const payload = await api<Partial<OrgTree>>(`/api/org-tree${query}`);
  return { companies: payload.companies ?? [], organizations: payload.organizations ?? [] };
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
