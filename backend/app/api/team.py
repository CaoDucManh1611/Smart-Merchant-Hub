"""Tenant-scoped team directory APIs."""

import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.tenancy.crm_session import get_tenant_db
from app.auth.passwords import hash_password
from app.models.business import Business, User
from app.models.signup import SignupEmailChallenge
from app.schemas.team import TeamOtpOut, TeamOtpRequest, TeamOtpVerify, TeamUserCreate, TeamUserListOut, TeamUserOut, TeamUserUpdate, PermissionOverrideCreate, PermissionOverrideListOut, PermissionOverrideOut, EffectivePermissionListOut, EffectivePermissionOut, normalize_team_role
from app.models.permission import PermissionOverride
from app.services.permission_service import permission_allowed, role_allows
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.auth.dependencies import require_admin_access
from app.services.audit_service import record_audit
from app.services.quota_service import QuotaExceededError, release_quota, reserve_quota
from app.services.customer_collection import generate_verification_code, hash_verification_code
from app.services.otp_delivery import OtpDeliveryError, OtpDeliveryNotConfigured, deliver_otp


router = APIRouter()


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _get_user(db: Session, user_id: int, tenant: TenantContext) -> User:
    user = db.query(User).filter(
        User.id == user_id,
        User.business_id == tenant.business_id,
    ).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Nhân viên không tồn tại.")
    return user


def _ensure_unique_email(db: Session, email: str, tenant: TenantContext, exclude_id: int | None = None) -> None:
    query = db.query(User.id).filter(
        User.business_id == tenant.business_id,
        func.lower(User.email) == email,
    )
    if exclude_id is not None:
        query = query.filter(User.id != exclude_id)
    if query.first() is not None:
        raise HTTPException(status_code=409, detail="Email nhân viên đã tồn tại trong business.")


