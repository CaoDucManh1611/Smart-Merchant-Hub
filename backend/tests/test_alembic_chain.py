import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from alembic.config import Config
from alembic.script import ScriptDirectory


class AlembicChainTests(unittest.TestCase):
    def test_platform_migration_ledger_is_idempotent_for_bootstrapped_database(self):
        migration_path = (
            Path(__file__).parents[1]
            / "alembic_platform"
            / "versions"
            / "20260915_0004_tenant_migration_operations.py"
        )
        spec = spec_from_file_location("platform_ledger_migration", migration_path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        inspector = SimpleNamespace(
            get_table_names=lambda: ["tenant_migration_operations"],
            get_indexes=lambda _table: [
                {"name": "ix_tenant_migration_operations_business_id"}
            ],
        )

        with (
            patch.object(module.op, "get_bind", return_value=object()),
            patch.object(module.sa, "inspect", return_value=inspector),
            patch.object(module.op, "create_table") as create_table,
            patch.object(module.op, "create_index") as create_index,
        ):
            module.upgrade()

        create_table.assert_not_called()
        create_index.assert_not_called()

    def test_baseline_bootstraps_legacy_and_tenant_tables(self):
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260903_0001_baseline.py"
        )
        spec = spec_from_file_location("baseline_migration", migration_path)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        with (
            patch.object(module.op, "get_bind", return_value=bind),
            patch.object(module.Base.metadata, "create_all") as create_legacy,
            patch.object(module.TenantBase.metadata, "create_all") as create_tenant,
        ):
            module.upgrade()

        create_legacy.assert_called_once_with(bind=bind)
        create_tenant.assert_called_once_with(bind=bind)

    def test_baseline_and_default_business_migrations_form_single_head(self):
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        scripts = ScriptDirectory.from_config(config)

        self.assertEqual(["20260922_0054"], scripts.get_heads())
        self.assertEqual("20260919_0045", scripts.get_revision("20260919_0046").down_revision)
        self.assertEqual("20260919_0044", scripts.get_revision("20260919_0045").down_revision)
        self.assertEqual("20260919_0043", scripts.get_revision("20260919_0044").down_revision)
        self.assertEqual("20260913_0042", scripts.get_revision("20260919_0043").down_revision)
        self.assertEqual("20260911_0036", scripts.get_revision("20260911_0037").down_revision)
        self.assertEqual("20260911_0037", scripts.get_revision("20260911_0038").down_revision)
        self.assertEqual("20260911_0038", scripts.get_revision("20260912_0039").down_revision)
        self.assertEqual("20260912_0039", scripts.get_revision("20260912_0040").down_revision)
        self.assertEqual("20260912_0040", scripts.get_revision("20260912_0041").down_revision)
        self.assertEqual("20260904_0013", scripts.get_revision("20260904_0014").down_revision)
        self.assertEqual("20260904_0012", scripts.get_revision("20260904_0013").down_revision)
        self.assertEqual("20260904_0011", scripts.get_revision("20260904_0012").down_revision)
        self.assertEqual("20260904_0010", scripts.get_revision("20260904_0011").down_revision)
        self.assertEqual("20260904_0009", scripts.get_revision("20260904_0010").down_revision)
        self.assertEqual("20260903_0008", scripts.get_revision("20260904_0009").down_revision)
        self.assertEqual("20260903_0007", scripts.get_revision("20260903_0008").down_revision)
        self.assertEqual("20260903_0006", scripts.get_revision("20260903_0007").down_revision)
        self.assertEqual("20260903_0001", scripts.get_revision("20260903_0002").down_revision)
        self.assertIsNone(scripts.get_revision("20260903_0001").down_revision)


if __name__ == "__main__":
    unittest.main()
