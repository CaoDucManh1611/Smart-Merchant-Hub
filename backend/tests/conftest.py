"""Test bootstrap for the repository's optional migration runtime."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _ensure_migration_dependencies() -> None:
    """Make direct ``pytest`` runs find the bundled Alembic runtime.

    Application dependencies are normally installed from requirements.txt.
    The lightweight local test image keeps migration-only packages under
    ``.migrationdeps`` instead, so collection should add that path only when
    Alembic is not already installed in the active interpreter.
    """
    # The repository's migration directory is itself named ``alembic`` but
    # is only a namespace (it has no ``config`` module), so checking the
    # submodule avoids treating that folder as the installed package.
    if importlib.util.find_spec("alembic.config") is not None:
        return
    bundled = Path(__file__).parents[1] / ".migrationdeps"
    if bundled.is_dir():
        sys.path.insert(0, str(bundled))
        # Pytest may have imported the repository's migration directory as an
        # ``alembic`` namespace package before loading this conftest. Remove
        # that placeholder so the real bundled package (with __version__) is
        # imported for the chain test.
        for module_name in list(sys.modules):
            if module_name == "alembic" or module_name.startswith("alembic."):
                del sys.modules[module_name]


_ensure_migration_dependencies()
