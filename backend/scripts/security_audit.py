"""Scan tracked files and Git history for likely credential exposure.

The scanner deliberately prints only commit/path/pattern labels, never the
matched line or value. It is a safety check, not a replacement for rotating a
credential at its provider.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("cloud-token", re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b")),
    ("password-assignment", re.compile(r'''(?i)\b(?:password|passwd)\s*[:=]\s*(?:"[^"\r\n]{8,}"|'[^'\r\n]{8,}')''')),
    ("token-assignment", re.compile(r'''(?i)\b(?:access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret)\s*[:=]\s*(?:"[^"\r\n]{8,}"|'[^'\r\n]{8,}')''')),
    ("legacy-default", re.compile(r"(?:postgres:postgres|crm_chatbot_2026)")),
)


@dataclass(frozen=True)
class Finding:
    scope: str
    location: str
    pattern: str


def _labels(text: str) -> set[str]:
    return {name for name, pattern in PATTERNS if pattern.search(text)}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


def _skip_path(path: str, *, include_tests: bool) -> bool:
    normalized = path.replace("\\", "/")
    if normalized == "backend/scripts/security_audit.py":
        return True
    return not include_tests and ("/tests/" in f"/{normalized}" or normalized.startswith("tests/"))


def scan_current(repo: Path, *, include_tests: bool) -> list[Finding]:
    result = _run("git", "ls-files", "-z")
    findings: list[Finding] = []
    for raw_path in result.stdout.split("\0"):
        if not raw_path:
            continue
        if _skip_path(raw_path, include_tests=include_tests):
            continue
        path = repo / raw_path
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label in sorted(_labels(text)):
            findings.append(Finding("working-tree", raw_path, label))
    return findings


def scan_history(*, include_tests: bool) -> list[Finding]:
    commits = _run("git", "rev-list", "--all").stdout.splitlines()
    findings: list[Finding] = []
    for commit in commits:
        paths = _run("git", "ls-tree", "-r", "--name-only", commit).stdout.splitlines()
        for path in paths:
            if _skip_path(path, include_tests=include_tests):
                continue
            # Do not attempt to decode generated/binary blobs. The scanner is
            # aimed at source and configuration files.
            if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".db", ".pyc"}:
                continue
            blob = _run("git", "show", f"{commit}:{path}")
            if blob.returncode != 0:
                continue
            for label in sorted(_labels(blob.stdout)):
                findings.append(Finding(f"commit:{commit[:12]}", path, label))
    return sorted(set(findings), key=lambda item: (item.scope, item.location, item.pattern))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit tracked files and Git history for likely secrets")
    parser.add_argument("--history", action="store_true", help="also scan every reachable Git commit")
    parser.add_argument("--include-tests", action="store_true", help="include test fixtures in the scan")
    parser.add_argument("--fail-on-findings", action="store_true")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    findings = scan_current(repo, include_tests=args.include_tests)
    if args.history:
        findings.extend(scan_history(include_tests=args.include_tests))
    findings = sorted(set(findings), key=lambda item: (item.scope, item.location, item.pattern))
    if not findings:
        print("No likely credential findings detected.")
        return 0
    print("Potential credential findings (values intentionally omitted):")
    current = [item for item in findings if not item.scope.startswith("commit:")]
    for item in current:
        print(f"- {item.scope} | {item.location} | {item.pattern}")
    history: dict[tuple[str, str], set[str]] = {}
    for item in findings:
        if item.scope.startswith("commit:"):
            history.setdefault((item.location, item.pattern), set()).add(item.scope.removeprefix("commit:"))
    for (location, pattern), commits in sorted(history.items()):
        sample = ", ".join(sorted(commits)[:3])
        suffix = f" (+{len(commits) - 3} more)" if len(commits) > 3 else ""
        print(f"- history | {location} | {pattern} | commits={len(commits)} [{sample}{suffix}]")
    return 1 if args.fail_on_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
