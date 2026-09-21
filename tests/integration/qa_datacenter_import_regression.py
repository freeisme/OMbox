"""End-to-end regression for the Excel (xlsx/csv) device import.

Builds a real .xlsx workbook in-process, uploads it through
``POST /api/datacenter-devices/import`` and checks preview, commit, duplicate
handling modes, per-row validation errors, audit trail and permissions.

Run with::

    $env:DB_PASSWORD = "<password>"
    $env:DB_NAME = "office_asset_mgmt_codex_datacenter_import_20260920"
    python .\\tests\\integration\\qa_datacenter_import_regression.py
"""

from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MYSQL = Path(os.environ.get("MYSQL_BIN", "mysql"))
DB_NAME = os.environ.get("DB_NAME", "office_asset_mgmt_codex_datacenter_import_20260920")
SERVER_PORT = int(os.environ.get("QA_DATACENTER_IMPORT_PORT", "8028"))
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"
PASSWORD = os.environ.get("QA_DATACENTER_IMPORT_PASSWORD") or f"Qa{secrets.token_urlsafe(12)}!"
PREFIX = "qaxl"

HEADERS = ["设备编号", "设备名称", "品牌型号", "设备类型", "占用高度", "SN/ST", "固资编码", "使用人", "状态", "备注"]


def column_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name


