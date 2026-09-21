"""Self-service shop onboarding and first-party catalog import."""

from __future__ import annotations

import logging
import hmac
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, issue_token, require_admin_access, token_hash
from app.auth.passwords import hash_password
from app.database.bootstrap import ensure_default_plans
from app.database.platform_session import PlatformSessionLocal
from app.db.dependencies import get_db, get_platform_db
from app.models.auth_session import AuthSession
from app.models.business import Business, Payment, ServicePlan, Subscription, User
from app.models.platform_control import PlatformBusiness
from app.models.platform_control import TenantRegistry
from app.models.signup_verification import SignupVerificationChallenge
from app.tenancy.provisioning import provision_shop, retry_provision_shop, ProvisioningValidationError
from app.models.channel import Channel
from app.models.inventory import StockMovement
from app.models.sales import Product
from app.schemas.onboarding import (
    OnboardingChannelCreate,
    OnboardingChannelOut,
    OnboardingChannelVerify,
    OnboardingChannelVerifyOut,
    OnboardingChannelStatusOut,
    OnboardingPlanOut,
    OnboardingProductImport,
    OnboardingProductImportOut,
    OnboardingShopCreate,
    OnboardingShopOut,
    OnboardingSubscriptionPurchase,
    OnboardingSubscriptionOut,
    SignupOtpRequestOut,
    SignupOtpVerify,
)
from app.schemas.platform import ProvisioningOut, ProvisioningRequest
from app.services.audit_service import record_audit
from app.services.channel_credentials import encrypt_token
from app.services.channel_service import upsert_channel_connection
from app.services.quota_service import QuotaExceededError, release_quota
from app.services.provider_connection import ProviderConnectionError, verify_and_configure_bot
from app.services.customer_collection import generate_verification_code, hash_verification_code
from app.services.otp_delivery import OtpDeliveryError, OtpDeliveryNotConfigured, deliver_otp
from app.core.config import settings
from app.tenancy.context import TenantContext
from app.tenancy.schema import schema_name_for


router = APIRouter(prefix="/onboarding")
logger = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SECRET_KEY_RE = re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key)")
_SIGNUP_OTP_TTL = timedelta(minutes=10)
_SIGNUP_OTP_RETRY_AFTER = 60
_SIGNUP_OTP_MAX_ATTEMPTS = 5


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return (slug or "shop")[:120]


def _unique_slug(db: Session, requested: str | None, name: str) -> str:
    base = _slugify(requested or name)
    candidate = base
    index = 2
    while db.query(Business.id).filter(Business.slug == candidate).first() is not None:
        suffix = f"-{index}"
        candidate = f"{base[:120-len(suffix)]}{suffix}"
        index += 1
    return candidate


def _active_plan(db: Session, code: str) -> ServicePlan:
    plan = db.query(ServicePlan).filter(
        ServicePlan.code == code.strip().lower(),
        ServicePlan.status == "active",
    ).first()
    if plan is None:
        raise HTTPException(status_code=422, detail="Gói dịch vụ không tồn tại hoặc đã lưu trữ.")
    return plan


def _start_platform_provisioning(business: Business) -> str:
    """Mirror identity and start the schema saga without blocking signup.

    Signup is committed in the legacy compatibility store first.  A temporary
    platform/tenant outage therefore leaves a retryable ``provision_failed``
    operation rather than losing the newly created shop.
    """

    try:
        with PlatformSessionLocal() as platform_db:
            platform_business = platform_db.get(PlatformBusiness, business.id)
            if platform_business is None:
                platform_business = PlatformBusiness(
                    id=business.id,
                    name=business.name,
                    slug=business.slug,
                    status=business.status,
                )
                platform_db.add(platform_business)
                platform_db.commit()
            registry = provision_shop(
                platform_db,
                business_id=business.id,
                idempotency_key=f"onboarding-{business.id}",
            )
            return registry.state
    except Exception as exc:  # noqa: BLE001 - signup must remain available
        logger.warning("Shop provisioning deferred (%s)", type(exc).__name__)
        return "provision_failed"


