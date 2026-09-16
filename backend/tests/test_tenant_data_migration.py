"""Deterministic, resumable per-shop migration contracts."""

from app.services.tenant_data_migration import (
    MigrationReport,
    checksum_rows,
    copy_rows,
)
from app.services.tenant_cutover_service import migrate_business
from app.services.tenant_cutover_service import DEFAULT_TABLE_ORDER
from app.services import tenant_cutover_service as cutover
from app.database.bases import PlatformBase, TenantBase
from app.models import platform_control
from app.models.platform_control import PlatformBusiness, TenantRegistry
from app.services.tenant_data_migration import TableMigrationResult
from pathlib import Path
from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table, create_engine, select
from sqlalchemy.orm import Session


def test_checksum_is_deterministic_and_order_independent():
    rows = [{"id": 2, "name": "B"}, {"id": 1, "name": "A"}]
    assert checksum_rows(rows) == checksum_rows(list(reversed(rows)))


def test_copy_rows_is_resumable_and_dry_run_does_not_write():
    writes: list[dict] = []
    first = copy_rows(
        rows=[{"id": 1}, {"id": 2}],
        write_row=writes.append,
        cursor=None,
        dry_run=True,
    )
    assert isinstance(first, MigrationReport)
    assert first.rows_copied == 2
    assert writes == []

    second = copy_rows(
        rows=[{"id": 1}, {"id": 2}, {"id": 3}],
        write_row=writes.append,
        cursor=2,
        dry_run=False,
    )
    assert second.rows_copied == 1
    assert writes == [{"id": 3}]


def test_migrate_business_filters_child_rows_through_tenant_parent():
    source_engine = create_engine("sqlite://")
    destination_engine = create_engine("sqlite://")
    source_metadata = MetaData()
    Table("orders", source_metadata, Column("id", Integer, primary_key=True), Column("business_id", Integer))
    Table("order_items", source_metadata, Column("id", Integer, primary_key=True), Column("order_id", Integer))
    source_metadata.create_all(source_engine)
    destination_metadata = MetaData()
    Table("orders", destination_metadata, Column("id", Integer, primary_key=True), Column("business_id", Integer))
    Table("order_items", destination_metadata, Column("id", Integer, primary_key=True), Column("order_id", Integer))
    destination_metadata.create_all(destination_engine)
    with Session(source_engine) as source_db, Session(destination_engine) as tenant_db:
        source_db.execute(source_metadata.tables["orders"].insert(), [
            {"id": 1, "business_id": 7}, {"id": 2, "business_id": 8}
        ])
        source_db.execute(source_metadata.tables["order_items"].insert(), [
            {"id": 11, "order_id": 1}, {"id": 12, "order_id": 2}
        ])
        source_db.commit()
        results = migrate_business(
            source_db,
            tenant_db,
            business_id=7,
            tables=("orders", "order_items"),
        )
        tenant_db.commit()
        assert [item.table for item in results] == ["orders", "order_items"]
        assert tenant_db.execute(destination_metadata.tables["orders"].select()).mappings().all() == [{"id": 1, "business_id": 7}]
        assert tenant_db.execute(destination_metadata.tables["order_items"].select()).mappings().all() == [{"id": 11, "order_id": 1}]


def test_migration_cli_exposes_explicit_non_destructive_rollback():
    source = (Path(__file__).parents[1] / "app" / "scripts" / "migrate_tenant.py").read_text(encoding="utf-8")
    assert '"--rollback"' in source
    assert "rollback_cutover" in source
    assert '"--cutover"' in source
    assert "if args.complete and not args.cutover" in source
    assert "operation_id=args.operation_id" in source
    assert "a write migration requires explicit --cutover approval" in source


def test_migration_order_covers_every_tenant_table():
    import app.models  # noqa: F401 - register all tenant models

    assert set(TenantBase.metadata.tables).issubset(set(DEFAULT_TABLE_ORDER))


