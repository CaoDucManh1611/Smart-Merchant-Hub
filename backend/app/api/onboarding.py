"""Self-service shop onboarding and first-party catalog import."""

from __future__ import annotations

import logging
import hmac
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, issue_token, require_admin_access, token_hash
from app.auth.passwords import hash_password
from app.database.bootstrap import ensure_default_plans
from app.database.platform_session import PlatformSessionLocal, get_platform_db
from app.database.tenant_session import tenant_session
from app.db.dependencies import get_db
from app.tenancy.crm_session import get_tenant_db
from app.models.auth_session import AuthSession
from app.models.business import Business, Payment, ServicePlan, Subscription, User
from app.models.signup import SignupEmailChallenge
from app.models.platform_control import PlatformBusiness, PlatformServicePlan, PlatformSubscription, TenantRegistry
from app.tenancy.provisioning import ProvisioningValidationError, provision_shop, retry_provision_shop
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
    OnboardingPlanPurchase,
    OnboardingSubscriptionSummaryOut,
    OnboardingBuyerOut,
    OnboardingShopCreate,
    OnboardingShopOut,
    OnboardingSubscriptionOut,
    SignupOtpOut,
    SignupOtpRequest,
    SignupOtpVerify,
)
from app.schemas.platform import ProvisioningOut, ProvisioningRequest
from app.services.audit_service import record_audit
from app.services.channel_credentials import encrypt_token
from app.services.channel_service import normalized_connection_state, upsert_channel_connection
from app.services.channel_health import check_channel_health
from app.services.quota_service import QuotaExceededError, release_quota
from app.services.provider_connection import ProviderConnectionError, verify_and_configure_bot
from app.services.customer_collection import generate_verification_code, hash_verification_code
from app.services.otp_delivery import OtpDeliveryError, OtpDeliveryNotConfigured, deliver_otp
from app.core.config import settings
from app.tenancy.context import TenantContext
from app.tenancy.schema import schema_name_for
from app.tenancy.registry import register_webhook_route, deactivate_route_for_channel


router = APIRouter(prefix="/onboarding")
logger = logging.getLogger(__name__)
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SECRET_KEY_RE = re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key)")


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
    # The UI calls the top tier "Gói Premium", while the billing catalogue
    # keeps the stable internal code ``pro``. Accept older aliases at the API
    # boundary so a stale client cannot lose a purchase.
    aliases = {
        "custom": "pro",
        "bot-starter": "starter",
        "bot-growth": "growth",
        "bot-custom": "pro",
    }
    normalized_code = str(code or "").strip().lower()
    normalized_code = aliases.get(normalized_code, normalized_code)
    plan = db.query(ServicePlan).filter(
        ServicePlan.code == normalized_code,
        ServicePlan.status == "active",
    ).first()
    if plan is None:
        raise HTTPException(status_code=422, detail="Gói dịch vụ không tồn tại hoặc đã lưu trữ.")
    return plan


def _validate_requested_channels(plan: ServicePlan, channels: list[str] | None) -> None:
    """Reject a package request that asks for more channels than its plan.

    The connection quota is still enforced when a channel is actually linked;
    this early validation keeps the onboarding request and the entitlement
    contract consistent (especially for the zero-channel Demo package).
    """

    requested = {
        str(channel).strip().lower()
        for channel in (channels or [])
        if str(channel).strip()
    }
    limit = max(0, int(plan.max_channels or 0))
    if len(requested) <= limit:
        return
    raise HTTPException(
        status_code=422,
        detail={
            "code": "plan_channel_limit",
            "message": f"Gói {plan.name} chỉ cho phép tối đa {limit} kênh.",
            "plan_code": plan.code,
            "max_channels": limit,
            "requested_channels": len(requested),
        },
    )


def _chatbot_rental_price(plan: ServicePlan) -> Decimal:
    """Resolve the chatbot price independently from the CRM package price."""

    raw_price = (plan.features or {}).get("chatbot_rental_price", plan.price)
    try:
        price = Decimal(str(raw_price))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(plan.price or 0)
    if not price.is_finite() or price < 0:
        return Decimal(plan.price or 0)
    return price


def _subscription_is_active(subscription: Subscription | None, *, now: datetime | None = None) -> bool:
    if subscription is None or subscription.status != "active":
        return False
    moment = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return (
        (subscription.starts_at is None or subscription.starts_at <= moment)
        and (subscription.ends_at is None or subscription.ends_at > moment)
    )


def _active_subscription_for(
    db: Session,
    business_id: int,
    *,
    service_type: str = "package",
) -> Subscription | None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.business_id == business_id,
            Subscription.service_type == service_type,
            Subscription.status == "active",
            (Subscription.starts_at.is_(None) | (Subscription.starts_at <= now)),
            (Subscription.ends_at.is_(None) | (Subscription.ends_at > now)),
        )
        .order_by(Subscription.id.desc())
    )


def _start_platform_provisioning(business: Business, subscription: Subscription) -> str:
    """Mirror identity and start the schema saga without blocking signup.

    Signup is committed in the legacy compatibility store first.  A temporary
    platform/tenant outage therefore leaves a retryable ``provision_failed``
    operation rather than losing the newly created shop.
    """

    # A paid sign-up is deliberately not provisioned before it is approved.
    # This leaves no tenant workspace to open while the request is pending.
    if not _subscription_is_active(subscription):
        return "awaiting_approval"

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


