"""Read-only CRM answers shared with internal RAG chat; all queries are tenant scoped."""
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from app.models.business import User
from app.models.customer_note import CustomerNote
from app.models.lead import Lead
from app.models.message import Message
from app.services.permission_service import permission_allowed
from app.services.crm_workspace_config import get_crm_workspace_config
from app.models.customer import Customer
from app.models.conversation import Conversation
from app.models.sales import Order, OrderItem, Product
from app.rag.lexical import identifiers
from app.rag.prompt_builder import detect_reply_language
from app.rag.topics import fold_topic_text
from app.schemas.rag import ChatResponse, SourceChunk
from app.services.chatbot_router import classify_crm_query, classify_intent
from app.services.auto_reply_service import (
    _find_exact_product, _format_product_fact_reply, _format_product_detail_reply,
    _is_price_question, _fold_text, build_product_catalog_reply,
    _contextual_retrieval_query, _is_product_attribute_question, _is_generic_product_detail_question,
    _is_product_fact_question,
)
from app.services.customer_order_service import extract_order_number, ORDER_STATUS_LABELS
from app.services.customer_collection_flow import is_stock_query_request
from app.services.privacy_service import customer_memory_opt_out_reply


def _is_monthly_bestseller_question(query: str) -> bool:
    folded = _fold_text(query)
    current_month = any(term in folded for term in ("thang nay", "this month", "current month"))
    sales_terms = ("ban chay", "ban nhieu", "bestseller", "top san pham", "best selling", "top selling", "most sold")
    return current_month and any(term in folded for term in sales_terms)


def _is_monthly_revenue_question(query: str) -> bool:
    folded = _fold_text(query)
    current_month = any(term in folded for term in ("thang nay", "this month", "current month"))
    return current_month and any(term in folded for term in (
        "doanh thu", "tong doanh so", "tong doanh thu", "sales revenue", "revenue",
    ))


def _monthly_revenue_reply(db, business_id: int, *, english: bool) -> ChatResponse:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month_start = (
        month_start.replace(year=month_start.year + 1, month=1)
        if month_start.month == 12
        else month_start.replace(month=month_start.month + 1)
    )
    paid_orders = db.query(Order).filter(
        Order.business_id == business_id,
        Order.status.in_(("completed", "delivered")),
        Order.payment_status == "paid",
        Order.total_amount > Order.refunded_amount,
        Order.created_at >= month_start,
        Order.created_at < next_month_start,
    )
    row = paid_orders.with_entities(
        func.count(Order.id),
        func.coalesce(func.sum(Order.total_amount - Order.refunded_amount), 0),
    ).one()
    order_count, revenue = int(row[0] or 0), float(row[1] or 0)
    period = month_start.strftime("%Y-%m")
    if not order_count:
        answer = (
            "There is no verified paid, completed sales data for this month yet. A staff member should check the sales report."
            if english else
            "Chưa có dữ liệu đơn đã hoàn tất và thanh toán trong tháng này để xác nhận doanh thu. Nhân viên cần kiểm tra báo cáo bán hàng."
        )
        return ChatResponse(answer=answer, sources=[], chunks_found=0, action="lookup_sales_summary",
                            answer_status="no_context", handoff_required=True,
                            data_sources=[{"type": "crm_sales_summary", "period": period, "orders": 0}])
    amount = f"{revenue:,.0f}".replace(",", ".")
    answer = (
        f"Verified paid sales for {period}: {order_count} completed orders, net revenue {amount} VND."
        if english else
        f"Doanh thu thuần đã thanh toán trong tháng {month_start.month}/{month_start.year} là {amount} đồng từ {order_count} đơn hoàn tất."
    )
    return ChatResponse(answer=answer, sources=[], chunks_found=0, action="lookup_sales_summary",
                        data_sources=[{"type": "crm_sales_summary", "period": period,
                                       "completed_paid_orders": order_count, "net_revenue": revenue}])


