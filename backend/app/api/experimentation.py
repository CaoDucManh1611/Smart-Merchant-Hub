"""Explainable rule suggestions and measurable AI experiments."""

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_user
from app.db.dependencies import get_db
from app.models.business import User
from app.models.customer import Customer
from app.models.experimentation import (
    BanditDecision,
    Experiment,
    ExperimentAssignment,
    ExperimentOutcome,
    FeatureSnapshot,
    RuleSuggestion,
)
from app.models.workflow import Workflow
from app.schemas.experimentation import (
    AssignmentOut,
    AssignmentRequest,
    BanditDecisionOut,
    BanditDecisionRequest,
    ExperimentCreate,
    ExperimentOut,
    FeatureSnapshotCreate,
    FeatureSnapshotOut,
    OutcomeOut,
    OutcomeRequest,
    RuleSuggestionCreate,
    RuleSuggestionOut,
    RuleSuggestionReview,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.auth.dependencies import require_write_access


router = APIRouter(prefix="/experiments")


def _experiment(db: Session, experiment_id: int, tenant: TenantContext) -> Experiment:
    row = db.query(Experiment).filter(Experiment.id == experiment_id, Experiment.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment không tồn tại.")
    return row


@router.post("/rule-suggestions", response_model=RuleSuggestionOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_rule_suggestion(payload: RuleSuggestionCreate, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    if payload.workflow_id is not None and db.query(Workflow.id).filter(Workflow.id == payload.workflow_id, Workflow.business_id == tenant.business_id).first() is None:
        raise HTTPException(status_code=404, detail="Workflow không thuộc business này.")
    row = RuleSuggestion(
        business_id=tenant.business_id,
        workflow_id=payload.workflow_id,
        title=payload.title.strip(),
        rationale=payload.rationale.strip(),
        proposed_action=payload.proposed_action,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/rule-suggestions", response_model=list[RuleSuggestionOut])
def list_rule_suggestions(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    return db.query(RuleSuggestion).filter(RuleSuggestion.business_id == tenant.business_id).order_by(RuleSuggestion.created_at.desc(), RuleSuggestion.id.desc()).limit(200).all()


@router.post("/rule-suggestions/{suggestion_id}/review", response_model=RuleSuggestionOut, dependencies=[Depends(require_write_access)])
def review_rule_suggestion(
    suggestion_id: int,
    payload: RuleSuggestionReview,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    user: User | None = Depends(get_optional_user),
):
    row = db.query(RuleSuggestion).filter(RuleSuggestion.id == suggestion_id, RuleSuggestion.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Rule suggestion không tồn tại.")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="Rule suggestion đã được duyệt.")
    row.status = payload.status
    row.reviewed_by = user.id if user else None
    row.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(row)
    return row


@router.post("/features/snapshots", response_model=FeatureSnapshotOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_feature_snapshot(payload: FeatureSnapshotCreate, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    if payload.customer_id is not None and db.query(Customer.id).filter(Customer.id == payload.customer_id, Customer.business_id == tenant.business_id).first() is None:
        raise HTTPException(status_code=404, detail="Customer không thuộc business này.")
    row = FeatureSnapshot(business_id=tenant.business_id, customer_id=payload.customer_id, feature_version=payload.feature_version.strip(), features=payload.features, label=payload.label)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/features/snapshots", response_model=list[FeatureSnapshotOut])
def list_feature_snapshots(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    return db.query(FeatureSnapshot).filter(FeatureSnapshot.business_id == tenant.business_id).order_by(FeatureSnapshot.captured_at.desc(), FeatureSnapshot.id.desc()).limit(200).all()


@router.post("", response_model=ExperimentOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_experiment(payload: ExperimentCreate, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    variants = list(dict.fromkeys(item.strip() for item in payload.variants if item.strip()))
    if len(variants) < 2:
        raise HTTPException(status_code=422, detail="Experiment cần ít nhất hai variant khác nhau.")
    row = Experiment(business_id=tenant.business_id, name=payload.name.strip(), variants=variants, status=payload.status)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[ExperimentOut])
def list_experiments(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    return db.query(Experiment).filter(Experiment.business_id == tenant.business_id).order_by(Experiment.id.desc()).all()


@router.post("/{experiment_id}/assign", response_model=AssignmentOut, dependencies=[Depends(require_write_access)])
def assign_experiment(experiment_id: int, payload: AssignmentRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    if experiment.status != "running":
        raise HTTPException(status_code=409, detail="Experiment chưa ở trạng thái running.")
    existing = db.query(ExperimentAssignment).filter(ExperimentAssignment.experiment_id == experiment.id, ExperimentAssignment.subject_key == payload.subject_key).first()
    if existing is not None:
        return existing
    variant = payload.variant or experiment.variants[int(hashlib.sha256(payload.subject_key.encode()).hexdigest(), 16) % len(experiment.variants)]
    if variant not in experiment.variants:
        raise HTTPException(status_code=422, detail="Variant không thuộc experiment.")
    row = ExperimentAssignment(business_id=tenant.business_id, experiment_id=experiment.id, subject_key=payload.subject_key, variant=variant)
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.query(ExperimentAssignment).filter(ExperimentAssignment.experiment_id == experiment.id, ExperimentAssignment.subject_key == payload.subject_key).first()
        if existing is not None:
            return existing
        raise HTTPException(status_code=409, detail="Subject đã được phân nhánh.") from exc
    db.refresh(row)
    return row


@router.post("/{experiment_id}/assignments/{assignment_id}/outcome", response_model=OutcomeOut, status_code=201, dependencies=[Depends(require_write_access)])
def record_outcome(experiment_id: int, assignment_id: int, payload: OutcomeRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    assignment = db.query(ExperimentAssignment).filter(ExperimentAssignment.id == assignment_id, ExperimentAssignment.experiment_id == experiment.id, ExperimentAssignment.business_id == tenant.business_id).first()
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment không tồn tại.")
    row = ExperimentOutcome(business_id=tenant.business_id, assignment_id=assignment.id, metric=payload.metric.strip(), value=payload.value)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/{experiment_id}/bandit/decision", response_model=BanditDecisionOut, status_code=201, dependencies=[Depends(require_write_access)])
def bandit_decision(experiment_id: int, payload: BanditDecisionRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    if experiment.status != "running":
        raise HTTPException(status_code=409, detail="Experiment chưa ở trạng thái running.")
    if payload.arm not in experiment.variants:
        raise HTTPException(status_code=422, detail="Arm không thuộc experiment.")
    row = BanditDecision(business_id=tenant.business_id, experiment_id=experiment.id, subject_key=payload.subject_key, arm=payload.arm, context=payload.context)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/{experiment_id}/bandit/{decision_id}/reward", response_model=BanditDecisionOut, dependencies=[Depends(require_write_access)])
def bandit_reward(experiment_id: int, decision_id: int, payload: OutcomeRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    row = db.query(BanditDecision).filter(BanditDecision.id == decision_id, BanditDecision.experiment_id == experiment.id, BanditDecision.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Bandit decision không tồn tại.")
    row.reward = payload.value
    db.commit()
    db.refresh(row)
    return row
