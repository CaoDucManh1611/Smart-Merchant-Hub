"""Role defaults and tenant permission override evaluation."""

from sqlalchemy.orm import Session

from app.models.business import User
from app.models.permission import PermissionOverride


def role_allows(role: str | None, action: str, resource: str) -> bool:
    role = (role or "").lower()
    action = action.lower()
    if role in {"owner", "admin"}:
        return True
    if role == "agent":
        return action == "read" or (action == "write" and resource not in {"team", "audit", "permissions"})
    if role in {"viewer", "business_agent"}:
        return action == "read"
    return False


def permission_allowed(db: Session, user: User, *, resource: str, action: str) -> bool:
    overrides = db.query(PermissionOverride).filter(
        PermissionOverride.business_id == user.business_id,
        PermissionOverride.resource == resource,
        PermissionOverride.action == action,
    ).filter(
        (PermissionOverride.user_id == user.id) | (PermissionOverride.role == user.role)
    ).all()
    if any(row.effect == "deny" for row in overrides):
        return False
    if any(row.effect == "allow" for row in overrides):
        return True
    return role_allows(user.role, action, resource)