def _monthly_bestseller_reply(db, business_id: int, *, english: bool) -> ChatResponse:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month_start = (
        month_start.replace(year=month_start.year + 1, month=1)
        if month_start.month == 12
        else month_start.replace(month=month_start.month + 1)
    )
    units_sold = func.sum(OrderItem.quantity)
    rows = db.query(Product.id, Product.name, Product.sku, units_sold.label("units_sold")).join(
        OrderItem, OrderItem.product_id == Product.id,
    ).join(Order, Order.id == OrderItem.order_id).filter(
        Product.business_id == business_id,
        Product.status == "active",
        Order.business_id == business_id,
        or_(Order.status == "completed", and_(Order.status == "delivered", Order.payment_status == "paid")),
        Order.payment_status == "paid",
        Order.total_amount > Order.refunded_amount,
        Order.created_at >= month_start,
        Order.created_at < next_month_start,
    ).group_by(Product.id, Product.name, Product.sku).order_by(units_sold.desc(), Product.id.asc()).limit(3).all()
    period = month_start.strftime("%Y-%m")
    if not rows:
        answer = (
            "There is not enough completed sales data for this month to verify a bestseller. A staff member should check the sales report."
            if english else
            "Chưa có đủ dữ liệu bán hàng đã hoàn tất trong tháng này để xác nhận sản phẩm bán chạy. Nhân viên cần kiểm tra báo cáo bán hàng."
        )
        return ChatResponse(answer=answer, sources=[], chunks_found=0, answer_status="no_context",
                            handoff_required=True, action="lookup_product_catalog",
                            data_sources=[{"type": "crm_sales_rank", "period": period, "items": 0}])

    lines = [f"- {name} ({sku}): {int(quantity)}" for _product_id, name, sku, quantity in rows]
    answer = (
        f"Based on completed sales data for {period}, the top-selling products are:\n" + "\n".join(lines)
        if english else
        f"Theo dữ liệu bán hàng đã hoàn tất trong tháng {month_start.month}/{month_start.year}, các sản phẩm bán chạy nhất là:\n"
        + "\n".join(lines)
    )
    return ChatResponse(answer=answer, sources=[], chunks_found=0, action="lookup_product_catalog",
                        data_sources=[{"type": "crm_sales_rank", "period": period,
                                       "items": [{"product_id": int(product_id), "units_sold": int(quantity)}
                                                 for product_id, _name, _sku, quantity in rows]}])


def _crm_no_context(action: str, *, english: bool, message: str, handoff: bool = True) -> ChatResponse:
    return ChatResponse(
        answer=message,
        sources=[],
        chunks_found=0,
        action=action,
        answer_status="no_context",
        handoff_required=handoff,
    )


def _crm_source(
    citation_id: int,
    *,
    source_type: str,
    record_id: int | None,
    filename: str,
    content: str,
    customer_id: int | None = None,
    deal_id: int | None = None,
    owner_user_id: int | None = None,
    status: str | None = None,
    stage: str | None = None,
    updated_at: datetime | None = None,
    extra: dict | None = None,
) -> SourceChunk:
    metadata = {
        "source_type": source_type,
        "record_id": record_id,
        "customer_id": customer_id,
        "deal_id": deal_id,
        "owner_user_id": owner_user_id,
        "status": status,
        "stage": stage,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "access_scope": "tenant",
    }
    if extra:
        metadata.update(extra)
    return SourceChunk(
        document_id=None,
        content=content[:700],
        similarity=1.0,
        metadata=metadata,
        citation_id=citation_id,
        filename=filename,
        source_type=source_type,
        record_id=record_id,
        customer_id=customer_id,
        deal_id=deal_id,
        owner_user_id=owner_user_id,
        status=status,
        stage=stage,
        updated_at=updated_at,
    )


def _crm_citation(index: int, english: bool) -> str:
    return f"[Source {index}]" if english else f"[Nguồn {index}]"


def _has_crm_permission(permission_db, user, business_id: int, resource: str) -> bool:
    return bool(
        permission_db is not None
        and user is not None
        and int(getattr(user, "business_id", 0) or 0) == int(business_id)
        and permission_allowed(permission_db, user, resource=resource, action="read")
    )


