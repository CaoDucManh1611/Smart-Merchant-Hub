"""Tenant-scoped team directory APIs."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.auth.passwords import hash_password
from app.models.business import User
from app.schemas.team import TeamUserCreate, TeamUserListOut, TeamUserOut, TeamUserUpdate
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.auth.dependencies import require_admin_access
from app.services.audit_service import record_audit


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
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    email = _normalize_email(payload.email)
    _ensure_unique_email(db, email, tenant)
    user = User(
        business_id=tenant.business_id,
        full_name=payload.full_name.strip(),
        email=email,
        role=payload.role,
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
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="create", resource_type="team_user", resource_id=str(user.id), metadata={"role": user.role, "email": user.email})
        db.commit()
    return _out(user)


@router.patch("/team/{user_id}", response_model=TeamUserOut, dependencies=[Depends(require_admin_access)])
def update_team_member(
    user_id: int,
    payload: TeamUserUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    user = _get_user(db, user_id, tenant)
    data = payload.model_dump(exclude_unset=True)
    if "email" in data:
        data["email"] = _normalize_email(data["email"])
        _ensure_unique_email(db, data["email"], tenant, exclude_id=user.id)
    if "full_name" in data:
        data["full_name"] = data["full_name"].strip()
    for field, value in data.items():
        setattr(user, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email nhân viên đã tồn tại trong business.") from exc
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="update", resource_type="team_user", resource_id=str(user.id), metadata={"fields": list(payload.model_dump(exclude_unset=True))})
        db.commit()
    return _out(_get_user(db, user.id, tenant))
