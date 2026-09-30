"""Tenant-scoped product recommendation serving and feedback endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_access, require_write_access
from app.tenancy.crm_session import get_tenant_db
from app.models.recommendation import RecommendationCustomerProfile, RecommendationTrainingRun
from app.schemas.recommendation import (
    RecommendationFeedbackCreate,
    RecommendationFeedbackOut,
    RecommendationInteractionCreate,
    RecommendationInteractionOut,
    RecommendationInteractionSummaryOut,
    RecommendationRequestCreate,
    RecommendationResponse,
    RecommendationTrainingScheduleOut,
)
from app.services.job_service import enqueue_job
from app.services.recommendation_service import (
    RecommendationServiceError,
    record_feedback,
    serve_recommendations,
)
from app.services.recommendation_artifacts import recommendation_artifact_status
from app.services.recommendation_interaction_service import (
    RecommendationInteractionError,
    record_interaction,
    summarize_interactions,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter(prefix="/recommendations")


def _raise_service_error(exc: RecommendationServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def _raise_interaction_error(exc: RecommendationInteractionError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/artifacts", dependencies=[Depends(require_admin_access)])
def artifacts_status():
    """Expose artifact discovery without loading untrusted checkpoints."""
    return recommendation_artifact_status()


@router.post(
    "/interactions",
    response_model=RecommendationInteractionOut,
    status_code=201,
    dependencies=[Depends(require_write_access)],
)
def track_interaction(
    payload: RecommendationInteractionCreate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Ingest a tenant-scoped browse, chat, cart, or conversion signal."""
    try:
        row, request_id = record_interaction(
            db,
            business_id=tenant.business_id,
            customer_id=payload.customer_id,
            product_id=payload.product_id,
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
        request_id=request_id,
        event_type=row.event_type,
        source=row.source,
        occurred_at=row.occurred_at,
    )


@router.get("/interactions/summary", response_model=RecommendationInteractionSummaryOut)
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


@router.post("", response_model=RecommendationResponse, status_code=201)
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
    return RecommendationResponse(
        request_id=row.request_id,
        customer_id=row.customer_id,
        segment=profile.segment_label if profile else None,
        strategy=row.strategy,
        model_version=row.model_version,
        candidate_count=int((row.context or {}).get("eligible_candidate_count", len(row.served_items or []))),
        items=row.served_items or [],
        created_at=row.created_at,
    )


@router.post("/{request_id}/feedback", response_model=RecommendationFeedbackOut, status_code=201, dependencies=[Depends(require_write_access)])
def feedback(
    request_id: str,
    payload: RecommendationFeedbackCreate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    try:
        row = record_feedback(
            db,
            business_id=tenant.business_id,
            request_id=request_id,
            product_id=payload.product_id,
            event_type=payload.event_type,
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
        )
    except RecommendationServiceError as exc:
        _raise_service_error(exc)
    return RecommendationFeedbackOut(
        id=row.id,
        request_id=request_id,
        product_id=row.product_id,
        event_type=row.event_type,
        reward=float(row.reward),
        occurred_at=row.occurred_at,
    )


@router.post("/training/segments", response_model=RecommendationTrainingScheduleOut, status_code=202, dependencies=[Depends(require_write_access)])
def schedule_segment_training(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    run = RecommendationTrainingRun(
        business_id=tenant.business_id,
        algorithm="deterministic_rfm_kmeans",
        status="queued",
        metrics={},
        artifact={"model_version": "rfm_kmeans_v1"},
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