def _extract_customer_id(query: str) -> int | None:
    patterns = (
        r"(?:customer(?:\s+(?:id|#))?|khách(?:\s+hàng)?(?:\s+(?:id|mã|#))?|"
        r"mã\s+khách(?:\s+hàng)?|id\s+khách(?:\s+hàng)?)\s*[:#-]?\s*(\d+)",
        r"#(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


_CUSTOMER_QUERY_WORDS = {
    "tim", "tra", "cuu", "xem", "ho", "so", "khach", "hang", "customer", "profile",
    "lich", "su", "trao", "doi", "noi", "dung", "conversation", "history", "message",
    "recent", "last", "gan", "day", "cuoc", "tro", "chuyen", "voi", "with", "ten", "id", "ma",
    "tuan", "thang", "hom", "nay", "truoc", "this", "week", "month", "today",
    "ghi", "chu", "notes", "note",
    "giup", "toi", "minh", "cho", "biet", "la", "ai", "nay", "ve", "cua", "thong", "tin",
    "theo", "chinh", "xac",
}


def _customer_name_query(query: str) -> str:
    tokens = re.findall(r"[\wÀ-ỹ][\wÀ-ỹ'.-]*", query, re.UNICODE)
    kept = [
        token.strip(" .'-")
        for token in tokens
        if len(token.strip(" .'-")) > 1
        and fold_topic_text(token) not in _CUSTOMER_QUERY_WORDS
        and not token.strip(" .'-").isdigit()
    ]
    return " ".join(kept[:6]).strip()


_NAME_ACCENTS = "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ"
_NAME_ASCII = "".join(
    "d" if char == "đ" else unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode()
    for char in _NAME_ACCENTS
)


def _folded_customer_name(db):
    dialect = getattr(getattr(db.get_bind(), "dialect", None), "name", "")
    if dialect == "sqlite":
        connection = db.connection().connection
        driver_connection = getattr(connection, "driver_connection", connection)
        driver_connection.create_function("rag_fold", 1, fold_topic_text)
        return func.rag_fold(Customer.name)
    if dialect == "postgresql":
        return func.translate(func.lower(Customer.name), _NAME_ACCENTS, _NAME_ASCII)
    return func.lower(Customer.name)


def _resolve_customer(db, business_id: int, request, selected_customer_id: int | None):
    explicit_id = _extract_customer_id(request.query)
    customer_id = explicit_id or selected_customer_id
    query = db.query(Customer).filter(
        Customer.business_id == business_id,
        Customer.status != "merged",
    )
    if customer_id is not None:
        return query.filter(Customer.id == customer_id).first(), [], False

    name = _customer_name_query(request.query)
    if not name:
        return None, [], False

    folded_name = _folded_customer_name(db)
    folded_query = fold_topic_text(name)
    exact = query.filter(folded_name == folded_query).limit(2).all()
    matches = exact
    if not matches:
        partial = query
        for token in folded_query.split():
            escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            partial = partial.filter(folded_name.like(f"%{escaped}%", escape="\\"))
        matches = partial.order_by(Customer.id.asc()).limit(3).all()
    if len(matches) == 1:
        return matches[0], matches, False
    return None, matches, len(matches) > 1


def _date_window(query: str) -> tuple[datetime | None, datetime | None, str | None]:
    folded = fold_topic_text(query)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "hom nay" in folded or "today" in folded:
        return today, today + timedelta(days=1), "today"
    if "tuan nay" in folded or "this week" in folded:
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=7), "this_week"
    if "tuan truoc" in folded or "last week" in folded:
        end = today - timedelta(days=today.weekday())
        return end - timedelta(days=7), end, "last_week"
    if "thang nay" in folded or "this month" in folded:
        start = today.replace(day=1)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        return start, end, "this_month"
    if "thang truoc" in folded or "last month" in folded:
        end = today.replace(day=1)
        start = end.replace(year=end.year - 1, month=12) if end.month == 1 else end.replace(month=end.month - 1)
        return start, end, "last_month"
    iso_dates = re.findall(r"(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)", query)
    if iso_dates:
        try:
            parsed = [date(int(y), int(m), int(d)) for y, m, d in iso_dates[:2]]
        except ValueError:
            return None, None, None
        if len(parsed) == 2 and parsed[1] < parsed[0]:
            parsed.reverse()
        start = datetime.combine(parsed[0], datetime.min.time())
        end_day = parsed[1] if len(parsed) == 2 else parsed[0]
        return start, datetime.combine(end_day + timedelta(days=1), datetime.min.time()), "custom"
    return None, None, None


