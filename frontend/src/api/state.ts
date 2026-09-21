import { api } from "./client";

export interface ComputerRow {
  id: string;
  deviceName: string;
  orgId: string;
  deviceType: string;
  brand: string;
  model: string;
  cpu: string;
  memory: string;
  storage: string;
  gpu: string;
  fixedAssetCode: string;
  purchaseDate: string;
  registeredDate: string;
  snSt: string;
  wifiMac: string;
  ethernetMac: string;
  location: string;
  department: string;
  position: string;
  status: string;
  remarks: string;
  userId: string;
}

export interface EmployeeRow {
  id: string;
  employeeNo: string;
  name: string;
  orgId: string;
  department: string;
  position: string;
  status: string;
  nonAssetItems?: Array<{ quantity?: number | string }>;
}

export interface MovementLogRow {
  id: string;
  direction: string;
  typeName: string;
  brandName: string;
  modelName: string;
  quantity: number | string;
  sourceLabel: string;
  occurredAt: string;
}

export interface OrgRow {
  id: string;
  code: string;
  name: string;
  parentId: string;
  sortOrder: number;
}
