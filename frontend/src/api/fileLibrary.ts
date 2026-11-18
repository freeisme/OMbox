/** 机房文件库：机房 → 设备两级目录，配置文件上传与版本管理。 */
import { readCsrfToken } from "./client";

export interface FileSite {
  id: string;
  name: string;
  type: string;
  folderId: string;
}
export interface FileDevice {
  id: string;
  name: string;
  code: string;
  siteId: string;
  status: string;
  active: string | number;
  folderId: string;
  fileCount: number;
}
export interface FileItem {
  id: string;
  name: string;
  size: number | string;
  sha256: string;
  contentType: string;
  description: string;
  version: number | string;
  isCurrent: number | string;
  uploadedBy: string;
  createdAt: string;
  deletedAt?: string;
}
export interface FileEvent {
  id: string;
  fileId: string;
  action: string;
  actor: string;
  detail: Record<string, unknown>;
  createdAt: string;
}

async function jsonFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...((init.headers as Record<string, string> | undefined) ?? {}),
  };
  const method = (init.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD"].includes(method)) headers["X-CSRF-Token"] = readCsrfToken();
  const response = await fetch(path, { ...init, headers, credentials: "same-origin" });
  const text = await response.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message = (payload as { error?: string } | null)?.error || "请求失败（" + response.status + "）";
    throw new Error(message);
  }
  return payload as T;
}

export function getFileTree(): Promise<{ sites: FileSite[]; devices: FileDevice[] }> {
  return jsonFetch("/api/file-library/tree");
}

export function listFiles(folderId: number | string): Promise<{ files: FileItem[] }> {
  return jsonFetch("/api/file-library/files?folderId=" + encodeURIComponent(String(folderId)));
}

export function listEvents(folderId: number | string): Promise<{ events: FileEvent[] }> {
  return jsonFetch("/api/file-library/events?folderId=" + encodeURIComponent(String(folderId)));
}

export async function uploadFile(params: {
  folderId: number | string;
  file: File;
  description?: string;
}): Promise<{ id: number; name: string; version: number; size: number }> {
  const query = new URLSearchParams({
    folderId: String(params.folderId),
    fileName: params.file.name,
    description: params.description ?? "",
  });
  return jsonFetch("/api/file-library/files?" + query.toString(), {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream" },
    body: params.file,
  });
}

export function updateFile(
  id: number | string,
  payload: { name?: string; description?: string },
): Promise<{ ok: boolean }> {
  return jsonFetch("/api/file-library/files/" + encodeURIComponent(String(id)), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteFile(id: number | string): Promise<{ ok: boolean }> {
  return jsonFetch("/api/file-library/files/" + encodeURIComponent(String(id)), { method: "DELETE" });
}

export function downloadUrl(id: number | string): string {
  return "/api/file-library/files/" + encodeURIComponent(String(id)) + "/download";
}