def _require_shop_admin(db: Session, business_id: int, actor: User | None) -> User:
    if actor is None or actor.business_id != business_id or actor.role not in {"owner", "admin"}:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    if business.status != "active":
        raise HTTPException(status_code=423, detail={"code": "business_suspended", "message": "Shop đang tạm khóa bởi quản trị nền tảng."})
    subscription = db.query(Subscription).filter(
        Subscription.business_id == business_id,
    ).order_by(Subscription.id.desc()).first()
    if subscription is not None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        active = (
            subscription.status == "active"
            and (subscription.starts_at is None or subscription.starts_at <= now)
            and (subscription.ends_at is None or subscription.ends_at > now)
        )
        if not active:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "subscription_inactive",
                    "message": "Gói dịch vụ chưa được kích hoạt hoặc đã hết hạn.",
                },
            )
    return actor


def _safe_channel_config(config: dict | None) -> dict:
    """Recursively remove credentials and encrypt supported webhook secrets."""

    def scrub(value):
        if isinstance(value, dict):
            safe: dict = {}
            for key, nested in value.items():
                normalized = str(key).strip()
                if _SECRET_KEY_RE.search(normalized):
                    if (
                        normalized.lower() in {"oa_secret_key", "webhook_secret"}
                        and settings.CHANNEL_ENCRYPTION_KEY
                    ):
                        safe[f"{normalized}_encrypted"] = encrypt_token(
                            str(nested), settings.CHANNEL_ENCRYPTION_KEY
                        )
                    continue
                safe[normalized] = scrub(nested)
            return safe
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(config or {})


@router.get("/plans", response_model=list[OnboardingPlanOut])
def list_onboarding_plans(db: Session = Depends(get_db)):
    plans = ensure_default_plans(db)
    db.commit()
    return [plan for plan in plans if plan.status == "active"]


