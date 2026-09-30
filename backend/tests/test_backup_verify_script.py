import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest


POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
SCRIPT = Path(__file__).parents[2] / "scripts" / "backup-verify.ps1"


def _sandbox() -> Path:
    path = Path(__file__).parents[1] / "test_data" / f"backup-verify-{uuid4().hex}"
    path.mkdir(parents=True)
    return path


def _write_command(directory: Path, name: str, exit_code: int) -> None:
    (directory / f"{name}.cmd").write_text(
        f"@echo off\r\nexit /b {exit_code}\r\n",
        encoding="ascii",
    )


def _run(directory: Path, *arguments: str, database_url: str | None = None):
    environment = os.environ.copy()
    environment["PATH"] = str(directory) + os.pathsep + environment.get("PATH", "")
    if database_url is not None:
        environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *arguments,
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_verify_only_never_reports_success_when_pg_restore_fails():
    directory = _sandbox()
    try:
        archive = directory / "broken.dump"
        archive.write_bytes(b"not-a-postgres-archive")
        _write_command(directory, "pg_restore", 17)

        result = _run(directory, "-BackupFile", str(archive), "-VerifyOnly")

        assert result.returncode != 0
        assert "exit code 17" in (result.stdout + result.stderr)
        assert "Backup archive is readable" not in result.stdout
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_verify_only_reports_success_after_zero_native_exit_code():
    directory = _sandbox()
    try:
        archive = directory / "readable.dump"
        archive.write_bytes(b"test fixture")
        _write_command(directory, "pg_restore", 0)

        result = _run(directory, "-BackupFile", str(archive), "-VerifyOnly")

        assert result.returncode == 0
        assert "Backup archive is readable" in result.stdout
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_backup_never_reports_success_when_pg_dump_fails():
    directory = _sandbox()
    try:
        archive = directory / "output.dump"
        _write_command(directory, "pg_restore", 0)
        _write_command(directory, "pg_dump", 23)

        result = _run(
            directory,
            "-BackupFile",
            str(archive),
            database_url="postgresql://crm:private@db/staging",
        )

        assert result.returncode != 0
        assert "exit code 23" in (result.stdout + result.stderr)
        assert "Backup created and verified" not in result.stdout
    finally:
        shutil.rmtree(directory, ignore_errors=True)
