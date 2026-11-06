"""Fail-closed authorization for durable Sales Journey state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.models.customer import Customer
from app.models.customer_collection import CustomerConsent


@dataclass(frozen=True)
class JourneyPersistenceAuthorization:
    allowed: bool
    status: str


def authorize_journey_persistence(
    db,
    *,
    business_id: int,
    customer_id: int | None,
    purpose: str,
    policy_version: str,
    requires_consent: bool = True,
    lock_consent: bool = False,
) -> JourneyPersistenceAuthorization:
    """Authorize a configured purpose; missing policy or consent never passes."""
    purpose = purpose.strip() if isinstance(purpose, str) else ""
    policy_version = policy_version.strip() if isinstance(policy_version, str) else ""
    if (
        not purpose
        or len(purpose) > 60
        or any(ord(char) < 32 for char in purpose)
        or not policy_version
        or len(policy_version) > 40
        or any(ord(char) < 32 for char in policy_version)
    ):
        return JourneyPersistenceAuthorization(False, "policy_decision_required")
    if customer_id is None and not requires_consent:
        return JourneyPersistenceAuthorization(True, "policy_authorized_without_consent")
    if customer_id is None:
        return JourneyPersistenceAuthorization(False, "customer_scope_required")
    try:
        if lock_consent:
            # Consent revocation serializes on the customer row. Lock it here
            # too, before reading the consent row, so a state write cannot race
            # past revocation and reintroduce durable journey context.
            customer = (
                db.query(Customer)
                .filter(Customer.business_id == business_id, Customer.id == customer_id)
                .populate_existing()
                .with_for_update()
                .first()
            )
            if customer is None:
                return JourneyPersistenceAuthorization(False, "customer_scope_unavailable")
        query = db.query(CustomerConsent).filter(
            CustomerConsent.business_id == business_id,
            CustomerConsent.customer_id == customer_id,
            CustomerConsent.purpose == purpose,
        ).order_by(CustomerConsent.id.desc())
        if lock_consent:
            query = query.with_for_update()
        consent = query.first()
    except Exception:
        return JourneyPersistenceAuthorization(False, "consent_lookup_unavailable")
    # A purpose configured as optional may proceed without a consent row, but
    # an explicit denial or revocation remains a veto and cannot be bypassed.
    if consent is not None and (
        consent.status in {"denied", "revoked"} or consent.revoked_at is not None
    ):
        return JourneyPersistenceAuthorization(False, "consent_explicitly_denied_or_revoked")
    if not requires_consent:
        return JourneyPersistenceAuthorization(True, "policy_authorized_without_consent")
    if (
        consent is not None
        and consent.status == "granted"
        and consent.revoked_at is None
        and consent.policy_version == policy_version
    ):
        return JourneyPersistenceAuthorization(True, "consent_granted")
    return JourneyPersistenceAuthorization(False, "consent_missing_revoked_or_policy_mismatch")


def filter_journey_metadata_for_persistence(
    db,
    metadata: Mapping[str, Any] | None,
    *,
    business_id: int,
    conversation_id: int,
    customer_id: int | None,
    lock_consent: bool = True,
) -> dict[str, Any]:
    """Recheck authorization at each durable write boundary and redact unsafe state."""
    from app.core.config import settings
    from app.services.sales_journey_adapter import JOURNEY_STATE_METADATA_KEY, sanitize_journey_metadata

    allowed = False
    if isinstance(metadata, Mapping) and JOURNEY_STATE_METADATA_KEY in metadata:
        from app.services.sales_journey_adapter import deserialize_state

        scope_matches = deserialize_state(
            metadata.get(JOURNEY_STATE_METADATA_KEY),
            tenant_id=business_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
        ) is not None
        if scope_matches:
            consent = authorize_journey_persistence(
                db,
                business_id=business_id,
                customer_id=customer_id,
                purpose=settings.SALES_JOURNEY_PERSISTENCE_PURPOSE,
                policy_version=settings.SALES_JOURNEY_PERSISTENCE_POLICY_VERSION,
                requires_consent=settings.SALES_JOURNEY_PERSISTENCE_REQUIRES_CONSENT,
                lock_consent=lock_consent,
            )
            allowed = consent.allowed
    return sanitize_journey_metadata(metadata, allow_state=allowed)


__all__ = [
    "JourneyPersistenceAuthorization",
    "authorize_journey_persistence",
    "filter_journey_metadata_for_persistence",
]
