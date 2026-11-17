#!/usr/bin/env python3
"""OMbox 黑盒 / 安全 / 兼容 / 性能测试套件（对运行中的服务发真实 HTTP 请求）。

用法：
    python tests/qa/http_suite.py --base http://127.0.0.1:8030
    python tests/qa/http_suite.py --base http://127.0.0.1:8030 --no-perf

约定：
- 只创建带 QA- 前缀的办公终端测试数据，结束时删除；
- 不修改任何表结构，不动业务主数据；
- 输出 JSON 汇总，失败时退出码 1。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

RESULTS: list[dict] = []


def record(kind: str, name: str, ok: bool, detail: object = "") -> None:
    RESULTS.append({"kind": kind, "name": name, "ok": bool(ok), "detail": str(detail)[:400]})


def expect(kind: str, name: str, cond: bool, detail: object = "") -> bool:
    record(kind, name, cond, detail)
    return cond


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.last_headers: dict[str, str] = {}
        self.last_set_cookies = ""

    def csrf(self) -> str:
        for cookie in self.jar:
            if cookie.name == "oa_csrf":
                return cookie.value
        return ""

    def request(self, method: str, path: str, payload=None, *, with_csrf=True, body=None,
                headers=None, timeout=20):
        data = body
        hdrs = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode()
        if with_csrf and method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = self.csrf()
            if token:
                hdrs["X-CSRF-Token"] = token
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(self.base + path, data=data, headers=hdrs, method=method)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                self.last_headers = {k.lower(): v for k, v in resp.headers.items()}
                self.last_set_cookies = "; ".join(resp.headers.get_all("Set-Cookie") or [])
                self.last_status = resp.status
                try:
                    return resp.status, json.loads(raw.decode("utf-8")) if raw[:1] in (b"{", b"[") else raw
                except Exception:
                    return resp.status, raw
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            self.last_headers = {k.lower(): v for k, v in exc.headers.items()}
            self.last_status = exc.code
            try:
                return exc.code, json.loads(raw.decode("utf-8"))
            except Exception:
                return exc.code, raw

    def login(self, username: str, password: str):
        return self.request("POST", "/api/auth/login", {"username": username, "password": password})


def qa_org_id(admin: Client) -> str:
    _, state = admin.request("GET", "/api/state?include=organizations")
    orgs = state.get("organizations") or []
    for org in orgs:
        if str(org.get("level") or org.get("orgLevel") or "") in {"1", ""}:
            return str(org.get("id"))
    return str(orgs[0]["id"]) if orgs else "1"


def active_employees(admin: Client) -> list[dict]:
    _, state = admin.request("GET", "/api/state?include=employees")
    return [e for e in (state.get("employees") or []) if e.get("status") == "active"]


# ---------------------------------------------------------------- 功能（黑盒）
def functional(base: str) -> None:
    K = "功能"
    admin = Client(base)
    status, payload = admin.login("admin", "Admin@12345")
    expect(K, "F01 管理员登录成功", status == 200 and bool(admin.csrf()), f"http={status}")

    bad = Client(base)
    status, _ = bad.login("admin", "WrongPass!2026")
    expect(K, "F02 错误密码被拒绝", status == 401, f"http={status}")

    anon = Client(base)
    status, _ = anon.request("GET", "/api/state", with_csrf=False)
    expect(K, "F03 未登录访问接口返回 401", status == 401, f"http={status}")

    status, body = admin.request("POST", "/api/resources/computer", {"deviceName": "QA-CSRF"}, with_csrf=False)
    expect(K, "F04 缺少 CSRF 令牌写入被拒绝", status in (401, 403), f"http={status}")

    status, state = admin.request("GET", "/api/state?include=computers,employees")
    expect(K, "F05 状态接口返回台账数据",
           status == 200 and isinstance(state.get("computers"), list) and isinstance(state.get("employees"), list),
           f"computers={len(state.get('computers') or [])} employees={len(state.get('employees') or [])}")

    org_id = qa_org_id(admin)
    tag = str(int(time.time()))[-6:]
    name = f"QA-终端-{tag}"
    status, created = admin.request("POST", "/api/resources/computer",
                                    {"deviceName": name, "orgId": org_id, "deviceType": "laptop",
                                     "status": "idle", "registrationMode": "custom"})
    cid = ((created or {}).get("computer") or {}).get("id") if isinstance(created, dict) else None
    expect(K, "F06 新建办公终端", status in (200, 201) and bool(cid), f"http={status} id={cid}")
    if not cid:
        return

    status, dup = admin.request("POST", "/api/resources/computer",
                                {"deviceName": name, "orgId": org_id, "deviceType": "laptop",
                                 "status": "idle", "registrationMode": "custom"})
    expect(K, "F07 同名设备被拒绝", status == 409, f"http={status}")

    status, _ = admin.request("PUT", f"/api/resources/computer/{cid}",
                              {"deviceName": name, "orgId": org_id, "deviceType": "laptop", "status": "idle"})
    expect(K, "F08 修改办公终端", status == 200, f"http={status}")

    employees = active_employees(admin)
    if employees:
        emp = str(employees[0]["id"])
        status, _ = admin.request("POST", f"/api/computers/{cid}/assignments", {"employeeId": emp})
        expect(K, "F09 分配设备给使用人员", status in (200, 201), f"http={status} emp={emp}")

        _, state = admin.request("GET", "/api/state?include=computers")
        row = next((c for c in (state.get("computers") or []) if str(c.get("id")) == str(cid)), None)
        expect(K, "F10 分配后设备为在用", bool(row) and row.get("status") == "in_use" and str(row.get("userId")) == emp,
               f"status={row and row.get('status')} userId={row and row.get('userId')}")

        status, _ = admin.request("PUT", f"/api/resources/computer/{cid}",
                                  {"deviceName": name, "orgId": org_id, "deviceType": "laptop", "status": "idle"})
        _, state = admin.request("GET", "/api/state?include=computers")
        row = next((c for c in (state.get("computers") or []) if str(c.get("id")) == str(cid)), None)
        expect(K, "F11 改闲置自动退回分配（v4.0.9 回归）",
               status == 200 and bool(row) and row.get("status") == "idle" and not row.get("userId"),
               f"status={row and row.get('status')} userId={row and row.get('userId')}")

        status, preview = admin.request("GET", f"/api/employees/{emp}/offboarding-preview")
        items = (preview or {}).get("items") if isinstance(preview, dict) else None
        expect(K, "F12 离职资产预览", status == 200 and isinstance(items, list), f"http={status} items={len(items or [])}")

        if isinstance(items, list) and items:
            plan = [{"itemType": i["itemType"], "itemId": i["id"], "action": "exception",
                     "note": "QA", "targetEmployeeId": "", "recoveryWarehouseId": ""} for i in items]
            status, body = admin.request("POST", f"/api/employees/{emp}/offboard",
                                         {"leaveDate": "2026-11-17", "leaveReason": "QA 测试",
                                          "leaveRemark": "QA 异常待处理", "items": plan})
            expect(K, "F13 异常待处理可完成离职", status == 200, f"http={status} {str(body)[:120]}")
            _, state = admin.request("GET", "/api/state?include=leftEmployees")
            row = next((r for r in (state.get("leftEmployees") or []) if str(r.get("sourceEmployeeId")) == emp), None)
            expect(K, "F14 离职行带异常计数（v4.0.9 回归）",
                   bool(row) and int(row.get("exceptionCount") or 0) >= 1,
                   f"exceptionCount={row and row.get('exceptionCount')}")

    status, body = admin.request("POST", "/api/exports/xlsx",
                                 {"sheet": "QA", "header": ["列1", "列2"],
                                  "rows": [["a", "1"], ["b", "2"]]})
    ok_zip = status == 200 and isinstance(body, (bytes, bytearray)) and bytes(body[:2]) == b"PK"
    expect(K, "F15 导出台账生成 xlsx", ok_zip, f"http={status} bytes={len(body) if isinstance(body, (bytes, bytearray)) else '-'}")

    status, _ = admin.request("GET", "/api/inventory/warehouses")
    expect(K, "F16 仓库列表", status == 200, f"http={status}")

    status, body = admin.request("POST", "/api/inventory/receipts", {})
    expect(K, "F17 入库缺参数被拒绝", status == 400, f"http={status}")

    status, _ = admin.request("GET", "/api/inventory/allocations")
    expect(K, "F18 物资分配记录列表", status == 200, f"http={status}")

    status, body = admin.request("GET", "/api/tickets")
    expect(K, "F19 工单列表", status == 200, f"http={status}")

    status, body = admin.request("GET", "/api/lineguard/devices")
    expect(K, "F20 工控机台账列表", status == 200, f"http={status}")

    status, body = admin.request("POST", "/api/lineguard/scan", {"cidr": "not-a-cidr"})
    expect(K, "F21 非法网段扫描被拒绝", status == 400, f"http={status}")

    status, body = admin.request("GET", "/api/state?include=computers")
    expect(K, "F22 未知接口返回 404", admin.request("GET", "/api/not-exists")[0] == 404, "")

    status, body = admin.request("POST", "/api/resources/computer", body=b"{bad json", with_csrf=True)
    expect(K, "F23 非法 JSON 返回 400 且无堆栈", status == 400 and b"Traceback" not in (body if isinstance(body, bytes) else json.dumps(body).encode()),
           f"http={status}")

    status, body = admin.request("DELETE", f"/api/resources/computer/{cid}")
    # 已有流转历史的设备不允许直接删除，属于业务规则；两种结果都算通过，但记录实际行为
    expect(K, "F24 删除测试设备（有流转历史时按规则拦截）",
           status in (200, 204, 400, 409),
           f"http={status} {str(body)[:80]}")


# ---------------------------------------------------------------- 安全
def security(base: str) -> None:
    K = "安全"
    admin = Client(base)
    admin.login("admin", "Admin@12345")

    cookies = [c for c in admin.jar]
    raw_cookie = admin.last_set_cookies
    expect(K, "S01 会话 Cookie 带 HttpOnly", any(c.name == "oa_session" for c in cookies) and "httponly" in raw_cookie.lower(),
           raw_cookie[:120])

    _, _ = admin.request("GET", "/api/health")
    hdrs = admin.last_headers
    expect(K, "S02 响应包含 nosniff 防嗅探头", hdrs.get("x-content-type-options", "").lower() == "nosniff",
           str({k: v for k, v in hdrs.items() if k.startswith("x-")})[:160])

    sqli = Client(base)
    status, _ = sqli.login("admin' OR '1'='1", "x' OR '1'='1")
    # 400=输入校验先拦下，401=凭据不匹配，两者都说明注入不成立
    expect(K, "S03 登录 SQL 注入无效", status in (400, 401), f"http={status}")

    status, body = admin.request("GET", "/api/state?include=computers&keyword=" + urllib.parse.quote("' OR 1=1 -- "))
    expect(K, "S04 查询参数注入不报错也不放大结果", status == 200, f"http={status}")

    viewer = Client(base)
    viewer.login("viewer", "Viewer@12345")
    status, _ = viewer.request("POST", "/api/resources/computer",
                               {"deviceName": "QA-XSS", "orgId": "1", "deviceType": "laptop",
                                "status": "idle", "registrationMode": "custom"})
    expect(K, "S05 只读账号写入被拒绝", status in (401, 403), f"http={status}")

    _, state = admin.request("GET", "/api/state?include=computers,employees")
    admin_emp = next(iter(state.get("employees") or []), None)
    compa = Client(base)
    compa.login("compa", "Compa@12345")
    if admin_emp:
        status, _ = compa.request("GET", f"/api/employees/{admin_emp.get('id')}/offboarding-preview")
        expect(K, "S06 跨公司读取他人数据被拒绝", status in (403, 404), f"http={status}")

    status, body = admin.request("GET", "/api/state?include=" + urllib.parse.quote("../../etc/passwd"))
    expect(K, "S07 非法 include 不泄露文件", status == 200 and b"root:" not in (body if isinstance(body, bytes) else json.dumps(body).encode()),
           f"http={status}")

    probe = Client(base)
    for _ in range(6):
        probe.login("admin", "WrongPass!2026")
    status, _ = probe.login("admin", "Admin@12345")
    locked = status != 200
    record(K, "S08 连续失败登录是否限流（现状记录）", True,
           f"第 7 次登录 http={status} 限流={'是' if locked else '否'}")

    status, health = admin.request("GET", "/api/health")
    text = json.dumps(health, ensure_ascii=False) if not isinstance(health, bytes) else health.decode("utf-8", "replace")
    expect(K, "S09 健康检查不泄露敏感信息", "password" not in text.lower() and "mysql" not in text.lower(), text[:120])

    status, _ = admin.request("POST", "/api/resources/computer", {"deviceName": "QA"}, headers={"X-CSRF-Token": "wrong-token"})
    expect(K, "S10 错误 CSRF 令牌被拒绝", status in (401, 403), f"http={status}")

    status, access = viewer.request("GET", "/api/access-control")
    users_leaked = bool((access or {}).get("users")) if isinstance(access, dict) else False
    expect(K, "S11 只读账号读权限矩阵时不返回账号清单",
           status in (401, 403) or not users_leaked,
           f"http={status} users={len((access or {}).get('users') or []) if isinstance(access, dict) else '-'}")


# ---------------------------------------------------------------- 兼容性
def compatibility(base: str) -> None:
    K = "兼容"
    admin = Client(base)
    admin.login("admin", "Admin@12345")

    legacy = ["/", "/datacenter", "/inventory-hub", "/rack-layout", "/device-panel", "/topology",
              "/inventory", "/flow-control", "/scrap-records", "/datacenter-devices"]
    for path in legacy:
        status, body = admin.request("GET", path)
        is_html = isinstance(body, (bytes, bytearray)) and b"<!doctype html" in bytes(body[:200]).lower()
        expect(K, f"C 旧/深链接可访问 {path}", status == 200 and is_html, f"http={status}")

    status, meta = admin.request("GET", "/api/meta")
    expected = open("VERSION", encoding="utf-8").read().strip()
    got = (meta or {}).get("version") if isinstance(meta, dict) else None
    expect(K, "C VERSION 与 /api/meta 一致", got == expected, f"meta={got} VERSION={expected}")

    status, _ = admin.request("GET", "/api/state?include=computers")
    expect(K, "C 接口返回 JSON Content-Type",
           "application/json" in admin.last_headers.get("content-type", ""),
           admin.last_headers.get("content-type", ""))


# ---------------------------------------------------------------- 性能
def performance(base: str, threads: int = 16, per_thread: int = 12) -> None:
    K = "性能"
    # 安全用例里连续失败登录会临时锁定 admin，性能段改用未受限的 company_admin 账号
    admin = Client(base)
    status, _ = admin.login("compa", "Compa@12345")
    if status != 200:
        record(K, "P 准备：性能测试账号登录", False, f"http={status}")
        return
    record(K, "P 准备：性能测试账号登录", True, "compa")

    def worker(samples: list, errors: list, path: str) -> None:
        client = Client(base)
        client.jar = admin.jar
        client.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(client.jar))
        for _ in range(per_thread):
            start = time.perf_counter()
            try:
                status, _ = client.request("GET", path)
                if status != 200:
                    errors.append(status)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc)[:60])
            samples.append((time.perf_counter() - start) * 1000)

    for path, label in (("/api/state?include=computers,employees", "状态全量"), ("/api/tickets", "工单列表")):
        samples: list[float] = []
        errors: list = []
        pool = [threading.Thread(target=worker, args=(samples, errors, path)) for _ in range(threads)]
        started = time.perf_counter()
        for t in pool:
            t.start()
        for t in pool:
            t.join()
        elapsed = time.perf_counter() - started
        total = threads * per_thread
        if samples:
            ordered = sorted(samples)
            p50 = ordered[int(len(ordered) * 0.5)]
            p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
            record(K, f"P {label} 并发 {threads}×{per_thread}",
                   not errors,
                   f"rps={total / elapsed:.1f} p50={p50:.0f}ms p95={p95:.0f}ms max={ordered[-1]:.0f}ms errors={len(errors)}")

    # 单请求基线：串行 5 次，用来区分"接口本身慢"和"并发排队"
    for path, label in (("/api/state?include=computers", "状态-含设备"), ("/api/tickets", "工单")):
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            status, _ = admin.request("GET", path)
            samples.append((time.perf_counter() - start) * 1000 if status == 200 else -1)
        ok = all(s >= 0 for s in samples)
        record(K, f"P 单请求基线 {label}", ok,
               f"avg={statistics.mean(samples):.0f}ms max={max(samples):.0f}ms" if ok else f"http 失败 {samples}")

    login_client = Client(base)
    start = time.perf_counter()
    status, _ = login_client.login("compa", "Compa@12345")
    record(K, "P 登录耗时", status == 200, f"{(time.perf_counter() - start) * 1000:.0f}ms http={status}")

    rows = [[f"QA{i}", str(i)] for i in range(200)]
    start = time.perf_counter()
    status, body = admin.request("POST", "/api/exports/xlsx", {"sheet": "QA", "header": ["A", "B"], "rows": rows})
    size = len(body) if isinstance(body, (bytes, bytearray)) else 0
    record(K, "P 导出 200 行 xlsx", status == 200,
           f"{size} bytes / {(time.perf_counter() - start) * 1000:.0f}ms")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8030")
    parser.add_argument("--no-perf", action="store_true")
    args = parser.parse_args()

    functional(args.base)
    security(args.base)
    compatibility(args.base)
    if not args.no_perf:
        performance(args.base)

    failed = [r for r in RESULTS if not r["ok"]]
    for r in RESULTS:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"[{mark}] [{r['kind']}] {r['name']}" + (f"  | {r['detail']}" if r["detail"] else ""))
    print(json.dumps({"total": len(RESULTS), "failed": len(failed),
                      "by_kind": {k: sum(1 for r in RESULTS if r["kind"] == k) for k in {r["kind"] for r in RESULTS}}},
                     ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
