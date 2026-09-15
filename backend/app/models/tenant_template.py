"""Versioned tenant-schema template metadata.

These tables are intentionally free of cross-database foreign keys. Detailed
column migrations can evolve per tenant after the initial SaaS cutover.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Column, DateTime, String, Table, Text, func

from app.database.bases import TenantBase
from app.core.config import settings

# Register the concrete tenant ORM graph before the fallback template tables
# are created.  This keeps Alembic and runtime metadata in lock-step while
# allowing legacy tables to coexist during the staged cutover.
from app.models.customer import Customer  # noqa: F401,E402
from app.models.customer_identity import CustomerIdentity  # noqa: F401,E402
from app.models.customer_note import CustomerNote  # noqa: F401,E402
from app.models.customer_fact import CustomerFact  # noqa: F401,E402
from app.models.customer_merge import CustomerMerge  # noqa: F401,E402
from app.models.customer_collection import (  # noqa: F401,E402
    CustomerContact,
    CustomerAddress,
    CustomerCollectionSession,
    CustomerVerificationChallenge,
    CustomerConsent,
)
from app.models.customer_360 import customer_merge_operations, customer_segments  # noqa: F401,E402
from app.models.audit_log import AuditLog  # noqa: F401,E402
from app.models.business_setting import BusinessSetting  # noqa: F401,E402
from app.models.channel import Channel, ChannelEvent  # noqa: F401,E402
from app.models.conversation import Conversation  # noqa: F401,E402
from app.models.message import Message  # noqa: F401,E402
from app.models.message_attachment import MessageAttachment  # noqa: F401,E402
from app.models.document import Document, DocumentChunk  # noqa: F401,E402
from app.models.sales import Product, Order, OrderItem  # noqa: F401,E402
from app.models.order_event import OrderEvent  # noqa: F401,E402
from app.models.order_payment import OrderPayment  # noqa: F401,E402
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem  # noqa: F401,E402
from app.models.inventory import StockMovement, PurchaseReceipt, PurchaseReceiptItem  # noqa: F401,E402
from app.models.supplier import Supplier  # noqa: F401,E402
from app.models.crm_extended import ConversationAssignment, ConversationTag, CustomerTag, Tag  # noqa: F401,E402
from app.models.lead import Lead  # noqa: F401,E402
from app.models.ticket import Ticket, TicketComment, TicketEvent  # noqa: F401,E402
from app.models.workflow import Workflow, WorkflowRun  # noqa: F401,E402
from app.models.notification import Notification  # noqa: F401,E402
from app.models.crm_job import CrmJob  # noqa: F401,E402
from app.models.rag_run import RagRun  # noqa: F401,E402
from app.models.oauth_state import OAuthState  # noqa: F401,E402
from app.models.channel_migration import ChannelMigrationAudit  # noqa: F401,E402
from app.models.chatbot import ChatbotConfig  # noqa: F401,E402
from app.models.canned_response import CannedResponse  # noqa: F401,E402
from app.models.chatbot_followup import ChatbotFollowUp  # noqa: F401,E402
from app.models.customer_feedback import CustomerFeedback  # noqa: F401,E402
from app.models.revenue import RevenueTouchpoint, RevenueAttribution, LeadActivity, LeadConversion  # noqa: F401,E402
from app.models.permission import PermissionOverride  # noqa: F401,E402
from app.models.experimentation import (  # noqa: F401,E402
    RuleSuggestion, FeatureSnapshot, Experiment, ExperimentAssignment,
    ExperimentExposure, ExperimentOutcome, ExperimentMetricAggregate,
    ModelVersion, ModelTrainingRun, ModelEvaluationMetric,
    BanditPolicy, BanditArmStat, BanditDecision,
)
from app.models.saas import DataLifecycleRequest  # noqa: F401,E402


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
if 'provider' not in TenantBase.metadata.tables['channels'].c:
    TenantBase.metadata.tables["channels"].append_column(Column("provider", String(30), nullable=True))
if 'external_account_id' not in TenantBase.metadata.tables['channels'].c:
    TenantBase.metadata.tables["channels"].append_column(Column("external_account_id", String(255), nullable=True))
if 'access_token_encrypted' not in TenantBase.metadata.tables['channels'].c:
    TenantBase.metadata.tables["channels"].append_column(Column("access_token_encrypted", Text, nullable=True))
if 'name' not in TenantBase.metadata.tables['customers'].c:
    TenantBase.metadata.tables["customers"].append_column(Column("name", String(255), nullable=True))
if 'content' not in TenantBase.metadata.tables['messages'].c:
    TenantBase.metadata.tables["messages"].append_column(Column("content", Text, nullable=True))
if 'filename' not in TenantBase.metadata.tables['documents'].c:
    TenantBase.metadata.tables["documents"].append_column(Column("filename", String(255), nullable=True))
if 'sku' not in TenantBase.metadata.tables['products'].c:
    TenantBase.metadata.tables["products"].append_column(Column("sku", String(120), nullable=True))
if 'name' not in TenantBase.metadata.tables['products'].c:
    TenantBase.metadata.tables["products"].append_column(Column("name", String(255), nullable=True))
if 'order_code' not in TenantBase.metadata.tables['orders'].c:
    TenantBase.metadata.tables["orders"].append_column(Column("order_code", String(120), nullable=True))
if 'status' not in TenantBase.metadata.tables['orders'].c:
    TenantBase.metadata.tables["orders"].append_column(Column("status", String(40), nullable=True))
if 'content' not in TenantBase.metadata.tables['document_chunks'].c:
    TenantBase.metadata.tables["document_chunks"].append_column(Column("content", Text, nullable=True))
if 'embedding' not in TenantBase.metadata.tables['document_chunks'].c:
    TenantBase.metadata.tables["document_chunks"].append_column(Column("embedding", Vector(settings.EMBEDDING_DIMENSION), nullable=True))
