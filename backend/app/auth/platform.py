"""Authentication dependency for tenant-independent platform operations."""

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.dependencies import get_db
from app.models.business import User
from app.models.saas import PlatformMembership


def require_platform_admin(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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
    return user
