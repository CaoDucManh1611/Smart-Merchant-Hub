"""Shop-to-platform connection support; independent of CRM and support grants."""
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.bases import PlatformBase


class PlatformSupportRequest(PlatformBase):
    __tablename__ = 'platform_support_requests'
    __table_args__ = (
        UniqueConstraint('business_id', 'idempotency_key', name='uq_support_requests_business_key'),
        CheckConstraint("status IN ('open','in_progress','resolved','closed')", name='ck_support_requests_status'),
        CheckConstraint("provider IN ('facebook','instagram','telegram','zalo','tiktok','shopee')", name='ck_support_requests_provider'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey('platform_businesses.id', ondelete='RESTRICT'), index=True)
    # Auth still uses legacy users; IDs are actor snapshots, not cross-database FKs.
    created_by_user_id: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(180))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(30))
    providers: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default='open')
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    history: Mapped[list['PlatformSupportRequestHistory']] = relationship(
        order_by='PlatformSupportRequestHistory.id', lazy='selectin',
    )


class PlatformSupportRequestHistory(PlatformBase):
    __tablename__ = 'platform_support_request_history'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey('platform_support_requests.id', ondelete='RESTRICT'), index=True)
    actor_user_id: Mapped[int] = mapped_column(Integer)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30))
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
