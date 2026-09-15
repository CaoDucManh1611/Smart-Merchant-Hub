from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.bases import TenantBase


class OAuthState(TenantBase):
    __tablename__ = "oauth_states"
    nonce: Mapped[str] = mapped_column(String(255), primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
