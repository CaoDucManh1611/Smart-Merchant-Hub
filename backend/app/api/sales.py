"""Tenant-scoped product catalog and order APIs."""

import csv
import io
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.tenancy.crm_session import get_tenant_db
from app.database.platform_session import get_platform_db
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.inventory import StockMovement
from app.models.sales import Order, OrderItem, Product
from app.models.order_event import OrderEvent
from app.models.business import User
from app.schemas.sales import (
    OrderCreate,
    OrderLogisticsUpdate,
    OrderItemOut,
    OrderListOut,
    OrderOut,
    OrderUpdate,
    OrderTransition,
    ProductCreate,
    ProductListOut,
    ProductOut,
    ProductUpdate,
    RevenueByChannelOut,
    RevenueChannelItem,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.services.workflow_engine import emit_workflow_event
from app.auth.dependencies import require_write_access
from app.services.audit_service import record_audit
from app.services.order_service import SalesOrderOperationError, SALES_TRANSITIONS as ORDER_TRANSITIONS, transition_sales_order
from app.tenancy.workspace_modules import require_module_enabled


router = APIRouter(dependencies=[Depends(require_module_enabled("retail"))])
REVENUE_ORDER_STATUSES = ("confirmed", "processing", "shipped", "delivered", "completed", "paid")

SALES_TRANSITIONS = ORDER_TRANSITIONS


_PRODUCT_IMPORT_FIELDS = {
    "sku": "sku",
    "ma": "sku",
    "mã": "sku",
    "ma_san_pham": "sku",
    "mã_sản_phẩm": "sku",
    "code": "sku",
    "name": "name",
    "ten": "name",
    "tên": "name",
    "ten_san_pham": "name",
    "tên_sản_phẩm": "name",
    "description": "description",
    "mo_ta": "description",
    "mô_tả": "description",
    "price": "price",
    "gia": "price",
    "giá": "price",
    "stock": "stock_quantity",
    "stock_quantity": "stock_quantity",
    "ton": "stock_quantity",
    "tồn": "stock_quantity",
    "ton_kho": "stock_quantity",
    "tồn_kho": "stock_quantity",
    "status": "status",
    "trang_thai": "status",
    "trạng_thái": "status",
    "category": "category",
    "danh_muc": "category",
    "danh_mục": "category",
    "suitable_for": "suitable_for",
    "phu_hop": "suitable_for",
    "phù_hợp": "suitable_for",
    "doi_tuong": "suitable_for",
    "đối_tượng": "suitable_for",
    "phu_hop_voi": "suitable_for",
    "phù_hợp_với": "suitable_for",
    "doi_tuong_phu_hop": "suitable_for",
    "đối_tượng_phù_hợp": "suitable_for",
    "colors": "colors",
    "mau": "colors",
    "màu": "colors",
    "sizes": "sizes",
    "kich_thuoc": "sizes",
    "kích_thước": "sizes",
    "keywords": "keywords",
    "tu_khoa": "keywords",
    "từ_khóa": "keywords",
}


def _normalise_import_key(value: str) -> str:
    return "_".join(str(value or "").strip().lower().split())


def _parse_import_decimal(value: str, *, row_number: int) -> Decimal:
    raw = str(value or "").strip().replace("₫", "").replace("đ", "").replace("Đ", "")
    if not raw:
        return Decimal("0")
    raw = raw.replace(" ", "")
    # Vietnamese exports commonly use dots as thousands separators and commas
    # for decimals.  Keep a single dot as a decimal point when no comma exists.
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    try:
        amount = Decimal(raw)
    except Exception as exc:
        raise ValueError(f"Dòng {row_number}: giá không hợp lệ.") from exc
    if amount < 0:
        raise ValueError(f"Dòng {row_number}: giá không được âm.")
    return amount


def _parse_import_stock(value: str, *, row_number: int) -> int:
    raw = str(value or "").strip().replace(" ", "")
    if not raw:
        return 0
    try:
        quantity = int(float(raw.replace(",", ".")))
    except Exception as exc:
        raise ValueError(f"Dòng {row_number}: tồn kho không hợp lệ.") from exc
    if quantity < 0:
        raise ValueError(f"Dòng {row_number}: tồn kho không được âm.")
    return quantity


def _import_product_attributes(values: dict[str, str]) -> dict[str, list[str]]:
    """Turn optional CSV facet columns into searchable product metadata."""
    attributes: dict[str, list[str]] = {}
    for key in ("category", "suitable_for", "colors", "sizes", "keywords"):
        raw = str(values.get(key) or "").strip()
        if not raw:
            continue
        parts = [" ".join(part.strip().split()) for part in raw.replace(";", ",").split(",")]
        attributes[key] = list(dict.fromkeys(part for part in parts if part))
    return attributes


def _generated_order_number(db: Session, business_id: int) -> str:
    """Generate a readable, tenant-scoped order number for API clients."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    base = f"ORD-{timestamp}"
    candidate = base
    sequence = 1
    while db.query(Order.id).filter(
        Order.business_id == business_id,
        Order.order_number == candidate,
    ).first() is not None:
        sequence += 1
        candidate = f"{base}-{sequence}"
    return candidate


def _product(db: Session, product_id: int, tenant: TenantContext) -> Product:
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.business_id == tenant.business_id,
    ).first()
    if product is None:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại.")
    return product


def _order(db: Session, order_id: int, tenant: TenantContext) -> Order:
    order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.product),
        joinedload(Order.conversation),
    ).filter(
        Order.id == order_id,
        Order.business_id == tenant.business_id,
    ).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Đơn hàng không tồn tại.")
    return order


def _order_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        business_id=order.business_id,
        customer_id=order.customer_id,
        conversation_id=order.conversation_id,
        channel=order.conversation.channel if order.conversation else None,
        order_number=order.order_number,
        status=order.status,
        total_amount=order.total_amount,
        reserved_quantity=int(order.reserved_quantity or 0),
        reservation_expires_at=order.reservation_expires_at,
        payment_status=order.payment_status,
        paid_amount=order.paid_amount,
        refunded_amount=order.refunded_amount,
        cancel_reason=order.cancel_reason,
        shipping_address=order.shipping_address,
        shipping_phone=order.shipping_phone,
        shipping_provider=order.shipping_provider,
        tracking_code=order.tracking_code,
        shipping_status=order.shipping_status,
        metadata=order.metadata_,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[OrderItemOut(
            id=item.id,
            product_id=item.product_id,
            product_name=item.product.name,
            quantity=item.quantity,
            unit_price=item.unit_price,
            line_total=item.line_total,
            product_name_snapshot=item.product_name_snapshot,
            sku_snapshot=item.sku_snapshot,
        ) for item in order.items],
    )


@router.get("/products", response_model=ProductListOut)
def list_products(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(Product).filter(Product.business_id == tenant.business_id)
    if status:
        query = query.filter(Product.status == status)
    total = query.count()
    products = query.order_by(Product.name.asc(), Product.id.asc()).offset(offset).limit(limit).all()
    return ProductListOut(items=[ProductOut.model_validate(product) for product in products], total=total)


@router.post(
    "/products/import",
    status_code=200,
    dependencies=[Depends(require_write_access)],
)
async def import_products(
    file: UploadFile = File(...),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    """Nhập danh mục sản phẩm từ CSV/TXT theo từng shop.

    The import intentionally accepts a small, human-friendly column set so a
    shop can export a spreadsheet as CSV without learning an internal API.
    A new SKU creates a product.  A SKU that already exists is treated as a
    stock receipt: the imported quantity is added to the existing stock and
    recorded in the inventory ledger.  This makes re-importing a delivery file
    safe and avoids silently replacing the current stock balance.
    """
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Tên tệp không hợp lệ.")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in {"csv", "txt"}:
        raise HTTPException(status_code=400, detail="Chỉ nhận tệp CSV hoặc TXT.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Tệp đang rỗng.")
    if len(file_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Tệp quá lớn. Giới hạn là 20MB.")
    try:
        content = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = file_bytes.decode("cp1258")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Không đọc được tệp. Hãy lưu tệp ở dạng UTF-8 rồi thử lại.") from exc

    try:
        sample = content[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="Tệp cần có hàng tiêu đề, ví dụ: Mã sản phẩm, Tên sản phẩm, Giá, Tồn kho.")
        mapped_headers = {
            header: _PRODUCT_IMPORT_FIELDS.get(_normalise_import_key(header))
            for header in reader.fieldnames
            if header
        }
        if "sku" not in mapped_headers.values() or "name" not in mapped_headers.values():
            raise HTTPException(status_code=400, detail="Tệp cần có ít nhất hai cột Mã sản phẩm (SKU) và Tên sản phẩm.")
    except HTTPException:
        raise
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail="Định dạng tệp không hợp lệ. Hãy dùng CSV có hàng tiêu đề.") from exc

    imported = 0
    # ``updated`` is kept as a backwards-compatible response alias.  The UI
    # uses ``restocked`` so operators can tell that the existing SKU received
    # more stock instead of interpreting the result as a failed import.
    restocked = 0
    restocked_quantity = 0
    skipped = 0
    errors: list[str] = []
    for row_number, row in enumerate(reader, start=2):
        values: dict[str, str] = {}
        for source_key, target_key in mapped_headers.items():
            if target_key and target_key not in values:
                values[target_key] = str(row.get(source_key) or "").strip()
        sku = values.get("sku", "").strip()
        name = values.get("name", "").strip()
        if not sku and not name and not any(str(value or "").strip() for value in row.values()):
            continue
        if not sku or not name:
            skipped += 1
            errors.append(f"Dòng {row_number}: cần có mã sản phẩm và tên sản phẩm.")
            continue
        if len(sku) > 80 or len(name) > 255:
            skipped += 1
            errors.append(f"Dòng {row_number}: mã tối đa 80 ký tự, tên tối đa 255 ký tự.")
            continue
        try:
            price = _parse_import_decimal(values.get("price", ""), row_number=row_number)
            stock = _parse_import_stock(values.get("stock_quantity", ""), row_number=row_number)
        except ValueError as exc:
            skipped += 1
            errors.append(str(exc))
            continue
        status = values.get("status", "active").strip().lower() or "active"
        status_aliases = {"đang bán": "active", "dang ban": "active", "hoạt động": "active", "active": "active", "lưu trữ": "archived", "luu tru": "archived", "archived": "archived", "inactive": "archived"}
        status = status_aliases.get(status, status)
        if status not in {"active", "archived"}:
            skipped += 1
            errors.append(f"Dòng {row_number}: trạng thái chỉ có Đang bán hoặc Lưu trữ.")
            continue
        imported_attributes = _import_product_attributes(values)

        product = db.query(Product).filter(
            Product.business_id == tenant.business_id,
            Product.sku == sku,
        ).with_for_update().first()
        if product is None:
            product = Product(
                business_id=tenant.business_id,
                sku=sku,
                name=name,
                description=values.get("description") or None,
                price=price,
                stock_quantity=stock,
                status=status,
                metadata_={"attributes": imported_attributes} if imported_attributes else {},
            )
            db.add(product)
            db.flush()
            if stock > 0:
                db.add(StockMovement(
                    business_id=tenant.business_id,
                    product_id=product.id,
                    movement_type="opening_balance",
                    quantity=stock,
                    quantity_before=0,
                    quantity_after=stock,
                    source_type="product_import",
                    source_id=product.id,
                    actor_id=actor.id if actor else None,
                    note=f"Nhập từ tệp {filename}",
                ))
            imported += 1
        else:
            before = int(product.stock_quantity or 0)
            after = before + stock
            product.name = name
            product.description = values.get("description") or None
            product.price = price
            product.status = status
            product.stock_quantity = after
            if imported_attributes:
                metadata = dict(product.metadata_ or {})
                metadata["attributes"] = imported_attributes
                product.metadata_ = metadata
            if stock > 0:
                db.add(StockMovement(
                    business_id=tenant.business_id,
                    product_id=product.id,
                    movement_type="inventory_import",
                    quantity=stock,
                    quantity_before=before,
                    quantity_after=after,
                    source_type="product_import",
                    source_id=product.id,
                    actor_id=actor.id if actor else None,
                    note=f"Cộng tồn từ tệp {filename}",
                ))
            restocked += 1
            restocked_quantity += stock

    if imported == 0 and restocked == 0:
        db.rollback()
        detail = "Không có sản phẩm hợp lệ để nhập."
        if errors:
            detail += " " + " ".join(errors[:3])
        raise HTTPException(status_code=400, detail=detail)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Có mã sản phẩm trùng. Hãy kiểm tra lại tệp rồi nhập lại.") from exc
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="import",
        resource_type="product_catalog",
        metadata={
            "filename": filename,
            "imported": imported,
            "restocked": restocked,
            "restocked_quantity": restocked_quantity,
            "skipped": skipped,
        },
    )
    db.commit()
    return {
        "filename": filename,
        "imported": imported,
        "restocked": restocked,
        "restocked_quantity": restocked_quantity,
        # Preserve the old field for API clients that still read it.
        "updated": restocked,
        "skipped": skipped,
        "errors": errors[:25],
    }


@router.post("/products", response_model=ProductOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    product = Product(
        business_id=tenant.business_id,
        sku=payload.sku.strip(),
        name=payload.name.strip(),
        description=payload.description,
        price=payload.price,
        stock_quantity=payload.stock_quantity,
        status=payload.status,
        metadata_=payload.metadata,
    )
    db.add(product)
    db.flush()
    initial_stock = int(product.stock_quantity or 0)
    if initial_stock > 0:
        db.add(StockMovement(
            business_id=tenant.business_id,
            product_id=product.id,
            movement_type="opening_balance",
            quantity=initial_stock,
            quantity_before=0,
            quantity_after=initial_stock,
            source_type="product_initialization",
            source_id=product.id,
            actor_id=actor.id if actor else None,
            note="Tồn đầu khi tạo sản phẩm",
        ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="SKU đã tồn tại trong business này.") from exc
    db.refresh(product)
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="create", resource_type="product", resource_id=str(product.id), metadata={"sku": product.sku})
        db.commit()
    return product


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return _product(db, product_id, tenant)


@router.patch("/products/{product_id}", response_model=ProductOut, dependencies=[Depends(require_write_access)])
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    product = _product(db, product_id, tenant)
    values = payload.model_dump(exclude_unset=True)
    if "stock_quantity" in values:
        requested_stock = int(values.pop("stock_quantity"))
        if requested_stock != int(product.stock_quantity or 0):
            raise HTTPException(
                status_code=409,
                detail="Không sửa tồn trực tiếp; dùng endpoint inventory adjustment để ghi ledger.",
            )
    for field, value in values.items():
        setattr(product, "metadata_" if field == "metadata" else field, value.strip() if isinstance(value, str) else value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="SKU đã tồn tại trong business này.") from exc
    db.refresh(product)
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="update", resource_type="product", resource_id=str(product.id), metadata={"fields": list(payload.model_dump(exclude_unset=True))})
        db.commit()
    return product


@router.delete("/products/{product_id}", status_code=204, dependencies=[Depends(require_write_access)])
def delete_product(
    product_id: int,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    product = _product(db, product_id, tenant)
    product.status = "archived"
    db.commit()
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="archive", resource_type="product", resource_id=str(product.id))
        db.commit()


@router.get("/orders", response_model=OrderListOut)
def list_orders(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    status: str | None = None,
    customer_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.product),
        joinedload(Order.conversation),
    ).filter(
        Order.business_id == tenant.business_id,
    )
    if status:
        query = query.filter(Order.status == status)
    if customer_id is not None:
        query = query.filter(Order.customer_id == customer_id)
    total = query.count()
    orders = query.order_by(Order.created_at.desc(), Order.id.desc()).offset(offset).limit(limit).all()
    return OrderListOut(items=[_order_out(order) for order in orders], total=total)


@router.get("/reports/revenue-by-channel", response_model=RevenueByChannelOut)
def revenue_by_channel(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Aggregate tenant orders by the channel of their originating conversation.

    Orders without a linked conversation remain visible under ``unknown`` so the
    report never silently drops revenue. Both the order and conversation are
    constrained to the active tenant.
    """
    channel_expr = func.coalesce(Conversation.channel, "unknown")
    rows = (
        db.query(
            channel_expr.label("channel"),
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.total_amount), Decimal("0")).label("revenue"),
        )
        .outerjoin(
            Conversation,
            (Conversation.id == Order.conversation_id)
            & (Conversation.business_id == tenant.business_id),
        )
        .filter(Order.business_id == tenant.business_id)
        .filter(Order.status.in_(REVENUE_ORDER_STATUSES))
        .group_by(channel_expr)
        .order_by(channel_expr.asc())
        .all()
    )
    items = [RevenueChannelItem(
        channel=str(row.channel),
        order_count=int(row.order_count),
        revenue=Decimal(row.revenue or 0),
    ) for row in rows]
    return RevenueByChannelOut(
        items=items,
        total_revenue=sum((item.revenue for item in items), Decimal("0")),
    )


