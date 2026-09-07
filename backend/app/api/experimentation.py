"""Explainable rule suggestions and measurable AI experiments."""

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_user
from app.db.dependencies import get_db
from app.models.business import User
from app.models.customer import Customer
from app.models.experimentation import (
    BanditDecision, BanditPolicy, BanditArmStat,
    Experiment,
    ExperimentAssignment,
    ExperimentExposure,
    ExperimentOutcome,
    ExperimentMetricAggregate,
    FeatureSnapshot,
    ModelVersion, ModelTrainingRun, ModelEvaluationMetric,
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
    ExposureOut, ExposureRequest, ExperimentArmReport, ExperimentReportOut,
    RuleSuggestionCreate,
    RuleSuggestionGenerate,
    RuleSuggestionConvertOut,
    RuleSuggestionOut,
    RuleSuggestionReview,
    ModelVersionCreate, ModelVersionOut, ModelTrainRequest, ModelTrainingRunOut,
    ModelInferenceRequest, ModelInferenceOut,
    BanditPolicyCreate, BanditPolicyOut, BanditSelectRequest,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.auth.dependencies import require_write_access
from app.services.audit_service import record_audit
from app.services.rule_recommendation import suggest_tag_rule


router = APIRouter(prefix="/experiments")


def _experiment(db: Session, experiment_id: int, tenant: TenantContext) -> Experiment:
    row = db.query(Experiment).filter(Experiment.id == experiment_id, Experiment.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment không tồn tại.")
    return row


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _context_hash(context: dict) -> str:
    encoded = json.dumps(context or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_number(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _ensure_exposure(db: Session, *, tenant: TenantContext, experiment: Experiment, assignment: ExperimentAssignment, idempotency_key: str | None = None) -> ExperimentExposure:
    key = idempotency_key or f"assignment:{assignment.id}"
    existing = db.query(ExperimentExposure).filter(
        ExperimentExposure.experiment_id == experiment.id,
        ExperimentExposure.idempotency_key == key,
    ).first()
    if existing:
        return existing
    row = ExperimentExposure(
        business_id=tenant.business_id,
        experiment_id=experiment.id,
        assignment_id=assignment.id,
        subject_key=assignment.subject_key,
        variant=assignment.variant,
        idempotency_key=key,
    )
    db.add(row)
    db.flush()
    aggregate = db.query(ExperimentMetricAggregate).filter(
        ExperimentMetricAggregate.experiment_id == experiment.id,
        ExperimentMetricAggregate.metric == "conversion",
        ExperimentMetricAggregate.variant == assignment.variant,
    ).first()
    if aggregate is None:
        aggregate = ExperimentMetricAggregate(
            business_id=tenant.business_id, experiment_id=experiment.id,
            metric="conversion", variant=assignment.variant, exposure_count=0,
            outcome_count=0, value_sum=Decimal("0"),
        )
        db.add(aggregate)
    aggregate.exposure_count = int(aggregate.exposure_count or 0) + 1
    return row


def _maybe_stop_experiment(db: Session, experiment: Experiment) -> None:
    minimum = int(experiment.min_sample_size or experiment.stop_criteria.get("min_sample_size", 0) or 0)
    if minimum <= 0:
        return
    counts = {
        variant: db.query(ExperimentExposure).filter(
            ExperimentExposure.experiment_id == experiment.id,
            ExperimentExposure.variant == variant,
        ).count()
        for variant in experiment.variants
    }
    if not all(value >= minimum for value in counts.values()):
        return
    criteria = experiment.stop_criteria or {}
    target = criteria.get("target_conversion_rate")
    if target is not None:
        aggregates = db.query(ExperimentMetricAggregate).filter(ExperimentMetricAggregate.experiment_id == experiment.id, ExperimentMetricAggregate.metric == "conversion").all()
        if not aggregates or not any((float(item.outcome_count or 0) / max(1, int(item.exposure_count or 0))) >= float(target) for item in aggregates):
            return
    if experiment.status == "running":
        experiment.status = "completed"
        experiment.stopped_at = _now()


def _experiment_report(db: Session, experiment: Experiment) -> dict:
    metrics = [row[0] for row in db.query(ExperimentOutcome.metric).join(ExperimentAssignment, ExperimentOutcome.assignment_id == ExperimentAssignment.id).filter(ExperimentAssignment.experiment_id == experiment.id).distinct().all()]
    metric = metrics[0] if metrics else "conversion"
    arms = []
    for variant in experiment.variants:
        exposures = db.query(ExperimentExposure).filter(ExperimentExposure.experiment_id == experiment.id, ExperimentExposure.variant == variant).count()
        outcomes = db.query(ExperimentOutcome).join(ExperimentAssignment, ExperimentOutcome.assignment_id == ExperimentAssignment.id).filter(ExperimentAssignment.experiment_id == experiment.id, ExperimentAssignment.variant == variant, ExperimentOutcome.metric == metric).all()
        values = [float(row.value) for row in outcomes]
        successes = sum(1 for value in values if value > 0)
        rate = successes / exposures if exposures else 0.0
        if exposures:
            z = 1.96
            denom = 1 + z * z / exposures
            centre = (rate + z * z / (2 * exposures)) / denom
            margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * exposures)) / exposures) / denom
            interval = [max(0.0, centre - margin), min(1.0, centre + margin)]
        else:
            interval = [0.0, 0.0]
        arms.append({"variant": variant, "exposures": exposures, "outcomes": len(outcomes), "value_sum": sum(values), "conversion_rate": rate, "confidence_interval": interval})
    return {
        "experiment_id": experiment.id, "status": experiment.status,
        "stopped": experiment.status == "completed" and experiment.stopped_at is not None,
        "min_sample_size": int(experiment.min_sample_size or 0), "arms": arms, "metrics": metrics or ["conversion"],
    }


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
        evidence=payload.evidence,
        evidence_refs=payload.evidence_refs,
        source_event_ids=payload.source_event_ids,
        proposed_workflow_version=payload.proposed_workflow_version,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/rule-suggestions/generate", response_model=RuleSuggestionOut, status_code=201, dependencies=[Depends(require_write_access)])
def generate_rule_suggestion(payload: RuleSuggestionGenerate, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    suggestion = suggest_tag_rule(channel=payload.channel.strip(), sample_size=payload.sample_size, tag=payload.tag.strip())
    row = RuleSuggestion(
        business_id=tenant.business_id,
        title=suggestion["title"],
        rationale=suggestion["rationale"],
        proposed_action=suggestion["proposed_action"],
        evidence=payload.evidence or {"sample_size": payload.sample_size, "channel": payload.channel.strip()},
        evidence_refs=payload.evidence_refs or payload.source_event_ids,
        source_event_ids=payload.source_event_ids,
        proposed_workflow_version="draft-1",
        status="pending",
    )
    db.add(row)
    record_audit(db, business_id=tenant.business_id, action="create", resource_type="rule_suggestion", metadata={"source_event_ids": payload.source_event_ids, "channel": payload.channel})
    db.commit(); db.refresh(row)
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
    row.reviewer_note = payload.reviewer_note
    row.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record_audit(db, business_id=tenant.business_id, user_id=user.id if user else None, action=f"rule_suggestion_{payload.status}", resource_type="rule_suggestion", resource_id=row.id, metadata={"reviewer_note": payload.reviewer_note, "source_event_ids": row.source_event_ids})
    db.commit()
    db.refresh(row)
    return row


@router.post("/rule-suggestions/{suggestion_id}/convert", response_model=RuleSuggestionConvertOut, dependencies=[Depends(require_write_access)])
def convert_rule_suggestion(suggestion_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context), user: User | None = Depends(get_optional_user)):
    row = db.query(RuleSuggestion).filter(RuleSuggestion.id == suggestion_id, RuleSuggestion.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Rule suggestion không tồn tại.")
    if row.status not in {"accepted", "converted"}:
        raise HTTPException(status_code=409, detail="Chỉ được chuyển suggestion đã accepted thành workflow draft.")
    if row.converted_workflow_id:
        workflow = db.query(Workflow).filter(Workflow.id == row.converted_workflow_id, Workflow.business_id == tenant.business_id).first()
        if workflow:
            return {"suggestion": row, "workflow_id": workflow.id, "workflow_status": "draft"}
    action = row.proposed_action or {}
    workflow = Workflow(
        business_id=tenant.business_id,
        name=row.title[:160],
        event_type=str(action.get("event_type") or "message.created"),
        conditions=action.get("conditions") or {},
        actions=[action],
        enabled=False,
    )
    db.add(workflow); db.flush()
    row.converted_workflow_id = workflow.id
    row.converted_at = _now()
    row.status = "converted"
    record_audit(db, business_id=tenant.business_id, user_id=user.id if user else None, action="rule_suggestion_convert", resource_type="rule_suggestion", resource_id=row.id, metadata={"workflow_id": workflow.id})
    db.commit(); db.refresh(row)
    return {"suggestion": row, "workflow_id": workflow.id, "workflow_status": "draft"}


@router.post("/rule-suggestions/{suggestion_id}/rollback", response_model=RuleSuggestionOut, dependencies=[Depends(require_write_access)])
def rollback_rule_suggestion(suggestion_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context), user: User | None = Depends(get_optional_user)):
    row = db.query(RuleSuggestion).filter(RuleSuggestion.id == suggestion_id, RuleSuggestion.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Rule suggestion không tồn tại.")
    if row.converted_workflow_id:
        workflow = db.query(Workflow).filter(Workflow.id == row.converted_workflow_id, Workflow.business_id == tenant.business_id).first()
        if workflow:
            workflow.enabled = False
    row.status = "rolled_back"
    row.rolled_back_at = _now()
    record_audit(db, business_id=tenant.business_id, user_id=user.id if user else None, action="rule_suggestion_rollback", resource_type="rule_suggestion", resource_id=row.id, metadata={"workflow_id": row.converted_workflow_id})
    db.commit(); db.refresh(row)
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


def _model_version_payload(row: ModelVersion) -> dict:
    return {
        "id": row.id, "business_id": row.business_id, "name": row.name,
        "version": row.version, "feature_version": row.feature_version,
        "target": row.target, "status": row.status, "artifact": row.artifact or {},
        "metadata": row.metadata_ or {}, "created_at": row.created_at, "trained_at": row.trained_at,
    }


@router.post("/models", response_model=ModelVersionOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_model_version(payload: ModelVersionCreate, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    existing = db.query(ModelVersion).filter(ModelVersion.business_id == tenant.business_id, ModelVersion.name == payload.name.strip(), ModelVersion.version == payload.version.strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Model version đã tồn tại.")
    row = ModelVersion(business_id=tenant.business_id, name=payload.name.strip(), version=payload.version.strip(), feature_version=payload.feature_version.strip(), target=payload.target.strip(), metadata_=payload.metadata, status="draft")
    db.add(row); db.commit(); db.refresh(row)
    return _model_version_payload(row)


@router.get("/models", response_model=list[ModelVersionOut])
def list_model_versions(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    return [_model_version_payload(row) for row in db.query(ModelVersion).filter(ModelVersion.business_id == tenant.business_id).order_by(ModelVersion.id.desc()).limit(200).all()]


@router.get("/models/{model_id}", response_model=ModelVersionOut)
def get_model_version(model_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    row = db.query(ModelVersion).filter(ModelVersion.id == model_id, ModelVersion.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Model version không tồn tại.")
    return _model_version_payload(row)


@router.post("/models/{model_id}/train", response_model=ModelTrainingRunOut, status_code=201, dependencies=[Depends(require_write_access)])
def train_model(model_id: int, payload: ModelTrainRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    model = db.query(ModelVersion).filter(ModelVersion.id == model_id, ModelVersion.business_id == tenant.business_id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="Model version không tồn tại.")
    query = db.query(FeatureSnapshot).filter(FeatureSnapshot.business_id == tenant.business_id, FeatureSnapshot.feature_version == model.feature_version, FeatureSnapshot.label.isnot(None))
    if payload.snapshot_ids:
        query = query.filter(FeatureSnapshot.id.in_(payload.snapshot_ids))
    snapshots = query.order_by(FeatureSnapshot.id.asc()).all()
    if len(snapshots) < 2:
        raise HTTPException(status_code=422, detail="Cần ít nhất hai feature snapshot có label để train.")
    holdout_count = max(1, int(round(len(snapshots) * payload.holdout_ratio)))
    train_rows, holdout_rows = snapshots[:-holdout_count], snapshots[-holdout_count:]
    def label_value(row):
        label = row.label or {}
        if isinstance(label, dict):
            value = label.get(model.target, label.get("value", label.get("label", 0)))
        else:
            value = label
        try: return float(value)
        except (TypeError, ValueError): return 0.0
    feature_names = sorted({key for row in train_rows for key, value in (row.features or {}).items() if isinstance(value, (int, float)) and not isinstance(value, bool)})
    means = {}
    for name in feature_names:
        vals = [float((row.features or {}).get(name, 0) or 0) for row in train_rows]
        means[name] = sum(vals) / len(vals) if vals else 0.0
    train_labels = [label_value(row) for row in train_rows]
    label_mean = sum(train_labels) / len(train_labels) if train_labels else 0.0
    artifact = {"algorithm": "deterministic_baseline", "feature_names": feature_names, "feature_means": means, "label_mean": label_mean, "target": model.target, "holdout_ratio": payload.holdout_ratio}
    predictions = [label_mean for row in holdout_rows]
    actuals = [label_value(row) for row in holdout_rows]
    mae = sum(abs(actual - prediction) for actual, prediction in zip(actuals, predictions, strict=True)) / len(actuals)
    binary = all(value in {0.0, 1.0} for value in actuals + train_labels)
    if binary:
        threshold = 0.5
        accuracy = sum((prediction >= threshold) == (actual >= threshold) for actual, prediction in zip(actuals, predictions, strict=True)) / len(actuals)
        metrics = {"mae": mae, "accuracy": accuracy, "holdout_count": len(holdout_rows)}
    else:
        metrics = {"mae": mae, "holdout_count": len(holdout_rows)}
    artifact["metrics"] = metrics
    run = ModelTrainingRun(business_id=tenant.business_id, model_version_id=model.id, status="completed", snapshot_ids=[row.id for row in snapshots], train_count=len(train_rows), holdout_count=len(holdout_rows), metrics=metrics, artifact=artifact, completed_at=_now())
    model.status = "ready"; model.artifact = artifact; model.trained_at = _now()
    db.add(run); db.flush()
    for metric, value in metrics.items():
        if isinstance(value, (int, float)):
            db.add(ModelEvaluationMetric(business_id=tenant.business_id, training_run_id=run.id, metric=metric, split="holdout", value=Decimal(str(value))))
    db.commit(); db.refresh(run)
    return run


@router.post("/models/{model_id}/infer", response_model=ModelInferenceOut)
def infer_model(model_id: int, payload: ModelInferenceRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    model = db.query(ModelVersion).filter(ModelVersion.id == model_id, ModelVersion.business_id == tenant.business_id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="Model version không tồn tại.")
    if model.status != "ready" or not model.artifact:
        raise HTTPException(status_code=409, detail="Model chưa được train.")
    artifact = model.artifact
    values = [float(payload.features.get(name, 0) or 0) for name in artifact.get("feature_names", [])]
    prediction = float(artifact.get("label_mean", 0.0))
    if values and artifact.get("feature_names"):
        # A stable baseline blends the learned prior with normalized feature signal.
        deviations = [value - float((artifact.get("feature_means") or {}).get(name, 0.0)) for name, value in zip(artifact["feature_names"], values, strict=True)]
        prediction = max(0.0, min(1.0, prediction + (sum(deviations) / max(1, len(deviations))) * 0.01))
    metrics = artifact.get("metrics") or {}
    confidence = min(1.0, max(0.0, 1.0 - float((metrics.get("mae") or 0.0))))
    return {"model_version_id": model.id, "model_version": model.version, "prediction": prediction, "confidence": confidence, "feature_snapshot_time": None, "metrics": metrics}


@router.post("", response_model=ExperimentOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_experiment(payload: ExperimentCreate, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    variants = list(dict.fromkeys(item.strip() for item in payload.variants if item.strip()))
    if len(variants) < 2:
        raise HTTPException(status_code=422, detail="Experiment cần ít nhất hai variant khác nhau.")
    row = Experiment(business_id=tenant.business_id, name=payload.name.strip(), variants=variants, status=payload.status, min_sample_size=payload.min_sample_size, stop_criteria=payload.stop_criteria)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[ExperimentOut])
def list_experiments(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    return db.query(Experiment).filter(Experiment.business_id == tenant.business_id).order_by(Experiment.id.desc()).all()


@router.post("/{experiment_id}/exposures", response_model=ExposureOut, status_code=201, dependencies=[Depends(require_write_access)])
def record_exposure(experiment_id: int, payload: ExposureRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    if experiment.status != "running":
        raise HTTPException(status_code=409, detail="Experiment chưa ở trạng thái running.")
    if payload.variant not in experiment.variants:
        raise HTTPException(status_code=422, detail="Variant không thuộc experiment.")
    key = payload.idempotency_key or f"{payload.subject_key}:{payload.variant}"
    existing = db.query(ExperimentExposure).filter(ExperimentExposure.experiment_id == experiment.id, ExperimentExposure.idempotency_key == key).first()
    if existing:
        return existing
    assignment = db.query(ExperimentAssignment).filter(ExperimentAssignment.experiment_id == experiment.id, ExperimentAssignment.subject_key == payload.subject_key).first()
    if assignment is None:
        assignment = ExperimentAssignment(business_id=tenant.business_id, experiment_id=experiment.id, subject_key=payload.subject_key, variant=payload.variant)
        db.add(assignment); db.flush()
    elif assignment.variant != payload.variant:
        raise HTTPException(status_code=409, detail="Subject đã được gán variant khác.")
    exposure = _ensure_exposure(db, tenant=tenant, experiment=experiment, assignment=assignment, idempotency_key=key)
    _maybe_stop_experiment(db, experiment)
    db.commit(); db.refresh(exposure)
    return exposure


@router.get("/{experiment_id}/report", response_model=ExperimentReportOut)
def experiment_report(experiment_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    _maybe_stop_experiment(db, experiment)
    db.commit()
    return _experiment_report(db, experiment)


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
        db.flush()
        _ensure_exposure(db, tenant=tenant, experiment=experiment, assignment=row)
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
    if payload.idempotency_key:
        existing = db.query(ExperimentOutcome).filter(ExperimentOutcome.business_id == tenant.business_id, ExperimentOutcome.idempotency_key == payload.idempotency_key).first()
        if existing:
            return existing
    row = ExperimentOutcome(business_id=tenant.business_id, assignment_id=assignment.id, metric=payload.metric.strip(), value=payload.value, idempotency_key=payload.idempotency_key)
    db.add(row)
    aggregate = db.query(ExperimentMetricAggregate).filter(ExperimentMetricAggregate.experiment_id == experiment.id, ExperimentMetricAggregate.metric == payload.metric.strip(), ExperimentMetricAggregate.variant == assignment.variant).first()
    if aggregate is None:
        aggregate = ExperimentMetricAggregate(business_id=tenant.business_id, experiment_id=experiment.id, metric=payload.metric.strip(), variant=assignment.variant, exposure_count=db.query(ExperimentExposure).filter(ExperimentExposure.experiment_id == experiment.id, ExperimentExposure.variant == assignment.variant).count(), outcome_count=0, value_sum=Decimal("0"))
        db.add(aggregate)
    aggregate.outcome_count = int(aggregate.outcome_count or 0) + 1
    aggregate.value_sum = Decimal(aggregate.value_sum or 0) + Decimal(payload.value)
    _maybe_stop_experiment(db, experiment)
    db.commit()
    db.refresh(row)
    return row


@router.post("/{experiment_id}/bandit/policies", response_model=BanditPolicyOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_bandit_policy(experiment_id: int, payload: BanditPolicyCreate, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    if db.query(BanditPolicy).filter(BanditPolicy.experiment_id == experiment.id, BanditPolicy.version == payload.version.strip()).first():
        raise HTTPException(status_code=409, detail="Policy version đã tồn tại.")
    row = BanditPolicy(business_id=tenant.business_id, experiment_id=experiment.id, version=payload.version.strip(), epsilon=payload.epsilon, config=payload.config, status=payload.status)
    db.add(row); db.commit(); db.refresh(row)
    return row


@router.get("/{experiment_id}/bandit/policies", response_model=list[BanditPolicyOut])
def list_bandit_policies(experiment_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    return db.query(BanditPolicy).filter(BanditPolicy.experiment_id == experiment.id, BanditPolicy.business_id == tenant.business_id).order_by(BanditPolicy.id.desc()).all()


def _active_bandit_policy(db: Session, experiment: Experiment, tenant: TenantContext) -> BanditPolicy:
    row = db.query(BanditPolicy).filter(BanditPolicy.experiment_id == experiment.id, BanditPolicy.business_id == tenant.business_id, BanditPolicy.status == "active").order_by(BanditPolicy.id.desc()).first()
    if row is not None:
        return row
    row = BanditPolicy(business_id=tenant.business_id, experiment_id=experiment.id, version="v1", epsilon=Decimal("0.10"), config={}, status="active")
    db.add(row); db.flush()
    return row


@router.post("/{experiment_id}/bandit/select", response_model=BanditDecisionOut, status_code=201, dependencies=[Depends(require_write_access)])
def bandit_select(experiment_id: int, payload: BanditSelectRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    if experiment.status != "running":
        raise HTTPException(status_code=409, detail="Experiment chưa ở trạng thái running.")
    policy = _active_bandit_policy(db, experiment, tenant)
    if payload.idempotency_key:
        existing = db.query(BanditDecision).filter(BanditDecision.experiment_id == experiment.id, BanditDecision.business_id == tenant.business_id, BanditDecision.idempotency_key == payload.idempotency_key).first()
        if existing:
            return existing
    context_hash = _context_hash(payload.context)
    seed = int(hashlib.sha256(f"{payload.subject_key}:{context_hash}:{policy.version}".encode()).hexdigest(), 16)
    epsilon = float(policy.epsilon)
    explore = (seed % 1_000_000) / 1_000_000 < epsilon
    stats = {arm: db.query(BanditArmStat).filter(BanditArmStat.policy_id == policy.id, BanditArmStat.arm == arm, BanditArmStat.context_hash == context_hash).first() for arm in experiment.variants}
    if explore or not any(item and item.pulls for item in stats.values()):
        arm = experiment.variants[seed % len(experiment.variants)]
        reason = "exploration"
    else:
        arm = max(experiment.variants, key=lambda item: (float((stats[item].reward_sum or 0) / max(1, stats[item].pulls)), item))
        reason = "exploitation"
    row = BanditDecision(business_id=tenant.business_id, experiment_id=experiment.id, subject_key=payload.subject_key, arm=arm, context=payload.context, policy_id=policy.id, policy_version=policy.version, context_hash=context_hash, selection_reason=reason, idempotency_key=payload.idempotency_key)
    db.add(row); db.commit(); db.refresh(row)
    return row


@router.post("/{experiment_id}/bandit/decision", response_model=BanditDecisionOut, status_code=201, dependencies=[Depends(require_write_access)])
def bandit_decision(experiment_id: int, payload: BanditDecisionRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    if experiment.status != "running":
        raise HTTPException(status_code=409, detail="Experiment chưa ở trạng thái running.")
    if payload.idempotency_key:
        existing = db.query(BanditDecision).filter(BanditDecision.experiment_id == experiment.id, BanditDecision.business_id == tenant.business_id, BanditDecision.idempotency_key == payload.idempotency_key).first()
        if existing:
            return existing
    if payload.arm is None or payload.arm not in experiment.variants:
        raise HTTPException(status_code=422, detail="Arm không thuộc experiment.")
    policy = _active_bandit_policy(db, experiment, tenant)
    row = BanditDecision(business_id=tenant.business_id, experiment_id=experiment.id, subject_key=payload.subject_key, arm=payload.arm, context=payload.context, policy_id=policy.id, policy_version=policy.version, context_hash=_context_hash(payload.context), selection_reason="manual", idempotency_key=payload.idempotency_key)
    db.add(row); db.commit(); db.refresh(row)
    return row


@router.post("/{experiment_id}/bandit/{decision_id}/reward", response_model=BanditDecisionOut, dependencies=[Depends(require_write_access)])
def bandit_reward(experiment_id: int, decision_id: int, payload: OutcomeRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    experiment = _experiment(db, experiment_id, tenant)
    row = db.query(BanditDecision).filter(BanditDecision.id == decision_id, BanditDecision.experiment_id == experiment.id, BanditDecision.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Bandit decision không tồn tại.")
    if row.reward is not None:
        if payload.idempotency_key and row.reward_idempotency_key == payload.idempotency_key:
            return row
        raise HTTPException(status_code=409, detail="Reward cho decision này đã được ghi nhận.")
    row.reward = payload.value
    row.reward_idempotency_key = payload.idempotency_key
    policy_id = row.policy_id
    if policy_id:
        context_hash = row.context_hash or _context_hash(row.context)
        stat = db.query(BanditArmStat).filter(BanditArmStat.policy_id == policy_id, BanditArmStat.arm == row.arm, BanditArmStat.context_hash == context_hash).first()
        if stat is None:
            stat = BanditArmStat(business_id=tenant.business_id, policy_id=policy_id, arm=row.arm, context_hash=context_hash, pulls=0, reward_sum=Decimal("0"))
            db.add(stat)
        stat.pulls = int(stat.pulls or 0) + 1
        stat.reward_sum = Decimal(stat.reward_sum or 0) + Decimal(payload.value)
    db.commit()
    db.refresh(row)
    return row
