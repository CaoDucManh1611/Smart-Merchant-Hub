from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.platform_control import PlatformBusiness


class PlatformBusinessIdentityConflict(ValueError):
    """A platform slug is owned by an identity that cannot be reconciled safely."""


def ensure_platform_business(
    platform_db: Session,
    legacy_db: Session,
    business_id: int,
) -> PlatformBusiness:
    platform_business = platform_db.get(PlatformBusiness, business_id)
    if platform_business is not None:
        return platform_business

    business = legacy_db.get(Business, business_id)
    if business is None:
        raise LookupError("Shop không tồn tại.")

    slug_owner = platform_db.scalar(
        select(PlatformBusiness)
        .where(PlatformBusiness.slug == business.slug)
        .with_for_update()
    )
    if slug_owner is not None and slug_owner.id != business_id:
        owner_business = legacy_db.get(Business, slug_owner.id)
        if owner_business is None or owner_business.slug == business.slug:
            raise PlatformBusinessIdentityConflict("Shop slug đang thuộc một định danh khác.")
        replacement_owner = platform_db.scalar(
            select(PlatformBusiness.id).where(
                PlatformBusiness.slug == owner_business.slug,
                PlatformBusiness.id != slug_owner.id,
            )
        )
        if replacement_owner is not None:
            raise PlatformBusinessIdentityConflict("Slug chuẩn của shop đang được dùng bởi định danh khác.")
        slug_owner.slug = owner_business.slug

    platform_business = PlatformBusiness(
        id=business.id,
        name=business.name,
        slug=business.slug,
        status=business.status,
    )
    platform_db.add(platform_business)
    platform_db.flush()
    return platform_business
