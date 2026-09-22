"""Release safety scan.

Fails when a revision still contains credentials, internal network details,
local machine paths or business identifiers that must never be published.
Run it before every push or release::

    python tools/scan_release_safety.py --rev HEAD

The scan reads files from the git object store, so it also works in CI on a
fresh checkout. Exit code 1 means at least one finding; the report lists the
file, line and matched rule.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SELF_PATH = "tools/scan_release_safety.py"

TEXT_EXTENSIONS = {
    ".cfg",
    ".conf",
    ".css",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".service",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
}

FORBIDDEN_FILES = (
    re.compile(r"(^|/)\.env$"),
    re.compile(r"\.sql\.gz$"),
    re.compile(r"\.bundle$"),
    re.compile(r"\.xlsx?$"),
    re.compile(r"\.log$"),
    re.compile(r"(^|/)PROJECT_HANDOVER\.md$"),
)

# Rules are ordered from most dangerous to least. Add new production
# identifiers here, never inside documents or test fixtures.
RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "cloud-or-personal-access-token",
        re.compile(
            r"(ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
            r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{20,})"
        ),
    ),
    ("private-key-material", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")),
    ("ssh-key-material", re.compile(r"(ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp256) AAAA")),
    (
        "internal-ipv4",
        re.compile(
            r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"
        ),
    ),
    (
        "local-machine-path",
        # 单反斜杠（文档里直接写 D:\数据库\...）与双反斜杠（JSON/Python 字符串里的转义写法）都要拦下来，
        # 正斜杠写法同样处理，否则只要不用转义就能绕过去。
        re.compile(r"\b[CDEF]:[\\/]{1,2}(?:Users|数据库|work|项目|temp|Temp)\b"),
    ),
    (
        "local-mysql-path",
        re.compile(r"[A-Za-z]:\\\\?MySQL|MySQL\\\\bin"),
    ),
    (
        "hardcoded-credential",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key)\b\s*[:=]\s*"
            r"[\"'][^\"'<>{}$\s]{6,}[\"']"
        ),
    ),
    (
        "business-employee-number",
        re.compile(r"\b[A-Z]{2,6}-[A-Z]{2,6}-[A-Z]{1,4}-\d{3}\b"),
    ),
    (
        "internal-account-name",
        re.compile(r"\badmin1\b|gitea-office-asset|server-admin"),
    ),
    # 个人信息与业务标识：文档、版本说明和测试数据里都不得出现真实取值。
    ("china-mobile-number", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("china-id-card-number", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    (
        "email-address",
        # 顶级域必须以字母开头，避免把 `包名@0.6.2`、`git@192.0.2.10` 这类
        # 版本号与文档地址误判成邮箱。
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z][A-Za-z0-9-]*\b"),
    ),
    # 本部署的资产编码前缀，形如「前缀 + 两位字母 + 三位数字」。换部署时按实际前缀调整。
    ("internal-asset-code", re.compile(r"\bK3D[A-Z]{2}\d{3}\b")),
)

# 邮箱规则单独放行明显的占位/测试地址（本地部分是这些词时不算个人信息），
# 例如测试 URL 校验用的 `https://token@github.com/...`。
EMAIL_PLACEHOLDER_LOCAL_PARTS = (
    "token",
    "user",
    "your",
    "example",
    "test",
    "qa",
    "dev",
    "admin",
    "noreply",
    "no-reply",
)

# 邮箱规则同时放行文档里用的保留域（example.* / *.invalid）。
EMAIL_PLACEHOLDER_DOMAIN_HINTS = ("example", ".invalid")

PLACEHOLDER_HINTS = (
    "replace-with",
    "change-me",
    "example",
    "placeholder",
    "your-",
    "xxx",
    "***",
    "替换",
    "安全配置",
    "读取",
    "占位",
    "示例",
    "<",
    "...",
)

# Hostname-style matches are checked separately so container/DNS helper names
# and reserved documentation domains are allowed while real internal names are
# still reported by the `internal-hostname` rule.
INTERNAL_HOST_PATTERN = re.compile(
    r"\b([A-Za-z0-9][A-Za-z0-9.-]*\.(?:local|lan|internal))\b"
)
ALLOWED_INTERNAL_HOST_SUFFIXES = (
    ".docker.internal",
    ".example.internal",
)

# 词表里常见的非取值内容（mysql -N 会把 NULL 打成 NULL），以及通用技术词
# ——它们既是合法的字典/账号名，也一定会出现在代码里，保留只会制造噪音。
WORDLIST_SKIP_VALUES = {
    "null",
    "\\n",
    "n/a",
    "na",
    "none",
    "-",
    "--",
    "admin",
    "root",
    "user",
    "operator",
    "viewer",
    "test",
    "demo",
    "sample",
    "localhost",
}


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT_DIR), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout


def tracked_files(revision: str) -> list[str]:
    output = git("ls-tree", "-r", "--name-only", revision)
    return [line.strip() for line in output.splitlines() if line.strip()]


def file_content(revision: str, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(ROOT_DIR), "show", f"{revision}:{path}"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(hint in lowered for hint in PLACEHOLDER_HINTS)


def scan(revision: str) -> list[str]:
    findings: list[str] = []
    for path in tracked_files(revision):
        if path == SELF_PATH:
            # The scanner contains the rule patterns themselves.
            continue
        for pattern in FORBIDDEN_FILES:
            if pattern.search(path):
                findings.append(f"{path}: forbidden file for a public release")
        if Path(path).suffix.lower() not in TEXT_EXTENSIONS and "." in Path(path).name:
            continue
        content = file_content(revision, path)
        if content is None:
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            for rule_name, regex in RULES:
                match = regex.search(line)
                if not match:
                    continue
                if rule_name == "hardcoded-credential" and is_placeholder(match.group(0)):
                    continue
                if rule_name == "email-address":
                    local_part = match.group(0).split("@", 1)[0].lower()
                    if local_part in EMAIL_PLACEHOLDER_LOCAL_PARTS:
                        continue
                    if any(hint in local_part for hint in ("example", "your-", "token", "test")):
                        continue
                    domain = match.group(0).split("@", 1)[1].lower()
                    if any(hint in domain for hint in EMAIL_PLACEHOLDER_DOMAIN_HINTS):
                        continue
                excerpt = match.group(0)[:60]
                findings.append(f"{path}:{line_number}: {rule_name} -> {excerpt}")
            for host_match in INTERNAL_HOST_PATTERN.finditer(line):
                host = host_match.group(1).lower()
                if host.endswith(ALLOWED_INTERNAL_HOST_SUFFIXES):
                    continue
                findings.append(
                    f"{path}:{line_number}: internal-hostname -> {host[:60]}"
                )
    return findings


def scan_wordlist(revision: str, words: list[str]) -> list[str]:
    """用内部数据词表反查受跟踪文件：正则覆盖不到真实姓名、设备编码、组织名称。"""
    findings: list[str] = []
    for path in tracked_files(revision):
        if path == SELF_PATH:
            continue
        if Path(path).suffix.lower() not in TEXT_EXTENSIONS and "." in Path(path).name:
            continue
        content = file_content(revision, path)
        if content is None:
            continue
        lowered = content.lower()
        matched = [word for word in words if word.lower() in lowered]
        if not matched:
            continue
        lines = content.splitlines()
        for word in matched:
            for line_number, line in enumerate(lines, start=1):
                if word.lower() in line.lower():
                    findings.append(f"{path}:{line_number}: internal-wordlist -> {word[:60]}")
                    break
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan a revision for sensitive content.")
    parser.add_argument("--rev", default="HEAD", help="Revision to scan (default: HEAD)")
    parser.add_argument(
        "--wordlist",
        default="",
        help=(
            "内部数据词表（每行一个值：人员姓名、工号、设备名、SN、组织/仓库名称…）。"
            "词表必须放在仓库之外；命中任意一项即视为泄漏。用于补正则覆盖不到的真实业务数据。"
        ),
    )
    parser.add_argument(
        "--wordlist-min-length",
        type=int,
        default=3,
        help="词表里短于该长度的值直接忽略（默认 3；两字姓名误报率高，需要时手工调低）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    wordlist: list[str] = []
    if args.wordlist:
        try:
            raw = Path(args.wordlist).read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            print(f"Release safety scan failed: cannot read wordlist: {error}", file=sys.stderr)
            return 2
        minimum = max(1, args.wordlist_min_length)
        wordlist = []
        for line in raw.splitlines():
            value = line.strip()
            if len(value) < minimum or value.lower() in WORDLIST_SKIP_VALUES:
                continue
            wordlist.append(value)
        wordlist = list(dict.fromkeys(wordlist))
    try:
        findings = scan(args.rev)
    except RuntimeError as error:
        print(f"Release safety scan failed: {error}", file=sys.stderr)
        return 2
    if wordlist:
        findings.extend(scan_wordlist(args.rev, wordlist))
    if findings:
        print(f"Release safety scan found {len(findings)} issue(s):")
        for item in findings:
            print(f"  {item}")
        print("Remove or replace the content above before pushing or releasing.")
        return 1
    print(f"Release safety scan passed for {args.rev}: no sensitive content detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