@router.post("/orders", response_model=OrderOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_tenant_db),
    platform_db: Session = Depends(get_platform_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    initial_status = payload.status.strip().lower()
    if initial_status != "draft":
        raise HTTPException(status_code=422, detail="Đơn mới phải bắt đầu ở trạng thái draft.")

    customer = db.query(Customer).filter(
        Customer.id == payload.customer_id,
        Customer.business_id == tenant.business_id,
    ).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer không tồn tại.")

    conversation = None
    if payload.conversation_id is not None:
        conversation = db.query(Conversation).filter(
            Conversation.id == payload.conversation_id,
            Conversation.business_id == tenant.business_id,
            Conversation.customer_id == payload.customer_id,
        ).first()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation không thuộc customer/business này.")

    product_ids = [item.product_id for item in payload.items]
    products = db.query(Product).filter(
        Product.business_id == tenant.business_id,
        Product.id.in_(product_ids),
    ).all()
    product_map = {product.id: product for product in products}
    missing = [product_id for product_id in product_ids if product_id not in product_map]
    if missing:
        raise HTTPException(status_code=404, detail=f"Sản phẩm không tồn tại trong tenant: {missing}")

    order_number = (payload.order_number or "").strip()
    if not order_number:
        order_number = _generated_order_number(db, tenant.business_id)
    if payload.status.strip().lower() != "draft":
        raise HTTPException(status_code=422, detail="Sales Order mới phải bắt đầu ở trạng thái draft.")

    order = Order(
        business_id=tenant.business_id,
        customer_id=customer.id,
        conversation_id=conversation.id if conversation else None,
        order_number=order_number,
        status=initial_status,
        shipping_address=payload.shipping_address,
        shipping_phone=payload.shipping_phone,
        metadata_=payload.metadata,
        total_amount=Decimal("0"),
    )
    db.add(order)
    db.flush()
    total = Decimal("0")
    for item_payload in payload.items:
        product = product_map[item_payload.product_id]
        unit_price = Decimal(product.price)
        line_total = unit_price * item_payload.quantity
        total += line_total
        db.add(OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=item_payload.quantity,
            unit_price=unit_price,
            line_total=line_total,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku,
        ))
    order.total_amount = total
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mã đơn hàng đã tồn tại trong business này.") from exc
    emit_workflow_event(
        db,
        tenant,
        "order.created",
        f"order:{order.id}:created",
        {"order_id": order.id, "customer_id": order.customer_id, "conversation_id": order.conversation_id, "status": order.status, "total_amount": float(order.total_amount or 0)},
        platform_db=platform_db,
    )
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="create", resource_type="sales_order", resource_id=str(order.id), metadata={"order_number": order.order_number, "total_amount": float(order.total_amount or 0)})
        db.commit()
    return _order_out(_order(db, order.id, tenant))


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return _order_out(_order(db, order_id, tenant))


