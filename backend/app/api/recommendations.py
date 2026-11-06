"""Tenant-scoped product recommendation serving and feedback endpoints."""

from types import SimpleNamespace
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_access, require_write_access
from app.tenancy.crm_session import get_tenant_db
from app.models.recommendation import RecommendationCustomerProfile, RecommendationRequest, RecommendationTrainingRun
from app.models.sales import Product
from app.database.tenant_session import tenant_session
from app.tenancy.schema import schema_name_for
from app.schemas.recommendation import (
    RecommendationFeedbackCreate,
    RecommendationFeedbackOut,
    RecommendationInteractionCreate,
    RecommendationInteractionOut,
    RecommendationInteractionSummaryOut,
    RecommendationRequestCreate,
    RecommendationResponse,
    RecommendationTrainingScheduleOut,
    RecommendationDemoPreviewRequest,
)
from app.services.job_service import enqueue_job
from app.services.recommendation_service import (
    RecommendationServiceError,
    SEGMENT_ALGORITHM,
    SEGMENT_MODEL_VERSION,
    record_feedback,
    safe_http_url,
    serve_recommendations,
    verify_recommendation_click_signature,
    _filter_query_candidates,
)
from app.services.recommendation_artifacts import RecommendationArtifactError, recommendation_artifact_status, registry as artifact_registry
from app.services.recommendation_interaction_service import (
    RecommendationInteractionError,
    record_interaction,
    summarize_interactions,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.tenancy.workspace_modules import require_module_enabled


router = APIRouter(prefix="/recommendations")

_LINK_PREVIEW_USER_AGENT_MARKERS = (
    "facebookexternalhit", "meta-externalagent", "twitterbot", "linkedinbot",
    "slackbot", "discordbot", "telegrambot", "whatsapp", "pinterestbot",
    "googlebot", "bingbot", "crawler", "spider", "linkpreview",
)


def _is_user_activated_product_navigation(http_request: Request) -> bool:
    """Exclude known unfurl/prefetch traffic without dropping older browsers."""
    purpose = " ".join((
        http_request.headers.get("purpose", ""),
        http_request.headers.get("sec-purpose", ""),
    )).casefold()
    if any(marker in purpose for marker in ("prefetch", "prerender", "preview")):
        return False

    user_agent = http_request.headers.get("user-agent", "").casefold()
    if any(marker in user_agent for marker in _LINK_PREVIEW_USER_AGENT_MARKERS):
        return False

    # Safari and some embedded browsers omit Fetch Metadata, so accept them
    # unless they explicitly report that navigation has no user activation.
    return http_request.headers.get("sec-fetch-user") in (None, "?1")


def _raise_service_error(exc: RecommendationServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _raise_interaction_error(exc: RecommendationInteractionError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/click/{business_id}/{request_id}/{product_id}", include_in_schema=False)
def track_recommendation_click(
    http_request: Request,
    business_id: int,
    request_id: str,
    product_id: int,
    expires: int = Query(...),
    signature: str = Query(...),
):
    """Record a signed user click, then redirect to the product URL."""
    if not verify_recommendation_click_signature(
        business_id=business_id,
        request_id=request_id,
        product_id=product_id,
        expires=expires,
        signature=signature,
    ):
        raise HTTPException(status_code=404, detail="Liên kết sản phẩm không hợp lệ hoặc đã hết hạn.")

    with tenant_session(schema_name_for(business_id)) as db:
        from app.services.capability_registry import resolve_capability_request
        from app.tenancy.workspace_modules import get_workspace_config

        permission = resolve_capability_request(
            get_workspace_config(db, business_id), tools=("recommendations",),
        )
        if not permission.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "workspace_capability_disabled",
                    "module": "recommendations",
                    "required_capabilities": list(permission.required_capabilities),
                    "message": "Gợi ý sản phẩm đang tắt trong Cài đặt của shop.",
                },
            )
        request = db.query(RecommendationRequest).filter(
            RecommendationRequest.business_id == business_id,
            RecommendationRequest.request_id == request_id,
        ).first()
        served_ids = {
            int(item["product_id"])
            for item in (request.served_items or [])
            if isinstance(item, dict) and str(item.get("product_id", "")).isdigit()
        } if request is not None else set()
        product = db.query(Product).filter(
            Product.business_id == business_id,
            Product.id == product_id,
        ).first() if product_id in served_ids else None
        target_url = safe_http_url(product.product_url if product else None)
        if target_url is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy liên kết sản phẩm.")
        # Link-preview bots and speculative fetches can follow signed URLs.
        if _is_user_activated_product_navigation(http_request):
            try:
                record_feedback(
                    db,
                    business_id=business_id,
                    request_id=request_id,
                    product_id=product_id,
                    event_type="click",
                    idempotency_key=f"tracked-click:{request_id}:{product_id}",
                    metadata={
                        "source": "signed_product_link",
                        "user_activation_header": http_request.headers.get("sec-fetch-user"),
                    },
                    verified_click=True,
                )
            except Exception:
                # Telemetry failure must not break a valid customer-facing link.
                db.rollback()
    return RedirectResponse(target_url, status_code=307)


@router.get("/artifacts", dependencies=[Depends(require_admin_access)])
def artifacts_status():
    """Expose artifact discovery without loading untrusted checkpoints."""
    return recommendation_artifact_status()


@router.post("/demo/preview", dependencies=[Depends(require_admin_access)])
def preview_data_rag(payload: RecommendationDemoPreviewRequest):
    """Read-only preview of the supplied synthetic catalog and trusted checkpoints."""
    try:
        catalog = artifact_registry.data_rag_asset("catalog.json")
        report = artifact_registry.data_rag_asset("training_report.json")
        products = [SimpleNamespace(
            id=int(row["product_id"]), sku=row["sku"], name=row["name"],
            price=float(row["price"]), stock_quantity=int(row["stock"]), reserved_quantity=0,
            description="", metadata_={"color": row["color"], "category": row["category"]},
        ) for row in catalog if int(row["stock"]) > 0]
        eligible = _filter_query_candidates(products, payload.query)
        shortlist = eligible[:3]
        scores = artifact_registry.data_rag_scores(0, shortlist, payload.query, preview=True)
        items = [{
            "product_id": p.id, "sku": p.sku, "name": p.name, "price": p.price,
            "available": p.stock_quantity, "baseline_position": i,
            "model_score": round(scores[p.id], 6),
        } for i, p in enumerate(shortlist, 1)]
        features = {"recency_days": float(payload.recency_days), "frequency": float(payload.frequency),
                    "monetary": payload.monetary if payload.frequency else 0.0}
        segment = artifact_registry.data_rag_segment(0, features, preview=True)
        return {
            "model_version": "data_rag_demo_v1", "data_scope": "synthetic",
            "eligible_candidates": len(eligible), "shortlist_size": len(items),
            "baseline": items, "ranked": sorted(items, key=lambda item: (-item["model_score"], item["baseline_position"])),
            "rfm": {"features": features, "cluster_id": segment,
                    "segment": "new_customer" if segment is None else f"data_rag_cluster_{segment}",
                    "training_cluster_summary": report["rfm"]["clusters"].get(str(segment)) if segment is not None else None},
            "held_out_metrics": report["product_ranker"]["metrics"]["test"],
        }
    except (OSError, ValueError, KeyError, TypeError, RecommendationArtifactError):
        raise HTTPException(503, "Chưa có bộ mô hình thử nghiệm hợp lệ. Hãy cài bộ kết quả huấn luyện.")



@router.post(
    "/interactions",
    response_model=RecommendationInteractionOut,
    status_code=201,
    dependencies=[
        Depends(require_write_access),
        Depends(require_module_enabled("recommendations")),
    ],
)
def track_interaction(
    payload: RecommendationInteractionCreate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Ingest low-risk browse/search/ask signals; exposures and outcomes are server-owned."""
    try:
        row, request_id = record_interaction(
            db,
            business_id=tenant.business_id,
            customer_id=payload.customer_id,
            product_id=payload.product_id,
            object_type=payload.object_type,
            recommendation_object_id=payload.recommendation_object_id,
            request_id=payload.request_id,
            event_type=payload.event_type,
            source=payload.source,
            query=payload.query,
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
            occurred_at=payload.occurred_at,
        )
        db.commit()
        db.refresh(row)
    except RecommendationInteractionError as exc:
        db.rollback()
        _raise_interaction_error(exc)
    return RecommendationInteractionOut(
        id=row.id,
        customer_id=row.customer_id,
        product_id=row.product_id,
        object_type=row.object_type,
        recommendation_object_id=row.recommendation_object_id,
        model_version=row.model_version,
        request_id=request_id,
        event_type=row.event_type,
        source=row.source,
        occurred_at=row.occurred_at,
    )


@router.get(
    "/interactions/summary",
    response_model=RecommendationInteractionSummaryOut,
    dependencies=[Depends(require_module_enabled("recommendations"))],
)
def interaction_summary(
    customer_id: int | None = Query(default=None, ge=1),
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    try:
        return summarize_interactions(
            db,
            business_id=tenant.business_id,
            customer_id=customer_id,
            days=days,
        )
    except RecommendationInteractionError as exc:
        _raise_interaction_error(exc)


@router.post(
    "", response_model=RecommendationResponse, status_code=201,
    dependencies=[Depends(require_module_enabled("recommendations"))],
)
def recommend(
    payload: RecommendationRequestCreate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    try:
        row = serve_recommendations(db, business_id=tenant.business_id, payload=payload)
    except RecommendationServiceError as exc:
        _raise_service_error(exc)
    profile = None
    if row.customer_id is not None:
        profile = db.query(RecommendationCustomerProfile).filter(
            RecommendationCustomerProfile.business_id == tenant.business_id,
            RecommendationCustomerProfile.customer_id == row.customer_id,
        ).first()
    context = row.context if isinstance(row.context, dict) else {}
    return RecommendationResponse(
        request_id=row.request_id,
        customer_id=row.customer_id,
        segment=profile.segment_label if profile else None,
        strategy=row.strategy,
        model_version=row.model_version,
        candidate_count=int((row.context or {}).get("eligible_candidate_count", len(row.served_items or []))),
        personalization_applied=bool(context.get("personalization_applied")),
        personalization_signals=context.get("personalization_signals") or [],
        available_personalization_signals=context.get("available_personalization_signals") or [],
        items=row.served_items or [],
        created_at=row.created_at,
    )


@router.post("/{request_id}/feedback", response_model=RecommendationFeedbackOut, status_code=201, dependencies=[Depends(require_write_access)])
def feedback(
    request_id: str,
    payload: RecommendationFeedbackCreate,
):
    """Retain a clear migration response; clicks are accepted only on signed links."""
    raise HTTPException(
        status_code=410,
        detail="Endpoint feedback trực tiếp đã ngừng nhận click. Hãy dùng liên kết sản phẩm có chữ ký.",
    )


@router.post(
    "/training/segments", response_model=RecommendationTrainingScheduleOut,
    status_code=202,
    dependencies=[
        Depends(require_write_access),
        Depends(require_module_enabled("recommendations")),
    ],
)
def schedule_segment_training(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    run = RecommendationTrainingRun(
        business_id=tenant.business_id,
        algorithm=SEGMENT_ALGORITHM,
        status="queued",
        metrics={},
        artifact={"model_version": SEGMENT_MODEL_VERSION},
    )
    db.add(run)
    db.flush()
    job = enqueue_job(
        db,
        business_id=tenant.business_id,
        kind="recommendations.train_segments",
        payload={"training_run_id": run.id},
        idempotency_key=f"recommendations:segments:{run.id}",
    )
    db.commit()
    return RecommendationTrainingScheduleOut(training_run_id=run.id, job_id=job.id, status=run.status)
