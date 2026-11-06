from decimal import Decimal

import pytest

from scripts.recover_reindex_quota import reconcile_values


def test_recovery_snapshot_detects_cross_database_orphan_and_metadata_mismatch():
    report = reconcile_values(14, 14, Decimal("17"))
    assert report["quota_delta"] == "-3" and not report["document_count_mismatch"]
    assert reconcile_values(14, 15, Decimal("14"))["document_count_mismatch"]
    with pytest.raises(ValueError):
        reconcile_values(-1, 0, None)
