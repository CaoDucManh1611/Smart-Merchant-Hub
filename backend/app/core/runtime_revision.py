"""Fingerprint loaded application sources for operator deployment checks."""
import hashlib
from pathlib import Path

def source_revision():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]

LOADED_REVISION = source_revision()
