export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function readCookie(name: string): string {
  const prefix = `${name}=`;
  for (const part of document.cookie.split(";")) {
    const value = part.trim();
    if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
  }
  return "";
}

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

/** 会话过期（接口返回 401）时的统一处理入口；由 main.ts 注入跳转逻辑。 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  csrf?: boolean;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  const hasBody = options.body !== undefined;
  if (hasBody) headers["Content-Type"] = "application/json";
  const safeMethod = ["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase());
  if (!safeMethod && options.csrf !== false) {
    const token = readCookie("oa_csrf");
    if (token) headers["X-CSRF-Token"] = token;
  }
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: hasBody ? JSON.stringify(options.body) : undefined,
  });
  const raw = await response.text();
  let payload: Record<string, unknown> = {};
  if (raw) {
    try {
      payload = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      payload = {};
    }
  }
  if (!response.ok) {
    // /api/auth/* 的 401 属于"尚未登录"的正常探测，交给路由守卫处理。
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      unauthorizedHandler?.();
    }
    throw new ApiError(
      String(payload.error ?? `请求失败（HTTP ${response.status}）`),
      response.status,
      String(payload.code ?? ""),
    );
  }
  return payload as T;
}

/** POST 一个会返回文件的接口（例如数据库备份下载），成功后触发浏览器下载并返回文件名。 */
export async function downloadFile(path: string, body: unknown = {}): Promise<string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = readCookie("oa_csrf");
  if (token) headers["X-CSRF-Token"] = token;
  const response = await fetch(path, {
    method: "POST",
    headers,
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const raw = await response.text();
    let payload: Record<string, unknown> = {};
    try {
      payload = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
    } catch {
      payload = {};
    }
    throw new ApiError(
      String(payload.error ?? `下载失败（HTTP ${response.status}）`),
      response.status,
      String(payload.code ?? ""),
    );
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const matched = /filename\*?=(?:UTF-8''|")?([^";]+)/i.exec(disposition);
  const filename = matched ? decodeURIComponent(matched[1].replace(/"/g, "")) : "download";
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  return filename;
}
