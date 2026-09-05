import unittest
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


class AlembicChainTests(unittest.TestCase):
    def test_baseline_and_default_business_migrations_form_single_head(self):
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        scripts = ScriptDirectory.from_config(config)

        self.assertEqual(["20260905_0023"], scripts.get_heads())
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