@router.post("/shops/{business_id}/subscription/purchase")
def purchase_subscription(
    business_id: int,
    payload: OnboardingSubscriptionPurchase,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """Request a plan change without interrupting an active shop plan.

    A paid upgrade is queued for platform approval; the current active
    subscription remains effective until that approval replaces it.
    """
    if actor.business_id != business_id or actor.role not in {"owner", "admin"}:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    ensure_default_plans(db)
    plan = _active_plan(db, payload.plan_code)
    active = db.query(Subscription).filter(
        Subscription.business_id == business_id,
        Subscription.status == "active",
    ).order_by(Subscription.id.desc()).first()
    pending = db.query(Subscription).filter(
        Subscription.business_id == business_id,
        Subscription.status == "pending",
        Subscription.plan_id == plan.id,
    ).order_by(Subscription.id.desc()).first()
    if active is not None and active.plan_id == plan.id:
        return {"id": active.id, "status": "active", "plan_name": plan.name, "plan_code": plan.code}
    if pending is not None:
        return {"id": pending.id, "status": "pending", "plan_name": plan.name, "plan_code": plan.code}

    # Free plans can activate immediately only when the shop has no active
    # plan. Switching an existing shop always remains an approval workflow.
    status = "active" if plan.price == 0 and active is None else "pending"
    subscription = Subscription(
        business_id=business_id,
        plan_id=plan.id,
        status=status,
        starts_at=_now() if status == "active" else None,
    )
    db.add(subscription)
    business.email = payload.contact_email
    business.phone = payload.contact_phone or business.phone
    db.flush()
    record_audit(
        db,
        business_id=business_id,
        user_id=actor.id,
        action="subscription_change_requested",
        resource_type="subscription",
        resource_id=subscription.id,
        metadata={"plan_code": plan.code, "service_type": payload.service_type, "channels": []},
    )
    db.commit()
    return {"id": subscription.id, "status": subscription.status, "plan_name": plan.name, "plan_code": plan.code}


@router.get("/shops/{business_id}/subscription/summary")
def subscription_summary(
    business_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """Return the account card data used by the service-plan screen."""
    if actor.business_id != business_id:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")

    subscription = db.query(Subscription).filter(
        Subscription.business_id == business_id,
    ).order_by(Subscription.id.desc()).first()
    plan = subscription.plan if subscription is not None else None
    payment = None
    if subscription is not None:
        payment = db.query(Payment).filter(
            Payment.subscription_id == subscription.id,
        ).order_by(Payment.id.desc()).first()
    connected_channels = db.query(Channel.id).filter(
        Channel.business_id == business_id,
        Channel.status == "active",
    ).count()

    return {
        "buyer": {
            "name": actor.full_name,
            "email": actor.email,
            "phone": business.phone,
            "shop_name": business.name,
        },
        "subscription": {
            "id": subscription.id if subscription else None,
            "status": subscription.status if subscription else "inactive",
            "plan_name": plan.name if plan else None,
            "plan_code": plan.code if plan else None,
        },
        "amount": float(payment.amount) if payment else float(plan.price) if plan else 0,
        "payment_status": payment.status if payment else "pending" if subscription and subscription.status == "pending" else None,
        "connected_channels": connected_channels,
        "channel_limit": plan.max_channels if plan else 0,
    }


@router.post("/shops", response_model=OnboardingShopOut, status_code=201)
def create_shop(payload: OnboardingShopCreate, db: Session = Depends(get_db)):
    """Create a shop for backwards-compatible internal/demo callers.

    The public UI uses the email-OTP flow below.  Keeping this endpoint
    available for the isolated test environment preserves existing fixtures;
    every real deployment must go through ``/signup/otp/request`` and
    ``/verify``.
    """
    if settings.ENVIRONMENT.strip().lower() != "test":
        raise HTTPException(
            status_code=410,
            detail={
                "code": "email_otp_required",
                "message": "Đăng ký shop phải xác minh email bằng mã OTP.",
            },
        )
    return _create_shop(db, payload)


def _create_shop(
    db: Session,
    payload: OnboardingShopCreate,
    *,
    password_hash: str | None = None,
) -> OnboardingShopOut:
    owner_email = payload.owner_email.strip().lower()
    if db.query(User.id).filter(User.email.ilike(owner_email)).first() is not None:
        raise HTTPException(status_code=409, detail="Email đã được sử dụng. Hãy đăng nhập hoặc dùng email khác.")
    ensure_default_plans(db)
    plan = _active_plan(db, payload.plan_code)
    business = Business(
        name=payload.shop_name.strip(),
        slug=_unique_slug(db, payload.slug, payload.shop_name),
        status="active",
    )
    db.add(business)
    db.flush()
    owner = User(
        business_id=business.id,
        full_name=payload.owner_name.strip(),
        email=owner_email,
        password_hash=password_hash or hash_password(payload.password),
        role="owner",
        is_active=True,
    )
    db.add(owner)
    db.flush()
    subscription = Subscription(
        business_id=business.id,
        plan_id=plan.id,
        status="active" if plan.price == 0 else "pending",
        starts_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(subscription)
    db.flush()
    token, expires_at = issue_token(owner.id, business_id=business.id, role=owner.role)
    db.add(AuthSession(
        user_id=owner.id,
        token_hash=token_hash(token),
        expires_at=expires_at,
        device_label="onboarding",
        user_agent_hash=None,
        ip_hash=None,
        mfa_verified=True,
    ))
    record_audit(db, business_id=business.id, user_id=owner.id, action="onboarding_shop_created", resource_type="business", resource_id=business.id, metadata={"plan_code": plan.code, "subscription_status": subscription.status})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Không thể tạo shop với thông tin đã nhập.") from exc
    provisioning_state = _start_platform_provisioning(business)
    return OnboardingShopOut(
        business_id=business.id,
        shop_name=business.name,
        slug=business.slug,
        owner_id=owner.id,
        owner_email=owner.email,
        access_token=token,
        expires_at=expires_at,
        subscription=OnboardingSubscriptionOut(id=subscription.id, plan_code=plan.code, plan_name=plan.name, status=subscription.status),
        provisioning_state=provisioning_state,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _signup_payload(challenge: SignupVerificationChallenge) -> OnboardingShopCreate:
    data = dict(challenge.signup_data or {})
    data["owner_email"] = challenge.owner_email
    # The raw password is intentionally never persisted in signup_data.  This
    # value is only used for Pydantic shape validation before the stored hash
    # is passed to _create_shop.
    data["password"] = "placeholder-password-1!"
    return OnboardingShopCreate(**data)


@router.post("/signup/otp/request", response_model=SignupOtpRequestOut, status_code=202)
def request_signup_otp(payload: OnboardingShopCreate, db: Session = Depends(get_db)):
    """Send a short-lived email OTP before creating the owner account."""

    owner_email = payload.owner_email.strip().lower()
    if db.query(User.id).filter(User.email.ilike(owner_email)).first() is not None:
        raise HTTPException(status_code=409, detail="Email đã được sử dụng. Hãy đăng nhập hoặc dùng email khác.")
    ensure_default_plans(db)
    _active_plan(db, payload.plan_code)

    now = _now()
    pending = db.scalar(
        select(SignupVerificationChallenge)
        .where(
            SignupVerificationChallenge.owner_email == owner_email,
            SignupVerificationChallenge.status == "pending",
        )
        .order_by(SignupVerificationChallenge.id.desc())
    )
    if pending is not None and pending.expires_at > now:
        elapsed = int((now - pending.last_sent_at).total_seconds())
        if elapsed < _SIGNUP_OTP_RETRY_AFTER:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "otp_rate_limited",
                    "message": "Mã OTP vừa được gửi. Hãy thử lại sau ít giây.",
                    "retry_after_seconds": _SIGNUP_OTP_RETRY_AFTER - elapsed,
                },
            )
    elif pending is not None:
        pending.status = "expired"

    code = generate_verification_code()
    signup_data = {
        "shop_name": payload.shop_name.strip(),
        "slug": payload.slug.strip() if payload.slug else None,
        "owner_name": payload.owner_name.strip(),
        "plan_code": payload.plan_code.strip().lower(),
    }
    if pending is None:
        pending = SignupVerificationChallenge(
            owner_email=owner_email,
            code_hash=hash_verification_code(code),
            password_hash=hash_password(payload.password),
            signup_data=signup_data,
            status="pending",
            attempts=0,
            max_attempts=_SIGNUP_OTP_MAX_ATTEMPTS,
            expires_at=now + _SIGNUP_OTP_TTL,
            last_sent_at=now,
            delivery_provider="smtp",
        )
        db.add(pending)
    else:
        pending.code_hash = hash_verification_code(code)
        pending.password_hash = hash_password(payload.password)
        pending.signup_data = signup_data
        pending.status = "pending"
        pending.attempts = 0
        pending.expires_at = now + _SIGNUP_OTP_TTL
        pending.last_sent_at = now
        pending.delivery_provider = "smtp"

    try:
        delivery = deliver_otp(channel="email", destination=owner_email, code=code)
    except (OtpDeliveryNotConfigured, OtpDeliveryError, ValueError, OSError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "otp_delivery_unavailable",
                "message": "Chưa thể gửi mã OTP. Vui lòng cấu hình dịch vụ email rồi thử lại.",
            },
        ) from exc
    if not delivery.delivered:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "otp_delivery_unavailable",
                "message": "Chưa thể gửi mã OTP. Vui lòng cấu hình dịch vụ email rồi thử lại.",
            },
        )
    pending.delivery_provider = delivery.provider
    db.commit()
    db.refresh(pending)
    return SignupOtpRequestOut(
        challenge_id=pending.id,
        email=owner_email,
        expires_at=pending.expires_at,
        retry_after_seconds=_SIGNUP_OTP_RETRY_AFTER,
        delivery_provider=delivery.provider,
    )