def _crm_pipeline_reply(db, business_id: int, request, *, user, permission_db, user_db, english: bool):
    action = "lookup_crm_pipeline"
    if not _has_crm_permission(permission_db, user, business_id, "leads"):
        return _crm_no_context(
            action, english=english,
            message="You do not have access to CRM leads." if english else "Tài khoản này không có quyền xem dữ liệu cơ hội CRM.",
        )

    query = db.query(Lead, Customer.name).join(
        Customer, and_(Customer.id == Lead.customer_id, Customer.business_id == business_id),
    ).filter(Lead.business_id == business_id)
    filters: dict[str, object] = {}
    folded = fold_topic_text(request.query)

    if any(term in folded for term in ("dang mo", "open", "chua dong", "active")):
        query = query.filter(Lead.status == "open")
        filters["status"] = "open"
    elif any(term in folded for term in ("da dong", "closed")):
        query = query.filter(Lead.status == "closed")
        filters["status"] = "closed"

    config = get_crm_workspace_config(db, business_id)
    stages = config.get("pipeline_stages", [])
    matched_stage = next((
        stage for stage in stages
        if stage.get("label") and fold_topic_text(stage["label"]) in folded
    ), None)
    if matched_stage:
        query = query.filter(Lead.stage == str(matched_stage["key"]))
        filters["stage"] = str(matched_stage["key"])
        filters["stage_label"] = str(matched_stage["label"])

    period_start, period_end, period_name = _date_window(request.query)
    if period_start:
        query = query.filter(Lead.created_at >= period_start)
        query = query.filter(Lead.created_at < period_end)
        filters["created_period"] = period_name
        filters["created_from"] = period_start.isoformat()
        filters["created_until"] = period_end.isoformat()

    own_work_terms = ("cua toi", "my deals", "my leads", "assigned to me")
    if any(term in folded for term in own_work_terms):
        if user is None:
            return _crm_no_context(
                action, english=english,
                message="Sign in to filter by assignee." if english else "Bạn cần đăng nhập để lọc theo người phụ trách.",
            )
        query = query.filter(Lead.assigned_user_id == user.id)
        filters["assigned_user_id"] = int(user.id)
        filters["assignee"] = "current_user"
    else:
        owner_terms = ("phu trach", "assigned to", "owner", "cua ")
        if user_db is not None and any(term in folded for term in owner_terms):
            users = user_db.query(User).filter(
                User.business_id == business_id, User.is_active.is_(True),
            ).all()
            owner_matches = [person for person in users if fold_topic_text(person.full_name) in folded]
            if len(owner_matches) == 1:
                query = query.filter(Lead.assigned_user_id == owner_matches[0].id)
                filters["assigned_user_id"] = int(owner_matches[0].id)
                filters["assignee"] = owner_matches[0].full_name
            elif len(owner_matches) > 1:
                names = ", ".join(person.full_name for person in owner_matches[:3])
                return _crm_no_context(
                    action, english=english,
                    message=(f"Which assignee do you mean: {names}?" if english
                             else f"Bạn muốn lọc theo người phụ trách nào: {names}?"),
                    handoff=False,
                )

    lead_id_match = re.search(r"\b(?:deal|lead)\s*#?\s*(\d+)\b", request.query, re.IGNORECASE)
    if lead_id_match:
        query = query.filter(Lead.id == int(lead_id_match.group(1)))
        filters["deal_id"] = int(lead_id_match.group(1))

    count = query.count()
    rows = query.order_by(Lead.updated_at.desc(), Lead.id.desc()).limit(5).all()
    if count == 0:
        answer = (
            "No CRM deals match those filters." if english
            else "Không có deal CRM nào khớp với các bộ lọc này."
        )
        summary = _crm_source(
            1, source_type="crm_lead_query", record_id=None, filename="CRM · kết quả lọc deal",
            content=f"Verified CRM lead query returned 0 records. Filters: {filters}.",
            extra={"filters": filters, "matched_count": 0},
        )
        return ChatResponse(
            answer=f"{answer} {_crm_citation(1, english)}",
            sources=[summary], chunks_found=1, action=action,
            data_sources=[{"type": "crm_lead_query", "filters": filters, "matched_count": 0}],
        )

    is_count = any(term in folded for term in ("bao nhieu", "so luong", "dem", "how many", "count"))
    label = "deal" if english else "deal"
    if is_count:
        answer = (
            f"The CRM contains {count} matching {label}{'' if count == 1 else 's'}."
            if english else f"CRM có {count} deal khớp với các bộ lọc đã nêu."
        ) + f" {_crm_citation(1, english)}"
        summary = _crm_source(
            1, source_type="crm_lead_query", record_id=None, filename="CRM · tổng hợp pipeline",
            content=f"Verified CRM lead query returned {count} records. Filters: {filters}.",
            extra={"filters": filters, "matched_count": count},
        )
        sources = [summary]
    else:
        sources = []
        lines = []
        owner_ids = {int(lead.assigned_user_id) for lead, _name in rows if lead.assigned_user_id}
        owners = {
            int(person.id): person.full_name
            for person in (user_db.query(User).filter(User.id.in_(owner_ids)).all() if user_db and owner_ids else [])
        }
        stage_labels = {str(item["key"]): str(item["label"]) for item in stages if item.get("key") and item.get("label")}
        for index, (lead, customer_name) in enumerate(rows, start=1):
            stage_label = stage_labels.get(lead.stage, lead.stage)
            assignee = owners.get(int(lead.assigned_user_id), "") if lead.assigned_user_id else ""
            content = (
                f"Deal #{lead.id}: {lead.title}; customer #{lead.customer_id} {customer_name or ''}; "
                f"status={lead.status}; stage={stage_label}; assignee={assignee or 'unassigned'}; "
                f"updated_at={lead.updated_at.isoformat() if lead.updated_at else ''}."
            )
            sources.append(_crm_source(
                index, source_type="crm_lead", record_id=int(lead.id), filename=f"Deal #{lead.id} · {lead.title}",
                content=content, customer_id=int(lead.customer_id), deal_id=int(lead.id),
                owner_user_id=int(lead.assigned_user_id) if lead.assigned_user_id else None,
                status=lead.status, stage=lead.stage, updated_at=lead.updated_at,
                extra={"stage_label": stage_label, "assignee": assignee or None},
            ))
            line = (
                f"- Deal #{lead.id}: {lead.title}; customer #{lead.customer_id} ({customer_name or 'unknown'}); "
                f"status {lead.status}; stage {stage_label}"
            )
            if assignee:
                line += f"; assignee {assignee}"
            lines.append(f"{line} {_crm_citation(index, english)}")
        answer = ("Matching CRM deals:\n" if english else "Các deal CRM phù hợp:\n") + "\n".join(lines)
        if count > len(rows):
            answer += (f"\nShowing the latest {len(rows)} of {count} matching deals."
                       if english else f"\nĐang hiển thị {len(rows)} deal mới cập nhật nhất trong tổng số {count} deal.")
    summary_data = {
        "type": "crm_lead_query", "filters": filters, "matched_count": count,
        "record_ids": [int(lead.id) for lead, _name in rows],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return ChatResponse(
        answer=answer, sources=sources, chunks_found=len(sources), action=action,
        data_sources=[summary_data],
    )


def _crm_customer_reply(
    db, business_id: int, request, selected_customer_id: int | None,
    *, user, permission_db, english: bool, action: str,
):
    if not _has_crm_permission(permission_db, user, business_id, "customers"):
        return _crm_no_context(
            action, english=english,
            message="You do not have access to CRM customer records." if english else "Tài khoản này không có quyền xem hồ sơ khách hàng CRM.",
        )

    customer, candidates, ambiguous = _resolve_customer(db, business_id, request, selected_customer_id)
    if ambiguous:
        sources = [
            _crm_source(
                index, source_type="crm_customer", record_id=int(item.id),
                filename=f"Khách hàng #{item.id} · {item.name or 'Chưa có tên'}",
                content=f"Customer #{item.id}; name={item.name or ''}; channel={item.channel}; status={item.status}.",
                customer_id=int(item.id), updated_at=item.updated_at,
            )
            for index, item in enumerate(candidates, start=1)
        ]
        choices = ", ".join(
            f"{item.name or 'Chưa có tên'} (#{item.id}) {_crm_citation(index, english)}"
            for index, item in enumerate(candidates, start=1)
        )
        return ChatResponse(
            answer=(f"Which customer do you mean: {choices}?" if english else f"Có nhiều khách hàng khớp. Bạn chọn hồ sơ nào: {choices}?"),
            sources=sources, chunks_found=len(sources), action=action,
            answer_status="no_context", handoff_required=False,
        )
    if customer is None:
        if selected_customer_id is None and _extract_customer_id(request.query) is None and not _customer_name_query(request.query):
            return _crm_no_context(
                action, english=english,
                message="Which customer should I look up? Give the exact name or customer ID." if english
                else "Bạn muốn tra cứu khách hàng nào? Hãy gửi tên chính xác hoặc mã khách hàng.",
                handoff=False,
            )
        return _crm_no_context(
            action, english=english,
            message="No matching CRM customer record was found." if english
            else "Không tìm thấy hồ sơ khách hàng CRM khớp với tên hoặc mã đã cung cấp.",
        )

    customer_id = int(customer.id)
    customer_name = customer.name or (f"Customer #{customer_id}" if english else f"Khách hàng #{customer_id}")
    if action == "lookup_crm_customer":
        content = (
            f"Customer #{customer_id}; name={customer_name}; channel={customer.channel}; "
            f"status={customer.status}; updated_at={customer.updated_at.isoformat() if customer.updated_at else ''}."
        )
        source = _crm_source(
            1, source_type="crm_customer", record_id=customer_id,
            filename=(f"Customer #{customer_id} · {customer_name}" if english else f"Hồ sơ khách hàng #{customer_id} · {customer_name}"),
            content=content, customer_id=customer_id, updated_at=customer.updated_at,
        )
        answer = (
            f"CRM customer: {customer_name} (ID #{customer_id}), channel {customer.channel}, status {customer.status}. {_crm_citation(1, english)}"
            if english else
            f"Khách hàng CRM: {customer_name} (mã #{customer_id}), kênh {customer.channel}, trạng thái {customer.status}. {_crm_citation(1, english)}"
        )
        return ChatResponse(
            answer=answer, sources=[source], chunks_found=1, action=action,
            data_sources=[{"type": "crm_customer", "record_id": customer_id, "customer_id": customer_id,
                           "source_type": "customer_profile", "updated_at": customer.updated_at.isoformat() if customer.updated_at else None,
                           "access_scope": "tenant"}],
        )

    if action == "lookup_crm_notes":
        notes_query = db.query(CustomerNote).filter(
            CustomerNote.business_id == business_id, CustomerNote.customer_id == customer_id,
        )
        period_start, period_end, period_name = _date_window(request.query)
        if period_start:
            notes_query = notes_query.filter(
                CustomerNote.created_at >= period_start,
                CustomerNote.created_at < period_end,
            )
        notes = notes_query.order_by(CustomerNote.updated_at.desc(), CustomerNote.id.desc()).limit(5).all()
        if not notes:
            return _crm_no_context(
                action, english=english,
                message="No CRM notes were found for this customer." if english
                else f"Chưa có ghi chú CRM cho {customer_name}.",
            )
        sources, lines = [], []
        for index, note in enumerate(notes, start=1):
            content = f"Customer #{customer_id} note #{note.id}: {note.content}"
            sources.append(_crm_source(
                index, source_type="crm_customer_note", record_id=int(note.id),
                filename=f"Ghi chú #{note.id} · {customer_name}", content=content,
                customer_id=customer_id, updated_at=note.updated_at or note.created_at,
                extra={"created_by": note.created_by},
            ))
            lines.append(f"- {note.content[:300]} {_crm_citation(index, english)}")
        answer = ("CRM notes:\n" if english else f"Ghi chú CRM của {customer_name}:\n") + "\n".join(lines)
        return ChatResponse(
            answer=answer, sources=sources, chunks_found=len(sources), action=action,
            data_sources=[{"type": "crm_customer_note", "customer_id": customer_id,
                           "record_ids": [int(note.id) for note in notes], "period": period_name,
                           "access_scope": "tenant"}],
        )

    period_start, period_end, period_name = _date_window(request.query)
    messages_query = db.query(Message, Conversation).join(
        Conversation, Conversation.id == Message.conversation_id,
    ).filter(
        Conversation.business_id == business_id,
        Conversation.customer_id == customer_id,
        Message.content.isnot(None),
        Message.content != "",
    )
    if period_start:
        message_time = func.coalesce(Message.received_at, Message.sent_at)
        messages_query = messages_query.filter(message_time >= period_start, message_time < period_end)
    messages = messages_query.order_by(
        func.coalesce(Message.received_at, Message.sent_at).desc(), Message.id.desc(),
    ).limit(5).all()
    if not messages:
        return _crm_no_context(
            action, english=english,
            message="No conversation messages were found for this customer in the requested period." if english
            else f"Không tìm thấy tin nhắn trao đổi của {customer_name} trong khoảng thời gian yêu cầu.",
        )
    sources, lines = [], []
    for index, (message, conversation) in enumerate(messages, start=1):
        timestamp = message.received_at or message.sent_at
        content = (
            f"Message #{message.id}; customer #{customer_id}; conversation #{conversation.id}; "
            f"sender={message.sender_type}; at={timestamp.isoformat() if timestamp else 'unknown'}; "
            f"content={message.content}"
        )
        sources.append(_crm_source(
            index, source_type="crm_message", record_id=int(message.id),
            filename=(f"Message #{message.id} · conversation #{conversation.id}" if english
                      else f"Tin nhắn #{message.id} · hội thoại #{conversation.id}"),
            content=content, customer_id=customer_id, updated_at=timestamp,
            extra={"conversation_id": int(conversation.id), "assigned_user_id": conversation.assigned_user_id},
        ))
        sender = message.sender_type or ("staff" if english else "nhân viên")
        lines.append(
            f"- {timestamp.isoformat() if timestamp else 'unknown'} · {sender}: {message.content[:300]} "
            f"{_crm_citation(index, english)}"
        )
    answer = (
        f"Recent verified messages with {customer_name}:\n" if english
        else f"Lịch sử trao đổi gần đây với {customer_name}:\n"
    ) + "\n".join(lines)
    return ChatResponse(
        answer=answer, sources=sources, chunks_found=len(sources), action=action,
        data_sources=[{"type": "crm_message", "customer_id": customer_id,
                       "record_ids": [int(message.id) for message, _conversation in messages],
                       "period": period_name, "access_scope": "tenant"}],
    )


def answer_crm_query(db, business_id: int, request, selected_customer_id: int | None, *, user, permission_db, user_db, english: bool):
    action = classify_crm_query(request.query)
    if action is None:
        return None
    if action == "lookup_crm_pipeline":
        return _crm_pipeline_reply(
            db, business_id, request, user=user, permission_db=permission_db,
            user_db=user_db, english=english,
        )
    return _crm_customer_reply(
        db, business_id, request, selected_customer_id,
        user=user, permission_db=permission_db, english=english, action=action,
    )


def answer_from_crm(db, business_id, request, *, user=None, permission_db=None, user_db=None):
    english = detect_reply_language(request.query, request.conversation_history) == "en"
    crm_action = classify_crm_query(request.query)
    if crm_action == "lookup_crm_pipeline":
        return answer_crm_query(
            db, business_id, request, None,
            user=user, permission_db=permission_db, user_db=user_db or permission_db,
            english=english,
        )
    if crm_action and not _has_crm_permission(permission_db, user, business_id, "customers"):
        return _crm_no_context(
            crm_action, english=english,
            message="You do not have access to CRM customer records." if english
            else "Tài khoản này không có quyền xem hồ sơ khách hàng CRM.",
        )
    customer_id = request.customer_id
    if request.conversation_id is not None:
        conversation = db.query(Conversation).filter(
            Conversation.id == request.conversation_id, Conversation.business_id == business_id,
        ).first()
        if conversation is None or (customer_id is not None and customer_id != conversation.customer_id):
            raise HTTPException(404, "Không tìm thấy hội thoại trong shop này.")
        customer_id = conversation.customer_id
    if customer_id is not None and not db.query(Customer.id).filter(
        Customer.id == customer_id, Customer.business_id == business_id, Customer.status != "merged",
    ).first():
        raise HTTPException(404, "Không tìm thấy khách hàng trong shop này.")
    privacy_reply = customer_memory_opt_out_reply(db, business_id, customer_id, request.query)
    if privacy_reply is not None:
        return ChatResponse(answer=privacy_reply, sources=[], chunks_found=0, action="privacy_opt_out",
                            answer_status="answered" if customer_id is not None else "no_context",
                            handoff_required=customer_id is None,
                            data_sources=[{"type": "crm_privacy", "opt_out": True}] if customer_id is not None else [])
    crm_answer = answer_crm_query(
        db, business_id, request, customer_id,
        user=user, permission_db=permission_db, user_db=user_db or permission_db,
        english=english,
    )
    if crm_answer is not None:
        return crm_answer

    lookup_query = _contextual_retrieval_query(
        db, business_id, request.query, request.conversation_id or 0, request.conversation_history,
    )
    action = classify_intent(lookup_query)
    if action in {"handoff", "clarify_product"}:
        answer = (
            "A shop staff member needs to help with this request." if english else
            "Yêu cầu này cần nhân viên của shop hỗ trợ."
        ) if action == "handoff" else (
            "Which product do you mean? Please send its name or SKU." if english else
            "Bạn muốn hỏi sản phẩm nào? Gửi mình tên hoặc mã sản phẩm nhé."
        )
        return ChatResponse(answer=answer, sources=[], chunks_found=0, action=action,
                            answer_status="handoff_required" if action == "handoff" else "no_context",
                            handoff_required=action == "handoff")
    if action == "lookup_order":
        if customer_id is None:
            return ChatResponse(answer="Select the customer or conversation to look up their order." if english else
                "Bạn chọn khách hàng hoặc hội thoại để tra cứu đúng đơn nhé.", sources=[], chunks_found=0,
                answer_status="no_context", handoff_required=True, action=action)
        orders = db.query(Order).filter(Order.business_id == business_id, Order.customer_id == customer_id)
        code = extract_order_number(request.query)
        if code:
            orders = orders.filter(Order.order_number == code)
        rows = orders.order_by(Order.created_at.desc(), Order.id.desc()).limit(2).all()
        if len(rows) != 1:
            return ChatResponse(answer="Please provide the order number so staff can check it." if english else
                "Bạn gửi mã đơn để nhân viên tra cứu chính xác nhé.", sources=[], chunks_found=0,
                answer_status="no_context", handoff_required=True, action=action)
        order = rows[0]
        text = f"Order {order.order_number}: {order.status}." if english else f"Đơn {order.order_number}: {ORDER_STATUS_LABELS.get(order.status, order.status)}."
        return ChatResponse(answer=text, sources=[], chunks_found=0, action=action,
            data_sources=[{"type": "crm_order", "order_id": order.id, "status": order.status}])
    if _is_monthly_revenue_question(request.query):
        return _monthly_revenue_reply(db, business_id, english=english)
    if _is_monthly_bestseller_question(request.query):
        return _monthly_bestseller_reply(db, business_id, english=english)
    has_catalog = db.query(Product.id).filter(Product.business_id == business_id, Product.status == "active").first()
    if not has_catalog:
        return None
    if action == "lookup_product_catalog":
        return ChatResponse(answer=build_product_catalog_reply(db, business_id, language="en" if english else "vi"),
                            sources=[], chunks_found=0, action=action, data_sources=[{"type": "crm_catalog"}])
    if action != "lookup_product":
        return None
    codes = identifiers(lookup_query)
    if codes:
        matches = db.query(Product).filter(Product.business_id == business_id, Product.status == "active",
                                           func.lower(Product.sku).in_(codes)).limit(2).all()
        product = matches[0] if len(matches) == 1 else None
    else:
        product, _ = _find_exact_product(db, business_id, lookup_query, conversation_id=request.conversation_id or 0)
    if product is None:
        return ChatResponse(answer="I could not find an exact match. Please send the product name or SKU." if english else
            "Chưa tìm thấy sản phẩm khớp chính xác. Bạn gửi tên hoặc mã sản phẩm nhé.",
            sources=[], chunks_found=0, answer_status="no_context", handoff_required=True, action=action)
    folded = _fold_text(request.query)
    # Attributes beyond a general description still need approved knowledge.
    generic_detail = _is_generic_product_detail_question(request.query)
    if _is_product_attribute_question(request.query) and not generic_detail:
        return None
    if not (generic_detail or _is_price_question(folded) or _is_product_fact_question(request.query)
            or is_stock_query_request(request.query)
            or any(term in folded for term in ("ton kho", "con hang", "stock", "available"))):
        return None
    text = (_format_product_detail_reply(product, language="en" if english else "vi")
            if generic_detail else
            _format_product_fact_reply(product, folded, language="en" if english else "vi"))
    return ChatResponse(answer=text, sources=[], chunks_found=0, action=action, data_sources=[{
        "type": "crm_product", "product_id": product.id, "sku": product.sku, "price": float(product.price),
        "available": max(0, product.stock_quantity - product.reserved_quantity),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }])