def _out(user: User) -> TeamUserOut:
    return TeamUserOut(
        id=user.id,
        business_id=user.business_id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("/team", response_model=TeamUserListOut)
def list_team(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    active_only: bool = Query(default=False),
):
    query = db.query(User).filter(User.business_id == tenant.business_id)
    if active_only:
        query = query.filter(User.is_active.is_(True))
    users = query.order_by(User.is_active.desc(), User.full_name.asc(), User.id.asc()).all()
    return TeamUserListOut(items=[_out(user) for user in users], total=len(users))


def _require_team_admin(actor: User | None, tenant: TenantContext) -> int:
    if actor is None or actor.business_id is None:
        raise HTTPException(status_code=401, detail="Chủ shop cần đăng nhập để quản lý đội ngũ.")
    business_id = int(actor.business_id)
    if int(tenant.business_id) != business_id:
        raise HTTPException(status_code=403, detail="Phiên đăng nhập không thuộc shop hiện tại.")
    return business_id


@router.post("/team/otp/request", response_model=TeamOtpOut, status_code=202, dependencies=[Depends(require_admin_access)])
def request_team_otp(
    payload: TeamOtpRequest,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    """Send an email OTP before creating a staff account."""
    business_id = _require_team_admin(actor, tenant)
    email = _normalize_email(payload.email)
    _ensure_unique_email(db, email, tenant)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    latest = db.query(SignupEmailChallenge).filter(
        SignupEmailChallenge.email == email,
        SignupEmailChallenge.business_id == business_id,
        SignupEmailChallenge.purpose == "team_invite",
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
        owner_name=payload.full_name.strip(),
        shop_name=f"team:{business_id}",
        purpose="team_invite",
        business_id=business_id,
        role=normalize_team_role(payload.role),
        password_hash=hash_password(payload.password),
        code_hash=hash_verification_code(code),
        status="pending",
        attempts=0,
        max_attempts=5,
        expires_at=now + timedelta(minutes=10),
    )
    db.add(challenge)
    db.flush()
    try:
        delivery = deliver_otp(channel="email", destination=email, code=code)
        if not delivery.delivered:
            db.rollback()
            raise HTTPException(status_code=503, detail="Chưa thể gửi mã OTP email. Vui lòng thử lại sau.")
    except HTTPException:
        raise
    except (OtpDeliveryNotConfigured, OtpDeliveryError, ValueError, OSError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Chưa thể gửi mã OTP email. Vui lòng thử lại sau.") from exc
    db.commit()
    return TeamOtpOut(status="otp_sent", email=email, expires_in=600)


@router.post("/team/otp/verify", response_model=TeamUserOut, status_code=201, dependencies=[Depends(require_admin_access)])
def verify_team_otp(
    payload: TeamOtpVerify,
    db: Session = Depends(get_db),
    audit_db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    """Verify the staff email OTP and create the account in this shop."""
    business_id = _require_team_admin(actor, tenant)
    email = _normalize_email(payload.email)
    challenge = db.query(SignupEmailChallenge).filter(
        SignupEmailChallenge.email == email,
        SignupEmailChallenge.business_id == business_id,
        SignupEmailChallenge.purpose == "team_invite",
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

    _ensure_unique_email(db, email, tenant)
    try:
        reserve_quota(
            db,
            business_id,
            "staff_users",
            idempotency_key=f"team-user:{business_id}:{email}",
        )
    except QuotaExceededError as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail=exc.detail) from exc

    user = User(
        business_id=business_id,
        full_name=challenge.owner_name.strip(),
        email=email,
        role=normalize_team_role(challenge.role),
        is_active=True,
        password_hash=challenge.password_hash,
    )
    challenge.status = "verified"
    challenge.verified_at = now
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email nhân viên đã tồn tại trong business.") from exc
    db.refresh(user)
    if actor:
        record_audit(
            audit_db,
            business_id=business_id,
            user_id=actor.id,
            action="create",
            resource_type="team_user",
            resource_id=str(user.id),
            metadata={"role": user.role, "email": user.email, "verified_by_otp": True},
        )
        audit_db.commit()
    return _out(user)


@router.get("/team/permissions", response_model=PermissionOverrideListOut)
def list_permission_overrides(db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context)):
    rows = db.query(PermissionOverride).filter(PermissionOverride.business_id == tenant.business_id).order_by(PermissionOverride.resource.asc(), PermissionOverride.action.asc(), PermissionOverride.id.asc()).all()
    return PermissionOverrideListOut(items=rows, total=len(rows))


@router.post("/team/permissions", response_model=PermissionOverrideOut, status_code=201)
def create_permission_override(
    payload: PermissionOverrideCreate,
    db: Session = Depends(get_tenant_db),
    legacy_db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    if payload.role is None and payload.user_id is None:
        raise HTTPException(status_code=422, detail="Permission cần role hoặc user_id.")
    if payload.user_id is not None and legacy_db.query(User.id).filter(User.id == payload.user_id, User.business_id == tenant.business_id).first() is None:
        raise HTTPException(status_code=404, detail="Nhân viên không thuộc business.")
    row = PermissionOverride(
        business_id=tenant.business_id,
        resource=payload.resource.strip().lower(),
        action=payload.action.strip().lower(),
        effect=payload.effect,
        role=normalize_team_role(payload.role) if payload.role else None,
        user_id=payload.user_id,
    )
    db.add(row)
    try:
        db.flush()
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id if actor else None,
            action="create",
            resource_type="permission_override",
            resource_id=row.id,
            metadata={
                "resource": row.resource,
                "permission_action": row.action,
                "effect": row.effect,
                "role": row.role,
                "user_id": row.user_id,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Permission override đã tồn tại.") from exc
    db.refresh(row)
    return row


@router.delete("/team/permissions/{override_id}", status_code=204)
def delete_permission_override(
    override_id: int,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    row = db.query(PermissionOverride).filter(
        PermissionOverride.id == override_id,
        PermissionOverride.business_id == tenant.business_id,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Permission override không tồn tại.")
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="delete",
        resource_type="permission_override",
        resource_id=row.id,
        metadata={
            "resource": row.resource,
            "permission_action": row.action,
            "effect": row.effect,
            "role": row.role,
            "user_id": row.user_id,
        },
    )
    db.delete(row)
    db.commit()


@router.get("/team/{user_id}", response_model=TeamUserOut)
def get_team_member(
    user_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return _out(_get_user(db, user_id, tenant))


@router.post("/team", response_model=TeamUserOut, status_code=201, dependencies=[Depends(require_admin_access)])
def create_team_member(
    payload: TeamUserCreate,
    db: Session = Depends(get_db),
    audit_db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    # An authenticated admin is the source of truth for the shop.  Do not
    # let a stale/dev tenant header redirect a staff account to another shop.
    if actor is None or actor.business_id is None:
        raise HTTPException(status_code=401, detail="Chủ shop cần đăng nhập để thêm tài khoản.")
    business_id = int(actor.business_id)
    if int(tenant.business_id) != business_id:
        raise HTTPException(status_code=403, detail="Phiên đăng nhập không thuộc shop hiện tại.")
    if db.get(Business, business_id) is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")

    email = _normalize_email(payload.email)
    _ensure_unique_email(db, email, tenant)
    try:
        reserve_quota(
            db,
            business_id,
            "staff_users",
            idempotency_key=f"team-user:{business_id}:{email}",
        )
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    user = User(
        business_id=business_id,
        full_name=payload.full_name.strip(),
        email=email,
        role=normalize_team_role(payload.role),
        is_active=True,
        password_hash=hash_password(payload.password) if payload.password else None,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email nhân viên đã tồn tại trong business.") from exc
    db.refresh(user)
    if actor:
        record_audit(audit_db, business_id=business_id, user_id=actor.id, action="create", resource_type="team_user", resource_id=str(user.id), metadata={"role": user.role, "email": user.email})
        audit_db.commit()
    return _out(user)


@router.patch("/team/{user_id}", response_model=TeamUserOut, dependencies=[Depends(require_admin_access)])
def update_team_member(
    user_id: int,
    payload: TeamUserUpdate,
    db: Session = Depends(get_db),
    audit_db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    user = _get_user(db, user_id, tenant)
    was_active = bool(user.is_active)
    data = payload.model_dump(exclude_unset=True)
    if "email" in data:
        data["email"] = _normalize_email(data["email"])
        _ensure_unique_email(db, data["email"], tenant, exclude_id=user.id)
    if "full_name" in data:
        data["full_name"] = data["full_name"].strip()
    if "role" in data:
        data["role"] = normalize_team_role(data["role"])
    will_be_active = bool(data.get("is_active", user.is_active))
    if not was_active and will_be_active:
        try:
            # A retry observes the user as active and does not reserve twice.
            reserve_quota(db, tenant.business_id, "staff_users")
        except QuotaExceededError as exc:
            raise HTTPException(status_code=429, detail=exc.detail) from exc
    for field, value in data.items():
        setattr(user, field, value)
    if was_active and not will_be_active:
        release_quota(db, tenant.business_id, "staff_users")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email nhân viên đã tồn tại trong business.") from exc
    if actor:
        record_audit(audit_db, business_id=tenant.business_id, user_id=actor.id, action="update", resource_type="team_user", resource_id=str(user.id), metadata={"fields": list(payload.model_dump(exclude_unset=True))})
        audit_db.commit()
    return _out(_get_user(db, user.id, tenant))


@router.delete("/team/{user_id}", status_code=204, dependencies=[Depends(require_admin_access)])
def delete_team_member(
    user_id: int,
    db: Session = Depends(get_db),
    audit_db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    user = _get_user(db, user_id, tenant)
    if actor is not None and user.id == actor.id:
        raise HTTPException(status_code=409, detail="Không thể tự xóa tài khoản đang đăng nhập.")
    if str(user.role or "").strip().lower() == "owner":
        raise HTTPException(status_code=409, detail="Không thể xóa tài khoản chủ shop.")

    if user.is_active:
        release_quota(db, tenant.business_id, "staff_users")
    db.query(PermissionOverride).filter(
        PermissionOverride.business_id == tenant.business_id,
        PermissionOverride.user_id == user.id,
    ).delete(synchronize_session=False)
    if actor is not None:
        record_audit(
            audit_db,
            business_id=tenant.business_id,
            user_id=actor.id,
            action="delete",
            resource_type="team_user",
            resource_id=str(user.id),
            metadata={"email": user.email, "role": user.role},
        )
    db.delete(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        audit_db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Không thể xóa tài khoản vì tài khoản đang được dùng cho phiên hỗ trợ.",
        ) from exc
    if actor is not None:
        audit_db.commit()


@router.get("/team/{user_id}/permissions/effective", response_model=EffectivePermissionListOut)
def effective_permissions(user_id: int, db: Session = Depends(get_tenant_db), legacy_db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    user = _get_user(legacy_db, user_id, tenant)
    canonical_role = normalize_team_role(user.role)
    role_values = {str(user.role or "").lower(), canonical_role}
    overrides = db.query(PermissionOverride).filter(PermissionOverride.business_id == tenant.business_id).filter((PermissionOverride.user_id == user.id) | (PermissionOverride.role.in_(role_values))).all()
    keys = {(row.resource, row.action) for row in overrides}
    keys.update({("customers", "read"), ("customers", "write"), ("orders", "read"), ("orders", "write"), ("tickets", "read"), ("tickets", "write"), ("team", "read"), ("team", "write"), ("reports", "read"), ("documents", "read"), ("documents", "write")})
    items = []
    for resource, action in sorted(keys):
        allowed = permission_allowed(db, user, resource=resource, action=action)
        items.append(EffectivePermissionOut(resource=resource, action=action, allowed=allowed, source="override" if any(row.resource == resource and row.action == action for row in overrides) else "role"))
    return EffectivePermissionListOut(user_id=user.id, items=items)