@router.post("/signup/otp/verify", response_model=OnboardingShopOut, status_code=201)
def verify_signup_otp(payload: SignupOtpVerify, db: Session = Depends(get_db)):
    """Verify the signup email and atomically create the owner session."""

    challenge = db.get(SignupVerificationChallenge, payload.challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail="Mã xác minh không tồn tại hoặc đã hết hạn.")
    now = _now()
    if challenge.status != "pending" or challenge.expires_at <= now:
        if challenge.status == "pending" and challenge.expires_at <= now:
            challenge.status = "expired"
            db.commit()
        raise HTTPException(status_code=400, detail="Mã xác minh không tồn tại hoặc đã hết hạn.")
    if challenge.attempts >= challenge.max_attempts:
        challenge.status = "locked"
        db.commit()
        raise HTTPException(status_code=400, detail="Mã OTP đã bị khóa do nhập sai quá số lần.")

    challenge.attempts += 1
    if not hmac.compare_digest(hash_verification_code(payload.code), challenge.code_hash):
        if challenge.attempts >= challenge.max_attempts:
            challenge.status = "locked"
        db.commit()
        raise HTTPException(status_code=400, detail="Mã OTP không đúng hoặc đã hết hạn.")

    signup = _signup_payload(challenge)
    try:
        result = _create_shop(db, signup, password_hash=challenge.password_hash)
    except Exception:
        db.rollback()
        raise
    challenge.status = "consumed"
    challenge.verified_at = now
    challenge.business_id = result.business_id
    db.commit()
    return result


