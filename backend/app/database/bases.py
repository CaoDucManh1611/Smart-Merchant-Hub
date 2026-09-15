"""Declarative metadata boundaries for the SaaS rollout.

LegacyBase intentionally remains available while request routing is migrated
to the platform/tenant databases task-by-task.
"""

from sqlalchemy.orm import DeclarativeBase


class LegacyBase(DeclarativeBase):
    pass


class PlatformBase(DeclarativeBase):
    pass


class TenantBase(DeclarativeBase):
    pass
