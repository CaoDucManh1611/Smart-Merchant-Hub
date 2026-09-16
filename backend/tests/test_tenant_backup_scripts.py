import os
from pathlib import Path


ROOT = next(
    candidate
    for candidate in (Path(__file__).parents[1], Path(__file__).parents[2], Path(__file__).parents[0])
    if (candidate / "scripts" / "tenant-backup.ps1").is_file()
)
SCRIPT_DIR = Path(os.environ.get("ROOT_SCRIPTS", str(ROOT / "scripts")))


def test_tenant_backup_derives_schema_and_checks_archive_and_native_exit():
    script = (SCRIPT_DIR / "tenant-backup.ps1").read_text(encoding="utf-8")
    assert "[ValidateRange(1, 2147483647)]" in script
    assert '$schema = "shop_$BusinessId"' in script
    assert '"--schema=$schema"' in script
    assert '"--exit-on-error"' in script
    assert "Assert-Archive -Path $BackupFile" in script
    assert "Get-FileHash" in script
    assert "alembic_revision" in script
    assert "server_major_version" in script
    assert "SHOW server_version_num" in script
    assert "SELECT version_num FROM" in script
    assert "table_count" in script
    assert "table_checksums" in script
    assert "row_to_json" in script


def test_tenant_restore_is_non_destructive_by_default_and_validates_manifest():
    script = (SCRIPT_DIR / "tenant-restore-verify.ps1").read_text(encoding="utf-8")
    assert '$schema = "shop_$BusinessId"' in script
    assert "TENANT_VERIFY_DATABASE_URL" in script
    assert "--clean" in script and "--if-exists" in script
    assert "if ($Overwrite)" in script
    assert "checksum" in script.lower()
    assert "Manifest does not match" in script or "manifest.business_id" in script
    assert "--exit-on-error" in script
    assert "ManifestFile is required" in script
    assert "server_major_version" in script
    assert "alembic_revision" in script
    assert "table_count" in script
    assert "table_checksums" in script
    assert "row_to_json" in script


def test_platform_backup_writes_a_versioned_manifest():
    script = (SCRIPT_DIR / "backup-verify.ps1").read_text(encoding="utf-8")
    assert "backup_type = \"platform\"" in script
    assert "server_major_version" in script
    assert "alembic_revision" in script
    assert "Get-FileHash" in script


def test_platform_restore_requires_manifest_and_matches_database_revision():
    script = (SCRIPT_DIR / "backup-verify.ps1").read_text(encoding="utf-8")
    assert "ManifestFile is required for a verified platform restore" in script
    assert "backup_type" in script
    assert "server_major_version" in script
    assert "alembic_revision" in script
    assert "SHOW server_version_num" in script
