"""Deterministic, resumable per-shop migration contracts."""

from app.services.tenant_data_migration import (
    MigrationReport,
    checksum_rows,
    copy_rows,
)
from app.services.tenant_cutover_service import migrate_business
from app.services.tenant_cutover_service import DEFAULT_TABLE_ORDER
from app.database.bases import TenantBase
from pathlib import Path
from sqlalchemy import Column, Integer, MetaData, Table, create_engine
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
