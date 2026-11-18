"""机房文件库：按「机房 → 设备」两级目录归档配置文件。

设计要点：
- 文件实体存磁盘（FILE_LIBRARY_ROOT，默认 <仓库>/file-library），数据库只存元数据；
- 一级目录 = 机房/弱电间（asset_site），二级目录 = 机房设备（datacenter_device）；
- 设备建档时自动建目录；历史数据在首次打开文件库时惰性补齐（sync_folders 幂等）；
- 同名文件默认保留历史版本：新版本置 is_current=1，旧版本置 0；
- 权限复用机房模块 rack_layout，本模块不单独定义权限。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

_CHUNK = 1024 * 1024
_SAFE_NAME = re.compile(r"[^0-9A-Za-z._\-]+")


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class FileLibraryService:
    def __init__(self, db, scope, api_error, conflict_error, forbidden_error, root_dir: Path) -> None:
        self.db = db
        self.scope = scope
        self.api_error = api_error
        self.conflict_error = conflict_error
        self.forbidden_error = forbidden_error
        self.root = Path(root_dir)
        self.max_bytes = int(os.environ.get("FILE_LIBRARY_MAX_BYTES", str(50 * 1024 * 1024)))

    def _insert(self, sql: str) -> int:
        """执行 INSERT 并在同一次连接里取回自增主键。"""
        output = self.db.execute(sql.rstrip().rstrip(";") + ";\nSELECT LAST_INSERT_ID();")
        for line in reversed([item.strip() for item in str(output or "").splitlines() if item.strip()]):
            if line.isdigit():
                return int(line)
        return 0

    # ------------------------------------------------------------ 目录
    def _safe_extension(self, name: str) -> str:
        suffix = Path(name).suffix
        return _SAFE_NAME.sub("_", suffix)[:16]

    def ensure_site_folder(self, site_id: int) -> int:
        site_id = int(site_id)
        row = self.db.json(
            f"SELECT JSON_OBJECT('id', CAST(folder_id AS CHAR)) FROM file_folder WHERE folder_type = 'site' AND site_id = {site_id} LIMIT 1",
            None,
        )
        if isinstance(row, dict) and row.get("id"):
            return int(row["id"])
        name = ""
        site = self.db.json(
            f"SELECT JSON_OBJECT('name', site_name) FROM asset_site WHERE site_id = {site_id} LIMIT 1",
            None,
        )
        if isinstance(site, dict):
            name = str(site.get("name") or "")
        return self._insert(
            "INSERT INTO file_folder (folder_type, site_id, display_name) VALUES ('site', "
            f"{site_id}, {self.db.quote(name)})"
        )

    def ensure_device_folder(self, device_id: int) -> int:
        """建/刷新设备文件夹：设备上架、改名后目录跟着更新。"""
        device_id = int(device_id)
        device = self.db.json(
            "SELECT JSON_OBJECT('name', device_name, 'siteId', CAST(COALESCE(site_id, 0) AS CHAR)) "
            f"FROM datacenter_device WHERE device_id = {device_id} LIMIT 1",
            None,
        )
        name = ""
        site_id = 0
        if isinstance(device, dict):
            name = str(device.get("name") or "")
            site_id = int(str(device.get("siteId") or 0) or 0)
        if site_id:
            self.ensure_site_folder(site_id)
        site_sql = "NULL" if not site_id else str(site_id)
        row = self.db.json(
            f"SELECT JSON_OBJECT('id', CAST(folder_id AS CHAR)) FROM file_folder "
            f"WHERE folder_type = 'device' AND device_id = {device_id} LIMIT 1",
            None,
        )
        if isinstance(row, dict) and row.get("id"):
            folder_id = int(row["id"])
            self.db.execute(
                "UPDATE file_folder SET site_id = " + site_sql
                + ", display_name = " + self.db.quote(name)
                + f" WHERE folder_id = {folder_id}"
            )
            return folder_id
        return self._insert(
            "INSERT INTO file_folder (folder_type, site_id, device_id, display_name) VALUES ('device', "
            + site_sql + f", {device_id}, {self.db.quote(name)})"
        )

    def sync_folders(self) -> dict:
        """为所有机房与设备补齐文件夹（幂等，打开文件库时调用一次）。"""
        sites = self._json_rows(
            "SELECT CAST(site_id AS CHAR) AS id FROM asset_site WHERE is_active = 1"
        )
        for row in sites:
            self.ensure_site_folder(int(row["id"]))
        devices = self._json_rows(
            "SELECT CAST(device_id AS CHAR) AS id FROM datacenter_device WHERE is_active = 1"
        )
        for row in devices:
            device_id = int(row["id"])
            exists = self.db.json(
                f"SELECT JSON_OBJECT('id', CAST(folder_id AS CHAR)) FROM file_folder WHERE folder_type = 'device' AND device_id = {device_id} LIMIT 1",
                None,
            )
            self.ensure_device_folder(device_id)
        return {"sites": len(sites), "devices": len(devices)}

    # ------------------------------------------------------------ 查询
    def _json_rows(self, sql: str) -> list:
        """逐行解析 JSON：既支持每行一个 JSON_OBJECT，也支持 JSON_ARRAYAGG 的数组。"""
        output = self.db.execute(sql)
        rows: list = []
        for line in str(output or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
            elif isinstance(value, list):
                rows.extend(value)
        return rows

    def tree(self, context: dict) -> dict:
        self.sync_folders()
        allowed = self.scope.scoped_company_ids(context)
        device_filter = ""
        if allowed is not None:
            if not allowed:
                device_filter = " AND 1 = 0"
            else:
                device_filter = " AND (d.company_id IN (" + ",".join(str(int(c)) for c in sorted(allowed)) + "))"
        sites = self._json_rows(
            """
            SELECT JSON_OBJECT(
              'id', CAST(s.site_id AS CHAR), 'name', s.site_name, 'type', s.site_type,
              'folderId', CAST(COALESCE(f.folder_id, 0) AS CHAR)
            )
            FROM asset_site s
            LEFT JOIN file_folder f ON f.folder_type = 'site' AND f.site_id = s.site_id
            WHERE s.is_active = 1
            ORDER BY s.site_type, s.site_name
            """
        )
        devices = self._json_rows(
            """
            SELECT JSON_OBJECT(
              'id', CAST(d.device_id AS CHAR), 'name', d.device_name, 'code', d.device_code,
              'siteId', CAST(COALESCE(d.site_id, 0) AS CHAR), 'status', d.status,
              'active', d.is_active,
              'folderId', CAST(COALESCE(f.folder_id, 0) AS CHAR),
              'fileCount', COALESCE((
                SELECT COUNT(*) FROM file_object o
                WHERE o.folder_id = f.folder_id AND o.is_current = 1 AND o.deleted_at IS NULL
              ), 0)
            )
            FROM datacenter_device d
            LEFT JOIN file_folder f ON f.folder_type = 'device' AND f.device_id = d.device_id
            WHERE 1 = 1""" + device_filter + """
            ORDER BY d.device_name
            """
        )
        return {"sites": sites, "devices": devices}

    def list_files(self, folder_id: int) -> dict:
        folder = self._folder(folder_id)
        rows = self._json_rows(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(file_id AS CHAR), 'name', file_name, 'size', size_bytes,
              'sha256', sha256, 'contentType', content_type, 'description', description,
              'version', version_no, 'isCurrent', is_current,
              'uploadedBy', uploaded_by, 'createdAt', DATE_FORMAT(created_at, '%Y-%m-%d %H:%i:%s'),
              'deletedAt', IFNULL(DATE_FORMAT(deleted_at, '%Y-%m-%d %H:%i:%s'), '')
            )
            FROM file_object WHERE folder_id = {int(folder_id)} AND deleted_at IS NULL
            ORDER BY is_current DESC, file_name, version_no DESC
            """
        )
        return {"folder": folder, "files": rows}

    def _folder(self, folder_id: int) -> dict:
        row = self.db.json(
            "SELECT JSON_OBJECT('id', CAST(folder_id AS CHAR), 'type', folder_type, "
            "'siteId', CAST(COALESCE(site_id, 0) AS CHAR), 'deviceId', CAST(COALESCE(device_id, 0) AS CHAR), "
            "'name', display_name) FROM file_folder WHERE folder_id = " + str(int(folder_id)) + " LIMIT 1",
            None,
        )
        if not isinstance(row, dict):
            raise self.api_error("文件夹不存在，请刷新后重试。")
        return row

    def events(self, folder_id: int) -> list:
        return self._json_rows(
            f"""
            SELECT JSON_OBJECT(
              'id', CAST(event_id AS CHAR), 'fileId', CAST(COALESCE(file_id, 0) AS CHAR),
              'action', action, 'actor', actor,
              'detail', IFNULL(detail, JSON_OBJECT()),
              'createdAt', DATE_FORMAT(created_at, '%Y-%m-%d %H:%i:%s')
            )
            FROM file_event WHERE folder_id = {int(folder_id)}
            ORDER BY created_at DESC, event_id DESC LIMIT 200
            """
        )

    # ------------------------------------------------------------ 上传
    def _absolute(self, rel_path: str) -> Path:
        target = (self.root / rel_path).resolve()
        root = self.root.resolve()
        if root not in target.parents and target != root:
            raise self.api_error("文件路径无效。")
        return target

    def _next_version(self, folder_id: int, file_name: str) -> int:
        row = self.db.json(
            "SELECT JSON_OBJECT('v', COALESCE(MAX(version_no), 0)) FROM file_object "
            f"WHERE folder_id = {int(folder_id)} AND file_name = {self.db.quote(file_name)}",
            None,
        )
        current = int(str((row or {}).get("v") or 0)) if isinstance(row, dict) else 0
        return current + 1

    def save_stream(self, context: dict, folder_id: int, file_name: str, description: str,
                    source, content_length: int, content_type: str) -> dict:
        """把请求体写入磁盘并登记元数据（流式，不占内存）。"""
        folder = self._folder(folder_id)
        clean_name = (file_name or "").strip().replace("\\", "/").split("/")[-1]
        if not clean_name:
            raise self.api_error("请提供文件名。")
        if len(clean_name) > 200:
            raise self.api_error("文件名过长（最多 200 字符）。")
        if content_length <= 0:
            raise self.api_error("文件内容为空。")
        if content_length > self.max_bytes:
            raise self.api_error(f"文件超过上限（{self.max_bytes // (1024 * 1024)}MB）。")

        version = self._next_version(folder_id, clean_name)
        device_id = int(str(folder.get("deviceId") or 0) or 0)
        site_id = int(str(folder.get("siteId") or 0) or 0)
        if folder.get("type") == "device" and device_id:
            # 设备可能在上架后才归属机房，这里以设备当前值为准
            fresh = self.db.json(
                "SELECT JSON_OBJECT('siteId', CAST(COALESCE(site_id, 0) AS CHAR)) "
                f"FROM datacenter_device WHERE device_id = {device_id} LIMIT 1",
                None,
            )
            if isinstance(fresh, dict):
                fresh_site = int(str(fresh.get("siteId") or 0) or 0)
                if fresh_site != site_id:
                    site_id = fresh_site
                    self.db.execute(
                        "UPDATE file_folder SET site_id = "
                        + ("NULL" if not site_id else str(site_id))
                        + f" WHERE folder_id = {int(folder_id)}"
                    )
        if folder.get("type") == "device":
            rel_dir = f"site-{site_id}/device-{device_id}" if site_id else f"device-{device_id}"
        else:
            rel_dir = f"site-{site_id}"
        stem = Path(clean_name).stem[:60]
        safe_stem = _SAFE_NAME.sub("_", stem) or "file"
        rel_path = f"{rel_dir}/{safe_stem}-v{version}{self._safe_extension(clean_name)}"
        target = self._absolute(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256()
        written = 0
        remaining = content_length
        with target.open("wb") as handle:
            while remaining > 0:
                chunk = source.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                written += len(chunk)
                remaining -= len(chunk)
        if written <= 0:
            target.unlink(missing_ok=True)
            raise self.api_error("文件内容为空。")

        self.db.execute(
            "UPDATE file_object SET is_current = 0 "
            f"WHERE folder_id = {int(folder_id)} AND file_name = {self.db.quote(clean_name)} AND is_current = 1"
        )
        actor = str(context.get("username") or "")
        file_id = self._insert(
            "INSERT INTO file_object (folder_id, file_name, stored_rel_path, size_bytes, sha256, "
            "content_type, description, version_no, is_current, uploaded_by) VALUES ("
            f"{int(folder_id)}, {self.db.quote(clean_name)}, {self.db.quote(rel_path)}, {written}, "
            f"{self.db.quote(digest.hexdigest())}, {self.db.quote(content_type[:100])}, "
            f"{self.db.quote(description[:500])}, {version}, 1, {self.db.quote(actor)})"
        )
        self._log_event(file_id, folder_id, "upload", actor,
                        {"name": clean_name, "version": version, "size": written})
        return {"id": file_id, "name": clean_name, "version": version, "size": written}

    def _log_event(self, file_id: int | None, folder_id: int | None, action: str, actor: str, detail: dict) -> None:
        self.db.execute(
            "INSERT INTO file_event (file_id, folder_id, action, actor, detail) VALUES ("
            f"{'NULL' if not file_id else int(file_id)}, {'NULL' if not folder_id else int(folder_id)}, "
            f"{self.db.quote(action)}, {self.db.quote(actor)}, {self.db.json_value(detail or {})})"
        )

    # ------------------------------------------------------------ 下载 / 改名 / 删除
    def download(self, file_id: int, context: dict) -> dict:
        row = self.db.json(
            "SELECT JSON_OBJECT('name', file_name, 'rel', stored_rel_path, 'type', content_type, "
            "'folderId', CAST(folder_id AS CHAR)) FROM file_object "
            f"WHERE file_id = {int(file_id)} AND deleted_at IS NULL LIMIT 1",
            None,
        )
        if not isinstance(row, dict):
            raise self.api_error("文件不存在或已删除。")
        path = self._absolute(str(row.get("rel") or ""))
        if not path.is_file():
            raise self.api_error("文件实体丢失，请联系管理员检查存储卷。")
        actor = str(context.get("username") or "")
        self._log_event(int(file_id), int(str(row.get("folderId") or 0) or 0) or None, "download", actor,
                        {"name": row.get("name")})
        return {"path": path, "name": str(row.get("name") or "download"), "contentType": str(row.get("type") or "")}

    def update_file(self, file_id: int, payload: dict, context: dict) -> dict:
        name = str(payload.get("name") or "").strip()
        description = payload.get("description")
        sets = []
        if name:
            clean = name.replace("\\", "/").split("/")[-1]
            sets.append("file_name = " + self.db.quote(clean))
        if description is not None:
            sets.append("description = " + self.db.quote(str(description)[:500]))
        if not sets:
            raise self.api_error("没有需要修改的内容。")
        folder = self.db.json(
            f"SELECT JSON_OBJECT('folderId', CAST(folder_id AS CHAR)) FROM file_object WHERE file_id = {int(file_id)} LIMIT 1",
            None,
        )
        folder_id = int(str((folder or {}).get("folderId") or 0) or 0) if isinstance(folder, dict) else 0
        self.db.execute("UPDATE file_object SET " + ", ".join(sets) + f" WHERE file_id = {int(file_id)}")
        self._log_event(int(file_id), folder_id or None, "rename", str(context.get("username") or ""), {"name": name})
        return {"ok": True}

    def delete_file(self, file_id: int, context: dict) -> dict:
        row = self.db.json(
            f"SELECT JSON_OBJECT('folderId', CAST(folder_id AS CHAR), 'name', file_name) FROM file_object WHERE file_id = {int(file_id)} LIMIT 1",
            None,
        )
        if not isinstance(row, dict):
            raise self.api_error("文件不存在。")
        actor = str(context.get("username") or "")
        self.db.execute(
            "UPDATE file_object SET deleted_at = NOW(), deleted_by = " + self.db.quote(actor)
            + f" WHERE file_id = {int(file_id)}"
        )
        self._log_event(int(file_id), int(str(row.get("folderId") or 0) or 0), "delete", actor,
                        {"name": row.get("name")})
        return {"ok": True}
