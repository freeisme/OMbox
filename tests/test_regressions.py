import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_asset.datacenter_devices import (  # noqa: E402  (ROOT must be importable first)
    CATEGORY_ALIASES,
    HEADER_ALIASES,
    STATUS_ALIASES,
    DatacenterDeviceService,
)
from office_asset.device_topology import layout_template_ports  # noqa: E402
from office_asset.xlsx import WorkbookError, read_sheet  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


server = load_module("office_asset_server_tests", ROOT / "server.py")
deploy_webhook = load_module(
    "office_asset_deploy_webhook_tests",
    ROOT / "deploy" / "gitea" / "deploy_webhook.py",
)
migration_runner = load_module(
    "office_asset_migration_runner_tests",
    ROOT / "tools" / "migration_runner.py",
)
next_version = load_module(
    "office_asset_next_version_tests",
    ROOT / "tools" / "next_version.py",
)


def empty_snapshot(revision: int = 1) -> dict:
    return {
        "stateRevision": revision,
        **{key: [] for key in server.STATE_ARRAY_KEYS},
    }


class StateValidationTests(TestCase):
    def test_state_snapshot_requires_all_arrays_and_positive_revision(self):
        with self.assertRaises(server.ApiError):
            server.validate_state_payload({})

        invalid_revision = empty_snapshot(0)
        with self.assertRaises(server.ApiError):
            server.validate_state_payload(invalid_revision)

        server.validate_state_payload(empty_snapshot())

    def test_generated_sync_sql_does_not_select_a_fixed_database(self):
        with mock.patch.object(server, "remap_existing_inventory_ids"):
            sql = server.build_sync_sql(empty_snapshot())

        self.assertNotIn("USE office_asset_mgmt", sql.upper())
        self.assertIn("START TRANSACTION;", sql)
        self.assertIn("INSERT INTO app_state_revision", sql)

    def test_employee_usage_items_carry_their_type_name(self):
        """人员名下的显示屏 / 非资产物资必须带 typeName。

        只下发 typeId 时，前端 `employeeUsageLabel` 只能退化成统一的「物资」标签，
        页面与 CSV 导出都会看不出这是什么类型的物资。
        """
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api" / "employees.ts").read_text(encoding="utf-8")

        monitors_block = source.split('employee["monitors"].append(', 1)[1][:900]
        non_asset_block = source.split('employee["nonAssetItems"].append(', 1)[1][:900]

        self.assertIn('"typeName"', monitors_block)
        self.assertIn('"typeName"', non_asset_block)
        self.assertIn("type_names.get(", monitors_block)
        self.assertIn("type_names.get(", non_asset_block)
        # 前端标签以 typeName 优先，兜底文案只在前端拿不到类型时出现
        self.assertIn("item.typeName", api)


class AuthenticationHardeningTests(TestCase):
    def test_password_length_limit_is_enforced_before_hashing(self):
        with self.assertRaises(server.ApiError):
            server.password_hash("x" * (server.PASSWORD_MAX_LENGTH + 1))

        self.assertFalse(
            server.verify_password("x" * (server.PASSWORD_MAX_LENGTH + 1), "not-a-hash")
        )

    def test_login_rate_limit_applies_to_ip_and_username(self):
        handler = SimpleNamespace(client_address=("198.51.100.10", 4321))
        original_limit = server.LOGIN_RATE_MAX_ATTEMPTS
        server.LOGIN_RATE_BUCKETS.clear()
        server.LOGIN_RATE_MAX_ATTEMPTS = 2
        try:
            server.enforce_login_rate_limit(handler, "qa_admin")
            server.enforce_login_rate_limit(handler, "qa_admin")
            with self.assertRaises(server.RateLimitError) as context:
                server.enforce_login_rate_limit(handler, "qa_admin")
            self.assertGreaterEqual(context.exception.retry_after, 1)
        finally:
            server.LOGIN_RATE_MAX_ATTEMPTS = original_limit
            server.LOGIN_RATE_BUCKETS.clear()

    def test_secure_cookie_clear_headers_match_secure_cookie_mode(self):
        original_secure = server.AUTH_COOKIE_SECURE
        server.AUTH_COOKIE_SECURE = True
        try:
            headers = server.clear_auth_cookie_headers()
        finally:
            server.AUTH_COOKIE_SECURE = original_secure

        self.assertEqual(2, len(headers))
        self.assertTrue(all("; Secure" in value for _, value in headers))


class ReleaseSelectionTests(TestCase):
    def test_only_annotated_releases_with_matching_notes_are_listed(self):
        current_sha = "a" * 40
        target_sha = "b" * 40
        tag_names = "\n".join(
            [
                "v1.0.0",
                "v1.1.0",
                "v1.2.0-rc.1",
                "v1.2.0",
                "v2.0.0",
            ]
        )
        annotated = {
            "v1.0.0": True,
            "v1.1.0": False,
            "v1.2.0-rc.1": True,
            "v1.2.0": True,
            "v2.0.0": True,
        }
        notes = {
            "v1.0.0": "初始版本说明",
            "v1.1.0": "轻量标签不应进入列表",
            "v1.2.0-rc.1": "预发布版本需要显式启用",
            "v1.2.0": "",
            "v2.0.0": "正式版本说明",
        }
        shas = {
            "v1.0.0": current_sha,
            "v1.1.0": "c" * 40,
            "v1.2.0-rc.1": "d" * 40,
            "v1.2.0": "e" * 40,
            "v2.0.0": target_sha,
        }

        with (
            mock.patch.object(deploy_webhook, "_git_output", return_value=tag_names),
            mock.patch.object(
                deploy_webhook,
                "_tag_is_annotated",
                side_effect=lambda tag: annotated[tag],
            ),
            mock.patch.object(
                deploy_webhook,
                "_release_notes_for_tag",
                side_effect=lambda tag: notes[tag],
            ),
            mock.patch.object(
                deploy_webhook,
                "_tag_commit_sha",
                side_effect=lambda tag: shas[tag],
            ),
            mock.patch.object(
                deploy_webhook,
                "_commit_details",
                return_value=("2026-08-06T00:00:00+08:00", "release"),
            ),
            mock.patch.object(
                deploy_webhook,
                "_is_ancestor",
                side_effect=lambda ancestor, descendant: ancestor == current_sha,
            ),
        ):
            versions, current, latest = deploy_webhook._available_versions(
                current_sha,
                "origin/main",
                "release",
            )

        self.assertEqual(["v2.0.0", "v1.0.0"], [item["version"] for item in versions])
        self.assertEqual("v1.0.0", current["version"])
        self.assertEqual("v2.0.0", latest["version"])
        self.assertTrue(versions[0]["isSelectable"])
        self.assertFalse(versions[1]["isSelectable"])
        self.assertEqual("正式版本说明", versions[0]["releaseNotes"])

    def test_release_channel_separates_stable_and_beta_versions(self):
        current_sha = "a" * 40
        stable_sha = "b" * 40
        beta_sha = "c" * 40
        tag_names = "\n".join(
            ["v1.2.2", "v1.2.3-alpha.1", "v1.2.3-beta.1", "v1.2.3"]
        )
        tag_shas = {
            "v1.2.2": current_sha,
            "v1.2.3-alpha.1": "d" * 40,
            "v1.2.3-beta.1": beta_sha,
            "v1.2.3": stable_sha,
        }

        with (
            mock.patch.object(deploy_webhook, "_git_output", return_value=tag_names),
            mock.patch.object(deploy_webhook, "_tag_is_annotated", return_value=True),
            mock.patch.object(deploy_webhook, "_release_notes_for_tag", return_value="版本说明"),
            mock.patch.object(
                deploy_webhook,
                "_tag_commit_sha",
                side_effect=lambda tag: tag_shas[tag],
            ),
            mock.patch.object(
                deploy_webhook,
                "_commit_details",
                return_value=("2026-08-13T00:00:00+08:00", "release"),
            ),
            mock.patch.object(
                deploy_webhook,
                "_is_ancestor",
                side_effect=lambda ancestor, descendant: ancestor == current_sha,
            ),
        ):
            release_versions, _, release_latest = deploy_webhook._available_versions(
                current_sha,
                "origin/main",
                "release",
            )
            beta_versions, _, beta_latest = deploy_webhook._available_versions(
                current_sha,
                "origin/main",
                "beta",
            )

        self.assertEqual(["v1.2.3", "v1.2.2"], [item["version"] for item in release_versions])
        self.assertEqual("v1.2.3", release_latest["version"])
        self.assertEqual(["v1.2.3-beta.1"], [item["version"] for item in beta_versions])
        self.assertEqual("v1.2.3-beta.1", beta_latest["version"])
        self.assertTrue(beta_versions[0]["isSelectable"])

    def test_invalid_release_channel_is_rejected(self):
        with self.assertRaises(server.ApiError):
            server.normalize_update_release_channel("nightly")
        with self.assertRaises(ValueError):
            deploy_webhook._normalize_release_channel("nightly")

    def test_repository_url_validation_accepts_github_and_internal_gitea(self):
        valid_urls = [
            "https://github.com/freeisme/OMbox.git",
            "ssh://git@192.0.2.10:2222/organization/office-asset-mgmt.git",
            "git@192.0.2.10:organization/office-asset-mgmt.git",
            "http://localhost:3001/example-org/office-asset-management.git",
        ]

        for repository_url in valid_urls:
            with self.subTest(repository_url=repository_url):
                self.assertEqual(
                    repository_url,
                    server.normalize_update_repository_url(repository_url),
                )
                self.assertEqual(
                    repository_url,
                    deploy_webhook._normalize_repository_url(repository_url),
                )

    def test_repository_url_validation_rejects_credentials_and_local_paths(self):
        invalid_urls = [
            "https://token@github.com/freeisme/OMbox.git",
            "https://user:token@github.com/freeisme/OMbox.git",
            "file:///etc/passwd",
            "ext::sh -c whoami",
            "https://github.com/freeisme/OMbox.git?token=secret",
            "http://github.com/freeisme/OMbox.git",
        ]

        for repository_url in invalid_urls:
            with self.subTest(repository_url=repository_url):
                with self.assertRaises(server.ApiError):
                    server.normalize_update_repository_url(repository_url)
                with self.assertRaises(deploy_webhook.InvalidRepositoryUrlError):
                    deploy_webhook._normalize_repository_url(repository_url)


class VersionGenerationTests(TestCase):
    def test_change_level_maps_patch_minor_and_major(self):
        self.assertEqual("patch", next_version.change_level(["fix: correct recovery"]))
        self.assertEqual("minor", next_version.change_level(["feat: split inventory batches"]))
        self.assertEqual(
            "major",
            next_version.change_level(["refactor!: replace allocation contract"]),
        )
        self.assertEqual(
            "major",
            next_version.change_level(["refactor: update API\n\nBREAKING CHANGE: yes"]),
        )

    def test_next_version_supports_explicit_release_level(self):
        with (
            mock.patch.object(
                next_version,
                "latest_stable_tag",
                return_value=("v2.0.0", (2, 0, 0)),
            ),
            mock.patch.object(next_version, "commit_messages", return_value=[]),
        ):
            self.assertEqual("v2.1.0", next_version.next_version(level="minor")["nextVersion"])
            self.assertEqual("v3.0.0", next_version.next_version(level="major")["nextVersion"])
            self.assertEqual("v2.0.1", next_version.next_version(level="patch")["nextVersion"])


class UpdateFetchTests(TestCase):
    def test_fetch_retries_transient_https_failure_and_syncs_release_tags(self):
        original_attempts = deploy_webhook.GIT_FETCH_ATTEMPTS
        original_retry_seconds = deploy_webhook.GIT_FETCH_RETRY_SECONDS
        transient_error = subprocess.CalledProcessError(
            128,
            ["git", "fetch"],
            stderr="fatal: Failure when receiving data from the peer",
        )
        try:
            deploy_webhook.GIT_FETCH_ATTEMPTS = 3
            deploy_webhook.GIT_FETCH_RETRY_SECONDS = 2
            with (
                mock.patch.object(
                    deploy_webhook.subprocess,
                    "run",
                    side_effect=[
                        transient_error,
                        subprocess.CompletedProcess(["git", "fetch"], 0),
                    ],
                ) as run,
                mock.patch.object(deploy_webhook.time, "sleep") as sleep,
            ):
                deploy_webhook._fetch_repository(
                    "https://github.com/freeisme/OMbox.git",
                    "refs/remotes/update-candidate/main",
                )
        finally:
            deploy_webhook.GIT_FETCH_ATTEMPTS = original_attempts
            deploy_webhook.GIT_FETCH_RETRY_SECONDS = original_retry_seconds

        self.assertEqual(2, run.call_count)
        command = run.call_args_list[0].args[0]
        self.assertIn("http.version=HTTP/1.1", command)
        self.assertIn("http.lowSpeedLimit=1", command)
        self.assertIn("http.lowSpeedTime=120", command)
        self.assertIn("+refs/tags/v*:refs/tags/v*", command)
        self.assertIn(
            "+refs/heads/main:refs/remotes/update-candidate/main",
            command,
        )
        sleep.assert_called_once_with(2)

    def test_fetch_does_not_retry_non_transient_failure(self):
        original_attempts = deploy_webhook.GIT_FETCH_ATTEMPTS
        non_transient_error = subprocess.CalledProcessError(
            128,
            ["git", "fetch"],
            stderr="fatal: repository access denied",
        )
        try:
            deploy_webhook.GIT_FETCH_ATTEMPTS = 3
            with (
                mock.patch.object(
                    deploy_webhook.subprocess,
                    "run",
                    side_effect=non_transient_error,
                ) as run,
                mock.patch.object(deploy_webhook.time, "sleep") as sleep,
            ):
                with self.assertRaises(deploy_webhook.RepositoryFetchError):
                    deploy_webhook._fetch_repository(
                        "https://github.com/freeisme/OMbox.git",
                        "refs/remotes/update-candidate/main",
                    )
        finally:
            deploy_webhook.GIT_FETCH_ATTEMPTS = original_attempts

        self.assertEqual(1, run.call_count)
        sleep.assert_not_called()

    def test_update_service_maps_repository_fetch_failure_to_readable_message(self):
        original_url = server.UPDATE_SERVICE_URL
        original_token = server.UPDATE_CONTROL_TOKEN
        try:
            server.UPDATE_SERVICE_URL = "https://update-service.example.test"
            server.UPDATE_CONTROL_TOKEN = "test-token"
            response = io.BytesIO(
                b'{"ok": false, "error": "repository_fetch_failed"}'
            )
            error = server.HTTPError(
                "https://update-service.example.test/control/status",
                503,
                "Service Unavailable",
                None,
                response,
            )
            with mock.patch.object(server, "urlopen", side_effect=error):
                with self.assertRaisesRegex(
                    server.ApiError,
                    "更新项目无法获取，请检查项目地址",
                ):
                    server.request_update_service()
        finally:
            server.UPDATE_SERVICE_URL = original_url
            server.UPDATE_CONTROL_TOKEN = original_token

    def test_local_gitea_http_repository_maps_to_configured_ssh_origin(self):
        original_http_origin = deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN
        original_ssh_origin = deploy_webhook.LOCAL_GITEA_SSH_ORIGIN
        try:
            deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN = "http://198.51.100.10:3001/"
            deploy_webhook.LOCAL_GITEA_SSH_ORIGIN = "ssh://git@198.51.100.10:2222/"
            self.assertEqual(
                "ssh://git@198.51.100.10:2222/example-org/office-asset-mgmt.git",
                deploy_webhook._fetch_remote_for_repository(
                    "http://198.51.100.10:3001/example-org/office-asset-mgmt.git"
                ),
            )
        finally:
            deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN = original_http_origin
            deploy_webhook.LOCAL_GITEA_SSH_ORIGIN = original_ssh_origin

    def test_local_gitea_mapping_does_not_apply_to_another_origin(self):
        original_http_origin = deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN
        original_ssh_origin = deploy_webhook.LOCAL_GITEA_SSH_ORIGIN
        try:
            deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN = "http://198.51.100.10:3001"
            deploy_webhook.LOCAL_GITEA_SSH_ORIGIN = "ssh://git@198.51.100.10:2222"
            repository_url = "http://198.51.100.11:3001/example-org/office-asset-mgmt.git"
            self.assertEqual(
                repository_url,
                deploy_webhook._fetch_remote_for_repository(repository_url),
            )
        finally:
            deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN = original_http_origin
            deploy_webhook.LOCAL_GITEA_SSH_ORIGIN = original_ssh_origin

    def test_local_gitea_mapping_requires_both_origins(self):
        original_http_origin = deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN
        original_ssh_origin = deploy_webhook.LOCAL_GITEA_SSH_ORIGIN
        try:
            deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN = "http://198.51.100.10:3001"
            deploy_webhook.LOCAL_GITEA_SSH_ORIGIN = ""
            with self.assertRaisesRegex(ValueError, "must be set together"):
                deploy_webhook._fetch_remote_for_repository(
                    "http://198.51.100.10:3001/example-org/office-asset-mgmt.git"
                )
        finally:
            deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN = original_http_origin
            deploy_webhook.LOCAL_GITEA_SSH_ORIGIN = original_ssh_origin

    def test_local_gitea_mapping_can_load_non_secret_origins_from_app_env_file(self):
        original_app_dir = deploy_webhook.APP_DIR
        original_environment = os.environ.get("DEPLOY_LOCAL_GITEA_HTTP_ORIGIN")
        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                env_path = Path(temporary_directory) / ".env"
                env_path.write_text(
                    "DEPLOY_LOCAL_GITEA_HTTP_ORIGIN=http://198.51.100.10:3001\n"
                    "DEPLOY_LOCAL_GITEA_SSH_ORIGIN=ssh://git@198.51.100.10:2222\n",
                    encoding="utf-8",
                )
                deploy_webhook.APP_DIR = Path(temporary_directory)
                os.environ.pop("DEPLOY_LOCAL_GITEA_HTTP_ORIGIN", None)
                self.assertEqual(
                    "http://198.51.100.10:3001",
                    deploy_webhook._deployment_setting("DEPLOY_LOCAL_GITEA_HTTP_ORIGIN"),
                )
                self.assertEqual(
                    "ssh://git@198.51.100.10:2222",
                    deploy_webhook._deployment_setting("DEPLOY_LOCAL_GITEA_SSH_ORIGIN"),
                )
        finally:
            deploy_webhook.APP_DIR = original_app_dir
            if original_environment is None:
                os.environ.pop("DEPLOY_LOCAL_GITEA_HTTP_ORIGIN", None)
            else:
                os.environ["DEPLOY_LOCAL_GITEA_HTTP_ORIGIN"] = original_environment

    def test_deployment_environment_passes_local_gitea_mapping_to_update_script(self):
        original_http_origin = deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN
        original_ssh_origin = deploy_webhook.LOCAL_GITEA_SSH_ORIGIN
        try:
            deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN = "http://198.51.100.10:3001"
            deploy_webhook.LOCAL_GITEA_SSH_ORIGIN = "ssh://git@198.51.100.10:2222"
            environment = deploy_webhook._deployment_environment(
                "a" * 40,
                "http://198.51.100.10:3001/example-org/office-asset-mgmt.git",
            )
        finally:
            deploy_webhook.LOCAL_GITEA_HTTP_ORIGIN = original_http_origin
            deploy_webhook.LOCAL_GITEA_SSH_ORIGIN = original_ssh_origin

        self.assertEqual("a" * 40, environment["DEPLOY_TARGET_SHA"])
        self.assertEqual(
            "http://198.51.100.10:3001/example-org/office-asset-mgmt.git",
            environment["DEPLOY_REPOSITORY_URL"],
        )
        self.assertEqual(
            "http://198.51.100.10:3001",
            environment["DEPLOY_LOCAL_GITEA_HTTP_ORIGIN"],
        )
        self.assertEqual(
            "ssh://git@198.51.100.10:2222",
            environment["DEPLOY_LOCAL_GITEA_SSH_ORIGIN"],
        )


