from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.bases import TenantBase


class Customer(TenantBase):
    __tablename__ = "customers"

    __table_args__ = (
        UniqueConstraint(
            "channel",
            "external_user_id",
            name="uq_customers_channel_user",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    # Redundant platform identity retained only as audit data; schema selects ownership.
    business_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    channel: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    external_user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    address: Mapped[str | None] = mapped_column(Text, nullable=True)

    avatar_url: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
    )

    merged_into_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )


    merged_into = relationship(
        "Customer",
        remote_side="Customer.id",
        foreign_keys=[merged_into_customer_id],
    )

    conversations = relationship(
        "Conversation",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    identities = relationship(
        "CustomerIdentity",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    facts = relationship(
        "CustomerFact",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    contacts = relationship(
        "CustomerContact",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    addresses = relationship(
        "CustomerAddress",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    collection_sessions = relationship(
        "CustomerCollectionSession",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    consents = relationship(
        "CustomerConsent",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    orders = relationship("Order", back_populates="customer")
