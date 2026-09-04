"""User login, bearer session lifecycle, and audit log views."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, issue_token, token_hash
from app.auth.passwords import verify_password
from app.db.dependencies import get_db
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.business import User
from app.schemas.auth import AuditLogOut, AuthUserOut, LoginOut, LoginRequest
from app.services.audit_service import record_audit
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter(prefix="/auth")


@router.post("/login", response_model=LoginOut)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
):
    query = db.query(User).filter(User.email.ilike(payload.email.strip()), User.is_active.is_(True))
    if x_business_id:
        try:
            query = query.filter(User.business_id == int(x_business_id))
        except ValueError:
            raise HTTPException(status_code=422, detail="X-Business-Id không hợp lệ.") from None
    users = query.all()
    if len(users) != 1 or not verify_password(payload.password, users[0].password_hash):
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng.")
    user = users[0]
    token, expires_at = issue_token(user.id)
    db.add(AuthSession(
        user_id=user.id,
        token_hash=token_hash(token),
        expires_at=expires_at,
    ))
    record_audit(
        db,
        business_id=user.business_id,
        user_id=user.id,
        action="login",
        resource_type="auth_session",
        metadata={"email": user.email},
    )
    db.commit()
    return LoginOut(
        access_token=token,
        expires_at=expires_at,
        user=AuthUserOut.model_validate(user),
    )


@router.get("/me", response_model=AuthUserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/logout", status_code=204)
def logout(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    token = authorization[7:].strip()
    session = db.query(AuthSession).filter(AuthSession.token_hash == token_hash(token)).first()
    if session is not None:
        session.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_audit(db, business_id=user.business_id, user_id=user.id, action="logout", resource_type="auth_session")
    db.commit()


@router.get("/audit-logs", response_model=list[AuditLogOut])
def list_audit_logs(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    user: User = Depends(get_current_user),
    limit: int = Query(default=100, ge=1, le=500),
):
    if user.business_id != tenant.business_id or user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Chỉ quản trị viên mới xem được audit log.")
    rows = db.query(AuditLog).filter(
        AuditLog.business_id == tenant.business_id,
    ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()
    return rows
