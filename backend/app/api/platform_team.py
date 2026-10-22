"""Platform-only staff accounts, roles and redacted change history."""
from datetime import datetime, timezone
from typing import Literal
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.platform import require_platform_admin
from app.auth.platform_permissions import PERMISSIONS, RESOURCES, ROLES, permissions_for
from app.auth.passwords import hash_password, validate_signup_password
from app.db.dependencies import get_db
from app.models.auth_session import AuthSession
from app.models.business import User
from app.models.saas import PlatformMembership
from app.models.platform_staff_audit import PlatformStaffAudit


class RedactedStaffRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def redacted(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={'detail': 'Thông tin chưa hợp lệ. Kiểm tra email, vai trò và mật khẩu ít nhất 12 ký tự với 3 nhóm ký tự.'})
        return redacted


router = APIRouter(prefix='/platform', route_class=RedactedStaffRoute, tags=['Platform staff'])
Role = Literal['owner', 'manager', 'support', 'content', 'viewer', 'custom']


def member_out(user, member):
    return {'user_id': user.id, 'full_name': user.full_name, 'email': user.email,
            'role': member.platform_role, 'is_active': bool(member.is_active),
            'permissions': permissions_for(member)}


@router.get('/access')
def access(actor: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    member = db.scalar(select(PlatformMembership).where(PlatformMembership.user_id == actor.id))
    return {'user_id': actor.id, 'role': member.platform_role, 'permissions': permissions_for(member)}


@router.get('/team')
def list_team(actor: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(User, PlatformMembership).join(PlatformMembership, PlatformMembership.user_id == User.id).order_by(User.id)).all()
    history = db.scalars(select(PlatformStaffAudit).order_by(PlatformStaffAudit.id.desc()).limit(30)).all()
    return {'items': [member_out(user, member) for user, member in rows], 'roles': ROLES,
            'resources': RESOURCES, 'permissions': sorted(PERMISSIONS),
            'history': [{'actor_id': event.actor_id, 'subject_id': event.subject_id, 'action': event.action,
                         'details': event.details, 'created_at': event.created_at} for event in history]}


class StaffPermissions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Role
    permissions: list[str] = Field(default_factory=list, max_length=50)
    is_active: bool = True

    @field_validator('permissions')
    @classmethod
    def known_permissions(cls, values):
        if set(values) - PERMISSIONS:
            raise ValueError('unknown permission')
        result = set(values)
        for permission in values:
            if permission.endswith(('.write', '.download', '.restore')):
                result.add(permission.split('.')[0] + '.read')
        return sorted(result)


class StaffCreate(StaffPermissions):
    full_name: str = Field(min_length=2, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=256)

    @field_validator('full_name')
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError('invalid name')
        return value

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('invalid email')
        return value

    @field_validator('password')
    @classmethod
    def valid_password(cls, value):
        return validate_signup_password(value)


def validate_scope(body):
    if body.role == 'custom' and not body.permissions:
        raise HTTPException(422, 'Hãy chọn ít nhất một quyền cho vai trò tùy chỉnh.')


def lock_owner(db, actor):
    # Serialize staff changes, recheck the acting owner after waiting for locks.
    # This also prevents two owners concurrently disabling one another.
    members = db.scalars(select(PlatformMembership).order_by(PlatformMembership.id).with_for_update().execution_options(populate_existing=True)).all()
    if not any(member.user_id == actor.id and member.is_active and member.platform_role == 'owner' for member in members):
        raise HTTPException(403, 'Chỉ chủ hệ thống mới được quản lý tài khoản quản trị.')


@router.post('/team', status_code=201)
def create_staff(body: StaffCreate, actor: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    lock_owner(db, actor)
    validate_scope(body)
    if db.scalar(select(User.id).where(func.lower(User.email) == body.email)):
        raise HTTPException(409, 'Email đã được sử dụng. Hãy dùng email riêng cho tài khoản nội bộ.')
    user = User(full_name=body.full_name.strip(), email=body.email, password_hash=hash_password(body.password),
                business_id=None, role='platform_staff', is_active=True)
    db.add(user); db.flush()
    member = PlatformMembership(user_id=user.id, platform_role=body.role,
                                platform_permissions=body.permissions if body.role == 'custom' else [], is_active=body.is_active)
    db.add(member)
    db.add(PlatformStaffAudit(actor_id=actor.id, subject_id=user.id, action='created',
                             details={'role': body.role, 'permissions': permissions_for(member), 'is_active': body.is_active}))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Tài khoản đã tồn tại. Hãy kiểm tra danh sách.') from None
    return member_out(user, member)


@router.patch('/team/{user_id}')
def update_staff(user_id: int, body: StaffPermissions, actor: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    lock_owner(db, actor)
    if user_id == actor.id:
        raise HTTPException(409, 'Không thể tự đổi quyền hoặc khóa tài khoản đang đăng nhập.')
    validate_scope(body)
    member = db.scalar(select(PlatformMembership).where(PlatformMembership.user_id == user_id).with_for_update())
    user = db.get(User, user_id)
    if member is None or user is None:
        raise HTTPException(404, 'Không tìm thấy tài khoản quản trị.')
    before = {'role': member.platform_role, 'permissions': permissions_for(member), 'is_active': member.is_active}
    member.platform_role = body.role
    member.platform_permissions = body.permissions if body.role == 'custom' else []
    member.is_active = body.is_active
    after = {'role': member.platform_role, 'permissions': permissions_for(member), 'is_active': member.is_active}
    if before != after:
        db.execute(update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        db.add(PlatformStaffAudit(actor_id=actor.id, subject_id=user_id, action='permissions_changed', details={'before': before, 'after': after}))
    db.commit()
    return member_out(user, member)
