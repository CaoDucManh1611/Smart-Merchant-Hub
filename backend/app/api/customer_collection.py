"""Customer contact, consent, address and verification collection APIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_write_access
from app.db.dependencies import get_db
from app.models.business import User
from app.models.customer import Customer
from app.models.customer_collection import (
    CustomerAddress,
    CustomerCollectionSession,
    CustomerConsent,
    CustomerContact,
    CustomerVerificationChallenge,
)
from app.models.message import Message
from app.schemas.customer_collection import (
    CustomerAddressCreate,
    CustomerAddressListOut,
    CustomerAddressOut,
    CustomerCollectionSessionCreate,
    CustomerCollectionSessionOut,
    CustomerCollectionSessionUpdate,
    CustomerConsentCreate,
    CustomerConsentListOut,
    CustomerConsentOut,
    CustomerContactCreate,
    CustomerContactListOut,
    CustomerContactOut,
    CustomerContactUpdate,
    VerificationChallengeCreate,
    VerificationChallengeOut,
    VerificationChallengeVerify,
    VerificationResultOut,
)
from app.services.audit_service import record_audit
from app.services.customer_collection import (
    contact_hash,
    decrypt_contact,
    encrypt_contact,
    generate_verification_code,
    hash_verification_code,
    mask_contact,
    normalize_contact,
)
from app.services.otp_delivery import OtpDeliveryError, OtpDeliveryNotConfigured, deliver_otp
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _customer(db: Session, customer_id: int, tenant: TenantContext) -> Customer:
    row = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.business_id == tenant.business_id,
        Customer.status != "merged",
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Customer không tồn tại trong business này.")
    return row


def _contact_out(row: CustomerContact) -> CustomerContactOut:
    return CustomerContactOut(
        id=row.id,
        customer_id=row.customer_id,
        kind=row.kind,
        masked_value=row.masked_value,
        verification_status=row.verification_status,
        source=row.source,
        confidence=row.confidence,
        is_primary=row.is_primary,
        verified_at=row.verified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _session_out(row: CustomerCollectionSession) -> CustomerCollectionSessionOut:
    return CustomerCollectionSessionOut(
        id=row.id,
        customer_id=row.customer_id,
        conversation_id=row.conversation_id,
        purpose=row.purpose,
        required_fields=list(row.required_fields or []),
        collected_fields=dict(row.collected_fields or {}),
        current_field=row.current_field,
        status=row.status,
        source_channel=row.source_channel,
        started_at=row.started_at,
        last_activity_at=row.last_activity_at,
        completed_at=row.completed_at,
    )


@router.post("/{customer_id}/contacts", response_model=CustomerContactOut, status_code=status.HTTP_201_CREATED)
def create_contact(
    customer_id: int,
    payload: CustomerContactCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _customer(db, customer_id, tenant)
    normalized = normalize_contact(payload.kind, payload.value)
    if not normalized or (payload.kind == "email" and "@" not in normalized):
        raise HTTPException(status_code=422, detail="Giá trị email/số điện thoại không hợp lệ.")
    value_hash = contact_hash(payload.kind, normalized)
    existing = db.query(CustomerContact).filter(
        CustomerContact.business_id == tenant.business_id,
        CustomerContact.kind == payload.kind,
        CustomerContact.value_hash == value_hash,
    ).first()
    if existing is not None:
        if existing.customer_id == customer_id:
            return _contact_out(existing)
        raise HTTPException(status_code=409, detail="Thông tin liên hệ đã thuộc một customer khác.")

    if payload.is_primary:
        db.query(CustomerContact).filter(
            CustomerContact.business_id == tenant.business_id,
            CustomerContact.customer_id == customer_id,
            CustomerContact.kind == payload.kind,
        ).update({CustomerContact.is_primary: False}, synchronize_session=False)
    row = CustomerContact(
        business_id=tenant.business_id,
        customer_id=customer_id,
        kind=payload.kind,
        value_encrypted=encrypt_contact(payload.kind, normalized),
        value_hash=value_hash,
        masked_value=mask_contact(payload.kind, normalized),
        source=payload.source,
        confidence=payload.confidence,
        is_primary=payload.is_primary,
    )
    db.add(row)
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="create",
        resource_type="customer_contact",
        metadata={"customer_id": customer_id, "kind": payload.kind, "source": payload.source},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Thông tin liên hệ đã tồn tại.") from None
    db.refresh(row)
    return _contact_out(row)


@router.get("/{customer_id}/contacts", response_model=CustomerContactListOut)
def list_contacts(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    _customer(db, customer_id, tenant)
    rows = db.query(CustomerContact).filter(
        CustomerContact.business_id == tenant.business_id,
        CustomerContact.customer_id == customer_id,
    ).order_by(CustomerContact.is_primary.desc(), CustomerContact.id.asc()).all()
    return CustomerContactListOut(items=[_contact_out(row) for row in rows], total=len(rows))


@router.patch("/{customer_id}/contacts/{contact_id}", response_model=CustomerContactOut)
def update_contact(
    customer_id: int,
    contact_id: int,
    payload: CustomerContactUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _customer(db, customer_id, tenant)
    row = db.query(CustomerContact).filter(
        CustomerContact.id == contact_id,
        CustomerContact.customer_id == customer_id,
        CustomerContact.business_id == tenant.business_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Thông tin liên hệ không tồn tại.")
    if payload.value is not None:
        normalized = normalize_contact(row.kind, payload.value)
        row.value_hash = contact_hash(row.kind, normalized)
        row.value_encrypted = encrypt_contact(row.kind, normalized)
        row.masked_value = mask_contact(row.kind, normalized)
        row.verification_status = "unverified"
        row.verified_at = None
    if payload.source is not None:
        row.source = payload.source
    if payload.confidence is not None:
        row.confidence = payload.confidence
    if payload.verification_status is not None:
        row.verification_status = payload.verification_status
        row.verified_at = _now() if payload.verification_status == "verified" else None
    if payload.is_primary:
        db.query(CustomerContact).filter(
            CustomerContact.business_id == tenant.business_id,
            CustomerContact.customer_id == customer_id,
            CustomerContact.kind == row.kind,
            CustomerContact.id != row.id,
        ).update({CustomerContact.is_primary: False}, synchronize_session=False)
        row.is_primary = True
    elif payload.is_primary is not None:
        row.is_primary = False
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="update",
        resource_type="customer_contact",
        resource_id=row.id,
        metadata={"customer_id": customer_id, "fields": list(payload.model_dump(exclude_unset=True))},
    )
    db.commit()
    db.refresh(row)
    return _contact_out(row)


@router.post("/{customer_id}/addresses", response_model=CustomerAddressOut, status_code=status.HTTP_201_CREATED)
def create_address(
    customer_id: int,
    payload: CustomerAddressCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _customer(db, customer_id, tenant)
    if payload.is_default:
        db.query(CustomerAddress).filter(
            CustomerAddress.business_id == tenant.business_id,
            CustomerAddress.customer_id == customer_id,
        ).update({CustomerAddress.is_default: False}, synchronize_session=False)
    row = CustomerAddress(
        business_id=tenant.business_id,
        customer_id=customer_id,
        **payload.model_dump(),
    )
    db.add(row)
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="create", resource_type="customer_address", metadata={"customer_id": customer_id})
    db.commit()
    db.refresh(row)
    return row


@router.get("/{customer_id}/addresses", response_model=CustomerAddressListOut)
def list_addresses(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    _customer(db, customer_id, tenant)
    rows = db.query(CustomerAddress).filter(
        CustomerAddress.business_id == tenant.business_id,
        CustomerAddress.customer_id == customer_id,
    ).order_by(CustomerAddress.is_default.desc(), CustomerAddress.id.asc()).all()
    return CustomerAddressListOut(items=rows, total=len(rows))


@router.post("/{customer_id}/collection-sessions", response_model=CustomerCollectionSessionOut, status_code=status.HTTP_201_CREATED)
def create_collection_session(
    customer_id: int,
    payload: CustomerCollectionSessionCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _customer(db, customer_id, tenant)
    if payload.conversation_id is not None:
        from app.models.conversation import Conversation
        conversation = db.query(Conversation).filter(
            Conversation.id == payload.conversation_id,
            Conversation.business_id == tenant.business_id,
            Conversation.customer_id == customer_id,
        ).first()
        if conversation is None:
            raise HTTPException(status_code=422, detail="Conversation không thuộc customer/business này.")
    row = CustomerCollectionSession(
        business_id=tenant.business_id,
        customer_id=customer_id,
        purpose=payload.purpose,
        required_fields=list(dict.fromkeys(payload.required_fields)),
        collected_fields={},
        current_field=(payload.required_fields[0] if payload.required_fields else None),
        source_channel=payload.source_channel,
        conversation_id=payload.conversation_id,
    )
    db.add(row)
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="create", resource_type="customer_collection_session", metadata={"customer_id": customer_id, "purpose": payload.purpose})
    db.commit()
    db.refresh(row)
    return _session_out(row)


@router.patch("/{customer_id}/collection-sessions/{session_id}", response_model=CustomerCollectionSessionOut)
def update_collection_session(
    customer_id: int,
    session_id: int,
    payload: CustomerCollectionSessionUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _customer(db, customer_id, tenant)
    row = db.query(CustomerCollectionSession).filter(
        CustomerCollectionSession.id == session_id,
        CustomerCollectionSession.customer_id == customer_id,
        CustomerCollectionSession.business_id == tenant.business_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Phiên thu thập không tồn tại.")
    row.collected_fields = dict(payload.collected_fields)
    row.current_field = payload.current_field
    row.last_activity_at = _now()
    if payload.status is not None:
        row.status = payload.status
    elif row.required_fields and all(field in row.collected_fields and row.collected_fields[field] not in (None, "") for field in row.required_fields):
        row.status = "completed"
    elif row.collected_fields:
        row.status = "partial"
    if row.status == "completed":
        row.completed_at = row.completed_at or _now()
        row.current_field = None
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="update", resource_type="customer_collection_session", resource_id=row.id, metadata={"customer_id": customer_id, "status": row.status})
    db.commit()
    db.refresh(row)
    return _session_out(row)


@router.get("/{customer_id}/collection-sessions", response_model=list[CustomerCollectionSessionOut])
def list_collection_sessions(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    _customer(db, customer_id, tenant)
    rows = db.query(CustomerCollectionSession).filter(
        CustomerCollectionSession.business_id == tenant.business_id,
        CustomerCollectionSession.customer_id == customer_id,
    ).order_by(CustomerCollectionSession.id.desc()).all()
    return [_session_out(row) for row in rows]


@router.post("/{customer_id}/consents", response_model=CustomerConsentOut, status_code=status.HTTP_201_CREATED)
def create_consent(
    customer_id: int,
    payload: CustomerConsentCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _customer(db, customer_id, tenant)
    if payload.evidence_message_id is not None:
        message = db.query(Message).join(Message.conversation).filter(
            Message.id == payload.evidence_message_id,
            Message.conversation.has(business_id=tenant.business_id, customer_id=customer_id),
        ).first()
        if message is None:
            raise HTTPException(status_code=422, detail="Message bằng chứng không thuộc customer/business này.")
    now = _now()
    row = CustomerConsent(
        business_id=tenant.business_id,
        customer_id=customer_id,
        purpose=payload.purpose,
        status=payload.status,
        source_channel=payload.source_channel,
        policy_version=payload.policy_version,
        evidence_message_id=payload.evidence_message_id,
        granted_at=now if payload.status == "granted" else None,
        revoked_at=now if payload.status == "revoked" else None,
    )
    db.add(row)
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action=payload.status, resource_type="customer_consent", metadata={"customer_id": customer_id, "purpose": payload.purpose})
    db.commit()
    db.refresh(row)
    return row


@router.get("/{customer_id}/consents", response_model=CustomerConsentListOut)
def list_consents(
    customer_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    _customer(db, customer_id, tenant)
    rows = db.query(CustomerConsent).filter(
        CustomerConsent.business_id == tenant.business_id,
        CustomerConsent.customer_id == customer_id,
    ).order_by(CustomerConsent.id.desc()).all()
    return CustomerConsentListOut(items=rows, total=len(rows))


@router.post("/{customer_id}/contacts/{contact_id}/verification-challenges", response_model=VerificationChallengeOut, status_code=status.HTTP_202_ACCEPTED)
def create_verification_challenge(
    customer_id: int,
    contact_id: int,
    payload: VerificationChallengeCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _customer(db, customer_id, tenant)
    contact = db.query(CustomerContact).filter(
        CustomerContact.id == contact_id,
        CustomerContact.business_id == tenant.business_id,
        CustomerContact.customer_id == customer_id,
    ).first()
    if contact is None:
        raise HTTPException(status_code=404, detail="Thông tin liên hệ không tồn tại.")
    if (payload.channel == "sms" and contact.kind != "phone") or (payload.channel == "email" and contact.kind != "email"):
        raise HTTPException(status_code=422, detail="Kênh xác minh không khớp loại thông tin liên hệ.")
    code = generate_verification_code()
    row = CustomerVerificationChallenge(
        business_id=tenant.business_id,
        customer_id=customer_id,
        contact_id=contact_id,
        channel=payload.channel,
        code_hash=hash_verification_code(code),
        expires_at=_now() + timedelta(minutes=10),
        status="queued",
    )
    contact.verification_status = "pending"
    db.add(row)
    db.flush()
    try:
        delivery = deliver_otp(
            channel=payload.channel,
            destination=decrypt_contact(contact.kind, contact.value_encrypted),
            code=code,
        )
        if delivery.delivered or delivery.provider == "disabled":
            row.status = "sent"
    except (OtpDeliveryNotConfigured, OtpDeliveryError, ValueError, OSError) as error:
        # Keep the challenge queued so an operator or a future retry can
        # deliver it; never expose the generated code or provider details.
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id if actor else None,
            action="verification_delivery_failed",
            resource_type="customer_contact",
            resource_id=contact.id,
            metadata={"customer_id": customer_id, "channel": payload.channel, "error_type": type(error).__name__},
        )
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="create", resource_type="verification_challenge", metadata={"customer_id": customer_id, "contact_id": contact_id, "channel": payload.channel})
    db.commit()
    db.refresh(row)
    return row


@router.post("/{customer_id}/contacts/{contact_id}/verification-challenges/{challenge_id}/verify", response_model=VerificationResultOut)
def verify_challenge(
    customer_id: int,
    contact_id: int,
    challenge_id: int,
    payload: VerificationChallengeVerify,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _customer(db, customer_id, tenant)
    contact = db.query(CustomerContact).filter(
        CustomerContact.id == contact_id,
        CustomerContact.business_id == tenant.business_id,
        CustomerContact.customer_id == customer_id,
    ).first()
    challenge = db.query(CustomerVerificationChallenge).filter(
        CustomerVerificationChallenge.id == challenge_id,
        CustomerVerificationChallenge.business_id == tenant.business_id,
        CustomerVerificationChallenge.customer_id == customer_id,
        CustomerVerificationChallenge.contact_id == contact_id,
    ).first()
    if contact is None or challenge is None:
        raise HTTPException(status_code=404, detail="Challenge hoặc thông tin liên hệ không tồn tại.")
    if challenge.status in {"verified", "locked", "expired"}:
        raise HTTPException(status_code=409, detail="Challenge không còn hiệu lực.")
    now = _now()
    if challenge.expires_at < now:
        challenge.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="Mã xác minh đã hết hạn.")
    if challenge.attempts >= challenge.max_attempts:
        challenge.status = "locked"
        db.commit()
        raise HTTPException(status_code=400, detail="Challenge đã bị khóa do nhập sai quá số lần.")
    challenge.attempts += 1
    if not hmac_compare(hash_verification_code(payload.code), challenge.code_hash):
        if challenge.attempts >= challenge.max_attempts:
            challenge.status = "locked"
        db.commit()
        raise HTTPException(status_code=400, detail="Mã xác minh không đúng.")
    challenge.status = "verified"
    challenge.verified_at = now
    contact.verification_status = "verified"
    contact.verified_at = now
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="verify", resource_type="customer_contact", resource_id=contact.id, metadata={"customer_id": customer_id, "challenge_id": challenge_id})
    db.commit()
    return VerificationResultOut(challenge_id=challenge.id, contact_id=contact.id, verification_status=contact.verification_status, verified_at=contact.verified_at)


def hmac_compare(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(left, right)