@router.patch("/orders/{order_id}/logistics", response_model=OrderOut, dependencies=[Depends(require_write_access)])
def update_order_logistics(
    order_id: int,
    payload: OrderLogisticsUpdate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=422, detail="Cần ít nhất một trường logistics để cập nhật.")
    order = _order(db, order_id, tenant)
    for field, value in values.items():
        setattr(order, field, value.strip() if isinstance(value, str) else value)
    db.add(OrderEvent(
        business_id=tenant.business_id,
        order_type="sales_order",
        order_id=order.id,
        event_type="logistics_updated",
        actor_id=actor.id if actor else None,
        metadata_={
            "shipping_provider": order.shipping_provider,
            "shipping_status": order.shipping_status,
            "fields": list(values),
        },
    ))
    db.commit()
    if actor:
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id,
            action="update",
            resource_type="sales_order_logistics",
            resource_id=str(order.id),
            metadata={"shipping_provider": order.shipping_provider, "shipping_status": order.shipping_status},
        )
        db.commit()
    return _order_out(_order(db, order.id, tenant))


@router.patch("/orders/{order_id}", response_model=OrderOut, dependencies=[Depends(require_write_access)])
def update_order(
    order_id: int,
    payload: OrderUpdate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    order = _order(db, order_id, tenant)
    values = payload.model_dump(exclude_unset=True)
    if "status" in values:
        raise HTTPException(status_code=409, detail="Trạng thái đơn phải đổi qua endpoint transition để cập nhật tồn kho.")
    for field, value in values.items():
        setattr(order, "metadata_" if field == "metadata" else field, value)
    db.commit()
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="update", resource_type="sales_order", resource_id=str(order.id), metadata={"fields": list(payload.model_dump(exclude_unset=True))})
        db.commit()
    return _order_out(_order(db, order_id, tenant))


@router.post("/orders/{order_id}/transition", response_model=OrderOut, dependencies=[Depends(require_write_access)])
def transition_order(
    order_id: int,
    payload: OrderTransition,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    try:
        transition_sales_order(
            db,
            order_id=order_id,
            to_status=payload.to_status,
            actor_id=actor.id if actor else None,
            business_id=tenant.business_id,
        )
        db.commit()
    except SalesOrderOperationError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    order = _order(db, order_id, tenant)
    if actor:
        record_audit(db, business_id=tenant.business_id, user_id=actor.id, action="transition", resource_type="sales_order", resource_id=str(order.id), metadata={"to_status": order.status})
        db.commit()
    if order.status == "delivered" and order.conversation_id is not None:
        try:
            from app.services.chatbot_followup import schedule_post_delivery_followup

            schedule_post_delivery_followup(
                db,
                business_id=tenant.business_id,
                conversation_id=int(order.conversation_id),
                order_id=order.id,
                run_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=24),
            )
            db.commit()
        except Exception:
            # Customer-care reminders are additive; a missing optional table
            # or scheduler must not make a successful delivery look failed.
            db.rollback()
    return _order_out(_order(db, order_id, tenant))
