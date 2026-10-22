from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class SubscriptionPaymentOut(BaseModel):
    status: Literal["not_created", "creating", "pending", "paid", "refunded", "expired",
                    "cancelled", "reconciliation_required"]
    amount: int | None = None
    currency: str = "VND"
    qr_code: str | None = None
    checkout_url: str | None = None
    bank_name: str | None = None
    bin: str | None = None
    account_name: str | None = None
    account_number: str | None = None
    reference: str | None = None
    expires_at: datetime | None = None
    approval_status: str
    reconciliation_required: bool = False
    provider: Literal['vietqr', 'payos', 'manual'] = 'manual'