def test_migrate_business_filters_webhook_and_assignment_children():
    source_engine = create_engine("sqlite://")
    destination_engine = create_engine("sqlite://")
    source_metadata = MetaData()
    Table("channels", source_metadata, Column("id", Integer, primary_key=True), Column("business_id", Integer))
    Table("channel_events", source_metadata, Column("id", Integer, primary_key=True), Column("channel_id", Integer))
    Table("conversations", source_metadata, Column("id", Integer, primary_key=True), Column("business_id", Integer))
    Table("conversation_assignments", source_metadata, Column("id", Integer, primary_key=True), Column("conversation_id", Integer))
    source_metadata.create_all(source_engine)
    destination_metadata = MetaData()
    Table("channels", destination_metadata, Column("id", Integer, primary_key=True), Column("business_id", Integer))
    Table("channel_events", destination_metadata, Column("id", Integer, primary_key=True), Column("channel_id", Integer))
    Table("conversations", destination_metadata, Column("id", Integer, primary_key=True), Column("business_id", Integer))
    Table("conversation_assignments", destination_metadata, Column("id", Integer, primary_key=True), Column("conversation_id", Integer))
    destination_metadata.create_all(destination_engine)
    with Session(source_engine) as source_db, Session(destination_engine) as tenant_db:
        source_db.execute(source_metadata.tables["channels"].insert(), [{"id": 1, "business_id": 7}, {"id": 2, "business_id": 8}])
        source_db.execute(source_metadata.tables["channel_events"].insert(), [{"id": 11, "channel_id": 1}, {"id": 12, "channel_id": 2}])
        source_db.execute(source_metadata.tables["conversations"].insert(), [{"id": 21, "business_id": 7}, {"id": 22, "business_id": 8}])
        source_db.execute(source_metadata.tables["conversation_assignments"].insert(), [{"id": 31, "conversation_id": 21}, {"id": 32, "conversation_id": 22}])
        source_db.commit()
        migrate_business(
            source_db,
            tenant_db,
            business_id=7,
            tables=("channels", "channel_events", "conversations", "conversation_assignments"),
        )
        tenant_db.commit()
        assert tenant_db.execute(destination_metadata.tables["channel_events"].select()).mappings().all() == [{"id": 11, "channel_id": 1}]
        assert tenant_db.execute(destination_metadata.tables["conversation_assignments"].select()).mappings().all() == [{"id": 31, "conversation_id": 21}]


def test_migrate_business_walks_nested_message_attachment_ownership():
    source_engine = create_engine("sqlite://")
    destination_engine = create_engine("sqlite://")
    source_metadata = MetaData()
    Table("conversations", source_metadata, Column("id", Integer, primary_key=True), Column("business_id", Integer))
    Table("messages", source_metadata, Column("id", Integer, primary_key=True), Column("conversation_id", Integer))
    Table("message_attachments", source_metadata, Column("id", Integer, primary_key=True), Column("message_id", Integer))
    source_metadata.create_all(source_engine)
    destination_metadata = MetaData()
    Table("conversations", destination_metadata, Column("id", Integer, primary_key=True), Column("business_id", Integer))
    Table("messages", destination_metadata, Column("id", Integer, primary_key=True), Column("conversation_id", Integer))
    Table("message_attachments", destination_metadata, Column("id", Integer, primary_key=True), Column("message_id", Integer))
    destination_metadata.create_all(destination_engine)
    with Session(source_engine) as source_db, Session(destination_engine) as tenant_db:
        source_db.execute(source_metadata.tables["conversations"].insert(), [{"id": 1, "business_id": 7}, {"id": 2, "business_id": 8}])
        source_db.execute(source_metadata.tables["messages"].insert(), [{"id": 11, "conversation_id": 1}, {"id": 12, "conversation_id": 2}])
        source_db.execute(source_metadata.tables["message_attachments"].insert(), [{"id": 21, "message_id": 11}, {"id": 22, "message_id": 12}])
        source_db.commit()
        migrate_business(
            source_db,
            tenant_db,
            business_id=7,
            tables=("conversations", "messages", "message_attachments"),
        )
        tenant_db.commit()
        assert tenant_db.execute(destination_metadata.tables["message_attachments"].select()).mappings().all() == [{"id": 21, "message_id": 11}]