def _create_shop_records(
    db: Session,
    *,
    shop_name: str,
    requested_slug: str | None,
    owner_name: str,
    owner_email: str,
    password_hash: str,
    plan_code: str,
):
    """Build the legacy shop records without committing them.

    Keeping the transaction open lets verified signup persist its challenge,
    owner, subscription and session atomically after the OTP is accepted.
    """

    ensure_default_plans(db)
    plan = _active_plan(db, plan_code)
    business = Business(
        name=shop_name.strip(),
        slug=_unique_slug(db, requested_slug, shop_name),
        status="active",
    )
    db.add(business)
    db.flush()
    owner = User(
        business_id=business.id,
        full_name=owner_name.strip(),
        email=owner_email,
        password_hash=password_hash,
        role="owner",
        is_active=True,
    )
    db.add(owner)
    db.flush()
    subscription = Subscription(
        business_id=business.id,
        plan_id=plan.id,
        service_type="package",
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
    record_audit(
        db,
        business_id=business.id,
        user_id=owner.id,
        action="onboarding_shop_created",
        resource_type="business",
        resource_id=business.id,
        metadata={"plan_code": plan.code, "subscription_status": subscription.status},
    )
    return business, owner, subscription, plan, token, expires_at


def _require_shop_admin(db: Session, business_id: int, actor: User | None) -> User:
    if actor is None or actor.business_id != business_id or actor.role not in {"owner", "admin"}:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    if business.status != "active":
        raise HTTPException(status_code=423, detail={"code": "business_suspended", "message": "Shop đang tạm khóa bởi quản trị nền tảng."})
    latest_subscription = db.query(Subscription).filter(
        Subscription.business_id == business_id,
    ).order_by(Subscription.id.desc()).first()
    if latest_subscription is not None:
        if _active_subscription_for(db, business_id) is None:
            raise HTTPException(
                status_code=402,
                detail={
                    "code": "subscription_inactive",
                    "message": "Gói dịch vụ chưa được kích hoạt hoặc đã hết hạn.",
                },
            )
    return actor


def _require_shop_member_for_purchase(db: Session, business_id: int, actor: User) -> User:
    """Authorize a same-shop operator to submit a request for platform review."""

    role = (actor.role or "").strip().lower()
    if (
        actor.business_id != business_id
        or role not in {"owner", "admin", "agent", "business_agent", "business_admin", "shop_admin", "shop_agent"}
    ):
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    if business.status != "active":
        raise HTTPException(status_code=423, detail={"code": "business_suspended", "message": "Shop đang tạm khóa bởi quản trị nền tảng."})
    return actor


def _sync_platform_subscription(platform_db: Session, business: Business, plan: ServicePlan) -> None:
    """Mirror the active legacy plan into the control-plane quota tables."""

    platform_business = platform_db.get(PlatformBusiness, business.id)
    if platform_business is None:
        platform_business = PlatformBusiness(
            id=business.id,
            name=business.name,
            slug=business.slug,
            status=business.status,
        )
        platform_db.add(platform_business)
        platform_db.flush()

    platform_plan = platform_db.scalar(
        select(PlatformServicePlan).where(PlatformServicePlan.code == plan.code)
    )
    quotas = {
        "staff_users": plan.max_users,
        "connected_channels": plan.max_channels,
        "documents": plan.max_documents,
        "rag_chunks": plan.max_rag_chunks,
        "ai_calls": plan.max_ai_calls,
        "ai_cost": float(plan.max_ai_cost or 0),
    }
    if platform_plan is None:
        platform_plan = PlatformServicePlan(
            code=plan.code,
            name=plan.name,
            price=plan.price,
            billing_cycle=plan.billing_cycle,
            quotas=quotas,
            features=plan.features,
        )
        platform_db.add(platform_plan)
        platform_db.flush()
    else:
        platform_plan.name = plan.name
        platform_plan.price = plan.price
        platform_plan.billing_cycle = plan.billing_cycle
        platform_plan.quotas = quotas
        platform_plan.features = plan.features

    current = platform_db.scalar(
        select(PlatformSubscription)
        .where(PlatformSubscription.business_id == business.id)
        .order_by(PlatformSubscription.id.desc())
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if current is not None and current.plan_id == platform_plan.id:
        current.status = "active"
        current.starts_at = current.starts_at or now
    else:
        if current is not None and current.status == "active":
            current.status = "cancelled"
        platform_db.add(
            PlatformSubscription(
                business_id=business.id,
                plan_id=platform_plan.id,
                status="active",
                starts_at=now,
                ends_at=None,
            )
        )
    platform_db.commit()


def _mirror_initial_subscription(business: Business, plan: ServicePlan) -> None:
    """Mirror a newly-created demo subscription into platform quota tables."""

    try:
        with PlatformSessionLocal() as platform_db:
            _sync_platform_subscription(platform_db, business, plan)
    except Exception:  # noqa: BLE001 - the provisioning retry can repair this
        logger.warning("Initial platform subscription mirror deferred for business_id=%s", business.id, exc_info=True)


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


@router.post("/shops/{business_id}/subscription/purchase", response_model=OnboardingSubscriptionOut)
def purchase_shop_plan(
    business_id: int,
    payload: OnboardingPlanPurchase,
    db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    actor: User = Depends(get_current_user),
):
    """Let shop operators request paid plans; keep immediate Demo activation privileged."""

    _require_shop_member_for_purchase(db, business_id, actor)
    business = db.get(Business, business_id)
    assert business is not None
    ensure_default_plans(db)
    plan = _active_plan(db, payload.plan_code)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    service_type = payload.service_type
    if service_type == "package":
        _validate_requested_channels(plan, payload.channels)
    # Older clients sent their selected CRM channels with chatbot requests.
    # Accept that payload for compatibility, but never validate or consume it
    # as chatbot quota; the assistant is an independent service.

    role = (actor.role or "").strip().lower()
    if plan.code == "demo" and role not in {"owner", "admin", "business_admin", "shop_admin"}:
        raise HTTPException(status_code=403, detail="Chỉ chủ shop hoặc quản trị viên shop mới được kích hoạt gói Demo.")

    # Only the free Demo package is immediate. Every rental or paid plan
    # becomes a visible request in the control plane for an administrator.
    if plan.code != "demo":
        current_pending = db.scalar(
            select(Subscription)
            .where(
                Subscription.business_id == business_id,
                Subscription.status == "pending",
            )
            .order_by(Subscription.id.desc())
        )
        if current_pending is not None and (
            current_pending.plan_id != plan.id
            or current_pending.service_type != service_type
        ):
            current_pending.status = "cancelled"
            current_pending = None
        if current_pending is None:
            current_pending = Subscription(
                business_id=business_id,
                plan_id=plan.id,
                service_type=service_type,
                status="pending",
                starts_at=None,
                ends_at=None,
                auto_renew=False,
            )
            db.add(current_pending)
            db.flush()
        record_audit(
            db,
            business_id=business_id,
            user_id=actor.id,
            action="subscription_request_submitted",
            resource_type="subscription",
            resource_id=current_pending.id,
            metadata={
                "plan_code": plan.code,
                "service_type": service_type,
                "request_details": payload.model_dump(
                    include={"contact_name", "contact_email", "contact_phone", "shop_name", "channels", "notes"},
                    exclude_none=True,
                ),
            },
        )
        db.commit()
        db.refresh(current_pending)
        return OnboardingSubscriptionOut(
            id=current_pending.id,
            plan_code=plan.code,
            plan_name=plan.name,
            service_type=service_type,
            status=current_pending.status,
        )

    current_active = _active_subscription_for(db, business_id, service_type=service_type)
    if (
        current_active is not None
        and current_active.plan_id == plan.id
        and current_active.service_type == service_type
    ):
        subscription = current_active
    else:
        if current_active is not None:
            current_active.status = "cancelled"
        for pending in db.scalars(
            select(Subscription).where(
                Subscription.business_id == business_id,
                Subscription.service_type == service_type,
                Subscription.status == "pending",
            )
        ):
            pending.status = "cancelled"
        subscription = Subscription(
            business_id=business_id,
            plan_id=plan.id,
            service_type=service_type,
            status="active",
            starts_at=now,
            ends_at=None,
            auto_renew=False,
        )
        db.add(subscription)
        db.flush()
    amount = _chatbot_rental_price(plan) if payload.service_type == "chatbot" else plan.price
    payment_reference = f"demo:{business_id}:{plan.code}:{payload.service_type}:{subscription.id}"
    payment = db.scalar(select(Payment).where(Payment.provider_transaction_id == payment_reference))
    if payment is None:
        db.add(Payment(
            business_id=business_id,
            subscription_id=subscription.id,
            amount=amount,
            currency="VND",
            provider="demo",
            provider_transaction_id=payment_reference,
            status="paid",
            paid_at=now,
            raw_response={"service_type": service_type, "plan_code": plan.code},
        ))

    record_audit(
        db,
        business_id=business_id,
        user_id=actor.id if actor else None,
        action="subscription_demo_activated",
        resource_type="subscription",
        resource_id=subscription.id,
        metadata={"plan_code": plan.code, "service_type": service_type, "amount": str(amount), "provider": "demo"},
    )
    db.commit()
    db.refresh(subscription)

    # Quota reservations for channels use the control-plane ledger when it is
    # available. Keep the legacy activation successful if a local database has
    # not run the optional platform migration yet; the next restart repairs it.
    if service_type == "package":
        try:
            _sync_platform_subscription(platform_db, business, plan)
        except Exception:  # noqa: BLE001 - subscription must remain usable in local demo
            platform_db.rollback()
            logger.warning("Platform plan mirror deferred for business_id=%s", business_id, exc_info=True)

    return OnboardingSubscriptionOut(
        id=subscription.id,
        plan_code=plan.code,
        plan_name=plan.name,
        service_type=service_type,
        status=subscription.status,
    )


@router.get("/shops/{business_id}/subscription/summary", response_model=OnboardingSubscriptionSummaryOut)
def get_shop_subscription_summary(
    business_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """Return buyer, package and payment details for the current shop only."""

    if actor.business_id != business_id:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    business = db.get(Business, business_id)
    if business is None or business.status != "active":
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    subscription = db.scalar(
        select(Subscription)
        .where(
            Subscription.business_id == business_id,
            Subscription.service_type == "package",
        )
        .order_by(Subscription.id.desc())
    )
    chatbot_subscription = db.scalar(
        select(Subscription)
        .where(
            Subscription.business_id == business_id,
            Subscription.service_type == "chatbot",
        )
        .order_by(Subscription.id.desc())
    )
    payment = None
    plan = None
    if subscription is not None:
        plan = subscription.plan or db.get(ServicePlan, subscription.plan_id)
        payment = db.scalar(
            select(Payment)
            .where(Payment.subscription_id == subscription.id)
            .order_by(Payment.id.desc())
        )

    connected_channels = 0
    try:
        with tenant_session(schema_name_for(business_id)) as tenant_db:
            connected_channels = int(
                tenant_db.query(Channel.id)
                .filter(Channel.business_id == business_id)
                .filter(Channel.status.in_(["active", "connected", "verifying", "reconnect_required"]))
                .count()
            )
    except Exception:  # noqa: BLE001 - summary remains useful while provisioning retries
        connected_channels = 0

    return OnboardingSubscriptionSummaryOut(
        business_id=business_id,
        buyer=OnboardingBuyerOut(
            name=actor.full_name,
            email=actor.email,
            phone=business.phone,
            shop_name=business.name,
        ),
        subscription=(OnboardingSubscriptionOut(
            id=subscription.id,
            plan_code=plan.code if plan else "",
            plan_name=plan.name if plan else "Chưa chọn gói",
            service_type=subscription.service_type,
            status=subscription.status,
        ) if subscription is not None else None),
        chatbot_subscription=(OnboardingSubscriptionOut(
            id=chatbot_subscription.id,
            plan_code=(chatbot_subscription.plan.code if chatbot_subscription.plan else ""),
            plan_name=(chatbot_subscription.plan.name if chatbot_subscription.plan else "Trợ lý AI"),
            service_type="chatbot",
            status=chatbot_subscription.status,
        ) if chatbot_subscription is not None else None),
        amount=payment.amount if payment is not None else (plan.price if plan is not None else None),
        currency=payment.currency if payment is not None else "VND",
        payment_status=payment.status if payment is not None else None,
        paid_at=payment.paid_at if payment is not None else None,
        connected_channels=connected_channels,
        channel_limit=plan.max_channels if plan is not None else None,
    )


@router.post("/signup/request", response_model=SignupOtpOut, status_code=202)
def request_signup_otp(payload: SignupOtpRequest, db: Session = Depends(get_db)):
    """Send a one-time email code before any shop records are created."""

    email = payload.email.strip().lower()
    if db.query(User.id).filter(User.email.ilike(email)).first() is not None:
        raise HTTPException(status_code=409, detail="Email đã được sử dụng. Hãy đăng nhập hoặc dùng email khác.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    latest = db.query(SignupEmailChallenge).filter(
        SignupEmailChallenge.email == email,
        SignupEmailChallenge.purpose == "signup",
        SignupEmailChallenge.status == "pending",
    ).order_by(SignupEmailChallenge.id.desc()).first()
    if latest is not None:
        if latest.expires_at <= now:
            latest.status = "expired"
        elif latest.created_at is not None and (now - latest.created_at).total_seconds() < 60:
            raise HTTPException(status_code=429, detail="Bạn vừa yêu cầu mã OTP. Hãy đợi một phút rồi thử lại.")

    code = generate_verification_code()
    challenge = SignupEmailChallenge(
        email=email,
        owner_name=payload.owner_name.strip(),
        shop_name=payload.shop_name.strip(),
        password_hash=hash_password(payload.password),
        code_hash=hash_verification_code(code),
        status="pending",
        expires_at=now + timedelta(minutes=10),
    )
    db.add(challenge)
    db.flush()
    try:
        delivery = deliver_otp(channel="email", destination=email, code=code)
        if not delivery.delivered:
            db.rollback()
            raise HTTPException(status_code=503, detail="Chưa thể gửi mã xác minh email. Vui lòng thử lại sau.")
    except HTTPException:
        raise
    except (OtpDeliveryNotConfigured, OtpDeliveryError, ValueError, OSError) as error:
        db.rollback()
        logger.warning("Signup OTP delivery failed: error_type=%s", type(error).__name__)
        raise HTTPException(status_code=503, detail="Chưa thể gửi mã xác minh email. Vui lòng thử lại sau.") from error
    db.commit()
    return SignupOtpOut(status="otp_sent", email=email, expires_in=600)


@router.post("/signup/verify", response_model=OnboardingShopOut, status_code=201)
def verify_signup_otp(payload: SignupOtpVerify, db: Session = Depends(get_db)):
    """Verify the email code, then create the tenant and owner account."""

    email = payload.email.strip().lower()
    challenge = db.query(SignupEmailChallenge).filter(
        SignupEmailChallenge.email == email,
        SignupEmailChallenge.purpose == "signup",
        SignupEmailChallenge.status == "pending",
    ).order_by(SignupEmailChallenge.id.desc()).first()
    if challenge is None:
        raise HTTPException(status_code=422, detail="Mã OTP không còn hiệu lực. Hãy yêu cầu mã mới.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if challenge.expires_at <= now:
        challenge.status = "expired"
        db.commit()
        raise HTTPException(status_code=422, detail="Mã OTP đã hết hạn. Hãy yêu cầu mã mới.")
    if challenge.attempts >= challenge.max_attempts:
        challenge.status = "locked"
        db.commit()
        raise HTTPException(status_code=422, detail="Mã OTP đã bị khóa. Hãy yêu cầu mã mới.")

    challenge.attempts += 1
    if not hmac.compare_digest(hash_verification_code(payload.otp), challenge.code_hash):
        if challenge.attempts >= challenge.max_attempts:
            challenge.status = "locked"
        db.commit()
        raise HTTPException(status_code=422, detail="Mã OTP không đúng.")

    if db.query(User.id).filter(User.email.ilike(email)).first() is not None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email đã được sử dụng. Hãy đăng nhập hoặc dùng email khác.")

    challenge.status = "verified"
    challenge.verified_at = now
    try:
        business, owner, subscription, plan, token, expires_at = _create_shop_records(
            db,
            shop_name=challenge.shop_name,
            requested_slug=None,
            owner_name=challenge.owner_name,
            owner_email=email,
            password_hash=challenge.password_hash,
            plan_code="demo",
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Không thể tạo shop với thông tin đã nhập.") from exc

    provisioning_state = _start_platform_provisioning(business, subscription)
    _mirror_initial_subscription(business, plan)
    return OnboardingShopOut(
        business_id=business.id,
        shop_name=business.name,
        slug=business.slug,
        owner_id=owner.id,
        owner_email=owner.email,
        access_token=token,
        expires_at=expires_at,
        subscription=OnboardingSubscriptionOut(
            id=subscription.id,
            plan_code=plan.code,
            plan_name=plan.name,
            service_type=subscription.service_type,
            status=subscription.status,
        ),
        provisioning_state=provisioning_state,
    )


@router.post("/shops", response_model=OnboardingShopOut, status_code=201)
def create_shop(payload: OnboardingShopCreate, db: Session = Depends(get_db)):
    # The browser registration flow must prove control of the email address.
    # Keep this endpoint for isolated test fixtures only; production and local
    # clients use /signup/request followed by /signup/verify.
    if settings.ENVIRONMENT.strip().lower() != "test":
        raise HTTPException(status_code=410, detail="Hãy dùng luồng đăng ký xác minh email OTP để tạo shop.")
    owner_email = payload.owner_email.strip().lower()
    if db.query(User.id).filter(User.email.ilike(owner_email)).first() is not None:
        raise HTTPException(status_code=409, detail="Email đã được sử dụng. Hãy đăng nhập hoặc dùng email khác.")
    business, owner, subscription, plan, token, expires_at = _create_shop_records(
        db,
        shop_name=payload.shop_name,
        requested_slug=payload.slug,
        owner_name=payload.owner_name,
        owner_email=owner_email,
        password_hash=hash_password(payload.password),
        plan_code=payload.plan_code,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Không thể tạo shop với thông tin đã nhập.") from exc
    provisioning_state = _start_platform_provisioning(business, subscription)
    return OnboardingShopOut(
        business_id=business.id,
        shop_name=business.name,
        slug=business.slug,
        owner_id=owner.id,
        owner_email=owner.email,
        access_token=token,
        expires_at=expires_at,
        subscription=OnboardingSubscriptionOut(id=subscription.id, plan_code=plan.code, plan_name=plan.name, service_type=subscription.service_type, status=subscription.status),
        provisioning_state=provisioning_state,
    )


def _authorize_provisioning(actor: User, business_id: int) -> None:
    if actor.business_id != business_id or actor.role not in {"owner", "admin"}:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")


def _authorize_provisioning_status(legacy_db: Session, actor: User, business_id: int) -> None:
    """Allow every active shop member to read readiness for their shop.

    Only owners/admins may trigger provisioning or retries; regular users still
    need the read-only status so the CRM does not mistake a valid tenant for a
    missing shop during login.
    """
    if actor.business_id != business_id or not actor.is_active:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    business = legacy_db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    if business.status != "active":
        raise HTTPException(status_code=423, detail={"code": "business_suspended", "message": "Shop đang tạm khóa bởi quản trị nền tảng."})


def _ensure_platform_identity(platform_db: Session, legacy_db: Session, business_id: int) -> None:
    if platform_db.get(PlatformBusiness, business_id) is not None:
        return
    business = legacy_db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    platform_db.add(PlatformBusiness(id=business.id, name=business.name, slug=business.slug, status=business.status))
    platform_db.commit()


def _provisioning_out_for_subscription(
    *,
    business_id: int,
    registry,
    active_subscription: Subscription | None,
    latest_subscription: Subscription | None,
) -> ProvisioningOut:
    """Return readiness without exposing a tenant before plan approval."""

    subscription = active_subscription or latest_subscription
    subscription_status = subscription.status if subscription is not None else None
    if active_subscription is None and latest_subscription is not None:
        return ProvisioningOut(
            business_id=business_id,
            schema_name=schema_name_for(business_id),
            state="awaiting_approval" if latest_subscription.status == "pending" else "subscription_inactive",
            feature_enabled=False,
            subscription_active=False,
            subscription_status=subscription_status,
        )
    if registry is None:
        return ProvisioningOut(
            business_id=business_id,
            schema_name=schema_name_for(business_id),
            state="provisioning",
            feature_enabled=False,
            subscription_active=active_subscription is not None,
            subscription_status=subscription_status,
        )
    return ProvisioningOut(
        business_id=registry.business_id,
        schema_name=registry.schema_name,
        state=registry.state,
        feature_enabled=registry.feature_enabled,
        subscription_active=active_subscription is not None,
        subscription_status=subscription_status,
        tenant_revision=registry.tenant_revision,
        migration_error=registry.migration_error,
    )


@router.get("/shops/{business_id}/provision", response_model=ProvisioningOut)
def get_onboarding_provisioning_status(
    business_id: int,
    actor: User = Depends(get_current_user),
    legacy_db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
):
    """Expose only the readiness state needed to safely open a new workspace."""

    _authorize_provisioning_status(legacy_db, actor, business_id)
    _ensure_platform_identity(platform_db, legacy_db, business_id)
    latest_subscription = legacy_db.scalar(
        select(Subscription)
        .where(Subscription.business_id == business_id)
        .order_by(Subscription.id.desc())
    )
    active_subscription = _active_subscription_for(legacy_db, business_id)
    registry = platform_db.scalar(
        select(TenantRegistry).where(TenantRegistry.business_id == business_id)
    )
    return _provisioning_out_for_subscription(
        business_id=business_id,
        registry=registry,
        active_subscription=active_subscription,
        latest_subscription=latest_subscription,
    )


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
    _require_shop_admin(legacy_db, business_id, actor)
    _ensure_platform_identity(platform_db, legacy_db, business_id)
    key = (payload.idempotency_key if payload else None) or idempotency_key
    if not key:
        raise HTTPException(status_code=422, detail="Cần idempotency_key hoặc Idempotency-Key.")
    try:
        registry = provision_shop(platform_db, business_id=business_id, idempotency_key=key)
    except ProvisioningValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    latest_subscription = legacy_db.scalar(
        select(Subscription).where(Subscription.business_id == business_id).order_by(Subscription.id.desc())
    )
    return _provisioning_out_for_subscription(
        business_id=business_id,
        registry=registry,
        active_subscription=_active_subscription_for(legacy_db, business_id),
        latest_subscription=latest_subscription,
    )


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
    _require_shop_admin(legacy_db, business_id, actor)
    _ensure_platform_identity(platform_db, legacy_db, business_id)
    key = (payload.idempotency_key if payload else None) or idempotency_key
    if not key:
        raise HTTPException(status_code=422, detail="Cần idempotency_key hoặc Idempotency-Key.")
    try:
        registry = retry_provision_shop(platform_db, business_id=business_id, idempotency_key=key)
    except ProvisioningValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    latest_subscription = legacy_db.scalar(
        select(Subscription).where(Subscription.business_id == business_id).order_by(Subscription.id.desc())
    )
    return _provisioning_out_for_subscription(
        business_id=business_id,
        registry=registry,
        active_subscription=_active_subscription_for(legacy_db, business_id),
        latest_subscription=latest_subscription,
    )


@router.post("/shops/{business_id}/channels", response_model=OnboardingChannelOut)
def connect_channel(
    business_id: int,
    payload: OnboardingChannelCreate,
    db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    actor: User | None = Depends(require_admin_access),
):
    _require_shop_admin(db, business_id, actor)
    raw_config = dict(payload.config or {})
    # A manually supplied webhook secret is used only for route hashing.  The
    # persisted tenant config is scrubbed/encrypted below and the secret is
    # never returned in the response or written to platform audit metadata.
    webhook_secret = str(raw_config.get("webhook_secret") or "").strip() or None
    # Telegram and Zalo deliver the webhook secret in the provider request
    # headers.  Without a secret there is no safe way to resolve the request
    # to this shop (and the generic shop-slug endpoint would otherwise reject
    # every inbound event).  The verified bot flow generates this value for
    # callers, while the legacy/manual endpoint must require it explicitly.
    if payload.channel_type in {"telegram", "zalo"} and not webhook_secret:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "webhook_secret_required",
                "message": "Telegram/Zalo cần webhook_secret để xác thực webhook riêng cho shop.",
            },
        )
    schema_name = schema_name_for(business_id)
    try:
        with tenant_session(schema_name) as tenant_db:
            channel = upsert_channel_connection(
                tenant_db,
                business_id=business_id,
                channel_type=payload.channel_type,
                external_account_id=payload.external_account_id.strip(),
                name=payload.name.strip(),
                access_token=payload.access_token,
                config=_safe_channel_config(raw_config),
                reserve_channel_slot=lambda: __import__("app.services.quota_service", fromlist=["reserve_quota"]).reserve_quota(platform_db, business_id, "connected_channels"),
                commit=False,
            )
            channel_payload = OnboardingChannelOut.model_validate(channel)
            register_webhook_route(
                platform_db,
                provider=channel.channel_type,
                external_account_id=channel.external_account_id,
                webhook_secret=webhook_secret,
                business_id=business_id,
                schema_name=schema_name,
                channel_id=channel.id,
            )
            record_audit(
                tenant_db,
                business_id=business_id,
                user_id=actor.id,
                action="onboarding_channel_connected",
                resource_type="channel",
                resource_id=channel.id,
                metadata={"channel_type": channel.channel_type, "external_account_id": channel.external_account_id},
            )
        # Quota reservations live in the platform database while the
        # encrypted credential lives in the shop schema.  Persist the quota
        # only after the tenant write succeeds; failures leave the platform
        # transaction rolled back by the dependency cleanup.
        platform_db.commit()
    except PermissionError as exc:
        platform_db.rollback()
        raise HTTPException(status_code=409, detail="Kênh này đã thuộc shop khác.") from exc
    except QuotaExceededError as exc:
        platform_db.rollback()
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    except ValueError as exc:
        platform_db.rollback()
        # Never fall back to plaintext channel credentials when the key is
        # missing or malformed.  The caller gets an actionable setup error.
        raise HTTPException(status_code=503, detail="Kênh chưa thể kết nối vì secret manager chưa sẵn sàng.") from exc
    except Exception:
        platform_db.rollback()
        raise
    return channel_payload


@router.get("/shops/{business_id}/channels", response_model=list[OnboardingChannelStatusOut])
def list_connected_channels(
    business_id: int,
    db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    actor: User | None = Depends(require_admin_access),
):
    """Return safe connection metadata without exposing provider secrets."""

    _require_shop_admin(db, business_id, actor)
    with tenant_session(schema_name_for(business_id)) as tenant_db:
        channels = (
            tenant_db.query(Channel)
            # Keep disconnected/reconnect-required records visible so the
            # shared connection card can explain what needs attention and
            # preserve one stable row per provider account.
            .filter(Channel.business_id == business_id)
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
                    status=normalized_connection_state(channel),
                    connected_at=channel.connected_at,
                    provider_account=provider_account if isinstance(provider_account, dict) else None,
                    webhook_url=str(config.get("webhook_url") or "") or None,
                    webhook_status=(
                        "disconnected"
                        if normalized_connection_state(channel) == "disconnected"
                        else "connected"
                        if config.get("webhook_url")
                        else "unknown"
                    ),
                )
            )
        return output


@router.post("/shops/{business_id}/channels/tiktok/bridge")
def connect_tiktok_bridge(
    business_id: int,
    db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    actor: User | None = Depends(require_admin_access),
):
    """Create or rotate the local ReLttk TikTok bridge credentials."""

    _require_shop_admin(db, business_id, actor)
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")

    import secrets

    bridge_secret = secrets.token_hex(32)
    platform_slug = platform_db.scalar(
        select(PlatformBusiness.slug).where(PlatformBusiness.id == int(business_id))
    ) or business.slug
    webhook_url = f"{str(settings.PUBLIC_BASE_URL or '').strip().rstrip('/')}/api/channels/tiktok/incoming"
    if webhook_url.startswith("/api"):
        webhook_url = "/api/channels/tiktok/incoming"
    try:
        with tenant_session(schema_name_for(business_id)) as tenant_db:
            channel = upsert_channel_connection(
                tenant_db,
                business_id=business_id,
                channel_type="tiktok",
                external_account_id=f"tiktok-bridge-{business_id}",
                name="TikTok Bridge",
                access_token=bridge_secret,
                config=_safe_channel_config(
                    {
                        "provider": "tiktok_bridge",
                        "webhook_url": webhook_url,
                        "bridge_control_url": str(settings.TIKTOK_BRIDGE_CONTROL_URL or "").strip().rstrip("/"),
                        "webhook_secret": bridge_secret,
                        "provider_account": {"id": f"tiktok-bridge-{business_id}", "name": "TikTok Bridge"},
                    }
                ),
                reserve_channel_slot=lambda: __import__("app.services.quota_service", fromlist=["reserve_quota"]).reserve_quota(platform_db, business_id, "connected_channels"),
                commit=False,
            )
            channel_id = int(channel.id)
            channel_status = normalized_connection_state(channel)
        platform_db.commit()
    except QuotaExceededError as exc:
        platform_db.rollback()
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    except (ValueError, RuntimeError) as exc:
        platform_db.rollback()
        raise HTTPException(status_code=503, detail="Secret manager chưa sẵn sàng để lưu mã TikTok bridge.") from exc
    except Exception:
        platform_db.rollback()
        raise

    return {
        "id": channel_id,
        "business_id": business_id,
        "channel_type": "tiktok",
        "name": "TikTok Bridge",
        "status": channel_status,
        "shop_slug": platform_slug,
        "webhook_url": webhook_url,
        "bridge_secret": bridge_secret,
        "headers": {"X-TikTok-Shop-Slug": platform_slug, "X-TikTok-Bridge-Secret": bridge_secret},
        "notice": "Hãy sao chép mã này vào máy chạy TikTok bridge. Mã chỉ hiển thị sau khi tạo hoặc cấp lại.",
    }


@router.delete("/shops/{business_id}/channels/{channel_id}")
def disconnect_bot_channel(
    business_id: int,
    channel_id: int,
    db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    actor: User | None = Depends(require_admin_access),
):
    """Disconnect a Bot Creator/BotFather channel while preserving history."""

    _require_shop_admin(db, business_id, actor)
    with tenant_session(schema_name_for(business_id)) as tenant_db:
        channel = tenant_db.get(Channel, channel_id)
        if channel is None or channel.business_id != business_id or channel.channel_type not in {"telegram", "zalo", "tiktok"}:
            raise HTTPException(status_code=404, detail="Kênh bot không tồn tại.")
        config = channel.config if isinstance(channel.config, dict) else {}
        if channel.status == "active":
            channel.status = "disconnected"
            channel.disconnected_at = datetime.now(timezone.utc).replace(tzinfo=None)
            release_quota(platform_db, business_id, "connected_channels")
            deactivate_route_for_channel(platform_db, channel.id)
        channel_id = channel.id
        channel_type = channel.channel_type
        external_account_id = channel.external_account_id
        record_audit(
            tenant_db,
            business_id=business_id,
            user_id=actor.id,
            action="onboarding_bot_disconnected",
            resource_type="channel",
            resource_id=channel_id,
            metadata={"channel_type": channel_type, "external_account_id": external_account_id},
        )
    platform_db.commit()
    return {"connected": False, "channel_id": channel_id}


@router.post("/shops/{business_id}/channels/health")
def check_shop_channel_health(
    business_id: int,
    db: Session = Depends(get_db),
    tenant_db: Session = Depends(get_tenant_db),
    actor: User | None = Depends(require_admin_access),
):
    """Refresh connection states without returning or logging credentials."""
    _require_shop_admin(db, business_id, actor)
    return {"items": check_channel_health(tenant_db, business_id)}


@router.post("/shops/{business_id}/channels/verify", response_model=OnboardingChannelVerifyOut)
def verify_bot_channel(
    business_id: int,
    payload: OnboardingChannelVerify,
    db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    actor: User | None = Depends(require_admin_access),
):
    """Verify a Telegram/Zalo Bot token and configure its tenant webhook."""

    _require_shop_admin(db, business_id, actor)
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    personal_zalo = payload.channel_type == "zalo" and payload.access_token.strip().lower().startswith("personal:")
    public_base = str(settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if not personal_zalo and not public_base.lower().startswith("https://"):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "public_https_required",
                "message": "Cần cấu hình PUBLIC_BASE_URL bằng URL HTTPS công khai trước khi kết nối bot.",
            },
        )
    webhook_url = (
        "/api/channels/zalo/incoming"
        if personal_zalo
        else f"{public_base}/api/webhooks/{business.slug}"
    )
    # Hex is accepted by both Telegram and Zalo and avoids unsupported base64
    # padding characters in the provider secret header.
    import secrets

    webhook_secret = secrets.token_hex(32)
    try:
        if personal_zalo:
            bridge_token = payload.access_token.strip().split(":", 1)[1].strip()
            if len(bridge_token) < 8:
                raise ProviderConnectionError("missing_bridge_key", "Mã phiên Zalo bridge chưa đủ dài.")
            verification = {
                "external_account_id": f"zalo-personal-{business_id}",
                "name": "Zalo cá nhân",
                "provider_account": {"id": f"zalo-personal-{business_id}", "name": "Zalo cá nhân", "mode": "personal_bridge"},
                "webhook_status": "connected",
                "webhook_url": webhook_url,
            }
        else:
            verification = verify_and_configure_bot(
                channel_type=payload.channel_type,
                access_token=payload.access_token,
                webhook_url=webhook_url,
                webhook_secret=webhook_secret,
            )
        with tenant_session(schema_name_for(business_id)) as tenant_db:
            channel = upsert_channel_connection(
                tenant_db,
                business_id=business_id,
                channel_type=payload.channel_type,
                external_account_id=verification["external_account_id"],
                name=verification["name"],
                access_token=payload.access_token.strip(),
                config=_safe_channel_config(
                    {
                        "provider": f"{payload.channel_type}_{'personal' if personal_zalo else 'bot'}",
                        "webhook_url": verification["webhook_url"],
                        "webhook_secret": webhook_secret,
                        "provider_account": verification["provider_account"],
                    }
                ),
                reserve_channel_slot=lambda: __import__("app.services.quota_service", fromlist=["reserve_quota"]).reserve_quota(platform_db, business_id, "connected_channels"),
                commit=False,
            )
            channel_id = channel.id
            channel_business_id = channel.business_id
            channel_type = channel.channel_type
            channel_external_account_id = channel.external_account_id
            channel_name = channel.name
            channel_status = normalized_connection_state(channel)
            channel_connected_at = channel.connected_at
            register_webhook_route(
                platform_db,
                provider=payload.channel_type,
                # Route by both the provider account and the generated
                # secret.  The account hash prevents the same bot being
                # attached to two shops; the secret hash is what Telegram /
                # Zalo send back on each webhook request.
                external_account_id=channel.external_account_id,
                webhook_secret=webhook_secret,
                business_id=business_id,
                schema_name=schema_name_for(business_id),
                channel_id=channel.id,
            )
            record_audit(
                tenant_db,
                business_id=business_id,
                user_id=actor.id,
                action="onboarding_bot_verified",
                resource_type="channel",
                resource_id=channel.id,
                metadata={"channel_type": channel.channel_type, "external_account_id": channel.external_account_id},
            )
        # The tenant context commits before the route transaction is made
        # durable.  If the platform commit fails, the route is absent and the
        # channel remains discoverable for a compensating retry instead of
        # exposing a half-created webhook route.
        platform_db.commit()
    except ProviderConnectionError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail="Bot này đã thuộc shop khác.") from exc
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Secret manager chưa sẵn sàng để lưu token.") from exc

    return OnboardingChannelVerifyOut(
        id=channel_id,
        business_id=channel_business_id,
        channel_type=channel_type,
        external_account_id=channel_external_account_id,
        name=channel_name,
        status=channel_status,
        connected_at=channel_connected_at,
        provider_account=verification["provider_account"],
        webhook_url=verification["webhook_url"],
        webhook_status=verification["webhook_status"],
    )


@router.post("/shops/{business_id}/products/import", response_model=OnboardingProductImportOut)
def import_products(
    business_id: int,
    payload: OnboardingProductImport,
    db: Session = Depends(get_db),
    tenant_db: Session = Depends(get_tenant_db),
    actor: User | None = Depends(require_admin_access),
):
    _require_shop_admin(db, business_id, actor)
    existing_skus = {
        str(row[0]).casefold(): row[1]
        for row in tenant_db.query(Product.sku, Product).filter(Product.business_id == business_id).all()
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
            tenant_db.add(product)
            tenant_db.flush()
            if item.stock_quantity > 0:
                tenant_db.add(StockMovement(
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
                tenant_db.add(StockMovement(
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
        tenant_db.commit()
    except IntegrityError as exc:
        tenant_db.rollback()
        raise HTTPException(status_code=409, detail="File import chứa SKU không hợp lệ hoặc trùng dữ liệu.") from exc
    record_audit(tenant_db, business_id=business_id, user_id=actor.id if actor else None, action="onboarding_products_imported", resource_type="product_import", metadata={"imported": imported, "updated": updated, "skipped": skipped})
    tenant_db.commit()
    return OnboardingProductImportOut(imported=imported, updated=updated, skipped=skipped, errors=errors)
