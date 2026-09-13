"""Self-service shop onboarding and first-party catalog import."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, issue_token, require_admin_access, token_hash
from app.auth.passwords import hash_password
from app.database.bootstrap import ensure_default_plans
from app.db.dependencies import get_db
from app.models.auth_session import AuthSession
from app.models.business import Business, ServicePlan, Subscription, User
from app.models.inventory import StockMovement
from app.models.sales import Product
from app.schemas.onboarding import (
    OnboardingChannelCreate,
    OnboardingChannelOut,
    OnboardingPlanOut,
    OnboardingProductImport,
    OnboardingProductImportOut,
    OnboardingShopCreate,
    OnboardingShopOut,
    OnboardingSubscriptionOut,
)
from app.services.audit_service import record_audit
from app.services.channel_credentials import encrypt_token
from app.services.channel_service import upsert_channel_connection
from app.services.quota_service import QuotaExceededError
from app.core.config import settings
from app.tenancy.context import TenantContext


router = APIRouter(prefix="/onboarding")
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
    plan = db.query(ServicePlan).filter(
        ServicePlan.code == code.strip().lower(),
        ServicePlan.status == "active",
    ).first()
    if plan is None:
        raise HTTPException(status_code=422, detail="Gói dịch vụ không tồn tại hoặc đã lưu trữ.")
    return plan


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


@router.post("/shops", response_model=OnboardingShopOut, status_code=201)
def create_shop(payload: OnboardingShopCreate, db: Session = Depends(get_db)):
    owner_email = payload.owner_email.strip().lower()
    if db.query(User.id).filter(User.email.ilike(owner_email)).first() is not None:
        raise HTTPException(status_code=409, detail="Email đã được sử dụng. Hãy đăng nhập hoặc dùng email khác.")
    plans = ensure_default_plans(db)
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
        password_hash=hash_password(payload.password),
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
    return OnboardingShopOut(
        business_id=business.id,
        shop_name=business.name,
        slug=business.slug,
        owner_id=owner.id,
        owner_email=owner.email,
        access_token=token,
        expires_at=expires_at,
        subscription=OnboardingSubscriptionOut(id=subscription.id, plan_code=plan.code, plan_name=plan.name, status=subscription.status),
    )


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
