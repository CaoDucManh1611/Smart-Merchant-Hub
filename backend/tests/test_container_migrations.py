from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_backend_image_runs_platform_migrations_before_serving():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY alembic-platform.ini ." in dockerfile
    assert "COPY alembic_platform ./alembic_platform" in dockerfile
    assert "python -m alembic -c alembic.ini upgrade head" in dockerfile
    assert "python -m alembic -c alembic-platform.ini upgrade head" in dockerfile
    assert dockerfile.index("alembic.ini upgrade head") < dockerfile.index("alembic-platform.ini upgrade head")


def test_tenant_migrations_are_not_run_globally_at_container_startup():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "alembic-tenant.ini upgrade head" not in dockerfile


def test_production_image_upgrades_active_tenants_without_global_tenant_alembic():
    dockerfile = (ROOT / "Dockerfile.production").read_text(encoding="utf-8")
    main_migration = "python -m alembic -c alembic.ini upgrade head"
    platform_migration = "python -m alembic -c alembic-platform.ini upgrade head"
    tenant_migration = "python -m app.scripts.upgrade_active_tenants --apply"

    assert "alembic-tenant.ini upgrade head" not in dockerfile
    assert main_migration in dockerfile
    assert platform_migration in dockerfile
    assert tenant_migration in dockerfile
    assert dockerfile.index(main_migration) < dockerfile.index(platform_migration)
    assert dockerfile.index(platform_migration) < dockerfile.index(tenant_migration)
