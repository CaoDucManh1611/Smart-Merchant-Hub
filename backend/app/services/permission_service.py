"""Role defaults and tenant permission override evaluation."""

from sqlalchemy.orm import Session

from app.models.business import User
from app.models.permission import PermissionOverride


ROLE_ALIASES = {
    "business_agent": "agent",
    "shop_agent": "agent",
    "business_admin": "admin",
    "shop_admin": "admin",
}


def role_allows(role: str | None, action: str, resource: str) -> bool:
    role = ROLE_ALIASES.get((role or "").lower(), (role or "").lower())
    action = action.lower()
    if role in {"owner", "admin"}:
        return True
    if role == "agent":
        return action == "read" or (action == "write" and resource not in {"team", "audit", "permissions"})
    if role == "viewer":
        return action == "read"
    return False


def permission_allowed(db: Session, user: User, *, resource: str, action: str) -> bool:
    raw_role = (user.role or "").lower()
    canonical_role = ROLE_ALIASES.get(raw_role, raw_role)
    role_values = {raw_role, canonical_role}
    overrides = db.query(PermissionOverride).filter(
        PermissionOverride.business_id == user.business_id,
        PermissionOverride.resource == resource,
        PermissionOverride.action == action,
    ).filter(
        (PermissionOverride.user_id == user.id) | (PermissionOverride.role.in_(role_values))
    ).all()
    if any(row.effect == "deny" for row in overrides):
        return False
    if any(row.effect == "allow" for row in overrides):
        return True
    return role_allows(user.role, action, resource)
