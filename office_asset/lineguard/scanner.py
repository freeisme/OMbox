"""网段扫描：发现存活主机并探测常见服务端口，输出"候选设备"清单。

设计要点（对应需求：扫描某网段自动加入设备）：
1. 扫描只做只读探测，不修改任何资产数据；
2. 结果以候选清单返回，由前端勾选后再调用 /devices/bulk-create 入库；
3. 自动识别疑似工控机：常见工控端口（SMB/RDP/WinRM 等）开放即标记；
4. 已存在于台账的 IP 会被标记 known=True，默认不重复添加。
"""
from __future__ import annotations

import ipaddress
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field

from .config import LineGuardConfig

# 常用的"工控机/Windows 主机"可识别端口
KNOWN_PORTS: dict[int, str] = {
    445: "SMB",
    3389: "RDP",
    5985: "WinRM",
    5986: "WinRM-HTTPS",
    135: "RPC",
    22: "SSH",
    80: "HTTP",
    102: "S7",          # 西门子 PLC
    502: "Modbus",
    44818: "EtherNet/IP",
}


@dataclass
class Candidate:
    ip: str
    alive: bool = False
    latency_ms: int | None = None
    hostname: str = ""
    mac: str = ""
    open_ports: list[int] = field(default_factory=list)
    port_services: list[str] = field(default_factory=list)
    likely_industrial: bool = False
    reason: str = ""
    known: bool = False
    known_device_id: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_network(cidr: str) -> list[str]:
    """把 CIDR / 起止 IP 解析成主机地址列表；限制最大规模以免误扫整个 A 类网。"""
    cidr = cidr.strip()
    if "-" in cidr:
        start, end = [p.strip() for p in cidr.split("-", 1)]
        first, last = ipaddress.IPv4Address(start), ipaddress.IPv4Address(end)
        if last < first:
            raise ValueError("结束地址必须大于起始地址")
        count = int(last) - int(first) + 1
        if count > 4096:
            raise ValueError("单次最多扫描 4096 个地址，请缩小范围")
        return [str(ipaddress.IPv4Address(int(first) + i)) for i in range(count)]
    net = ipaddress.ip_network(cidr, strict=False)
    if net.version != 4:
        raise ValueError("目前仅支持 IPv4 网段")
    if net.num_addresses > 4096:
        raise ValueError("单次最多扫描 4096 个地址（例如 /20），请缩小网段")
    return [str(ip) for ip in net.hosts()]


def _ping(ip: str, timeout_ms: int) -> tuple[bool, int | None]:
    """ICMP 存活探测；命令不可用时返回不可达（由端口探测兜底）。"""
    timeout_s = max(1, round(timeout_ms / 1000))
    if sys.platform == "win32":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", str(timeout_s), ip]
    started = time.perf_counter()
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout_s + 1)
        return (result.returncode == 0, int((time.perf_counter() - started) * 1000))
    except (subprocess.SubprocessError, OSError):
        return (False, None)


def _tcp_open(ip: str, port: int, timeout_ms: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_ms / 1000)
            return sock.connect_ex((ip, port)) == 0
    except OSError:
        return False


def _resolve_hostname(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror, OSError):
        return ""


def _arp_table() -> dict[str, str]:
    """读取本机 ARP 表，拿到同一网段主机的 MAC（Linux: ip neigh，Windows: arp -a）。"""
    mapping: dict[str, str] = {}
    try:
        if sys.platform == "win32":
            out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].count(".") == 3:
                    mapping[parts[0]] = parts[1].replace("-", ":").lower()
        else:
            out = subprocess.run(["ip", "neigh"], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[1] == "dev":
                    continue
                if parts and parts[0].count(".") == 3 and "lladdr" in parts:
                    mapping[parts[0]] = parts[parts.index("lladdr") + 1].lower()
    except (subprocess.SubprocessError, OSError):
        pass
    return mapping


def scan_network(
    cidr: str,
    config: LineGuardConfig,
    known_ips: dict[str, int] | None = None,
    probe_ports: list[int] | None = None,
) -> dict:
    """扫描网段，返回 {cidr, total, alive, candidates, started_at, finished_at, duration_ms}。"""
    known_ips = known_ips or {}
    ports = probe_ports or [445, 3389, 5985, 22]
    hosts = parse_network(cidr)
    arp = _arp_table()
    started = time.time()

    def probe(ip: str) -> Candidate:
        cand = Candidate(ip=ip)
        alive, latency = _ping(ip, config.scan_timeout_ms)
        open_ports = [p for p in ports if _tcp_open(ip, p, config.scan_timeout_ms)]
        cand.alive = alive or bool(open_ports)
        cand.latency_ms = latency if alive else None
        cand.open_ports = open_ports
        cand.port_services = [KNOWN_PORTS.get(p, str(p)) for p in open_ports]
        cand.mac = arp.get(ip, "")
        if cand.alive:
            cand.hostname = _resolve_hostname(ip)
        # 疑似工控机判定：开放了 SMB/RDP/WinRM（Windows 主机特征）或工业协议口
        windows_marks = {445, 3389, 5985, 5986, 135}
        if windows_marks & set(open_ports):
            cand.likely_industrial = True
            cand.reason = "开放 Windows 远程/文件服务端口，疑似工控机"
        elif set(open_ports) & {102, 502, 44818}:
            cand.likely_industrial = True
            cand.reason = "开放工业协议端口"
        elif cand.alive:
            cand.reason = "仅 ICMP 可达"
        if ip in known_ips:
            cand.known = True
            cand.known_device_id = known_ips[ip]
        return cand

    candidates: list[Candidate] = []
    with ThreadPoolExecutor(max_workers=max(1, config.scan_concurrency)) as pool:
        futures = {pool.submit(probe, ip): ip for ip in hosts}
        for fut in as_completed(futures):
            try:
                candidates.append(fut.result())
            except Exception:  # 单台失败不影响整体扫描
                pass

    candidates.sort(key=lambda c: ipaddress.IPv4Address(c.ip))
    alive = [c.to_dict() for c in candidates if c.alive]
    return {
        "cidr": cidr,
        "total": len(hosts),
        "alive_count": len(alive),
        "may_add_count": sum(1 for c in alive if not c["known"]),
        "candidates": alive,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_ms": int((time.time() - started) * 1000),
    }