def test_cutover_ledger_records_only_counts_hashes_and_cursors():
    engine = create_engine("sqlite://")
    PlatformBase.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(PlatformBusiness(id=7, name="Pilot", slug="pilot"))
        db.add(TenantRegistry(business_id=7, schema_name="shop_7", state="ready"))
        db.commit()

        registry = cutover.begin_cutover(db, 7, operation_id="pilot-7", approved=True)
        assert registry.state == "migrating"
        cutover.record_migration_results(
            db,
            "pilot-7",
            [
                TableMigrationResult(
                    table="customers",
                    source_rows=2,
                    copied_rows=2,
                    source_checksum="a" * 64,
                    destination_checksum="a" * 64,
                    cursor=9,
                    dry_run=False,
                )
            ],
        )
        operation = db.scalar(
            select(platform_control.TenantMigrationOperation).where(
                platform_control.TenantMigrationOperation.operation_id == "pilot-7"
            )
        )
        assert operation.state == "copied"
        assert operation.cursors == {"customers": 9}
        assert operation.row_counts == {"customers": {"source": 2, "copied": 2}}
        assert operation.checksums == {"customers": {"source": "a" * 64, "destination": "a" * 64}}
        assert "Pilot" not in str(operation.row_counts)


def test_cutover_cannot_activate_until_verification_succeeds():
    engine = create_engine("sqlite://")
    PlatformBase.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(PlatformBusiness(id=8, name="Verify", slug="verify"))
        db.add(TenantRegistry(business_id=8, schema_name="shop_8", state="ready"))
        db.commit()
        cutover.begin_cutover(db, 8, operation_id="pilot-8", approved=True)

        import pytest

        with pytest.raises(RuntimeError, match="verified"):
            cutover.complete_cutover(db, 8, operation_id="pilot-8", revision="20260915_0001")

        cutover.record_migration_results(db, "pilot-8", [])
        cutover.mark_cutover_verified(db, "pilot-8")
        registry = cutover.complete_cutover(db, 8, operation_id="pilot-8", revision="20260915_0001")
        assert registry.state == "active"
        assert registry.feature_enabled is True


def test_cutover_ledger_keeps_cursors_when_retrying_a_subset_of_tables():
    engine = create_engine("sqlite://")
    PlatformBase.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(PlatformBusiness(id=9, name="Resume", slug="resume"))
        db.add(TenantRegistry(business_id=9, schema_name="shop_9", state="ready"))
        db.commit()
        cutover.begin_cutover(db, 9, operation_id="pilot-9", approved=True)
        cutover.record_migration_results(
            db,
            "pilot-9",
            [
                TableMigrationResult(
                    table="customers",
                    source_rows=4,
                    copied_rows=4,
                    source_checksum="a" * 64,
                    destination_checksum="a" * 64,
                    cursor=12,
                    dry_run=False,
                ),
                TableMigrationResult(
                    table="orders",
                    source_rows=2,
                    copied_rows=2,
                    source_checksum="b" * 64,
                    destination_checksum="b" * 64,
                    cursor=7,
                    dry_run=False,
                ),
            ],
        )
        db.commit()

        # A retry that only copied customers must not erase the orders cursor.
        cutover.rollback_cutover(db, 9, operation_id="pilot-9")
        db.commit()
        cutover.begin_cutover(db, 9, operation_id="pilot-9", approved=True)
        cutover.record_migration_results(
            db,
            "pilot-9",
            [
                TableMigrationResult(
                    table="customers",
                    source_rows=5,
                    copied_rows=1,
                    source_checksum="c" * 64,
                    destination_checksum="c" * 64,
                    cursor=13,
                    dry_run=False,
                )
            ],
        )
        operation = db.scalar(
            select(platform_control.TenantMigrationOperation).where(
                platform_control.TenantMigrationOperation.operation_id == "pilot-9"
            )
        )
        assert operation.cursors == {"customers": 13, "orders": 7}
        assert set(operation.row_counts) == {"customers", "orders"}
        assert set(operation.checksums) == {"customers", "orders"}


def test_foreign_key_validation_rejects_orphaned_destination_rows():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table("parents", metadata, Column("id", Integer, primary_key=True))
    children = Table(
        "children",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer, ForeignKey("parents.id"), nullable=False),
    )
    metadata.create_all(engine)
    with Session(engine) as db:
        db.execute(children.insert().values(id=1, parent_id=999))
        db.commit()
        assert cutover.validate_destination_foreign_keys(db) is False
