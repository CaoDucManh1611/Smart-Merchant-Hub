import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.bases import TenantBase
from app.tenancy.context import TenantContext
from app.tenancy.workspace_modules import (
    get_workspace_config,
    require_module_enabled,
    save_workspace_config,
)


def test_workspace_modules_are_shop_scoped_persistent_and_enforced():
    engine = create_engine("sqlite://")
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            assert get_workspace_config(db, 7) == {
                "business_type": "retail",
                "enabled_modules": ["retail"],
            }
            save_workspace_config(db, 7, {"business_type": "services", "enabled_modules": ["appointments", "projects"]})
            db.commit()
            assert get_workspace_config(db, 7) == {"business_type": "services", "enabled_modules": ["appointments", "projects"]}
            assert get_workspace_config(db, 8) == {"business_type": "retail", "enabled_modules": ["retail"]}

            guard = require_module_enabled("retail")
            with pytest.raises(HTTPException) as disabled:
                guard(db=db, tenant=TenantContext(business_id=7, source="test"))
            assert disabled.value.status_code == 403

            save_workspace_config(db, 7, {"business_type": "mixed", "enabled_modules": ["retail", "appointments", "projects"]})
            db.commit()
            guard(db=db, tenant=TenantContext(business_id=7, source="test"))
    finally:
        engine.dispose()
