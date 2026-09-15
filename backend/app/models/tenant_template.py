"""Versioned tenant-schema template metadata.

These tables are intentionally free of cross-database foreign keys. Detailed
column migrations can evolve per tenant after the initial SaaS cutover.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Column, DateTime, String, Table, Text, func

from app.database.bases import TenantBase
from app.core.config import settings


def _base_table(name: str) -> Table:
    return Table(
        name,
        TenantBase.metadata,
        Column("id", BigInteger, primary_key=True),
        Column("business_id", BigInteger, nullable=True, index=True),
        Column("created_at", DateTime, nullable=False, server_default=func.now()),
    )


TENANT_TABLE_NAMES = (
    "channels",
    "channel_events",
    "customers",
    "customer_identities",
    "customer_contacts",
    "customer_addresses",
    "customer_facts",
    "conversations",
    "messages",
    "message_attachments",
    "documents",
    "document_chunks",
    "products",
    "orders",
    "order_items",
    "order_events",
    "order_payments",
    "suppliers",
    "purchase_orders",
    "purchase_order_items",
    "stock_movements",
    "workflows",
    "workflow_runs",
    "tickets",
    "ticket_comments",
    "ticket_events",
    "notifications",
    "crm_jobs",
    "rag_runs",
    "business_settings",
    "app_settings",
    "audit_logs",
    "data_lifecycle_requests",
)


for _table_name in TENANT_TABLE_NAMES:
    if _table_name not in TenantBase.metadata.tables:
        _base_table(_table_name)


# Add a few stable fields needed by routing/smoke tests without coupling the
# template to the legacy single-database ORM.
TenantBase.metadata.tables["channels"].append_column(Column("provider", String(30), nullable=True))
TenantBase.metadata.tables["channels"].append_column(Column("external_account_id", String(255), nullable=True))
TenantBase.metadata.tables["channels"].append_column(Column("access_token_encrypted", Text, nullable=True))
TenantBase.metadata.tables["customers"].append_column(Column("name", String(255), nullable=True))
TenantBase.metadata.tables["messages"].append_column(Column("content", Text, nullable=True))
TenantBase.metadata.tables["documents"].append_column(Column("filename", String(255), nullable=True))
TenantBase.metadata.tables["products"].append_column(Column("sku", String(120), nullable=True))
TenantBase.metadata.tables["products"].append_column(Column("name", String(255), nullable=True))
TenantBase.metadata.tables["orders"].append_column(Column("order_code", String(120), nullable=True))
TenantBase.metadata.tables["orders"].append_column(Column("status", String(40), nullable=True))
TenantBase.metadata.tables["document_chunks"].append_column(Column("content", Text, nullable=True))
TenantBase.metadata.tables["document_chunks"].append_column(Column("embedding", Vector(settings.EMBEDDING_DIMENSION), nullable=True))
