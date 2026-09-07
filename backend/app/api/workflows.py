"""Tenant-scoped workflow definitions and safe manual event execution."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.workflow import Workflow, WorkflowRun
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowListOut,
    WorkflowOut,
    WorkflowRunOut,
    WorkflowRunRequest,
    WorkflowUpdate,
)
from app.services.workflow_engine import execute_workflow
from app.services.job_service import dispatch_due_jobs, enqueue_job
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.auth.dependencies import require_write_access


router = APIRouter()


def _run_out(run: WorkflowRun, status: str | None = None) -> WorkflowRunOut:
    return WorkflowRunOut(
        id=run.id,
        workflow_id=run.workflow_id,
        event_id=run.event_id,
        status=status or run.status,
        matched=run.matched,
        error_message=run.error_message,
        executed_at=run.executed_at,
        attempts=run.attempts or 1,
        next_run_at=run.next_run_at,
    )


def _workflow(db: Session, workflow_id: int, tenant: TenantContext) -> Workflow:
    workflow = db.query(Workflow).filter(
        Workflow.id == workflow_id,
        Workflow.business_id == tenant.business_id,
    ).first()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow không tồn tại.")
    return workflow


def _out(workflow: Workflow) -> WorkflowOut:
    return WorkflowOut(
        id=workflow.id,
        business_id=workflow.business_id,
        name=workflow.name,
        event_type=workflow.event_type,
        conditions=workflow.conditions or {},
        actions=workflow.actions or [],
        enabled=workflow.enabled,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


@router.get("/workflows", response_model=WorkflowListOut)
def list_workflows(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    items = db.query(Workflow).filter(Workflow.business_id == tenant.business_id).order_by(Workflow.id.desc()).all()
    return WorkflowListOut(items=[_out(item) for item in items], total=len(items))


@router.get("/workflows/runs/dispatch", response_model=list[WorkflowRunOut])
def dispatch_due_workflows(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    """Execute due scheduled runs; safe to call repeatedly from a scheduler."""
    def handle_job(payload: dict) -> None:
        workflow = _workflow(db, int(payload["workflow_id"]), tenant)
        execute_workflow(
            db,
            workflow,
            str(payload["event_id"]),
            str(payload.get("event_type") or workflow.event_type),
            payload.get("event_payload") or {},
            tenant,
            allow_retry=True,
        )

    dispatch_due_jobs(
        db,
        business_id=tenant.business_id,
        handlers={"workflow.run": handle_job},
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    runs = db.query(WorkflowRun).filter(
        WorkflowRun.business_id == tenant.business_id,
        WorkflowRun.status == "scheduled",
        WorkflowRun.next_run_at <= now,
    ).order_by(WorkflowRun.next_run_at.asc(), WorkflowRun.id.asc()).limit(100).all()
    results = []
    for run in runs:
        workflow = _workflow(db, run.workflow_id, tenant)
        results.append(execute_workflow(
            db,
            workflow,
            run.event_id,
            run.event_type or workflow.event_type,
            run.payload or {},
            tenant,
            allow_retry=True,
        ))
    return [_run_out(run) for run in results]


@router.post("/workflows", response_model=WorkflowOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_workflow(payload: WorkflowCreate, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    workflow = Workflow(
        business_id=tenant.business_id,
        name=payload.name.strip(),
        event_type=payload.event_type,
        conditions=payload.conditions,
        actions=[action.model_dump(exclude_none=True) for action in payload.actions],
        enabled=payload.enabled,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return _out(workflow)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut, dependencies=[Depends(require_write_access)])
def update_workflow(workflow_id: int, payload: WorkflowUpdate, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    workflow = _workflow(db, workflow_id, tenant)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        data["name"] = data["name"].strip()
    if "actions" in data:
        data["actions"] = [action for action in data["actions"]]
    for field, value in data.items():
        setattr(workflow, field, value)
    db.commit()
    db.refresh(workflow)
    return _out(workflow)


@router.post("/workflows/{workflow_id}/run", response_model=WorkflowRunOut, dependencies=[Depends(require_write_access)])
def run_workflow(workflow_id: int, payload: WorkflowRunRequest, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    workflow = _workflow(db, workflow_id, tenant)
    existing = db.query(WorkflowRun).filter(
        WorkflowRun.workflow_id == workflow.id,
        WorkflowRun.event_id == payload.event_id,
        WorkflowRun.business_id == tenant.business_id,
    ).first()
    if existing is not None:
        return _run_out(existing, status="duplicate")
    if payload.delay_seconds:
        run = WorkflowRun(
            business_id=tenant.business_id,
            workflow_id=workflow.id,
            event_id=payload.event_id,
            event_type=payload.event_type,
            payload=payload.payload,
            status="scheduled",
            matched=False,
            attempts=0,
            next_run_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=payload.delay_seconds),
        )
        db.add(run)
        db.flush()
        enqueue_job(
            db,
            business_id=tenant.business_id,
            kind="workflow.run",
            payload={
                "workflow_id": workflow.id,
                "event_id": payload.event_id,
                "event_type": payload.event_type,
                "event_payload": payload.payload,
            },
            idempotency_key=f"workflow:{workflow.id}:{payload.event_id}",
            run_at=run.next_run_at,
        )
        db.commit()
        db.refresh(run)
        return _run_out(run)
    run = execute_workflow(db, workflow, payload.event_id, payload.event_type, payload.payload, tenant)
    return _run_out(run)


@router.get("/workflows/{workflow_id}/runs", response_model=list[WorkflowRunOut])
def list_workflow_runs(workflow_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    workflow = _workflow(db, workflow_id, tenant)
    runs = db.query(WorkflowRun).filter(
        WorkflowRun.business_id == tenant.business_id,
        WorkflowRun.workflow_id == workflow.id,
    ).order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc()).limit(200).all()
    return [_run_out(run) for run in runs]


@router.post("/workflows/{workflow_id}/runs/{run_id}/retry", response_model=WorkflowRunOut, dependencies=[Depends(require_write_access)])
def retry_workflow_run(workflow_id: int, run_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    workflow = _workflow(db, workflow_id, tenant)
    run = db.query(WorkflowRun).filter(
        WorkflowRun.id == run_id,
        WorkflowRun.workflow_id == workflow.id,
        WorkflowRun.business_id == tenant.business_id,
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run không tồn tại.")
    if run.status != "failed":
        raise HTTPException(status_code=409, detail="Chỉ workflow run thất bại mới được retry.")
    result = execute_workflow(
        db,
        workflow,
        run.event_id,
        run.event_type or workflow.event_type,
        run.payload or {},
        tenant,
        allow_retry=True,
    )
    return _run_out(result)


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_workflow(workflow_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    return _out(_workflow(db, workflow_id, tenant))
