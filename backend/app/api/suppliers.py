"""Tenant-scoped supplier master data API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_write_access
from app.db.dependencies import get_db
from app.models.business import User
from app.models.supplier import Supplier
from app.schemas.supplier import SupplierCreate, SupplierListOut, SupplierOut, SupplierUpdate
from app.services.audit_service import record_audit
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter()


def _supplier(db: Session, supplier_id: int, tenant: TenantContext) -> Supplier:
    supplier = db.query(Supplier).filter(
        Supplier.id == supplier_id,
        Supplier.business_id == tenant.business_id,
    ).first()
    if supplier is None:
        raise HTTPException(status_code=404, detail="Nhà cung cấp không tồn tại.")
    return supplier


def _clean(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


@router.get("/suppliers", response_model=SupplierListOut)
def list_suppliers(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    status: str | None = Query(default=None, max_length=30),
    search: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(Supplier).filter(Supplier.business_id == tenant.business_id)
    if status:
        query = query.filter(Supplier.status == status.strip().lower())
    if search:
        term = f"%{search.strip()}%"
        query = query.filter((Supplier.name.ilike(term)) | (Supplier.code.ilike(term)))
    total = query.count()
    items = query.order_by(Supplier.name.asc(), Supplier.id.asc()).offset(offset).limit(limit).all()
    return SupplierListOut(items=items, total=total)


@router.post("/suppliers", response_model=SupplierOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_supplier(
    payload: SupplierCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    supplier = Supplier(
        business_id=tenant.business_id,
        code=payload.code.strip(),
        name=payload.name.strip(),
        contact_name=_clean(payload.contact_name),
        email=_clean(payload.email),
        phone=_clean(payload.phone),
        address=_clean(payload.address),
        status=payload.status.strip().lower(),
        metadata_=payload.metadata,
    )
    db.add(supplier)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mã nhà cung cấp đã tồn tại trong business này.") from exc
    db.refresh(supplier)
    if actor:
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id,
            action="create",
            resource_type="supplier",
            resource_id=str(supplier.id),
            metadata={"code": supplier.code},
        )
        db.commit()
    return supplier


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut)
def get_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return _supplier(db, supplier_id, tenant)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut, dependencies=[Depends(require_write_access)])
def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    supplier = _supplier(db, supplier_id, tenant)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(supplier, "metadata_" if field == "metadata" else field, _clean(value))
    if supplier.status:
        supplier.status = supplier.status.strip().lower()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mã nhà cung cấp đã tồn tại trong business này.") from exc
    db.refresh(supplier)
    if actor:
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id,
            action="update",
            resource_type="supplier",
            resource_id=str(supplier.id),
            metadata={"fields": list(payload.model_dump(exclude_unset=True))},
        )
        db.commit()
    return supplier


@router.delete("/suppliers/{supplier_id}", status_code=204, dependencies=[Depends(require_write_access)])
def archive_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    supplier = _supplier(db, supplier_id, tenant)
    supplier.status = "archived"
    db.commit()
    if actor:
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id,
            action="archive",
            resource_type="supplier",
            resource_id=str(supplier.id),
        )
        db.commit()
