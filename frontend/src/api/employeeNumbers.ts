/** 工号体检：找出不合规、重复、与组织前缀不一致的工号。 */
import { api } from "./client";

export interface EmployeeNumberIssue {
  id: string;
  no: string;
  name: string;
  orgId: string;
  reason: string;
}
export interface EmployeeNumberAudit {
  total: number;
  malformed: EmployeeNumberIssue[];
  duplicated: EmployeeNumberIssue[];
  mismatched: EmployeeNumberIssue[];
  mismatchedCount: number;
}

export function auditEmployeeNumbers(): Promise<EmployeeNumberAudit> {
  return api("/api/employees/number-audit");
}

export function renumberEmployees(employeeIds: string[] = []): Promise<{
  updated: number;
  changes: { id: string; name: string; old: string; new: string }[];
}> {
  return api("/api/employees/number-audit/renumber", {
    method: "POST",
    body: { employeeIds },
  });
}