def build_xlsx(rows: list[list[object]]) -> bytes:
    """Create a minimal workbook with inline strings (no shared string table)."""
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row):
            if value is None or value == "":
                continue
            reference = f"{column_name(column_index)}{row_index}"
            cells.append(f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="设备" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        "</Types>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


def password_hash(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=32768,
        r=8,
        p=1,
        dklen=64,
        maxmem=64 * 1024 * 1024,
    )
    return "scrypt$N=32768,r=8,p=1${}${}".format(
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )


def _mysql_args(sql: str, database: str) -> list[str]:
    return [
        str(MYSQL),
        "--protocol=tcp",
        "--host=127.0.0.1",
        "--port=3306",
        "--user=root",
        f"--database={database}",
        "--default-character-set=utf8mb4",
        "--batch",
        "--raw",
        "--skip-column-names",
        "--silent",
        "-e",
        sql,
    ]


def sql_rows(sql: str, database: str | None = None) -> list[str]:
    env = os.environ.copy()
    env["MYSQL_PWD"] = os.environ.get("DB_PASSWORD", "")
    result = subprocess.run(
        _mysql_args(sql, database or DB_NAME),
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def sql_run(sql: str, database: str | None = None) -> None:
    sql_rows(sql, database)


def server_log_path() -> Path:
    return Path(tempfile.gettempdir()) / f"qa_datacenter_import_server_{SERVER_PORT}.log"


def cleanup() -> None:
    statements = [
        f"DELETE FROM audit_log WHERE actor LIKE '{PREFIX}%'",
        f"DELETE FROM datacenter_device WHERE device_code LIKE '{PREFIX.upper()}%'",
        f"DELETE FROM user_account WHERE username LIKE '{PREFIX}%'",
    ]
    for statement in statements:
        try:
            sql_run(statement)
        except RuntimeError as error:
            print(f"cleanup skipped: {statement[:60]} :: {error}", flush=True)


class Client:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def csrf(self) -> str:
        return next((item.value for item in self.jar if item.name == "oa_csrf"), "")

    def request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        expected: int | None = None,
    ) -> tuple[int, dict]:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if method not in {"GET", "HEAD", "OPTIONS"}:
            headers["X-CSRF-Token"] = self.csrf()
        request = urllib.request.Request(BASE_URL + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=20) as response:
                status = response.status
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            status = error.code
            raw = error.read().decode("utf-8")
        result = json.loads(raw) if raw else {}
        if expected is not None and status != expected:
            raise AssertionError(f"{method} {path}: expected {expected}, got {status}: {result}")
        return status, result


def login(username: str) -> Client:
    last_error: object | None = None
    for _ in range(30):
        client = Client()
        status, payload = client.request("POST", "/api/auth/login", {"username": username, "password": PASSWORD})
        if status == 200:
            return client
        last_error = (status, payload)
        time.sleep(0.4)
    raise AssertionError(f"login failed for {username}: {last_error}")


def seed(suffix: str) -> dict[str, str]:
    account_hash = password_hash(PASSWORD)
    sql_run(
        f"""
        INSERT INTO user_account (username, display_name, password_hash, user_role, role_code, is_active)
        VALUES
          ('{PREFIX}_admin_{suffix}', '{PREFIX}管理员', '{account_hash}', 'admin', 'admin', 1),
          ('{PREFIX}_viewer_{suffix}', '{PREFIX}只读', '{account_hash}', 'viewer', 'viewer', 1);
        """
    )
    return {
        "suffix": suffix,
        "admin": f"{PREFIX}_admin_{suffix}",
        "viewer": f"{PREFIX}_viewer_{suffix}",
    }


def start_server() -> "subprocess.Popen[str]":
    env = os.environ.copy()
    env.update(
        {
            "DB_USER": "root",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": "3306",
            "DB_NAME": DB_NAME,
            "MYSQL_BIN": str(MYSQL),
            "MYSQLDUMP_BIN": os.environ.get("MYSQLDUMP_BIN", "mysqldump"),
            "SERVER_HOST": "127.0.0.1",
            "SERVER_PORT": str(SERVER_PORT),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=str(ROOT),
        env=env,
        stdout=open(server_log_path(), "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        text=True,
    )
    for _ in range(40):
        try:
            status, payload = Client().request("GET", "/api/health")
            if status == 200 and payload.get("ok"):
                return process
        except Exception:
            pass
        if process.poll() is not None:
            raise AssertionError("server process exited before becoming healthy")
        time.sleep(0.5)
    process.terminate()
    raise AssertionError("service did not become healthy")


def main() -> int:
    if not os.environ.get("DB_PASSWORD"):
        raise RuntimeError("DB_PASSWORD environment variable is required.")
    cleanup()
    suffix = str(int(time.time()))[-6:]
    fixture = seed(suffix)
    admin = login(fixture["admin"])

    rows = [
        HEADERS,
        [f"{PREFIX.upper()}-SW-{suffix}", f"{PREFIX} 核心交换机", "华为 S5731-H48T4XC", "交换机", "1U",
         f"{PREFIX.upper()}-SN-1-{suffix}", f"{PREFIX.upper()}-FA-1-{suffix}", "机房公用", "未上架", "A 列 1 号柜"],
        [f"{PREFIX.upper()}-SRV-{suffix}", f"{PREFIX} 服务器", "戴尔 PowerEdge R650", "服务器", "2",
         f"{PREFIX.upper()}-SN-2-{suffix}", f"{PREFIX.upper()}-FA-2-{suffix}", "测试部门", "维修", ""],
        [f"{PREFIX.upper()}-UPS-{suffix}", f"{PREFIX} UPS", "山特 C6KS", "UPS", "4", "", "", "", "报废", "待处置"],
        # 故意出错的三行：类型无法识别、状态写成上架、缺少设备名称
        [f"{PREFIX.upper()}-BAD-1-{suffix}", f"{PREFIX} 未知类型", "X", "外星设备", "1", "", "", "", "未上架", ""],
        [f"{PREFIX.upper()}-BAD-2-{suffix}", f"{PREFIX} 上架状态", "X", "服务器", "1", "", "", "", "上架", ""],
        [f"{PREFIX.upper()}-BAD-3-{suffix}", "", "X", "服务器", "1", "", "", "", "未上架", ""],
    ]
    content = base64.b64encode(build_xlsx(rows)).decode("ascii")

    status, preview = admin.request(
        "POST",
        "/api/datacenter-devices/import",
        {"fileName": "机房设备.xlsx", "contentBase64": content, "dryRun": True, "mode": "skip"},
        expected=200,
    )
    assert preview["dryRun"] is True, preview
    assert preview["totalRows"] == 6, preview
    assert preview["created"] == 3 and preview["errorCount"] == 3, preview
    assert preview["sheetHeaders"]["code"] == "设备编号", preview["sheetHeaders"]
    assert any("无法识别" in item["message"] for item in preview["errors"]), preview["errors"]
    assert any("上架" in item["message"] for item in preview["errors"]), preview["errors"]
    assert any("缺少设备名称" in item["message"] for item in preview["errors"]), preview["errors"]
    print("preview ok:", preview["created"], "新增", preview["errorCount"], "错误")

    status, result = admin.request(
        "POST",
        "/api/datacenter-devices/import",
        {"fileName": "机房设备.xlsx", "contentBase64": content, "dryRun": False, "mode": "skip"},
        expected=200,
    )
    assert result["created"] == 3 and result["errorCount"] == 3, result

    status, payload = admin.request("GET", f"/api/datacenter-devices?keyword={PREFIX.upper()}", expected=200)
    devices = {item["code"]: item for item in payload["devices"]}
    switch = devices[f"{PREFIX.upper()}-SW-{suffix}"]
    assert switch["category"] == "network" and switch["uHeight"] == 1, switch
    assert switch["status"] == "stock" and switch["assetCode"].endswith(f"1-{suffix}"), switch
    server = devices[f"{PREFIX.upper()}-SRV-{suffix}"]
    assert server["category"] == "server" and server["status"] == "repair", server
    ups = devices[f"{PREFIX.upper()}-UPS-{suffix}"]
    assert ups["category"] == "power" and ups["uHeight"] == 4 and ups["status"] == "scrapped", ups
    print("commit ok:", len(devices), "台设备")

    status, rerun = admin.request(
        "POST",
        "/api/datacenter-devices/import",
        {"fileName": "机房设备.xlsx", "contentBase64": content, "dryRun": False, "mode": "skip"},
        expected=200,
    )
    assert rerun["created"] == 0 and rerun["skipped"] == 3, rerun
    status, updated = admin.request(
        "POST",
        "/api/datacenter-devices/import",
        {"fileName": "机房设备.xlsx", "contentBase64": content, "dryRun": False, "mode": "update"},
        expected=200,
    )
    assert updated["updated"] == 3 and updated["created"] == 0, updated
    print("duplicate handling ok:", rerun["skipped"], "跳过 /", updated["updated"], "更新")

    # 已上架设备不能被导入改成未上架
    status, payload = admin.request(
        "POST",
        "/api/datacenter-devices",
        {
            "code": f"{PREFIX.upper()}-PLACED-{suffix}",
            "name": f"{PREFIX} 已上架设备",
            "category": "server",
            "uHeight": 1,
            "status": "stock",
        },
        expected=201,
    )
    placed_id = payload["id"]
    sql_run(
        f"UPDATE datacenter_device SET status = 'installed' WHERE device_id = {int(placed_id)};"
    )
    status, guarded = admin.request(
        "POST",
        "/api/datacenter-devices/import",
        {
            "fileName": "已上架.xlsx",
            "contentBase64": base64.b64encode(
                build_xlsx(
                    [
                        HEADERS,
                        [f"{PREFIX.upper()}-PLACED-{suffix}", f"{PREFIX} 已上架设备", "", "服务器", "1",
                         "", "", "", "未上架", ""],
                    ]
                )
            ).decode("ascii"),
            "dryRun": False,
            "mode": "update",
        },
        expected=200,
    )
    assert guarded["errorCount"] == 1 and "机柜视图" in guarded["errors"][0]["message"], guarded
    print("placed-device guard ok")

    audit_rows = sql_rows(
        f"SELECT action_type FROM audit_log WHERE actor LIKE '{PREFIX}%' GROUP BY action_type;"
    )
    assert "datacenter_device_imported" in audit_rows, audit_rows
    print("audit ok:", sorted(audit_rows))

    status, payload = admin.request(
        "POST",
        "/api/datacenter-devices/import",
        {"fileName": "x.txt", "contentBase64": base64.b64encode(b"nope").decode("ascii")},
        expected=400,
    )
    print("unsupported file rejected:", payload.get("error"))

    viewer = login(fixture["viewer"])
    viewer.request(
        "POST",
        "/api/datacenter-devices/import",
        {"fileName": "机房设备.xlsx", "contentBase64": content, "dryRun": True},
        expected=403,
    )
    print("permission checks ok")

    print("DATACENTER IMPORT REGRESSION OK")
    return 0


if __name__ == "__main__":
    server_process = None
    try:
        server_process = start_server()
        raise SystemExit(main())
    finally:
        if server_process is not None:
            server_process.terminate()