def _authorize_provisioning(actor: User, business_id: int) -> None:
    if actor.business_id != business_id or actor.role not in {"owner", "admin"}:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")


def _ensure_platform_identity(platform_db: Session, legacy_db: Session, business_id: int) -> None:
    if platform_db.get(PlatformBusiness, business_id) is not None:
        return
    business = legacy_db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    platform_db.add(PlatformBusiness(id=business.id, name=business.name, slug=business.slug, status=business.status))
    platform_db.commit()


@router.get("/shops/{business_id}/provision", response_model=ProvisioningOut)
def get_onboarding_provisioning_status(
    business_id: int,
    actor: User = Depends(get_current_user),
    platform_db: Session = Depends(get_platform_db),
):
    """Read provisioning readiness without touching the tenant database."""

    _authorize_provisioning(actor, business_id)
    registry = platform_db.scalar(
        select(TenantRegistry).where(TenantRegistry.business_id == business_id)
    )
    if registry is None:
        return ProvisioningOut(
            business_id=business_id,
            schema_name=schema_name_for(business_id),
            state="provisioning",
            feature_enabled=False,
        )
    return registry


@router.post("/shops/{business_id}/provision", response_model=ProvisioningOut)
def provision_onboarding_shop(
    business_id: int,
    payload: ProvisioningRequest | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(get_current_user),
    legacy_db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
):
    _authorize_provisioning(actor, business_id)
    _ensure_platform_identity(platform_db, legacy_db, business_id)
    key = (payload.idempotency_key if payload else None) or idempotency_key
    if not key:
        raise HTTPException(status_code=422, detail="Cần idempotency_key hoặc Idempotency-Key.")
    try:
        return provision_shop(platform_db, business_id=business_id, idempotency_key=key)
    except ProvisioningValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/shops/{business_id}/provision/retry", response_model=ProvisioningOut)
def retry_onboarding_shop(
    business_id: int,
    payload: ProvisioningRequest | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: User = Depends(get_current_user),
    legacy_db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
):
    _authorize_provisioning(actor, business_id)
    _ensure_platform_identity(platform_db, legacy_db, business_id)
    key = (payload.idempotency_key if payload else None) or idempotency_key
    if not key:
        raise HTTPException(status_code=422, detail="Cần idempotency_key hoặc Idempotency-Key.")
    try:
        return retry_provision_shop(platform_db, business_id=business_id, idempotency_key=key)
    except ProvisioningValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/shops/{business_id}/channels", response_model=OnboardingChannelOut)
def connect_channel(
    business_id: int,
    payload: OnboardingChannelCreate,
    db: Session = Depends(get_db),
    actor: User | None = Depends(require_admin_access),
):
    _require_shop_admin(db, business_id, actor)
    try:
        channel = upsert_channel_connection(
            db,
            business_id=business_id,
            channel_type=payload.channel_type,
            external_account_id=payload.external_account_id.strip(),
            name=payload.name.strip(),
            access_token=payload.access_token,
            config=_safe_channel_config(payload.config),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail="Kênh này đã thuộc shop khác.") from exc
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    except ValueError as exc:
        # Never fall back to plaintext channel credentials when the key is
        # missing or malformed.  The caller gets an actionable setup error.
        raise HTTPException(status_code=503, detail="Kênh chưa thể kết nối vì secret manager chưa sẵn sàng.") from exc
    record_audit(
        db,
        business_id=business_id,
        user_id=actor.id,
        action="onboarding_channel_connected",
        resource_type="channel",
        resource_id=channel.id,
        metadata={"channel_type": channel.channel_type, "external_account_id": channel.external_account_id},
    )
    db.commit()
    return OnboardingChannelOut.model_validate(channel)


