"""Trusted tenant context primitives shared by API and background services."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    business_id: int
    source: str


def resolve_tenant_context(
    *,
    authenticated_business_id: int | None = None,
    channel_business_id: int | None = None,
    development_header: str | None = None,
    environment: str = "development",
) -> TenantContext:
    """Resolve one tenant from trusted sources; never select a default tenant."""
    env = environment.strip().lower()
    header_id: int | None = None
    if development_header is not None:
        if env == "production":
            raise PermissionError("X-Business-Id is disabled in production")
        try:
            header_id = int(development_header)
        except (TypeError, ValueError) as exc:
            raise PermissionError("X-Business-Id must be a positive integer") from exc
        if header_id <= 0:
            raise PermissionError("X-Business-Id must be a positive integer")

    candidates = [
        (authenticated_business_id, "authenticated_user"),
        (channel_business_id, "channel_account"),
        (header_id, "development_header"),
    ]
    trusted = [(business_id, source) for business_id, source in candidates[:2] if business_id is not None]
    selected = trusted or ([(header_id, "development_header")] if header_id is not None else [])
    if not selected:
        raise PermissionError("Tenant context is required")
    if any(business_id <= 0 for business_id, _ in selected):
        raise PermissionError("business_id must be a positive integer")
    if len({business_id for business_id, _ in selected}) != 1:
        raise PermissionError("Conflicting tenant contexts")

    business_id, source = next(
        item for item in candidates if item[0] is not None
    )
    return TenantContext(int(business_id), source)
