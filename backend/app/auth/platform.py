"""Authentication dependency for tenant-independent platform operations."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.dependencies import get_db
from app.models.business import User
from app.models.saas import PlatformMembership
from app.auth.platform_permissions import permissions_for, required_permission


def require_platform_admin(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    membership = db.scalar(
        select(PlatformMembership).where(
            PlatformMembership.user_id == user.id,
            PlatformMembership.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "platform_admin_required", "message": "Chỉ quản trị nền tảng mới được thao tác."},
        )
    if request is not None:
        required = required_permission(request.url.path, request.method)
        permissions = permissions_for(membership)
        if required and '*' not in permissions and required not in permissions:
            raise HTTPException(403, detail={"code": "platform_permission_denied", "message": "Bạn chưa được cấp quyền cho thao tác quản trị này.", "permission": required})
    return user