@router.get("/shops/{business_id}/channels", response_model=list[OnboardingChannelStatusOut])
def list_connected_channels(
    business_id: int,
    db: Session = Depends(get_db),
    actor: User | None = Depends(require_admin_access),
):
    """Return safe connection metadata without exposing provider secrets."""

    _require_shop_admin(db, business_id, actor)
    channels = (
        db.query(Channel)
        .filter(Channel.business_id == business_id, Channel.status == "active")
        .order_by(Channel.channel_type.asc(), Channel.id.asc())
        .all()
    )
    output = []
    for channel in channels:
        config = channel.config if isinstance(channel.config, dict) else {}
        provider_account = config.get("provider_account")
        output.append(
            OnboardingChannelStatusOut(
                id=channel.id,
                business_id=channel.business_id,
                channel_type=channel.channel_type,
                external_account_id=channel.external_account_id,
                name=channel.name,
                status=channel.status,
                connected_at=channel.connected_at,
                provider_account=provider_account if isinstance(provider_account, dict) else None,
                webhook_url=str(config.get("webhook_url") or "") or None,
                webhook_status="connected" if config.get("webhook_url") else "unknown",
            )
        )
    return output


@router.delete("/shops/{business_id}/channels/{channel_id}")
def disconnect_bot_channel(
    business_id: int,
    channel_id: int,
    db: Session = Depends(get_db),
    actor: User | None = Depends(require_admin_access),
):
    """Disconnect a Bot Creator/BotFather channel while preserving history."""

    _require_shop_admin(db, business_id, actor)
    channel = db.get(Channel, channel_id)
    if channel is None or channel.business_id != business_id or channel.channel_type not in {"telegram", "zalo"}:
        raise HTTPException(status_code=404, detail="Kênh bot không tồn tại.")
    if channel.status == "active":
        channel.status = "disconnected"
        channel.disconnected_at = datetime.now(timezone.utc).replace(tzinfo=None)
        release_quota(db, business_id, "connected_channels")
    record_audit(
        db,
        business_id=business_id,
        user_id=actor.id,
        action="onboarding_bot_disconnected",
        resource_type="channel",
        resource_id=channel.id,
        metadata={"channel_type": channel.channel_type, "external_account_id": channel.external_account_id},
    )
    db.commit()
    return {"connected": False, "channel_id": channel.id}


@router.post("/shops/{business_id}/channels/verify", response_model=OnboardingChannelVerifyOut)
def verify_bot_channel(
    business_id: int,
    payload: OnboardingChannelVerify,
    db: Session = Depends(get_db),
    actor: User | None = Depends(require_admin_access),
):
    """Verify a Telegram/Zalo Bot token and configure its tenant webhook."""

    _require_shop_admin(db, business_id, actor)
    public_base = str(settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if not public_base.lower().startswith("https://"):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "public_https_required",
                "message": "Cần cấu hình PUBLIC_BASE_URL bằng URL HTTPS công khai trước khi kết nối bot.",
            },
        )
    webhook_url = f"{public_base}/api/webhooks/{payload.channel_type}"
    # Hex is accepted by both Telegram and Zalo and avoids unsupported base64
    # padding characters in the provider secret header.
    import secrets

    webhook_secret = secrets.token_hex(32)
    try:
        verification = verify_and_configure_bot(
            channel_type=payload.channel_type,
            access_token=payload.access_token,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
        )
        channel = upsert_channel_connection(
            db,
            business_id=business_id,
            channel_type=payload.channel_type,
            external_account_id=verification["external_account_id"],
            name=verification["name"],
            access_token=payload.access_token.strip(),
            config=_safe_channel_config(
                {
                    "provider": f"{payload.channel_type}_bot",
                    "webhook_url": verification["webhook_url"],
                    "webhook_secret": webhook_secret,
                    "provider_account": verification["provider_account"],
                }
            ),
        )
    except ProviderConnectionError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail="Bot này đã thuộc shop khác.") from exc
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Secret manager chưa sẵn sàng để lưu token.") from exc

    record_audit(
        db,
        business_id=business_id,
        user_id=actor.id,
        action="onboarding_bot_verified",
        resource_type="channel",
        resource_id=channel.id,
        metadata={"channel_type": channel.channel_type, "external_account_id": channel.external_account_id},
    )
    db.commit()
    return OnboardingChannelVerifyOut(
        id=channel.id,
        business_id=channel.business_id,
        channel_type=channel.channel_type,
        external_account_id=channel.external_account_id,
        name=channel.name,
        status=channel.status,
        connected_at=channel.connected_at,
        provider_account=verification["provider_account"],
        webhook_url=verification["webhook_url"],
        webhook_status=verification["webhook_status"],
    )