class DeploymentScriptTests(TestCase):
    def test_repository_layout_has_canonical_paths_and_compatibility_entries(self):
        self.assertTrue((ROOT / "database" / "bootstrap").is_dir())
        self.assertTrue((ROOT / "database" / "migrations").is_dir())
        self.assertTrue((ROOT / "database" / "manual").is_dir())
        self.assertTrue((ROOT / "tools" / "migration_runner.py").is_file())
        self.assertTrue((ROOT / "scripts" / "windows" / "deploy.ps1").is_file())
        self.assertTrue((ROOT / "docs" / "README.md").is_file())

        runner = (ROOT / "tools" / "migration_runner.py").read_text(encoding="utf-8")
        self.assertIn('ROOT_DIR = Path(__file__).resolve().parents[1]', runner)
        self.assertIn('ROOT_DIR / "database" / "migrations"', runner)

        root_runner = (ROOT / "migration_runner.py").read_text(encoding="utf-8")
        root_deploy = (ROOT / "deploy.ps1").read_text(encoding="utf-8")
        windows_deploy = (ROOT / "scripts" / "windows" / "deploy.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("from tools.migration_runner import main", root_runner)
        self.assertIn('scripts\\windows\\deploy.ps1', root_deploy)
        self.assertIn('[Alias("DbName")][string]$Database', windows_deploy)
        self.assertNotIn('[Alias("DbName")][string]$DbName', windows_deploy)
        self.assertIn("$lastLine = $result | Select-Object -Last 1", windows_deploy)
        self.assertIn("if ($null -eq $lastLine)", windows_deploy)

    def test_backup_script_uses_atomic_private_output(self):
        script = (ROOT / "deploy" / "scripts" / "backup_database.sh").read_text(
            encoding="utf-8"
        )

        for option in ("--skip-lock-tables", "--no-tablespaces", "--hex-blob"):
            self.assertIn(option, script)
        self.assertIn("temporary_file=\"$(mktemp", script)
        self.assertIn('mv -- "${temporary_file}" "${backup_file}"', script)
        self.assertNotIn('> "${backup_file}"', script)

    def test_compose_backup_script_uses_deployment_user_home_and_atomic_output(self):
        script = (ROOT / "deploy" / "scripts" / "backup_compose_database.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('${HOME:-/tmp}/backups/office-asset-mgmt', script)
        self.assertIn('docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T db', script)
        self.assertIn('sql_temporary_file="$(mktemp', script)
        self.assertIn('gzip --stdout -- "${sql_temporary_file}" > "${archive_temporary_file}"', script)
        self.assertIn('sha256sum "${archive_temporary_file}" > "${checksum_temporary_file}"', script)
        self.assertIn('mv -- "${archive_temporary_file}" "${backup_file}"', script)
        self.assertIn('mv -- "${checksum_temporary_file}" "${checksum_file}"', script)

    def test_docker_initializer_does_not_put_root_password_in_arguments(self):
        script = (ROOT / "deploy" / "docker" / "init_database.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('export MYSQL_PWD="${MYSQL_ROOT_PASSWORD}"', script)
        self.assertNotIn('"--password=${MYSQL_ROOT_PASSWORD}"', script)
        self.assertIn("22_update_repository_setting.sql", script)

    def test_compose_healthcheck_keeps_mysql_password_out_of_arguments(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        docker_doc = (ROOT / "docs" / "deployment" / "docker.md").read_text(
            encoding="utf-8"
        )

        self.assertIn('MYSQL_PWD=\\"$$MYSQL_PASSWORD\\" mysql', compose)
        self.assertNotIn('-p"$$MYSQL_PASSWORD"', compose)
        self.assertNotIn('-p"$MYSQL_PASSWORD"', docker_doc)

    def test_security_migration_adds_session_provenance_columns(self):
        migration = (
            ROOT / "database" / "bootstrap" / "21_security_hardening.sql"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn("ADD COLUMN ip_address VARCHAR(64)", migration)
        self.assertIn("ADD COLUMN user_agent VARCHAR(500)", migration)

    def test_legacy_security_compatibility_migration_is_first_and_idempotent(self):
        migration_path = (
            ROOT
            / "database"
            / "migrations"
            / "20260813_001_legacy_security_compatibility.sql"
        )
        migration = migration_path.read_text(encoding="utf-8")
        discovered = migration_runner.discover_migrations()

        self.assertEqual(migration_path, discovered[0].path)
        self.assertIn("CREATE TABLE IF NOT EXISTS auth_bootstrap_guard", migration)
        self.assertIn("ADD COLUMN ip_address VARCHAR(64)", migration)
        self.assertIn("ADD COLUMN user_agent VARCHAR(500)", migration)
        self.assertIn("table_name = 'auth_session') = 1", migration)

    def test_update_repository_setting_migration_exists(self):
        migration = (
            ROOT / "database" / "bootstrap" / "22_update_repository_setting.sql"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn("update_repository_url", migration)
        self.assertIn("ON DUPLICATE KEY UPDATE", migration)

    def test_update_script_can_fetch_selected_repository_url(self):
        script = (ROOT / "deploy" / "scripts" / "update_from_gitea.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("DEPLOY_REPOSITORY_URL", script)
        self.assertIn("DEPLOY_LOCAL_GITEA_HTTP_ORIGIN", script)
        self.assertIn("DEPLOY_LOCAL_GITEA_SSH_ORIGIN", script)
        self.assertIn("fetch_repository()", script)
        self.assertIn("fetch_remote_for_repository()", script)
        self.assertIn("http.version=HTTP/1.1", script)
        self.assertIn("http.lowSpeedLimit=1", script)
        self.assertIn("http.lowSpeedTime=120", script)
        self.assertIn('"+refs/tags/v*:refs/tags/v*"', script)
        self.assertIn("DEPLOY_GIT_FETCH_ATTEMPTS", script)
        self.assertIn("DEPLOY_GIT_FETCH_RETRY_SECONDS", script)
        self.assertIn('build --pull app migrate', script)
        self.assertIn('up -d --wait --no-deps db', script)
        self.assertIn('stop app || true', script)
        self.assertIn('run --rm --no-deps -T migrate', script)
        self.assertIn('up -d --no-deps --remove-orphans app', script)
        self.assertNotIn('docker compose "${compose_args[@]}" up -d --remove-orphans', script)


class MigrationBaselineTests(TestCase):
    def test_existing_database_requires_explicit_baseline_adoption(self):
        with (
            mock.patch.object(migration_runner, "table_exists", return_value=False),
            mock.patch.object(migration_runner, "has_existing_business_tables", return_value=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "schema_migration registry"):
                migration_runner.prepare_migration_registry("office_asset_mgmt")

    def test_baseline_adoption_validates_legacy_schema_before_writing_registry(self):
        with (
            mock.patch.object(migration_runner, "table_exists", return_value=False),
            mock.patch.object(migration_runner, "has_existing_business_tables", return_value=True),
            mock.patch.object(
                migration_runner,
                "missing_tables",
                return_value=["auth_session"],
            ),
            mock.patch.object(migration_runner, "ensure_registry") as ensure_registry,
            mock.patch.object(migration_runner, "mark_baseline") as mark_baseline,
        ):
            with self.assertRaisesRegex(RuntimeError, "missing required tables"):
                migration_runner.prepare_migration_registry(
                    "office_asset_mgmt",
                    migration_runner.LEGACY_BASELINE_VERSION,
                )
            ensure_registry.assert_not_called()
            mark_baseline.assert_not_called()

    def test_legacy_baseline_does_not_require_compatible_security_guard(self):
        self.assertIn("auth_session", migration_runner.LEGACY_BASELINE_REQUIRED_TABLES)
        self.assertNotIn(
            "auth_bootstrap_guard",
            migration_runner.LEGACY_BASELINE_REQUIRED_TABLES,
        )

    def test_baseline_adoption_records_only_verified_legacy_baseline(self):
        with (
            mock.patch.object(migration_runner, "table_exists", return_value=False),
            mock.patch.object(migration_runner, "has_existing_business_tables", return_value=True),
            mock.patch.object(migration_runner, "missing_tables", return_value=[]),
            mock.patch.object(migration_runner, "ensure_registry") as ensure_registry,
            mock.patch.object(migration_runner, "mark_baseline") as mark_baseline,
        ):
            migration_runner.prepare_migration_registry(
                "office_asset_mgmt",
                migration_runner.LEGACY_BASELINE_VERSION,
            )

        ensure_registry.assert_called_once_with("office_asset_mgmt")
        mark_baseline.assert_called_once_with(
            "office_asset_mgmt",
            migration_runner.LEGACY_BASELINE_VERSION,
        )

    def test_only_the_known_legacy_baseline_can_be_adopted(self):
        with self.assertRaisesRegex(RuntimeError, "Unsupported baseline"):
            migration_runner.validate_legacy_baseline(
                "office_asset_mgmt",
                "legacy-unknown",
            )

    def test_version_notes_use_semver_headings(self):
        notes = (ROOT / "VERSION_NOTES.md").read_text(encoding="utf-8")
        headings = re.findall(r"^## (v\S+)$", notes, flags=re.MULTILINE)

        self.assertTrue(headings)
        self.assertTrue(
            all(
                re.fullmatch(
                    r"v\d+\.\d+\.\d+(?:-beta\.(?:0|[1-9]\d*))?",
                    item,
                )
                for item in headings
            )
        )

    def test_update_panel_has_release_channel_and_motion_support(self):
        settings_api = (ROOT / "frontend" / "src" / "api" / "settings.ts").read_text(
            encoding="utf-8"
        )
        settings_view = (ROOT / "frontend" / "src" / "views" / "SettingsView.vue").read_text(
            encoding="utf-8"
        )
        tokens = (ROOT / "frontend" / "src" / "styles" / "tokens.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('DEFAULT_UPDATE_RELEASE_CHANNEL = "beta"', settings_api)
        self.assertIn("releaseChannel", settings_api)
        self.assertIn("updateReleaseChannel", settings_view)
        # 换页动效只作用于页面容器，并尊重系统"减少动效"设置
        self.assertIn("oa-page-enter", tokens)
        self.assertIn("prefers-reduced-motion", tokens)


class FrontendLegacyRemovalTests(TestCase):
    """旧前端（web/app.js、web/styles.css、web/index.html 与 /legacy/ 桥接）已整体下线。"""

    def test_legacy_frontend_bundle_is_removed(self):
        for name in ("app.js", "styles.css", "index.html"):
            self.assertFalse(
                (ROOT / "web" / name).exists(),
                f"旧前端文件 web/{name} 应已随 SPA 迁移删除",
            )

    def test_server_no_longer_serves_a_legacy_frontend(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")

        self.assertNotIn("LEGACY_PREFIX", source)
        self.assertNotIn("legacy_frame", source)
        self.assertNotIn("_legacy_request", source)
        self.assertIn('self.send_header("X-Frame-Options", "DENY")', source)

    def test_vue_sources_no_longer_reference_the_legacy_bridge(self):
        sources = [
            path
            for path in (ROOT / "frontend" / "src").rglob("*")
            if path.suffix in {".ts", ".vue"}
        ]
        self.assertTrue(sources)
        joined = "\n".join(path.read_text(encoding="utf-8") for path in sources)

        for token in ("legacyBridge", "LegacyFrame", "LegacyPage", "oaLegacy", "applyLegacyAccent"):
            self.assertNotIn(token, joined, f"{token} 仍被引用，旧前端桥接未清理干净")

    def test_session_expiry_redirects_to_login(self):
        """接口返回 401 时必须清会话并回到登录页，而不是停在"看起来已登录"的页面。"""
        client = (ROOT / "frontend" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
        main = (ROOT / "frontend" / "src" / "main.ts").read_text(encoding="utf-8")

        self.assertIn("setUnauthorizedHandler", client)
        self.assertIn("response.status === 401", client)
        self.assertIn("setUnauthorizedHandler(", main)
        self.assertIn("expireSession()", main)
        self.assertIn('path: "/login"', main)

    def test_sidebar_menu_is_themed_through_element_plus_variables(self):
        """深色侧栏必须用 Element Plus 菜单自己的变量着色。

        Element Plus 的组件样式按需加载、排在 app.css 之后，同权重会盖掉
        `.oa-nav { background: transparent }` 这类覆盖——之前正是这样把侧栏菜单
        变成了白底灰字。改成写变量后与加载顺序无关。
        """
        styles = (ROOT / "frontend" / "src" / "styles" / "app.css").read_text(encoding="utf-8")

        for variable in (
            "--el-menu-bg-color: transparent;",
            "--el-menu-text-color: #d3dce6;",
            "--el-menu-hover-bg-color: rgba(255, 255, 255, 0.08);",
            "--el-menu-active-color: #ffffff;",
            "--el-menu-item-height: 40px;",
        ):
            self.assertIn(variable, styles, f"侧栏菜单变量缺失：{variable}")
        # 选中项底色 Element Plus 不提供变量，这条必须带 .oa-rail 前缀提高权重
        self.assertIn(".oa-rail .oa-nav .el-menu-item.is-active {", styles)


class EmployeeWorkflowUiTests(TestCase):
    def test_employee_editor_does_not_collect_offboarding_details(self):
        view = (ROOT / "frontend" / "src" / "views" / "EmployeesView.vue").read_text(
            encoding="utf-8"
        )
        left_view = (ROOT / "frontend" / "src" / "views" / "LeftEmployeesView.vue").read_text(
            encoding="utf-8"
        )
        # 新增/编辑人员只维护在职/停用/公用，离职信息由独立的离职弹窗收集
        editor = view.split('v-model="formVisible"', 1)[1].split('v-model="offboardVisible"', 1)[0]

        self.assertIn('<el-option label="在职" value="active" />', editor)
        self.assertIn('<el-option label="停用" value="inactive" />', editor)
        self.assertIn('<el-option label="公用" value="shared" />', editor)
        for field in ("leaveDate", "leaveReason", "leaveRemark", "leaveInfo"):
            self.assertNotIn(field, editor, f"人员编辑表单不应收集离职字段 {field}")
        self.assertIn('v-model="offboardVisible"', view)
        self.assertIn("离职时设备快照", left_view)

    def test_employee_offboarding_is_an_independent_backend_command(self):
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        server_source = (ROOT / "server.py").read_text(encoding="utf-8")

        self.assertIn("/api/employees/", router)
        self.assertIn("/offboard", router)
        self.assertIn('self._write_context(handler, "employees", "update")', router)
        self.assertIn("offboard_employee", router)

        self.assertIn("def offboard_employee(", service)
        self.assertIn('"recover": "回收"', service)
        self.assertIn("办理离职需要使用人员的全部数据或所属部门数据权限。", service)
        self.assertIn("left_employee_archive", service)
        self.assertIn("UPDATE auth_session session", service)
        self.assertIn("SET employee_id = NULL", service)
        self.assertIn("service_notification", service)
        self.assertIn("employee_offboarded", service)
        self.assertIn("api_idempotency_key", service)
        self.assertIn('"employee_offboarded": "办理离职"', server_source)

    def test_employee_offboarding_requires_complete_item_handling(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "EmployeesView.vue").read_text(
            encoding="utf-8"
        )

        self.assertIn("离职日期、离职原因和备注不能为空。", service)
        self.assertIn("当前名下资产或物资必须逐项处理后才能办理离职。", service)
        self.assertIn("异常待处理必须填写说明。", service)
        self.assertIn("转交他人时必须选择接收人员。", service)
        self.assertIn("离职资产只能转交给在职人员或公用人员。", service)
        self.assertIn("离职办理异常待处理", service)
        self.assertIn("离职办理转交给", service)
        self.assertIn("离职办理回收入库", service)
        self.assertIn("current_keys != submitted_key_set", service)
        self.assertIn("@current_item_count = {len(plan)}", service)
        self.assertIn("_recovery_catalog_sql", service)
        self.assertIn("trigger_action", service)
        # 前端逐项处理：接收人、处理说明与异常必填校验都在 Vue 离职弹窗里
        self.assertIn("targetEmployeeId", view)
        self.assertIn("异常待处理必须填写说明。", view)


class FlowRecordUiTests(TestCase):
    def test_flow_page_has_filters_export_classification_and_inline_notes(self):
        view = (ROOT / "frontend" / "src" / "views" / "FlowControlView.vue").read_text(
            encoding="utf-8"
        )
        flows = (ROOT / "frontend" / "src" / "api" / "flows.ts").read_text(encoding="utf-8")

        self.assertIn('title="物资流转记录"', view)
        self.assertIn("导出当前结果", view)
        self.assertIn("修正流转备注", view)
        self.assertIn("库存影响", view)
        self.assertIn("/note-corrections", flows)
        self.assertIn("correctionReason", flows)
        # 业务动作码 → 中文分类，避免列表里出现英文原始码
        self.assertIn('return: { label: "归还回收", category: "归还回收"', flows)
        self.assertIn('category: "库存入库"', flows)
        self.assertIn('category: "领用发放"', flows)
        self.assertIn('category: "归还回收"', flows)
        self.assertNotIn("登记物资调动", view)

    def test_movement_note_corrections_are_append_only_and_audited(self):
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        state_reader = (ROOT / "server.py").read_text(encoding="utf-8")

        self.assertIn("/api/inventory/movement-logs/", router)
        self.assertIn("/note-corrections", router)
        self.assertIn("add_inventory_movement_note_correction", service)
        self.assertIn("START TRANSACTION", service)
        self.assertIn("inventory_movement_note_correction", service)
        self.assertIn("inventory_movement_note_corrected", service)
        self.assertNotIn("UPDATE inventory_movement_log SET note", service)
        self.assertIn("'originalNote'", state_reader)
        self.assertIn("'effectiveNote'", state_reader)
        self.assertIn("'noteCorrections'", state_reader)


class DataQualityRegressionTests(TestCase):
    def test_quality_outputs_are_chinese_and_resolution_requires_a_result(self):
        operations = (ROOT / "office_asset" / "operations.py").read_text(encoding="utf-8")
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "GovernanceView.vue").read_text(
            encoding="utf-8"
        )

        self.assertIn('"high": "高"', operations)
        self.assertIn('"computer": "办公终端"', operations)
        self.assertIn('"resolved": "已解决"', operations)
        self.assertIn("请填写处理结果后再解决问题。", operations)
        self.assertIn("resolution_result", operations)
        self.assertIn("data_quality_issue_resolved", operations)
        self.assertIn('self._write_context(handler, "quality", "approve")', router)
        # 解决弹窗必须收集处理结果，前端与后端校验保持一致
        self.assertIn("resolveForm.resolutionResult", view)
        self.assertIn("请填写处理结果。", view)

    def test_quality_resolution_migration_is_retry_safe(self):
        migration = (
            ROOT
            / "database"
            / "migrations"
            / "20260827_001_flow_note_corrections_and_quality_resolution.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS inventory_movement_note_correction", migration)
        self.assertIn("information_schema.columns", migration)
        self.assertIn("resolution_result", migration)


class InventoryRecoveryRegressionTests(TestCase):
    def test_inventory_model_identity_is_used_for_allocations_and_recovery(self):
        bootstrap = (
            ROOT / "database" / "bootstrap" / "01_schema.sql"
        ).read_text(encoding="utf-8")
        compatibility_migration = (
            ROOT
            / "database"
            / "migrations"
            / "20260907_000_usage_inventory_model_identity_compatibility.sql"
        ).read_text(encoding="utf-8")
        migration = (
            ROOT
            / "database"
            / "migrations"
            / "20260907_001_usage_inventory_model_identity.sql"
        ).read_text(encoding="utf-8")
        individual_usage_migration = (
            ROOT
            / "database"
            / "migrations"
            / "20260909_001_individual_inventory_usage_records.sql"
        ).read_text(encoding="utf-8")
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        allocation_source = service.split("    def allocate_inventory(", 1)[1].split(
            "\n    def adjust_inventory(",
            1,
        )[0]
        offboard_source = service.split("    def offboard_employee(", 1)[1]

        self.assertIn("inventory_model_key", bootstrap)
        self.assertIn("GENERATED ALWAYS AS (COALESCE(inventory_model_id, 0)) VIRTUAL", bootstrap)
        self.assertIn("KEY idx_non_asset_usage_item_model", bootstrap)
        self.assertIn("KEY idx_employee_monitor_model", bootstrap)
        self.assertNotIn("UNIQUE KEY uq_non_asset_usage_item_model", bootstrap)
        self.assertNotIn("UNIQUE KEY uq_employee_monitor_model", bootstrap)
        self.assertIn("GENERATED ALWAYS AS (COALESCE(inventory_model_id, 0)) VIRTUAL", compatibility_migration)
        self.assertTrue(
            (
                ROOT
                / "database"
                / "migrations"
                / "20260907_000_usage_inventory_model_identity_compatibility.sql"
            ).is_file()
        )
        self.assertIn("ADD COLUMN inventory_model_key", migration)
        self.assertIn("ADD UNIQUE KEY uq_non_asset_usage_item_model", migration)
        self.assertIn("ADD UNIQUE KEY uq_employee_monitor_model", migration)
        discovered_versions = [item.version for item in migration_runner.discover_migrations()]
        self.assertLess(
            discovered_versions.index("20260907_000_usage_inventory_model_identity_compatibility"),
            discovered_versions.index("20260907_001_usage_inventory_model_identity"),
        )
        self.assertLess(
            migration.index("ADD UNIQUE KEY uq_non_asset_usage_item_model"),
            migration.index("DROP INDEX uq_non_asset_usage_item"),
        )
        self.assertLess(
            migration.index("ADD UNIQUE KEY uq_employee_monitor_model"),
            migration.index("DROP INDEX uq_employee_monitor"),
        )
        self.assertIn("DROP INDEX uq_non_asset_usage_item_model", individual_usage_migration)
        self.assertIn("DROP INDEX uq_employee_monitor_model", individual_usage_migration)
        self.assertIn("ADD KEY idx_non_asset_usage_item_model", individual_usage_migration)
        self.assertIn("ADD KEY idx_employee_monitor_model", individual_usage_migration)
        self.assertLess(
            discovered_versions.index("20260907_001_usage_inventory_model_identity"),
            discovered_versions.index("20260909_001_individual_inventory_usage_records"),
        )
        self.assertIn('model_id_sql = "NULL"', allocation_source)
        self.assertNotIn("quantity = quantity + 1", allocation_source)
        self.assertNotIn("quantity = quantity + VALUES(quantity)", allocation_source)
        self.assertIn(
            "SET @usage_ref = IF(@stock_updated = 1, LAST_INSERT_ID(), 0);",
            allocation_source,
        )
        self.assertIn("allocation_groups: dict[int, dict[str, int]]", offboard_source)
        self.assertIn("inventory_model_id <=> {group_model_id_sql}", offboard_source)
        # 回收统一走单一路径：解析（必要时新建）库存型号后按使用记录数量入库。
        self.assertIn("@recovery_model_id", offboard_source)
        self.assertIn("AND @recovery_model_id > 0", offboard_source)
        self.assertIn("_recovery_catalog_sql", offboard_source)
        self.assertNotIn("@allocation_recovery_quantity", offboard_source)
        self.assertNotIn("显示屏品牌型号重复", server_source := (ROOT / "server.py").read_text(encoding="utf-8"))
        self.assertNotIn("非资产设备品牌型号重复", server_source)

    def test_register_without_deduction_honors_json_false(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        allocation_source = service.split("    def allocate_inventory(", 1)[1].split(
            "\n    def adjust_inventory(",
            1,
        )[0]

        self.assertIn('stock_adjusted = parse_bool(payload.get("stockAdjusted"), True)', allocation_source)
        self.assertIn('if stock_adjusted:\n                raise self.api_error("Inventory deduction requires a registered inventory model.")', allocation_source)
        self.assertIn('model_id_sql = "NULL"', allocation_source)
        self.assertIn('if model_id > 0:', allocation_source)
        self.assertIn('if allocation_type == "monitor":', allocation_source)
        self.assertNotIn('self.db.text(payload.get("stockAdjusted"))', allocation_source)
        self.assertFalse(server.parse_bool(False, True))
        self.assertTrue(server.parse_bool(None, True))

    def test_custom_inventory_registration_keeps_fallback_brand_and_model_names(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        return_source = service.split("    def return_inventory(", 1)[1].split(
            "\n    def return_usage_inventory(",
            1,
        )[0]
        usage_source = service.split("    def return_usage_inventory(", 1)[1].split(
            "\n    def list_allocations(",
            1,
        )[0]
        list_source = service.split("    def list_allocations(", 1)[1].split(
            "\n    def _sql_id_list(",
            1,
        )[0]

        self.assertIn("monitor_usage.display_name", return_source)
        self.assertIn("non_asset_usage.brand", return_source)
        self.assertIn("usage_row.display_name", usage_source)
        self.assertIn("usage_row.model", usage_source)
        self.assertIn("monitor_usage.display_name", list_source)
        self.assertIn("non_asset_usage.brand", list_source)

    def test_inventory_operations_use_scoped_default_warehouses(self):
        view = (ROOT / "frontend" / "src" / "views" / "EmployeesView.vue").read_text(
            encoding="utf-8"
        )
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        allocation_return = service.split("    def return_inventory(", 1)[1].split(
            "\n    def return_usage_inventory(",
            1,
        )[0]
        legacy_return = service.split("    def return_usage_inventory(", 1)[1].split(
            "\n    def list_allocations(",
            1,
        )[0]
        offboard_normalization = service.split("    def _normalize_offboarding_plan(", 1)[1].split(
            "\n    def offboard_employee(",
            1,
        )[0]

        # 回收必须显式选择目标仓库，前端下拉里不再预选任何仓库
        self.assertIn('placeholder="回收目标仓库"', view)
        self.assertIn('preferred_org_id=employee.get("orgId")', service)
        self.assertIn("preferred_org_id=self._actor_org_id(context)", allocation_return)
        self.assertIn("preferred_org_id=self._actor_org_id(context)", legacy_return)
        self.assertIn("require_explicit=True", offboard_normalization)
        self.assertIn("选择回收时必须指定回收目标仓库。", offboard_normalization)
        self.assertIn("Every recovery must name its destination warehouse", offboard_normalization)
        self.assertIn(
            "ON DUPLICATE KEY UPDATE quantity = inventory_warehouse_stock.quantity",
            allocation_return,
        )
        self.assertIn(
            "ON DUPLICATE KEY UPDATE quantity = inventory_warehouse_stock.quantity",
            legacy_return,
        )

    def test_computer_registration_has_custom_and_warehouse_modes(self):
        view = (ROOT / "frontend" / "src" / "views" / "ComputersView.vue").read_text(
            encoding="utf-8"
        )
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")

        self.assertIn("自定义登记", view)
        self.assertIn("从库存登记", view)
        self.assertIn("registrationMode", view)
        self.assertIn('registration_mode == "warehouse"', service)
        self.assertIn("The selected warehouse does not have enough inventory.", service)
        self.assertIn("inventory_stock_adjusted", service)
        self.assertIn("inventoryStockAdjusted", service)
        self.assertIn('preferred_org_id=employee.get("orgId")', service)

    def test_legacy_usage_return_has_compatibility_route_and_transactional_guards(self):
        employees = (ROOT / "frontend" / "src" / "api" / "employees.ts").read_text(
            encoding="utf-8"
        )
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")

        self.assertIn("/api/inventory/usage/", employees)
        self.assertIn('if path.startswith("/api/inventory/usage/")', router)
        self.assertIn("len(parts) != 7", router)
        self.assertIn("def return_usage_inventory(", service)
        self.assertIn("START TRANSACTION;", service)
        self.assertIn("ORDER BY allocation_id DESC", service)
        self.assertIn("LIMIT 1", service)
        self.assertIn("FOR UPDATE;", service)
        self.assertIn("Legacy usage reconciled during return.", service)

    def test_inventory_returns_do_not_write_zero_quantity_usage_rows(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        allocation_return = service.split("    def return_inventory(", 1)[1].split(
            "\n    def return_usage_inventory(",
            1,
        )[0]
        legacy_return = service.split("    def return_usage_inventory(", 1)[1].split(
            "\n    def list_allocations(",
            1,
        )[0]

        self.assertIn("SET @usage_quantity = 0;", allocation_return)
        self.assertIn("AND quantity > {quantity}", allocation_return)
        self.assertIn("AND quantity = {quantity}", allocation_return)
        self.assertNotIn("SET quantity = quantity - @usage_quantity", legacy_return)
        self.assertIn("DELETE FROM {usage_table}", legacy_return)
        self.assertIn("AND quantity = @usage_quantity", legacy_return)


class ScrapManagementRegressionTests(TestCase):
    def test_scrap_migration_is_incremental_and_never_destroys_history(self):
        migration = (
            ROOT / "database" / "migrations" / "20260915_001_scrap_management.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS scrap_reason", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS inventory_scrap_record", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS asset_scrap_record", migration)
        self.assertIn("information_schema.columns", migration)
        self.assertIn("information_schema.table_constraints", migration)
        self.assertIn("ADD COLUMN is_archived TINYINT(1) NOT NULL DEFAULT 0", migration)
        self.assertIn("CHECK (status IN ('active', 'returned', 'cancelled', 'scrapped'))", migration)
        self.assertIn("'scrap_management', '报废管理'", migration)
        self.assertIn("INSERT INTO auth_role_permission", migration)
        self.assertNotIn("DROP TABLE", migration.upper())
        self.assertNotIn("DROP COLUMN is_active", migration.upper())
        self.assertNotIn("DELETE FROM employee_monitor_usage", migration)
        self.assertNotIn("DELETE FROM employee_non_asset_usage", migration)
        self.assertNotIn("DELETE FROM computer_asset", migration)

    def test_scrap_routes_require_dedicated_permissions_and_commands(self):
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")

        self.assertIn('path.endswith("/scrap") and method == "POST"', router)
        self.assertIn('self._write_context(handler, "scrap_management", "create")', router)
        self.assertIn('self.deps.require_permission(context, "inventory_operations", "view")', router)
        self.assertIn('self.deps.require_permission(context, "it_assets", "view")', router)
        self.assertIn('path == "/api/scrap-records" and method == "GET"', router)
        self.assertIn('path.startswith("/api/scrap-records/") and method == "GET"', router)
        self.assertIn('path == "/api/scrap-reasons" and method == "GET"', router)
        self.assertIn('self._read_context(handler, "scrap_management")', router)
        self.assertIn("self.assets.scrap_inventory_usage(", router)
        self.assertIn("self.assets.scrap_computer(", router)

    def test_inventory_scrap_never_restores_stock_and_keeps_the_usage_row(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        inventory_scrap = service.split("    def scrap_inventory_usage(", 1)[1].split(
            "\n    def scrap_computer(",
            1,
        )[0]

        self.assertIn("START TRANSACTION;", inventory_scrap)
        self.assertIn("FOR UPDATE;", inventory_scrap)
        self.assertIn("SET @scrap_allowed = IF(", inventory_scrap)
        self.assertIn("SET is_active = 0", inventory_scrap)
        self.assertIn("SET status = 'scrapped'", inventory_scrap)
        self.assertIn("INSERT INTO inventory_scrap_record", inventory_scrap)
        self.assertIn("inventory_scrapped", inventory_scrap)
        self.assertIn('self._store_idempotency_result("inventory.scrap"', inventory_scrap)
        # 报废不得回补库存：不允许增加型号或仓库库存，也不允许删除使用记录。
        self.assertNotIn("quantity = quantity +", inventory_scrap)
        self.assertNotIn("DELETE FROM {usage_table}", inventory_scrap)
        self.assertNotIn("inventory_movement_log", inventory_scrap)

    def test_computer_scrap_retires_archives_and_snapshots_the_asset(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        computer_scrap = service.split("    def scrap_computer(", 1)[1].split(
            "\n    def _inventory_scrap_rows(",
            1,
        )[0]

        self.assertIn("START TRANSACTION;", computer_scrap)
        self.assertIn("FOR UPDATE;", computer_scrap)
        self.assertIn("it_asset_status = 'retired'", computer_scrap)
        self.assertIn("is_archived = 1", computer_scrap)
        self.assertIn("archived_at = CURRENT_TIMESTAMP", computer_scrap)
        self.assertIn("assignment_status = 'returned'", computer_scrap)
        self.assertIn("INSERT INTO asset_scrap_record", computer_scrap)
        self.assertIn("'Computer scrap'", computer_scrap)
        self.assertIn("computer_scrapped", computer_scrap)
        self.assertIn('self._store_idempotency_result("computer.scrap"', computer_scrap)
        self.assertNotIn("quantity = quantity +", computer_scrap)
        self.assertNotIn("DELETE FROM computer_asset", computer_scrap)

    def test_archived_computers_leave_the_ledger_but_keep_their_records(self):
        state_reader = (ROOT / "server.py").read_text(encoding="utf-8")
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")

        self.assertIn("AND ca.is_archived = 0", state_reader)
        self.assertIn("AND asset.is_archived = 0", service)
        self.assertIn("'scrap_reason', 'inventory_scrap_record', 'asset_scrap_record', ", state_reader)
        self.assertIn("required_table_count = 70", state_reader)

    def test_frontend_exposes_scrap_actions_and_records_page(self):
        scrap_view = (ROOT / "frontend" / "src" / "views" / "ScrapRecordsView.vue").read_text(
            encoding="utf-8"
        )
        computers_view = (ROOT / "frontend" / "src" / "views" / "ComputersView.vue").read_text(
            encoding="utf-8"
        )
        navigation = (ROOT / "frontend" / "src" / "navigation.ts").read_text(encoding="utf-8")

        # 办公终端发起报废，并受报废管理权限控制
        self.assertIn("hasPermission('scrap_management', 'create')", computers_view)
        self.assertIn('title="报废登记"', computers_view)
        # 报废记录页提供筛选、导出与详情
        self.assertIn('title="报废记录"', scrap_view)
        self.assertIn("导出当前结果", scrap_view)
        self.assertIn("报废记录详情", scrap_view)
        self.assertIn("库存影响", scrap_view)
        self.assertIn('page: "scrapRecords"', navigation)
        self.assertIn('modules: ["scrap_management"]', navigation)

    def test_scrap_release_documents_no_stock_return(self):
        """报废不回补库存这条业务规则要留在迁移脚本与页面文案里。

        v2.3.0 的版本说明已随仓库重建作废（版本说明只保留 v3.0.x），
        因此这里改为校验迁移文件与页面上的口径。
        """
        migration = (
            ROOT / "database" / "migrations" / "20260915_001_scrap_management.sql"
        ).read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "ScrapRecordsView.vue").read_text(
            encoding="utf-8"
        )

        self.assertIn("不回补库存", migration)
        self.assertIn("报废", migration)
        self.assertIn("不回收、不回补库存", view)


class UpdateSourceSelectionTests(TestCase):
    """更新按钮内置 GitHub 来源，并提供自定义地址入口。"""

    def test_update_panel_has_builtin_github_and_custom_source(self):
        settings_api = (ROOT / "frontend" / "src" / "api" / "settings.ts").read_text(
            encoding="utf-8"
        )
        view = (ROOT / "frontend" / "src" / "views" / "SettingsView.vue").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'export const GITHUB_UPDATE_REPOSITORY_URL = "https://github.com/freeisme/OMbox.git";',
            settings_api,
        )
        self.assertIn('const updateSource = ref("github");', view)
        self.assertIn('updateSource.value === "github" ? GITHUB_UPDATE_REPOSITORY_URL', view)
        self.assertIn('<el-select v-model="updateSource"', view)
        self.assertIn("自定义项目地址", view)
        self.assertIn('"从 GitHub 检查更新"', view)
        self.assertIn("updateSource === 'custom'", view)

    def test_only_custom_source_persists_the_repository_url(self):
        view = (ROOT / "frontend" / "src" / "views" / "SettingsView.vue").read_text(
            encoding="utf-8"
        )
        server_source = (ROOT / "server.py").read_text(encoding="utf-8")

        self.assertIn('persistRepositoryUrl: updateSource.value === "custom",', view)
        self.assertIn('payload.get("persistRepositoryUrl", True)', server_source)
        self.assertIn("if \"repositoryUrl\" in payload and parse_bool(", server_source)


class SharedEmployeeStatusTests(TestCase):
    """公用人员：可挂靠设备、禁止绑定账号、办理离职等同删除。"""

    def test_migration_allows_the_shared_status(self):
        migration = (
            ROOT / "database" / "migrations" / "20260916_001_shared_employee_status.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("ck_employee_status", migration)
        self.assertIn(
            "CHECK (employment_status IN ('active', 'inactive', 'left', 'shared'))",
            migration,
        )
        self.assertIn("information_schema.table_constraints", migration)
        self.assertNotIn("DROP TABLE", migration.upper())

    def test_backend_accepts_shared_and_blocks_account_binding(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        server_source = (ROOT / "server.py").read_text(encoding="utf-8")
        save_employee = service.split("    def _save_employee(", 1)[1].split(
            "\n    def _save_organization(",
            1,
        )[0]

        self.assertIn('if status not in {"active", "inactive", "shared"}', save_employee)
        self.assertIn("def _shared_employee_number(", service)
        self.assertIn('prefix = f"SHARED-{org_code}-"', service)
        self.assertIn('not in {"active", "shared"}', service)
        self.assertIn("离职资产只能转交给在职人员或公用人员。", service)
        self.assertIn("AND employment_status <> 'shared';", server_source)
        self.assertIn("或为不可绑定账号的公用人员", server_source)

    def test_offboarding_a_shared_holder_skips_the_left_employee_archive(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        offboard = service.split("    def offboard_employee(", 1)[1].split(
            "\n    def _recovery_records_since(",
            1,
        )[0]

        self.assertIn('shared_employee = self.db.text(employee.get("status")) == "shared"', offboard)
        self.assertIn("is_active = 0", offboard)
        self.assertIn('"sharedRemoved": shared_employee', offboard)
        self.assertIn("公用人员 {employee_label} 已删除", offboard)

    def test_frontend_exposes_the_shared_status(self):
        labels = (ROOT / "frontend" / "src" / "labels.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "EmployeesView.vue").read_text(
            encoding="utf-8"
        )
        left_view = (ROOT / "frontend" / "src" / "views" / "LeftEmployeesView.vue").read_text(
            encoding="utf-8"
        )

        self.assertIn('shared: "公用"', labels)
        self.assertIn('<el-option label="公用" value="shared" />', view)
        # 公用人员同样能被分配设备/物资
        self.assertIn('["active", "shared"].includes(deviceEmployee.value?.status ?? "")', view)
        # 公用人员的「离职」等价于删除
        self.assertIn('row.status === "shared" ? "删除" : "办理离职"', view)
        # 公用人员不进入离职人员页
        self.assertNotIn("shared", left_view)


class RecoveryInboundTests(TestCase):
    """登记物资回收也必须入库，缺少品牌型号时自动建档并输出记录。"""

    def test_recovery_creates_catalog_entries_and_always_adds_stock(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        offboard = service.split("    def offboard_employee(", 1)[1].split(
            "\n    def _recovery_records_since(",
            1,
        )[0]

        self.assertIn("def _recovery_catalog_sql(", service)
        self.assertIn("INSERT IGNORE INTO it_inventory_brand", service)
        self.assertIn("INSERT IGNORE INTO it_inventory_model", service)
        self.assertIn("未填写品牌", service)
        self.assertIn("未填写型号", service)
        # 登记物资（未扣库存）同样入库，不再以 stock_adjusted 作为入库条件
        self.assertIn("SELECT {recovery_warehouse_id_sql}, @recovery_model_id, {quantity}", offboard)
        self.assertNotIn("@allocation_recovery_quantity", offboard)
        self.assertIn("AND @recovery_model_id > 0", offboard)
        self.assertNotIn("AND {stock_adjusted} = 1", offboard)
        self.assertIn("'leave_recovery'", offboard)

    def test_single_returns_recover_into_stock_as_well(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        allocation_return = service.split("    def return_inventory(", 1)[1].split(
            "\n    def return_usage_inventory(",
            1,
        )[0]
        legacy_return = service.split("    def return_usage_inventory(", 1)[1].split(
            "\n    def list_allocations(",
            1,
        )[0]

        for source in (allocation_return, legacy_return):
            self.assertIn("_recovery_catalog_sql(", source)
            self.assertIn("@recovery_model_id > 0", source)
            self.assertNotIn("{1 if stock_adjusted else 0} = 1", source)
            self.assertIn("请选择回收目标仓库。", source)

    def test_recovery_records_are_returned_and_shown_in_a_modal(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "EmployeesView.vue").read_text(
            encoding="utf-8"
        )

        self.assertIn("def _recovery_records_since(", service)
        self.assertIn("def _offboarding_unrecovered_items(", service)
        self.assertIn('"recoveryRecords"', service)
        self.assertIn('"unrecoveredItems"', service)
        # 回收结果在办理离职弹窗里逐项展示：处理方式、回收仓库/接收人、处理说明
        self.assertIn('v-model="offboardVisible"', view)
        self.assertIn("回收仓库 / 接收人", view)
        self.assertIn("处理说明", view)
        self.assertIn("异常待处理必填", view)
        self.assertIn("已回收并回补库存。", view)


class OffboardingRecoveryWarehouseTests(TestCase):
    """回收必须显式选择目标仓库，且仓库要落库留痕。"""

    def test_backend_requires_and_records_the_recovery_warehouse(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        normalization = service.split("    def _normalize_offboarding_plan(", 1)[1].split(
            "\n    def offboard_employee(",
            1,
        )[0]
        offboard = service.split("    def offboard_employee(", 1)[1]

        self.assertIn('raise self.api_error("选择回收时必须指定回收目标仓库。")', normalization)
        self.assertIn(
            'raw_item.get("recoveryWarehouseId") or raw_item.get("warehouseId")',
            normalization,
        )
        self.assertIn('{"warehouseId": requested_warehouse_id}', normalization)
        self.assertIn('"employees",', normalization)
        self.assertIn("require_explicit=True", normalization)
        # 目标仓库对所有回收项生效，不再以“是否扣减过库存”为条件。
        self.assertNotIn("and stock_adjusted:\n                    source_warehouse_ids", normalization)
        self.assertIn("THEN {recovery_warehouse_id_sql}", offboard)
        self.assertIn('{recovery_warehouse_id_sql if action == "recover" else "NULL"}', offboard)

    def test_frontend_requires_an_explicit_warehouse_without_preselecting_one(self):
        view = (ROOT / "frontend" / "src" / "views" / "EmployeesView.vue").read_text(
            encoding="utf-8"
        )
        api_module = (ROOT / "frontend" / "src" / "api" / "employees.ts").read_text(
            encoding="utf-8"
        )

        # 选择"回收"时必须显式指定目标仓库：下拉不预选，提交前校验
        self.assertIn("row.action === 'recover'", view)
        self.assertIn('placeholder="回收目标仓库"', view)
        self.assertIn("选择回收时必须指定回收目标仓库。", view)
        self.assertIn("recoveryWarehouseId", api_module)


class WarehouseInventoryRegressionTests(TestCase):
    def test_warehouse_migration_is_incremental_and_preserves_legacy_history(self):
        migration = (
            ROOT / "database" / "migrations" / "20260902_001_inventory_warehouses.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS inventory_warehouse", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS inventory_warehouse_stock", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS inventory_transfer_log", migration)
        self.assertIn("information_schema.columns", migration)
        self.assertIn("information_schema.table_constraints", migration)
        self.assertIn("INSERT INTO inventory_warehouse", migration)
        self.assertIn("VALUES ('WH-001', '仓库1'", migration)
        self.assertIn("SELECT @default_warehouse_id, model_id, quantity", migration)
        self.assertIn("warehouse_management", migration)
        self.assertNotIn("DROP TABLE", migration.upper())
        self.assertNotIn("DELETE FROM inventory_movement_log", migration)

        transfer_table = migration.split(
            "CREATE TABLE IF NOT EXISTS inventory_transfer_log",
            1,
        )[1].split("\n\nSET @has_allocation_warehouse", 1)[0]
        self.assertIn(
            "ON DELETE RESTRICT,\n"
            "  CONSTRAINT fk_inventory_transfer_target",
            transfer_table,
        )
        self.assertNotIn(
            "source_warehouse_id) REFERENCES inventory_warehouse (warehouse_id)\n"
            "    ON DELETE RESTRICT ON UPDATE CASCADE",
            transfer_table,
        )
        self.assertNotIn(
            "target_warehouse_id) REFERENCES inventory_warehouse (warehouse_id)\n"
            "    ON DELETE RESTRICT ON UPDATE CASCADE",
            transfer_table,
        )

        bootstrap = (
            ROOT / "database" / "bootstrap" / "01_schema.sql"
        ).read_text(encoding="utf-8")
        bootstrap_transfer_table = bootstrap.split(
            "CREATE TABLE inventory_transfer_log",
            1,
        )[1].split("\n\nCREATE TABLE inventory_movement_log", 1)[0]
        self.assertNotIn(
            "warehouse_id)\n    ON DELETE RESTRICT ON UPDATE CASCADE",
            bootstrap_transfer_table,
        )

    def test_warehouse_routes_require_permissions_and_use_command_endpoint(self):
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")
        server_source = (ROOT / "server.py").read_text(encoding="utf-8")

        self.assertIn('path == "/api/inventory/warehouses" and method == "GET"', router)
        self.assertIn('path == "/api/inventory/warehouses" and method == "POST"', router)
        self.assertIn('len(parts) == 5 and method == "DELETE"', router)
        self.assertIn('self._write_context(handler, "warehouse_management", "create")', router)
        self.assertIn('self._write_context(handler, "warehouse_management", "update")', router)
        self.assertIn('self._write_context(handler, "warehouse_management", "delete")', router)
        self.assertIn('path == "/api/inventory/transfers" and method == "POST"', router)
        self.assertIn('self._inventory_write_context(handler, "update")', router)
        self.assertIn('self.deps.require_permission(context, "warehouse_management", "create")', router)
        self.assertIn('self.assets.transfer_inventory(', router)
        delete_handler = server_source.split("    def do_DELETE(self) -> None:", 1)[1].split(
            "\n    def end_headers",
            1,
        )[0]
        self.assertIn('if self.path.startswith("/api/"):', delete_handler)
        self.assertIn("self.handle_api()", delete_handler)
        self.assertIn('"code": "STATE_CONFLICT"', delete_handler)

    def test_warehouse_service_is_scoped_transactional_and_idempotent(self):
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        transfer = service.split("    def transfer_inventory(", 1)[1].split(
            "\n    def return_inventory(",
            1,
        )[0]
        delete = service.split("    def delete_warehouse(", 1)[1].split(
            "\n    def list_warehouse_stock(",
            1,
        )[0]

        self.assertIn("def _assert_warehouse_access(", service)
        self.assertIn('module_code: str = "warehouse_management"', service)
        self.assertIn("self.scope.assert_org_access(context, warehouse.get(\"orgId\"))", service)
        self.assertIn('self._idempotency_result("inventory.transfer"', transfer)
        self.assertIn("START TRANSACTION;", transfer)
        self.assertIn("first_warehouse_id, second_warehouse_id = sorted(", transfer)
        self.assertIn("FOR UPDATE;", transfer)
        self.assertIn("UPDATE inventory_warehouse_stock", transfer)
        self.assertIn("INSERT INTO inventory_transfer_log", transfer)
        self.assertIn("inventory_transfer", transfer)
        self.assertIn('self._store_idempotency_result("inventory.transfer"', transfer)
        self.assertIn('warehouse.get("code")) == "WH-001"', delete)
        self.assertIn("默认仓库“仓库1”不能删除", delete)
        self.assertIn("inventory_transfer_log", delete)

    def test_warehouse_state_filtering_and_frontend_controls_are_scoped(self):
        view = (ROOT / "frontend" / "src" / "views" / "InventoryView.vue").read_text(
            encoding="utf-8"
        )
        state_reader = (ROOT / "server.py").read_text(encoding="utf-8")

        self.assertIn('for module_code in ("it_assets", "employees", "organizations", "warehouse_management")', state_reader)
        self.assertIn('if can_view("warehouse_management"):', state_reader)
        self.assertIn('result["warehouseStocks"] = [', state_reader)
        self.assertIn('text_value(item.get("warehouseId")) in visible_warehouse_ids', state_reader)
        # IT物资页按仓库切换，入库/调拨都必须显式选仓库
        self.assertIn("当前仓库", view)
        self.assertIn("调出仓库和调入仓库不能相同", view)


class InspectionManagementRegressionTests(TestCase):
    def test_inspection_migration_is_incremental_and_only_adds_objects(self):
        migration = (
            ROOT / "database" / "migrations" / "20260918_001_inspection_management.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS asset_site", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS asset_rack", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS inspection_template", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS inspection_template_item", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS inspection_task", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS inspection_task_item", migration)
        self.assertIn("CHECK (site_type IN ('server_room', 'weak_room'))", migration)
        self.assertIn("CHECK (scope_kind IN ('site', 'rack'))", migration)
        self.assertIn("CHECK (result IN ('pending', 'ok', 'fail', 'na'))", migration)
        self.assertIn("'inspection_management', '巡检管理'", migration)
        self.assertIn("INSERT INTO auth_role_permission", migration)
        self.assertIn("'XJ-SERVER-ROOM', '机房巡检'", migration)
        self.assertIn("'XJ-WEAK-ROOM', '弱电间巡检'", migration)
        # 巡检对象只包含机房、弱电间和机柜，不允许出现办公区或仓库对象。
        self.assertNotIn("'office_area'", migration)
        self.assertNotIn("'warehouse'", migration)
        self.assertNotIn("DROP TABLE", migration.upper())
        self.assertNotIn("DELETE FROM computer_asset", migration)
        self.assertNotIn("DELETE FROM employee", migration)

    def test_inspection_routes_require_dedicated_permissions(self):
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")

        self.assertIn('self._read_context(handler, "inspection_management")', router)
        self.assertIn('self._write_context(handler, "inspection_management", "create")', router)
        self.assertIn('self._write_context(handler, "inspection_management", "update")', router)
        self.assertIn('self._write_context(handler, "inspection_management", "delete")', router)
        self.assertIn('path == "/api/inspection/sites" and method == "GET"', router)
        self.assertIn('path == "/api/inspection/racks" and method == "POST"', router)
        self.assertIn('path == "/api/inspection/templates" and method == "POST"', router)
        self.assertIn('path == "/api/inspection/tasks" and method == "POST"', router)
        self.assertIn('parts[7] == "check" and method == "POST"', router)
        self.assertIn('parts[5] == "submit" and method == "POST"', router)
        self.assertIn('parts[5] == "void" and method == "POST"', router)
        self.assertIn("self.inspection.start_task(", router)
        self.assertIn("self.inspection.submit_task(", router)
        self.assertIn("self._idempotency_key(handler)", router)

    def test_inspection_service_snapshots_items_and_requires_abnormal_notes(self):
        service = (ROOT / "office_asset" / "inspection.py").read_text(encoding="utf-8")
        start_task = service.split("    def start_task(", 1)[1].split(
            "\n    def _task_items(",
            1,
        )[0]
        check_item = service.split("    def check_item(", 1)[1].split(
            "\n    def submit_task(",
            1,
        )[0]
        submit_task = service.split("    def submit_task(", 1)[1].split(
            "\n    def void_task(",
            1,
        )[0]

        # 开始巡检时把模板事项快照进任务明细，模板后续修改不影响历史巡检表。
        self.assertIn("INSERT INTO inspection_task_item", start_task)
        self.assertIn("template_id = {template_id}", start_task)
        self.assertIn("START TRANSACTION;", start_task)
        self.assertIn("inspection_started", start_task)
        self.assertIn('self._idempotency_result("inspection.task.start"', start_task)
        self.assertIn('self._store_idempotency_result("inspection.task.start"', start_task)

        # 异常项必须填写说明：填写时和提交时各校验一次。
        self.assertIn('if result == "fail" and not notes:', check_item)
        self.assertIn('raise self.api_error("异常项必须填写说明。")', check_item)
        self.assertIn('== "fail"', submit_task)
        self.assertIn("未填写说明", submit_task)
        self.assertIn("未检查", submit_task)
        self.assertIn("inspection_submitted", submit_task)
        self.assertIn("status = 'submitted'", submit_task)
        self.assertIn("AND status = 'running'", submit_task)

        # 没有周期计划或自动派单：巡检只能手动发起，提交后不可修改。
        self.assertNotIn("schedule", service.lower())
        self.assertNotIn("cron", service.lower())

    def test_void_requires_reason_and_records_audit(self):
        service = (ROOT / "office_asset" / "inspection.py").read_text(encoding="utf-8")
        void_task = service.split("    def void_task(", 1)[1]

        self.assertIn("必须填写原因", void_task)
        self.assertIn("inspection_voided", void_task)
        self.assertIn("status = 'void'", void_task)
        self.assertIn("已提交的巡检表不能作废", void_task)

    def test_health_check_counts_the_inspection_tables(self):
        server = (ROOT / "server.py").read_text(encoding="utf-8")

        self.assertIn("'asset_site', 'asset_rack', 'inspection_template', 'inspection_template_item', ", server)
        self.assertIn("'inspection_task'", server)
        self.assertIn("required_table_count = 70", server)

    def test_inspection_page_is_wired_into_navigation_and_exports(self):
        navigation = (ROOT / "frontend" / "src" / "navigation.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "InspectionView.vue").read_text(
            encoding="utf-8"
        )
        api_module = (ROOT / "frontend" / "src" / "api" / "governance.ts").read_text(
            encoding="utf-8"
        )

        self.assertIn('page: "inspection"', navigation)
        self.assertIn('modules: ["inspection_management"]', navigation)
        for endpoint in (
            "/api/inspection/tasks",
            "/check",
            "/submit",
            "/void",
        ):
            self.assertIn(endpoint, api_module)
        for text in ("机房巡检", "巡检模板", "机房与机柜", "提交巡检"):
            self.assertIn(text, view)
        self.assertIn("异常项必须填写说明。", view)
        # 巡检不生成周期计划，只允许手动开始。
        self.assertNotIn("setInterval(", view)


class RackLayoutRegressionTests(TestCase):
    def test_rack_layout_migration_is_incremental_and_only_adds_objects(self):
        migration = (ROOT / "database" / "migrations" / "20260918_002_rack_layout.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("CREATE TABLE IF NOT EXISTS rack_device_placement", migration)
        self.assertIn("UNIQUE KEY uq_rack_placement_computer (computer_id)", migration)
        self.assertIn("CHECK (source_kind IN ('computer', 'custom'))", migration)
        self.assertIn("CHECK (face IN ('front', 'rear', 'both'))", migration)
        self.assertIn("CHECK (u_height BETWEEN 1 AND 50)", migration)
        self.assertIn("'rack_layout', '机柜视图'", migration)
        self.assertIn("INSERT INTO auth_role_permission", migration)
        # 机柜视图是独立模块：只新增表与权限，不改动台账与历史数据。
        self.assertNotIn("DROP TABLE", migration.upper())
        self.assertNotIn("ALTER TABLE computer_asset", migration)
        self.assertNotIn("DELETE FROM", migration.upper())
        self.assertNotIn("quantity = quantity", migration)

    def test_rack_layout_routes_require_dedicated_permissions(self):
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")

        self.assertIn('self._read_context(handler, "rack_layout")', router)
        self.assertIn('self._write_context(handler, "rack_layout", "create")', router)
        self.assertIn('self._write_context(handler, "rack_layout", "update")', router)
        self.assertIn('self._write_context(handler, "rack_layout", "delete")', router)
        self.assertIn('path == "/api/rack-layout/racks" and method == "GET"', router)
        self.assertIn('path == "/api/rack-layout/available" and method == "GET"', router)
        self.assertIn('len(parts) == 6 and parts[5] == "placements" and method == "POST"', router)
        self.assertIn('len(parts) == 6 and parts[5] == "remove" and method == "POST"', router)
        self.assertIn('len(parts) == 5 and method == "PUT"', router)
        self.assertIn("self.rack_layout.place_device(", router)
        self.assertIn("self.rack_layout.update_placement(", router)
        self.assertIn("self.rack_layout.remove_placement(", router)
        self.assertIn("self._idempotency_key(handler)", router)

    def test_rack_layout_service_validates_faces_range_and_duplicates(self):
        service = (ROOT / "office_asset" / "rack_layout.py").read_text(encoding="utf-8")
        validate_slot = service.split("    def _validate_slot(", 1)[1].split(
            "\n    @staticmethod",
            1,
        )[0]
        place_device = service.split("    def place_device(", 1)[1].split(
            "\n    def update_placement(",
            1,
        )[0]

        # 前后面板各自成层：只有整机深度或同面才算冲突。
        self.assertIn('(placement.face = \'both\' OR placement.face = ', service)
        self.assertIn("hits = self._conflicting_placements(", validate_slot)
        self.assertIn("超出机柜范围", validate_slot)
        self.assertIn("U 位已被占用", validate_slot)
        self.assertIn("position_u + u_height - 1 > height", validate_slot)
        # 一台设备同时只能在一个机柜上架。
        self.assertIn("该机房设备已经在某个机柜上架", place_device)
        self.assertIn("START TRANSACTION;", place_device)
        self.assertIn("rack_placement_created", place_device)
        self.assertIn('self._idempotency_result("rack.placement.create"', place_device)
        self.assertIn('self._store_idempotency_result("rack.placement.create"', place_device)
        # 上架不改变库存与固定资产状态。
        self.assertNotIn("quantity = quantity", place_device)
        self.assertNotIn("UPDATE computer_asset", place_device)
        self.assertNotIn("it_inventory_model", place_device.replace("inventory_model_id", ""))

    def test_rack_layout_occupancy_counts_physical_rows_and_audits_removal(self):
        service = (ROOT / "office_asset" / "rack_layout.py").read_text(encoding="utf-8")
        remove_placement = service.split("    def remove_placement(", 1)[1]

        self.assertIn("def _occupied_units(", service)
        self.assertIn("rows: set[int] = set()", service)
        self.assertIn("used_units = self._occupied_units(placements)", service)
        # 下架是软删除并写审计，不删除台账记录。
        self.assertIn("SET is_active = 0", remove_placement)
        self.assertIn("rack_placement_removed", remove_placement)
        self.assertNotIn("DELETE FROM rack_device_placement", remove_placement)
        self.assertNotIn("DELETE FROM computer_asset", remove_placement)

    def test_rack_layout_frontend_page_and_drag_editing_are_wired(self):
        navigation = (ROOT / "frontend" / "src" / "navigation.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "RackLayoutView.vue").read_text(encoding="utf-8")
        api_client = (ROOT / "frontend" / "src" / "api" / "datacenter.ts").read_text(encoding="utf-8")

        # 机柜视图只存在于 Vue 前端，旧前端已整体删除。
        self.assertIn('page: "rackLayout", path: "/rack-layout"', navigation)
        self.assertFalse((ROOT / "web" / "app.js").exists())
        self.assertIn("onPointerDown", view)
        self.assertIn("placeAt", view)
        self.assertIn("unlinkPlacement", view)
        self.assertIn("printRack", view)
        self.assertIn("exportCsv", view)
        self.assertIn("/api/rack-layout/racks", api_client)


class FrontendSpaMigrationTests(TestCase):
    """新版 Vue 前端（web/app）的回归约束。"""

    def test_version_file_is_single_source_of_truth(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        notes = (ROOT / "VERSION_NOTES.md").read_text(encoding="utf-8")
        latest_heading = next(
            line.strip() for line in notes.splitlines() if line.startswith("## v")
        )

        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertEqual(latest_heading, f"## v{version}")

    def test_server_exposes_version_endpoint_and_frontend_routes(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")

        self.assertIn('APP_VERSION = load_app_version()', source)
        self.assertIn('if parsed.path == "/api/meta" and self.command == "GET":', source)
        self.assertIn('SPA_DIR = WEB_DIR / "app"', source)
        self.assertIn("def serve_frontend_route(self) -> bool:", source)
        self.assertIn("def send_spa_index(self) -> None:", source)
        # 新版前端没有任何 iframe 承载页，统一禁止被嵌入
        self.assertIn('self.send_header("X-Frame-Options", "DENY")', source)

    def test_frontend_project_targets_web_app_and_keeps_stack_pinned(self):
        config = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
        package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))

        self.assertIn('outDir: "../web/app"', config)
        self.assertIn('base: "/app/"', config)
        self.assertIn("vue", package["dependencies"])
        self.assertIn("vue-router", package["dependencies"])
        self.assertIn("element-plus", package["dependencies"])
        self.assertIn("vite", package["devDependencies"])
        self.assertTrue((ROOT / "frontend" / "pnpm-lock.yaml").exists())

    def test_docker_builds_frontend_in_multistage(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("AS frontend", dockerfile)
        self.assertIn("pnpm install --frozen-lockfile", dockerfile)
        self.assertIn("COPY --from=frontend /web/app ./web/app", dockerfile)
        self.assertIn("COPY VERSION ./", dockerfile)

    def test_audit_page_migrated_to_vue(self):
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "AuditView.vue").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api" / "audit.ts").read_text(encoding="utf-8")

        self.assertIn('audit: () => import("../views/AuditView.vue"),', router)
        self.assertIn("fetchAuditLogs", api)
        self.assertIn("/api/audit-logs?", api)
        self.assertIn("auditLogsToCsv", view)
        # 审计动作码 → 中文标签，避免列表里出现英文原始码
        for label in ("离职归档", "办公终端分配变更", "库存数量变更"):
            self.assertIn(label, api)

    def test_theme_color_support(self):
        theme = (ROOT / "frontend" / "src" / "theme.ts").read_text(encoding="utf-8")
        settings = (ROOT / "frontend" / "src" / "views" / "SettingsView.vue").read_text(encoding="utf-8")
        shell = (ROOT / "frontend" / "src" / "layouts" / "AppShell.vue").read_text(encoding="utf-8")
        styles = (ROOT / "frontend" / "src" / "styles" / "app.css").read_text(encoding="utf-8")

        self.assertIn("THEME_COLOR_PRESETS", theme)
        self.assertIn("--el-color-primary", theme)
        self.assertIn("--el-color-primary-light-", theme)
        self.assertIn("oa-theme-color", theme)
        self.assertIn("外观主题", settings)
        self.assertIn("恢复默认", settings)
        self.assertIn("var(--el-color-primary", styles)
        self.assertIn("toggleTheme", shell)

    def test_dashboard_page_migrated_to_vue(self):
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "DashboardView.vue").read_text(encoding="utf-8")
        workbench_api = (ROOT / "frontend" / "src" / "api" / "workbench.ts").read_text(
            encoding="utf-8"
        )

        self.assertIn('dashboard: () => import("../views/DashboardView.vue"),', router)
        # 工作台走专用汇总接口，不再整包拉 /api/state
        self.assertIn("fetchWorkbench", workbench_api)
        self.assertIn("/api/workbench/summary", workbench_api)
        # v2.16.0 起该页面是工作台：详情断言见 test_workbench_modules_roles_and_customization
        registry = (ROOT / "frontend" / "src" / "workbench.ts").read_text(encoding="utf-8")
        for text in ("工作台", "待办事项", "核心统计", "最近登记资产", "最近入库物资"):
            self.assertTrue(text in view or text in registry, f"{text} 未出现在工作台页面或模块注册表中")
        # 状态/设备类型标签收敛到单一来源
        self.assertTrue((ROOT / "frontend" / "src" / "labels.ts").exists())
        labels = (ROOT / "frontend" / "src" / "labels.ts").read_text(encoding="utf-8")
        for label in ("在用", "闲置", "维修", "笔记本", "台式机"):
            self.assertIn(label, labels)

    def test_workbench_modules_roles_and_customization(self):
        registry = (ROOT / "frontend" / "src" / "workbench.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "DashboardView.vue").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api" / "workbench.ts").read_text(encoding="utf-8")

        modules_block = registry.split("export const WORKBENCH_MODULES", 1)[1].split("];", 1)[0]
        keys = re.findall(r'key: "([A-Za-z]+)"', modules_block)
        # 设计约束：模块数量控制在 5~9 个
        self.assertGreaterEqual(len(keys), 5)
        self.assertLessEqual(len(keys), 9)
        for key in ("todos", "quickActions", "assets", "notifications", "progress"):
            self.assertIn(key, keys)

        # 角色过滤 + 自定义（顺序/显隐）与本地持久化
        self.assertIn("moduleAvailable", registry)
        self.assertIn("availableModules", registry)
        self.assertIn("resolveModules", registry)
        self.assertIn("oa-workbench-", registry)
        # 模块标题定义在注册表；页面负责渲染与自定义交互
        for text in ("待办事项", "快捷入口", "核心统计", "通知公告", "处理进度", "我的设备"):
            self.assertIn(text, registry)
        for text in ("自定义工作台", "恢复默认", "刷新数据"):
            self.assertIn(text, view)

        # 数据接口按权限请求，失败降级为模块空值
        self.assertIn("fetchWorkbench", api)
        self.assertIn("/api/workbench/summary", api)
        self.assertIn("/api/notifications", api)
        # 汇总接口在服务端按权限裁剪，并按账号做短期缓存 + 支持强制刷新
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('parsed.path == "/api/workbench/summary"', server)
        self.assertIn("def build_workbench_summary(context: dict) -> dict:", server)
        self.assertIn("def workbench_can_view(context: dict, module_code: str) -> bool:", server)
        self.assertIn("def workbench_summary_cached(context: dict, refresh: bool = False) -> dict:", server)
        self.assertIn("WORKBENCH_CACHE_TTL_SECONDS", server)
        # 汇总不再整包拉取 /api/state，也不再按模块发多个请求
        self.assertNotIn('api<Partial<StatePayload>>("/api/state")', api)
        self.assertNotIn('"/api/tickets"', api)
        self.assertIn("include_audit_logs=False", server)

    def test_computers_page_migrated_to_vue(self):
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "ComputersView.vue").read_text(encoding="utf-8")
        api_module = (ROOT / "frontend" / "src" / "api" / "computers.ts").read_text(encoding="utf-8")

        self.assertIn('computers: () => import("../views/ComputersView.vue"),', router)
        # 新增/编辑与报废复用既有领域接口
        self.assertIn("/api/resources/computer", api_module)
        self.assertIn("/api/computers/${computerId}/scrap", api_module)
        self.assertIn("/api/scrap-reasons", api_module)
        for text in ("办公终端台账", "报废登记", "全选当前结果", "导出选中"):
            self.assertIn(text, view)
        # 表单字段必须覆盖后端会写入的列，否则保存会把未提交字段清空
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        for field in ("deviceName", "deviceType", "fixedAssetCode", "snSt", "wifiMac", "position"):
            self.assertIn(f'payload.get("{field}")', service)
            self.assertIn(field, api_module)
        server = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("'position', COALESCE(position_name, '')", server)

    def test_left_employees_and_dictionary_pages_migrated(self):
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
        left_view = (ROOT / "frontend" / "src" / "views" / "LeftEmployeesView.vue").read_text(
            encoding="utf-8"
        )
        dict_view = (ROOT / "frontend" / "src" / "views" / "DictionaryView.vue").read_text(
            encoding="utf-8"
        )
        directory = (ROOT / "frontend" / "src" / "api" / "directory.ts").read_text(encoding="utf-8")

        self.assertIn('leftEmployees: () => import("../views/LeftEmployeesView.vue"),', router)
        self.assertIn('dictionary: () => import("../views/DictionaryView.vue"),', router)
        for text in ("离职人员", "查看详情", "离职时设备快照"):
            self.assertIn(text, left_view)
        for text in ("组织架构树", "非资产设备类型", "新增根组织", "引用人数"):
            self.assertIn(text, dict_view)
        # 新增/编辑沿用资源接口；删除能力与旧版一致地不提供
        self.assertIn("/api/resources/organization", directory)
        self.assertIn("/api/resources/inventory-type", directory)
        self.assertNotIn('method: "DELETE"', directory)
        self.assertIn("leftEmployees", directory)

    def test_employees_page_migrated_to_vue(self):
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "EmployeesView.vue").read_text(
            encoding="utf-8"
        )
        api_module = (ROOT / "frontend" / "src" / "api" / "employees.ts").read_text(
            encoding="utf-8"
        )

        self.assertIn('employees: () => import("../views/EmployeesView.vue"),', router)
        # 人员新增/编辑与离职命令走既有接口
        self.assertIn("/api/resources/employee", api_module)
        self.assertIn("/offboarding-preview", api_module)
        self.assertIn("/offboard", api_module)
        # 离职处置的三种方式与后端 OFFBOARD_ACTION_LABELS 保持一致
        for action in ('"recover"', '"transfer"', '"exception"'):
            self.assertIn(action, api_module)
        service = (ROOT / "office_asset" / "asset_service.py").read_text(encoding="utf-8")
        for label in ("回收", "转交他人", "异常待处理"):
            self.assertIn(label, service)
        # 回收必须指定目标仓库：前端提交 recoveryWarehouseId，并在提交前校验
        self.assertIn("recoveryWarehouseId", api_module)
        self.assertIn("选择回收时必须指定回收目标仓库", view)
        for text in ("组织架构", "人员清单", "办理离职", "新增人员"):
            self.assertIn(text, view)

    def test_flow_and_scrap_pages_migrated_to_vue(self):
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
        flow_view = (ROOT / "frontend" / "src" / "views" / "FlowControlView.vue").read_text(
            encoding="utf-8"
        )
        scrap_view = (ROOT / "frontend" / "src" / "views" / "ScrapRecordsView.vue").read_text(
            encoding="utf-8"
        )
        flows = (ROOT / "frontend" / "src" / "api" / "flows.ts").read_text(encoding="utf-8")
        scrap = (ROOT / "frontend" / "src" / "api" / "scrap.ts").read_text(encoding="utf-8")

        self.assertIn('flowControl: () => import("../views/FlowControlView.vue"),', router)
        self.assertIn('scrapRecords: () => import("../views/ScrapRecordsView.vue"),', router)
        # 备注修正与报废记录接口
        self.assertIn("/note-corrections", flows)
        self.assertIn("/api/scrap-records?", scrap)
        # 业务类型映射需覆盖现网实际使用的动作码，避免显示英文原始码
        for action in (
            "assignment",
            "leave_recovery",
            "inventory_allocation",
            "inventory_return",
            "delete_inventory_model",
        ):
            self.assertIn(f"{action}: {{", flows)
        for text in ("物资流转记录", "修正流转备注", "库存影响"):
            self.assertIn(text, flow_view)
        for text in ("报废记录", "报废记录详情", "库存影响"):
            self.assertIn(text, scrap_view)

    def test_inventory_page_migrated_to_vue(self):
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "InventoryView.vue").read_text(encoding="utf-8")
        api_module = (ROOT / "frontend" / "src" / "api" / "inventory.ts").read_text(encoding="utf-8")

        self.assertIn('inventory: () => import("../views/InventoryView.vue"),', router)
        # 入库/调拨/仓库维护复用既有接口
        self.assertIn("/api/inventory/receipts", api_module)
        self.assertIn("/api/inventory/transfers", api_module)
        self.assertIn("/api/inventory/warehouses", api_module)
        self.assertIn('method: "DELETE"', api_module)
        # 调拨前端自校验与后端规则一致
        self.assertIn("调出仓库和调入仓库不能相同", view)
        for text in ("IT物资", "库存调拨", "采购入库记录", "新增仓库"):
            self.assertIn(text, view)

    def test_tickets_and_service_pages_migrated_to_vue(self):
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
        tickets_view = (ROOT / "frontend" / "src" / "views" / "TicketsView.vue").read_text(
            encoding="utf-8"
        )
        service_view = (ROOT / "frontend" / "src" / "views" / "ServiceManagementView.vue").read_text(
            encoding="utf-8"
        )
        service_api = (ROOT / "frontend" / "src" / "api" / "service.ts").read_text(encoding="utf-8")

        self.assertIn('tickets: () => import("../views/TicketsView.vue"),', router)
        self.assertIn('serviceManagement: () => import("../views/ServiceManagementView.vue"),', router)
        for endpoint in (
            "/api/tickets",
            "/transitions",
            "/notes",
            "/api/changes",
            "/api/problems",
            "/api/knowledge",
            "/api/sla/policies",
            "/api/approvals/",
            "/api/notifications",
        ):
            self.assertIn(endpoint, service_api)
        # 状态流转表必须与后端 TICKET_TRANSITIONS 一致
        tickets_source = (ROOT / "office_asset" / "tickets.py").read_text(encoding="utf-8")
        for status in ("new", "assigned", "in_progress", "pending", "resolved", "closed", "cancelled"):
            self.assertIn(f'"{status}"', tickets_source)
            self.assertIn(status, service_api)
        for text in ("工单", "状态流转", "处理记录"):
            self.assertIn(text, tickets_view)
        for text in ("服务管理", "变更", "问题", "知识库", "SLA 策略", "审批", "通知"):
            self.assertIn(text, service_view)

    def test_all_navigation_pages_migrated_to_vue(self):
        """16 个导航页面都必须有对应的 Vue 视图，避免悄悄退回旧前端渲染。"""
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
        navigation = (ROOT / "frontend" / "src" / "navigation.ts").read_text(encoding="utf-8")
        pages = re.findall(r'page: "([A-Za-z]+)"', navigation)

        self.assertGreaterEqual(len(pages), 16)
        migrated_block = router.split("const VIEW_LOADERS", 1)[1].split("};", 1)[0]
        for page in pages:
            self.assertIn(f"{page}: ", migrated_block, f"{page} 未注册 Vue 视图")
        # 页面按需加载：首屏只带外壳，其余页面各自分包
        self.assertIn('() => import("../views/', migrated_block)

    def test_inspection_and_governance_pages_migrated_to_vue(self):
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
        inspection_view = (ROOT / "frontend" / "src" / "views" / "InspectionView.vue").read_text(
            encoding="utf-8"
        )
        governance_view = (ROOT / "frontend" / "src" / "views" / "GovernanceView.vue").read_text(
            encoding="utf-8"
        )
        api_module = (ROOT / "frontend" / "src" / "api" / "governance.ts").read_text(
            encoding="utf-8"
        )

        self.assertIn('inspection: () => import("../views/InspectionView.vue"),', router)
        self.assertIn('governance: () => import("../views/GovernanceView.vue"),', router)
        for endpoint in (
            "/api/inspection/tasks",
            "/items/",
            "/check",
            "/submit",
            "/void",
            "/api/sync-runs",
            "/api/data-quality/issues",
            "/api/data-quality/run",
        ):
            self.assertIn(endpoint, api_module)
        for text in ("机房巡检", "巡检任务", "巡检模板", "机房与机柜", "提交巡检"):
            self.assertIn(text, inspection_view)
        for text in ("同步与质量", "同步暂存批次", "数据质量问题", "运行质量检查"):
            self.assertIn(text, governance_view)


class DevicePanelTopologyRegressionTests(TestCase):
    """占位：以下为设备面板与拓扑的既有约束。"""

    def test_migration_adds_catalog_ports_cables_and_positions(self):
        migration = (
            ROOT / "database" / "migrations" / "20260918_003_device_ports_and_cables.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS device_type_catalog", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS device_type_port_template", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS rack_device_port", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS rack_cable_run", migration)
        self.assertIn("CREATE TABLE IF NOT EXISTS topology_node_position", migration)
        self.assertIn("UNIQUE KEY uq_rack_port_name (placement_id, face, port_name)", migration)
        # 一个端口只能有一条活动链路：软删除用生成列 + 唯一索引表达。
        self.assertIn("a_active_key BIGINT UNSIGNED", migration)
        self.assertIn("UNIQUE KEY uq_cable_port_a (a_active_key)", migration)
        self.assertIn("UNIQUE KEY uq_cable_port_b (b_active_key)", migration)
        self.assertIn("medium IN ('cat5e', 'cat6', 'fiber-om3', 'fiber-os2', 'dac', 'power', 'console', 'other')", migration)
        self.assertIn("port_kind IN ('network', 'fiber', 'power', 'console', 'other')", migration)
        self.assertNotIn("DROP TABLE", migration.upper())
        self.assertNotIn("ALTER TABLE computer_asset", migration)
        self.assertNotIn("quantity = quantity", migration)

    def test_template_ports_are_laid_out_into_rows(self):
        ports = [
            {"name": "GE1", "type": "1000base-t", "kind": "network", "face": "front"},
            {"name": "GE2", "type": "1000base-t", "kind": "network", "face": "front"},
            {"name": "XGE1", "type": "10gbase-x-sfpp", "kind": "fiber", "face": "front"},
            {"name": "Console", "type": "rj-45", "kind": "console", "face": "front"},
            {"name": "PSU1", "type": "iec-60320-c14", "kind": "power", "face": "rear"},
        ]
        layouted = layout_template_ports(ports)
        network_rows = [item["row_index"] for item in layouted if item["kind"] == "network"]
        self.assertEqual(network_rows, [1, 1])
        positions = [item["position_index"] for item in layouted if item["kind"] == "network"]
        self.assertEqual(positions, [1, 2])
        self.assertEqual(len({item["row_index"] for item in layouted}), 4)

    def test_netbox_import_path_is_removed(self):
        service = (ROOT / "office_asset" / "device_topology.py").read_text(encoding="utf-8")
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")
        notes = (ROOT / "docs" / "development" / "device-panel-and-topology.md").read_text(encoding="utf-8")

        # 不再从 NetBox devicetype-library 抓取型号
        self.assertNotIn("devicetype-library", service)
        self.assertNotIn("fetch_netbox_yaml", service)
        self.assertNotIn("raw.githubusercontent.com", service)
        self.assertNotIn("/api/device-types/import", router)
        self.assertFalse((ROOT / "tools" / "import_device_types.py").exists())
        # 型号库改为手工维护，接口仍在
        self.assertIn('path == "/api/device-types" and method == "POST"', router)
        self.assertIn("create_device_type", router)
        self.assertNotIn("import_device_types.py", notes)

    def test_routes_require_rack_layout_permissions_and_commands(self):
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")

        self.assertIn('path == "/api/device-types" and method == "GET"', router)
        self.assertIn('path == "/api/rack-layout/cables" and method == "POST"', router)
        self.assertIn('path == "/api/rack-layout/cables/import" and method == "POST"', router)
        self.assertIn('path == "/api/rack-layout/topology" and method == "GET"', router)
        self.assertIn('path == "/api/rack-layout/topology/positions" and method == "POST"', router)
        self.assertIn('len(parts) == 6 and parts[5] == "ports" and method == "POST"', router)
        self.assertIn('len(parts) == 7 and parts[5] == "ports" and parts[6] == "import" and method == "POST"', router)
        self.assertIn("self.device_topology.create_cable(", router)
        self.assertIn("self.device_topology.import_ports_from_template(", router)
        self.assertIn("self._read_context(handler, \"rack_layout\")", router)
        self.assertIn("self._write_context(handler, \"rack_layout\", \"create\")", router)

    def test_service_validates_endpoints_and_keeps_audit_trail(self):
        service = (ROOT / "office_asset" / "device_topology.py").read_text(encoding="utf-8")
        endpoint_check = service.split("    def _validate_cable_endpoints(", 1)[1].split(
            "\n    def _validate_cable_payload(",
            1,
        )[0]
        remove_port = service.split("    def remove_port(", 1)[1].split(
            "\n    def import_ports_from_template(",
            1,
        )[0]

        self.assertIn("链路两端不能是同一个端口", endpoint_check)
        self.assertIn("已经连接到", endpoint_check)
        for action in (
            "device_type_saved",
            "placement_ports_initialized",
            "rack_port_created",
            "rack_port_updated",
            "rack_port_removed",
            "rack_cable_created",
            "rack_cable_updated",
            "rack_cable_removed",
            "topology_positions_saved",
        ):
            self.assertIn(action, service)
        # 删除端口会级联删除它的链路，并写审计而不是留下悬挂链路。
        self.assertIn("DELETE FROM rack_cable_run", remove_port)
        self.assertIn("DELETE FROM rack_device_port", remove_port)
        # 上架/端口操作都不改库存与台账记录。
        self.assertNotIn("UPDATE computer_asset", service)
        self.assertNotIn("quantity = quantity", service)

    def test_vue_pages_replaced_the_legacy_rack_layout_page(self):
        navigation = (ROOT / "frontend" / "src" / "navigation.ts").read_text(encoding="utf-8")
        router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")

        self.assertIn('page: "rackLayout", path: "/rack-layout"', navigation)
        self.assertIn('page: "devicePanel", path: "/device-panel"', navigation)
        self.assertIn('page: "topology", path: "/topology"', navigation)
        self.assertIn("RackLayoutView", router)
        self.assertIn("DevicePanelView", router)
        self.assertIn("TopologyView", router)
        self.assertIn("VIEW_LOADERS", router)
        for name in ("RackLayoutView.vue", "DevicePanelView.vue", "TopologyView.vue"):
            self.assertTrue((ROOT / "frontend" / "src" / "views" / name).exists(), name)
        self.assertIn("createCable", (ROOT / "frontend" / "src" / "views" / "DevicePanelView.vue").read_text(encoding="utf-8"))
        self.assertIn("saveTopologyPositions", (ROOT / "frontend" / "src" / "views" / "TopologyView.vue").read_text(encoding="utf-8"))
        self.assertIn("availableDevices", (ROOT / "frontend" / "src" / "views" / "RackLayoutView.vue").read_text(encoding="utf-8"))
        # 旧前端整体删除，避免两套实现并存
        self.assertFalse((ROOT / "web" / "app.js").exists())
        self.assertFalse((ROOT / "web" / "index.html").exists())

    def test_health_check_counts_the_new_tables(self):
        server_source = (ROOT / "server.py").read_text(encoding="utf-8")

        for table in (
            "device_type_catalog",
            "device_type_port_template",
            "rack_device_port",
            "rack_cable_run",
            "topology_node_position",
            "datacenter_device",
        ):
            self.assertIn(f"'{table}'", server_source)
        self.assertIn("required_table_count = 70", server_source)


class DatacenterDeviceLedgerRegressionTests(TestCase):
    def test_migration_adds_datacenter_ledger_and_placement_source(self):
        migration = (
            ROOT / "database" / "migrations" / "20260918_004_datacenter_devices.sql"
        ).read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS datacenter_device", migration)
        self.assertIn(
            "CHECK (status IN ('stock', 'installed', 'repair', 'scrapped'))",
            migration,
        )
        self.assertIn("ADD COLUMN datacenter_device_id BIGINT UNSIGNED NULL", migration)
        self.assertIn(
            "ADD UNIQUE KEY uq_rack_placement_datacenter (datacenter_device_id)",
            migration,
        )
        self.assertIn("CHECK (source_kind IN ('computer', 'custom', 'datacenter'))", migration)
        self.assertIn("information_schema.columns", migration)
        self.assertIn("information_schema.table_constraints", migration)
        self.assertNotIn("DROP TABLE", migration.upper())
        self.assertNotIn("DELETE FROM", migration.upper())
        self.assertNotIn("ALTER TABLE computer_asset", migration)

    def test_rack_palette_only_offers_datacenter_devices(self):
        service = (ROOT / "office_asset" / "rack_layout.py").read_text(encoding="utf-8")
        available = service.split("    def available_devices(", 1)[1].split(
            "\n    # ------------------------------------------------------------------- writes",
            1,
        )[0]

        self.assertIn("FROM datacenter_device device", available)
        self.assertIn("device.status = 'stock'", available)
        self.assertIn("placement.placement_id IS NULL", available)
        # 办公终端与 IT 物资不再出现在未上架设备里
        self.assertNotIn("computer_asset", available)
        self.assertNotIn("it_inventory_model", available)
        self.assertNotIn("inventoryModels", available)

    def test_placing_and_removing_sync_the_device_status(self):
        service = (ROOT / "office_asset" / "rack_layout.py").read_text(encoding="utf-8")
        place_device = service.split("    def place_device(", 1)[1].split(
            "\n    def update_placement(",
            1,
        )[0]
        remove_placement = service.split("    def remove_placement(", 1)[1]

        self.assertIn("'datacenter'", place_device)
        self.assertIn("只有“未上架”的设备可以上架", place_device)
        # 办公终端与 IT 物资不再参与机柜上架
        self.assertNotIn("computerId", place_device)
        self.assertNotIn("inventoryModelId", place_device)
        self.assertIn("请选择要上架的机房设备", place_device)
        self.assertIn("该机房设备已经在某个机柜上架", place_device)
        self.assertIn("SET status = 'installed'", place_device)
        self.assertIn("datacenter_device_id", place_device)
        # 下架后回到未上架并清空位置
        self.assertIn("SET status = 'stock'", remove_placement)
        self.assertIn("rack_id = NULL", remove_placement)
        self.assertIn("site_id = NULL", remove_placement)
        self.assertIn("'datacenterDeviceId'", remove_placement)

    def test_datacenter_device_service_guards_status_and_placement(self):
        service = (ROOT / "office_asset" / "datacenter_devices.py").read_text(encoding="utf-8")

        self.assertIn('STATUSES = {"stock", "installed", "repair", "scrapped"}', service)
        self.assertIn("“上架”状态由机柜视图的上架操作设置", service)
        self.assertIn("请先在机柜视图下架再改回未上架", service)
        self.assertIn("设备仍在机柜里，请先在机柜视图下架", service)
        for action in (
            "datacenter_device_created",
            "datacenter_device_updated",
            "datacenter_device_removed",
        ):
            self.assertIn(action, service)
        # 台账只新增自己的表，不写办公终端与 IT 物资
        self.assertNotIn("UPDATE computer_asset", service)
        self.assertNotIn("INSERT INTO computer_asset", service)

    def test_datacenter_routes_and_vue_page_are_wired(self):
        router_py = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")
        navigation = (ROOT / "frontend" / "src" / "navigation.ts").read_text(encoding="utf-8")
        vue_router = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")

        self.assertIn('path == "/api/datacenter-devices" and method == "GET"', router_py)
        self.assertIn('path == "/api/datacenter-devices" and method == "POST"', router_py)
        self.assertIn('len(parts) == 6 and parts[5] == "remove" and method == "POST"', router_py)
        self.assertIn("self.datacenter_devices.", router_py)
        # 机房管理分组：四个页面 + 设备台账
        self.assertIn('group: "机房管理"', navigation)
        self.assertIn('page: "datacenterDevices"', navigation)
        self.assertIn('path: "/datacenter-devices"', navigation)
        self.assertIn('title: "机房巡检", group: "机房管理"', navigation)
        self.assertIn('NAV_GROUPS = ["资产台账", "机房管理"', navigation)
        self.assertIn("DatacenterDeviceView", vue_router)
        self.assertTrue(
            (ROOT / "frontend" / "src" / "views" / "DatacenterDeviceView.vue").exists()
        )
        self.assertNotIn('page: "inspection", path: "/inspection", title: "机房巡检", group: "资源与审计"', navigation)


def build_test_xlsx(rows: list[list[object]], *, inline: bool = False) -> bytes:
    """Build a minimal .xlsx workbook for the importer tests."""
    import zipfile

    def column_name(index: int) -> str:
        name = ""
        index += 1
        while index:
            index, remainder = divmod(index - 1, 26)
            name = chr(ord("A") + remainder) + name
        return name

    shared: list[str] = []
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row):
            reference = f"{column_name(column_index)}{row_index}"
            if value is None or value == "":
                continue
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            elif inline:
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'
                )
            else:
                if str(value) not in shared:
                    shared.append(str(value))
                cells.append(f'<c r="{reference}" t="s"><v>{shared.index(str(value))}</v></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared)}" '
        f'uniqueCount="{len(shared)}">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared)
        + "</sst>"
    )
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
        if not inline:
            archive.writestr("xl/sharedStrings.xml", shared_xml)
    return buffer.getvalue()


class DatacenterImportRegressionTests(TestCase):
    def _service(self) -> DatacenterDeviceService:
        gateway = SimpleNamespace(
            text=lambda value: "" if value is None else str(value).strip(),
            integer=lambda value, default=0: int(value)
            if str(value if value is not None else "").strip().lstrip("-").isdigit()
            else default,
            quote=lambda value: "'" + str(value).replace("'", "''") + "'",
        )
        return DatacenterDeviceService(
            db=gateway,  # type: ignore[arg-type]
            scope=SimpleNamespace(),
            api_error=ValueError,
            conflict_error=ValueError,
            forbidden_error=ValueError,
        )

    def test_xlsx_reader_handles_shared_and_inline_strings(self):
        rows = [
            ["设备编号", "设备名称", "占用高度"],
            ["SW-A01", "核心交换机", 1],
            ["SRV-A01", "服务器", 2],
        ]
        for inline in (False, True):
            parsed = read_sheet(build_test_xlsx(rows, inline=inline))
            self.assertEqual(parsed[0], ["设备编号", "设备名称", "占用高度"])
            self.assertEqual(parsed[1], ["SW-A01", "核心交换机", "1"])
            self.assertEqual(parsed[2], ["SRV-A01", "服务器", "2"])

    def test_xlsx_reader_rejects_invalid_input(self):
        with self.assertRaises(WorkbookError):
            read_sheet(b"not a spreadsheet")
        with self.assertRaises(WorkbookError):
            read_sheet(build_test_xlsx([["a"]], inline=True), sheet_name="不存在的工作表")

    def test_upload_only_accepts_xlsx_and_csv(self):
        service = self._service()
        with self.assertRaises(ValueError):
            service._read_upload("devices.txt", b"whatever")
        rows = service._read_upload("devices.csv", "设备编号,设备名称\nSW-A01,核心交换机\n".encode("utf-8-sig"))
        self.assertEqual(rows[1], ["SW-A01", "核心交换机"])

    def test_header_aliases_and_row_validation(self):
        service = self._service()
        mapping = service._map_headers(["设备编号", "设备名", "型号", "类型", "U高", "SN", "固资编码", "责任人", "状态", "备注"])
        self.assertEqual(mapping["code"], 0)
        self.assertEqual(mapping["name"], 1)
        self.assertEqual(mapping["brandModel"], 2)
        self.assertEqual(mapping["category"], 3)
        self.assertEqual(mapping["uHeight"], 4)
        self.assertEqual(mapping["serialNumber"], 5)
        self.assertEqual(mapping["assetCode"], 6)
        self.assertEqual(mapping["ownerLabel"], 7)
        self.assertEqual(mapping["status"], 8)
        self.assertEqual(mapping["notes"], 9)

        record, problems = service._row_to_payload(
            ["SW-A01", "核心交换机", "华为 S5731", "交换机", "2U", "SN123", "FA-1", "机房公用", "未上架", "A 柜"],
            mapping,
        )
        self.assertEqual(problems, [])
        self.assertEqual(record["category"], "network")
        self.assertEqual(record["uHeight"], 2)
        self.assertEqual(record["status"], "stock")

        _, problems = service._row_to_payload(
            ["SW-A02", "交换机", "", "不认识的类型", "0", "", "", "", "上架", ""],
            mapping,
        )
        self.assertTrue(any("无法识别" in item for item in problems), problems)
        self.assertTrue(any("超出 1-50U" in item for item in problems), problems)
        self.assertTrue(any("不能是「上架」" in item for item in problems), problems)

        _, missing = service._row_to_payload(["", "", "", "", "", "", "", "", "", ""], mapping)
        self.assertIn("缺少设备编号", missing)
        self.assertIn("缺少设备名称", missing)

    def test_alias_tables_cover_chinese_headers(self):
        self.assertIn("设备编号", HEADER_ALIASES["code"])
        self.assertIn("品牌型号", HEADER_ALIASES["brandModel"])
        self.assertEqual(CATEGORY_ALIASES["交换机"], "network")
        self.assertEqual(CATEGORY_ALIASES["ups"], "power")
        self.assertEqual(CATEGORY_ALIASES["patchpanel"], "patch-panel")
        self.assertEqual(STATUS_ALIASES["报废"], "scrapped")
        self.assertEqual(STATUS_ALIASES["未上架"], "stock")

    def test_service_import_writes_audit_and_reports_errors(self):
        service_source = (ROOT / "office_asset" / "datacenter_devices.py").read_text(encoding="utf-8")
        self.assertIn("def import_workbook(", service_source)
        self.assertIn("datacenter_device_imported", service_source)
        self.assertIn("MAX_IMPORT_ROWS", service_source)
        self.assertIn("base64.b64decode", service_source)
        self.assertIn('mode not in {"skip", "update"}', service_source)
        self.assertIn("contentBase64", service_source)

    def test_import_route_and_ui_are_wired(self):
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "DatacenterDeviceView.vue").read_text(encoding="utf-8")
        client = (ROOT / "frontend" / "src" / "api" / "datacenter.ts").read_text(encoding="utf-8")

        self.assertIn('path == "/api/datacenter-devices/import" and method == "POST"', router)
        self.assertIn("self.datacenter_devices.import_workbook(", router)
        self.assertIn("importDatacenterDevices", client)
        self.assertIn("/api/datacenter-devices/import", client)
        self.assertIn("导入 Excel", view)
        self.assertIn("下载模板", view)
        self.assertIn("dryRun: true", view)
        self.assertIn('accept=".xlsx,.xlsm,.csv"', view)


class StageThreeRegressionTests(TestCase):
    """阶段 3：面板图片、多机柜并排、拓扑坐标保存。"""

    def test_panel_image_upload_validates_and_stores_images(self):
        from office_asset.device_topology import (
            IMAGE_DIR,
            MAX_IMAGE_BYTES,
            detect_image_extension,
        )

        self.assertEqual(detect_image_extension(b"\x89PNG\r\n\x1a\n" + b"rest"), "png")
        self.assertEqual(detect_image_extension(b"\xff\xd8\xff\xe0" + b"rest"), "jpg")
        self.assertEqual(detect_image_extension(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "webp")
        with self.assertRaises(ValueError):
            detect_image_extension(b"GIF89a")
        self.assertIn("device-images", str(IMAGE_DIR))
        self.assertEqual(MAX_IMAGE_BYTES, 2 * 1024 * 1024)

        service = (ROOT / "office_asset" / "device_topology.py").read_text(encoding="utf-8")
        self.assertIn("def save_device_type_image(", service)
        self.assertIn("def remove_device_type_image(", service)
        self.assertIn("device_type_image_saved", service)
        self.assertIn("device_type_image_removed", service)
        # 只接受浏览器能直接显示的三种格式，并在替换时清掉旧文件
        self.assertIn("只支持 PNG、JPEG 或 WebP 图片", service)
        self.assertIn('folder.glob(f"{slug}.{face}.*")', service)

    def test_panel_image_routes_and_ui_are_wired(self):
        router = (ROOT / "office_asset" / "api_router.py").read_text(encoding="utf-8")
        client = (ROOT / "frontend" / "src" / "api" / "datacenter.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "DevicePanelView.vue").read_text(encoding="utf-8")

        self.assertIn('parts[4] == "image" and method == "POST"', router)
        self.assertIn('parts[5] == "remove" and method == "POST"', router)
        self.assertIn("save_device_type_image(", router)
        self.assertIn("remove_device_type_image(", router)
        self.assertIn("uploadDeviceTypeImage", client)
        self.assertIn("removeDeviceTypeImage", client)
        self.assertIn("型号与面板图", view)
        self.assertIn("hasPanelImage", view)
        self.assertIn("imageFailed", view)
        self.assertIn('accept="image/png,image/jpeg,image/webp"', view)
        self.assertIn("显示面板图", view)

    def test_multi_rack_side_by_side_view(self):
        view = (ROOT / "frontend" / "src" / "views" / "RackLayoutView.vue").read_text(encoding="utf-8")

        self.assertIn('viewMode = ref<"single" | "side">("single")', view)
        self.assertIn("loadSideBySide", view)
        self.assertIn("openInSingleView", view)
        self.assertIn("side-by-side", view)
        self.assertIn("并排", view)
        self.assertIn("deviceTopOf", view)
        # 并排视图是只读展示，编辑仍回到单柜视图
        self.assertIn("@click=\"openInSingleView(item.id, placement.id)\"", view)

    def test_topology_positions_can_be_dragged_and_saved(self):
        view = (ROOT / "frontend" / "src" / "views" / "TopologyView.vue").read_text(encoding="utf-8")
        service = (ROOT / "office_asset" / "device_topology.py").read_text(encoding="utf-8")

        self.assertIn("saveTopologyPositions", view)
        self.assertIn("onNodePointerDown", view)
        self.assertIn("有未保存的拖动", view)
        self.assertIn("def save_topology_positions(", service)
        self.assertIn("topology_node_position", service)
        self.assertIn("topology_positions_saved", service)


class InspectionEntryRegressionTests(TestCase):
    """巡检执行页：填写即暂存、单行保存、提交前列出未填项。"""

    def test_inspection_rows_have_save_button_and_keep_unsaved_input(self):
        view = (ROOT / "frontend" / "src" / "views" / "InspectionView.vue").read_text(
            encoding="utf-8"
        )

        # 每个检查项单独保存；表单状态本地维护，保存后只刷新受影响的行
        self.assertIn("saveItem(item.id)", view)
        self.assertIn("itemForms", view)
        self.assertIn("isItemDirty", view)
        self.assertIn("unsavedItems", view)
        self.assertIn("检查项已保存。", view)
        # 顶部进度同时给出「未检查」与「未保存」计数
        self.assertIn("未检查 {{ pendingItems.length }}", view)
        self.assertIn("未保存 {{ unsavedItems.length }}", view)

    def test_submit_lists_pending_items_by_name(self):
        service = (ROOT / "office_asset" / "inspection.py").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "InspectionView.vue").read_text(
            encoding="utf-8"
        )

        self.assertIn("请补全后再提交：{names}", service)
        self.assertIn("异常项未填写说明，请补全后再提交：{names}", service)
        # 前端提交前先提醒"填了内容但没点保存"的行，并列出具体条目名
        self.assertIn("填了内容但没点「保存」", view)
        self.assertIn("请逐项选择结论并点该行「保存」。", view)

    def test_inventory_list_shows_warehouse_quantity_column(self):
        view = (ROOT / "frontend" / "src" / "views" / "InventoryView.vue").read_text(
            encoding="utf-8"
        )
        tokens = (ROOT / "frontend" / "src" / "styles" / "tokens.css").read_text(
            encoding="utf-8"
        )

        # 物资目录树按仓库展示数量，型号行给出品牌/型号/批次等元信息
        self.assertIn('<el-table-column label="库存数量"', view)
        self.assertIn("modelMeta(row)", view)
        self.assertIn("当前仓库", view)
        # 数值列使用等宽数字，长文本在公共令牌里统一截断
        # 数值列用等宽数字：类名要和 tokens.css 里的定义一致，否则样式是死的
        self.assertIn("oa-tabular", view)
        self.assertIn(".oa-tabular", tokens)

    def test_vue_inspection_view_prevents_silent_pending_items(self):
        view = (ROOT / "frontend" / "src" / "views" / "InspectionView.vue").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api" / "governance.ts").read_text(encoding="utf-8")

        # 异常选项必须与后端 fail 一致，否则选异常会 400
        self.assertIn('{ value: "fail", label: "异常" }', api)
        self.assertNotIn('value: "abnormal"', api)
        # 未检查的项不预选结论
        self.assertIn('item.result && item.result !== "pending" ? item.result : ""', view)
        self.assertIn('placeholder="请选择结论"', view)
        # 行内状态与提交前提醒
        self.assertIn("未检查", view)
        self.assertIn("未保存", view)
        self.assertIn("请先选择结论（正常 / 异常 / 不适用）再保存。", view)
        self.assertIn("const pendingItems = computed(", view)
        self.assertIn("const unsavedItems = computed(", view)
        self.assertIn("还有 ${pending.length} 项未保存结论", view)

    def test_vue_inventory_view_levels_and_quantity_column(self):
        view = (ROOT / "frontend" / "src" / "views" / "InventoryView.vue").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api" / "inventory.ts").read_text(encoding="utf-8")

        self.assertIn("inventoryRowLevel(row)", view)
        self.assertIn('共 ', view)
        # 三层目录：类型行给品牌/型号汇总，品牌行给型号数，
        # 型号行只把配置 / 批次 / 入库日期合并成一行补充说明（不再给每行挂层级标签）。
        self.assertIn("function modelMeta(row:", view)
        self.assertIn("function typeSummary(row:", view)
        self.assertIn("function brandSummary(row:", view)
        self.assertIn('v-if="modelMeta(row)"', view)
        # 只有电脑类物资才有配置 / 批次 / 入库日期，普通物资保持一行，避免参差不齐。
        self.assertIn("if (!isComputerType(String(row.typeId ?? \"\"))) return \"\";", view)
        # 每一级都排在上一级下面：类型按名称，品牌与型号先按 sortOrder 再按名称，
        # 不能沿用接口按主键返回的顺序（那就是“乱排序”）。
        self.assertIn("function sortInventoryRefs(", api)
        self.assertIn("byOrderThenName(data.brands)", api)
        self.assertIn("byOrderThenName(data.models)", api)
        self.assertIn('localeCompare(String(b || ""), "zh-CN"', api)
        # 三层的自增主键会互相撞车（类型 22 与品牌 22 同号），row-key 必须带层级前缀，
        # 否则 el-table 的树会把行挂到别的层级上。
        self.assertIn('key: `type:${type.id}`', api)
        self.assertIn('key: `brand:${brand.id}`', api)
        self.assertIn('key: `model:${model.id}`', api)
        self.assertIn('row-key="key"', view)
        # 默认摊开类型与品牌，筛选时强制展开命中的分支
        self.assertIn("expandedKeys.value = allKeys.value", view)
        self.assertIn("effectiveExpandKeys", view)
        # 缩进要真的落到内容上：el-table 的缩进是 .cell 里的行内元素，
        # 插槽内容若用块级 div 会另起一行，看起来就是「所有层级都不缩进」。
        self.assertIn(':indent="32"', view)
        self.assertIn("display: inline-flex", view)

    def test_inventory_tree_levels_and_units_are_explicit(self):
        """层级与单位要显式写在树节点上，不能靠“有没有 unit”猜层级。"""
        api = (ROOT / "frontend" / "src" / "api" / "inventory.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "InventoryView.vue").read_text(encoding="utf-8")

        self.assertIn('level: "type" as const', api)
        self.assertIn('level: "brand" as const', api)
        self.assertIn('level: "model" as const', api)
        self.assertIn("typeId: type.id", api)
        self.assertIn("brandId: brand.id", api)
        # 类型、品牌、型号都带上类型单位，避免“类型显示台、型号显示件”。
        self.assertEqual(api.count('unit: type.unit || "件"'), 3)
        # 品牌即使当前仓库没有在库型号也要保留，否则新建的品牌会“消失”。
        self.assertNotIn(".filter((brand) => brand.children.length > 0)", api)
        self.assertIn('const level = String(row.level ?? "");', view)

    def test_vue_inventory_catalog_can_be_maintained(self):
        """IT物资要能维护类型 / 品牌 / 型号，与旧前端一致。"""
        api = (ROOT / "frontend" / "src" / "api" / "inventory.ts").read_text(encoding="utf-8")
        view = (ROOT / "frontend" / "src" / "views" / "InventoryView.vue").read_text(encoding="utf-8")

        for label in ("编辑类型", "新增品牌", "编辑品牌", "新增型号"):
            self.assertIn(label, view)
        self.assertIn("function openTypeDialog(", view)
        self.assertIn("function openBrandDialog(", view)
        self.assertIn("function openModelDialog(", view)
        self.assertIn("function submitBrand(", view)
        self.assertIn("function submitModel(", view)
        # 数量维护走既有的入库 / 调整命令，不直接改库存字段。
        self.assertIn('"/api/resources/inventory-brand"', api)
        self.assertIn('"/api/resources/inventory-model"', api)
        self.assertIn('"/api/inventory/adjustments"', api)
        self.assertIn('sourceLabel: "库存型号维护入库"', view)

    def test_vue_settings_page_migrated_without_legacy_frame(self):
        """设置页不再用 iframe 承载旧前端，系统参数 / 备份 / 账号 / 权限 / 更新都在 Vue 里。"""
        view = (ROOT / "frontend" / "src" / "views" / "SettingsView.vue").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api" / "settings.ts").read_text(encoding="utf-8")

        self.assertNotIn("LegacyFrame", view)
        self.assertNotIn("LegacyFrame", api)
        for tab in ("系统参数", "安全与密码", "数据库备份", "账号管理", "角色与权限", "系统更新"):
            self.assertIn(tab, view)
        for endpoint in (
            '"/api/settings"',
            '"/api/users"',
            '"/api/backups"',
            '"/api/access-control"',
            '"/api/roles"',
            '"/api/updates/check"',
            '"/api/updates/apply"',
            '"/api/auth/change-password"',
        ):
            self.assertIn(endpoint, api)
        # 角色主键是数字、用户主键是字符串，必须统一成字符串，否则下拉框显示原始 id。
        self.assertIn("id: String(role.id)", api)
        self.assertIn("id: String(user.id)", api)
        self.assertIn("downloadFile(", api)

    def test_vue_employees_table_column_spacing(self):
        """人员清单列多，需要统一放宽列间距。"""
        view = (ROOT / "frontend" / "src" / "views" / "EmployeesView.vue").read_text(encoding="utf-8")

        self.assertIn('class="employees-table"', view)
        self.assertIn(".employees-table :deep(.el-table__cell .cell)", view)
        self.assertIn("padding: 0 14px;", view)

    def test_inspection_sites_racks_and_templates_can_be_created(self):
        """机房 / 机柜 / 巡检模板必须有新建入口。

        后端一直有 POST /api/inspection/{sites,racks,templates}，但 Vue 迁移时把入口丢了，
        表现为"机柜建不出来、页面上也没有新增按钮"。
        """
        view = (ROOT / "frontend" / "src" / "views" / "InspectionView.vue").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api" / "governance.ts").read_text(encoding="utf-8")
        rack_view = (ROOT / "frontend" / "src" / "views" / "RackLayoutView.vue").read_text(
            encoding="utf-8"
        )

        for label in ("＋ 新增机房 / 弱电间", "＋ 新增机柜", "＋ 新增模板"):
            self.assertIn(label, view)
        for name in ("saveInspectionSite", "saveInspectionRack", "saveInspectionTemplate"):
            self.assertIn(f"export async function {name}(", api)
        self.assertIn('"/api/inspection/sites"', api)
        self.assertIn('"/api/inspection/racks"', api)
        self.assertIn('"/api/inspection/templates"', api)
        # 机柜必须归属机房：前端要先拦住，别等后端 400
        self.assertIn("机柜编码、名称与所属机房必填。", view)
        # 列表接口只返回 itemCount，检查项数量不能读 items（否则永远显示 0）
        self.assertIn("row.itemCount ?? (row.items ?? []).length", view)
        # 机柜视图要能直接跳到新建机柜
        self.assertIn("/inspection?tab=sites", rack_view)
        self.assertIn('["tasks", "templates", "sites"].includes(requested)', view)

    def test_datacenter_devices_and_racks_can_be_copied(self):
        """网络设备与机柜要能"复制"复用配置：唯一字段清空，其余沿用。"""
        devices = (ROOT / "frontend" / "src" / "views" / "DatacenterDeviceView.vue").read_text(
            encoding="utf-8"
        )
        inspection = (ROOT / "frontend" / "src" / "views" / "InspectionView.vue").read_text(
            encoding="utf-8"
        )

        # 网络设备：复制入口 + 标题提示 + 唯一字段清空 + 状态回到未上架
        self.assertIn("function copyDevice(", devices)
        self.assertIn('@click="copyDevice(row)"', devices)
        self.assertIn("复制机房设备（来自 ${copyFromName}）", devices)
        self.assertIn('serialNumber: "",', devices)
        self.assertIn('assetCode: "",', devices)
        self.assertIn('status: "stock",', devices)
        # 型号库与品牌型号要沿用，否则"复制"没有意义
        self.assertIn("catalogId: device.catalogId || \"\",", devices)
        self.assertIn("brandModel: device.brandModel,", devices)

        # 机柜：复制入口 + 清空编码名称 + 沿用所属机房与高度
        self.assertIn("function copyRack(", inspection)
        self.assertIn('@click="copyRack(row)"', inspection)
        self.assertIn("复制机柜（来自 ${rackCopyFrom}）", inspection)
        self.assertIn('rackForm.code = "";', inspection)
        self.assertIn('rackForm.name = "";', inspection)
        self.assertIn("rackForm.siteId = row.siteId ?? sites.value[0]?.id ?? \"\";", inspection)
    def test_vue_employees_view_can_edit_devices_under_a_person(self):
        """使用人员清单要能像旧版一样维护人员名下的设备（办公终端 / 显示屏 / 非资产设备）。"""
        view = (ROOT / "frontend" / "src" / "views" / "EmployeesView.vue").read_text(encoding="utf-8")
        api = (ROOT / "frontend" / "src" / "api" / "employees.ts").read_text(encoding="utf-8")

        # 人员行上有入口，弹窗内有三个分区
        self.assertIn("openDeviceManager(row)", view)
        self.assertIn("设备清单 ·", view)
        self.assertIn("办公终端 ·", view)
        self.assertIn("显示屏 ·", view)
        self.assertIn("非资产设备 ·", view)

        # 分配 / 解除办公终端
        self.assertIn('@click="submitAssignComputer"', view)
        self.assertIn("@click=\"releaseComputer(row)\"", view)

        # 回收显示屏 / 非资产设备，并带回收仓库与备注
        self.assertIn("recoverUsage('monitor'", view)
        self.assertIn("recoverUsage('non_asset'", view)
        self.assertIn("回收设置（解除 / 回收时使用）", view)
        self.assertIn('@click="submitAllocate"', view)

        # 物资类型的 id 是数字主键，"monitor" 是编码，必须按编码判断显示屏。
        self.assertIn('String(type.code).toLowerCase() === "monitor"', view)
        self.assertIn("monitorTypeIds.value.has(String(model.typeId))", view)

        # 前端 API 走现有的命令接口，而不是旧的本地状态
        self.assertIn("export async function assignComputerToEmployee(", api)
        self.assertIn("export async function releaseComputerFromEmployee(", api)
        self.assertIn("export async function allocateInventoryToEmployee(", api)
        self.assertIn("export async function returnEmployeeUsage(", api)
        self.assertIn('"/api/inventory/allocations"', api)


if __name__ == "__main__":
    import unittest

    unittest.main()
