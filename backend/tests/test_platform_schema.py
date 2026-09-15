from sqlalchemy import CheckConstraint, UniqueConstraint

from app.database.bases import PlatformBase
from app.models.channel_route import ChannelRoute
from app.models.platform_control import ProvisioningOperation, SupportGrant, TenantRegistry


def _unique_columns(table):
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_control_plane_has_required_unique_constraints_and_states():
    assert ("business_id",) in _unique_columns(TenantRegistry.__table__)
    assert ("schema_name",) in _unique_columns(TenantRegistry.__table__)
    assert ("provider", "external_account_id_hash") in _unique_columns(ChannelRoute.__table__)
    assert ("idempotency_key",) in _unique_columns(ProvisioningOperation.__table__)

    registry_checks = [c.sqltext.text for c in TenantRegistry.__table__.constraints if isinstance(c, CheckConstraint)]
    assert any("provisioning" in check and "ready" in check and "error" in check for check in registry_checks)


def test_platform_metadata_contains_no_customer_content_tables_or_columns():
    forbidden_tables = {"customers", "messages", "orders", "documents", "document_chunks"}
    assert not forbidden_tables.intersection(PlatformBase.metadata.tables)

    forbidden_columns = {"message_content", "customer_payload", "document_content", "access_token"}
    platform_columns = {
        column.name
        for table in PlatformBase.metadata.tables.values()
        for column in table.columns
    }
    assert not forbidden_columns.intersection(platform_columns)
    assert {"business_id", "reason", "scopes", "expires_at"} <= set(SupportGrant.__table__.columns.keys())