@router.post("/shops/{business_id}/products/import", response_model=OnboardingProductImportOut)
def import_products(
    business_id: int,
    payload: OnboardingProductImport,
    db: Session = Depends(get_db),
    actor: User | None = Depends(require_admin_access),
):
    _require_shop_admin(db, business_id, actor)
    existing_skus = {
        str(row[0]).casefold(): row[1]
        for row in db.query(Product.sku, Product).filter(Product.business_id == business_id).all()
    }
    seen: set[str] = set()
    imported = updated = skipped = 0
    errors: list[str] = []
    for item in payload.items:
        sku = item.sku.strip()
        sku_key = sku.casefold()
        if sku_key in seen:
            skipped += 1
            errors.append(f"SKU trùng trong file: {sku}")
            continue
        seen.add(sku_key)
        product = existing_skus.get(sku_key)
        if product is None:
            product = Product(
                business_id=business_id,
                sku=sku.upper(),
                name=item.name.strip(),
                description=item.description,
                price=item.price,
                stock_quantity=item.stock_quantity,
                status=item.status,
                metadata_=item.metadata,
            )
            db.add(product)
            db.flush()
            if item.stock_quantity > 0:
                db.add(StockMovement(
                    business_id=business_id,
                    product_id=product.id,
                    movement_type="opening_balance",
                    quantity=item.stock_quantity,
                    quantity_before=0,
                    quantity_after=item.stock_quantity,
                    source_type="onboarding_import",
                    source_id=product.id,
                    actor_id=actor.id if actor else None,
                    note="Tồn đầu từ onboarding import",
                ))
            imported += 1
        else:
            if "stock_quantity" in item.model_fields_set and item.stock_quantity < int(product.reserved_quantity or 0):
                skipped += 1
                errors.append(
                    f"SKU {product.sku}: tồn mới thấp hơn số lượng đang giữ ({product.reserved_quantity})."
                )
                continue
            old_stock = int(product.stock_quantity or 0)
            product.name = item.name.strip()
            product.description = item.description
            product.price = item.price
            product.status = item.status
            product.metadata_ = item.metadata
            if "stock_quantity" in item.model_fields_set and item.stock_quantity != old_stock:
                product.stock_quantity = item.stock_quantity
                db.add(StockMovement(
                    business_id=business_id,
                    product_id=product.id,
                    movement_type="onboarding_reconcile",
                    quantity=item.stock_quantity - old_stock,
                    quantity_before=old_stock,
                    quantity_after=item.stock_quantity,
                    source_type="onboarding_import",
                    source_id=product.id,
                    actor_id=actor.id if actor else None,
                    note="Đối soát tồn từ onboarding import",
                ))
            updated += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="File import chứa SKU không hợp lệ hoặc trùng dữ liệu.") from exc
    record_audit(db, business_id=business_id, user_id=actor.id if actor else None, action="onboarding_products_imported", resource_type="product_import", metadata={"imported": imported, "updated": updated, "skipped": skipped})
    db.commit()
    return OnboardingProductImportOut(imported=imported, updated=updated, skipped=skipped, errors=errors)
