"""Connection support ledger only: no tenant access or provider calls."""
import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.platform import _sync_platform_business
from app.auth.dependencies import get_current_user
from app.auth.platform import require_platform_admin
from app.database.platform_session import get_platform_db
from app.db.dependencies import get_db
from app.services.quota_service import quota_snapshot
from app.models.business import User
from app.models.platform_support_request import PlatformSupportRequest, PlatformSupportRequestHistory
from app.schemas.platform_support_request import (
    SupportRequestCreate, SupportRequestUpdate, SupportRequestOut, SupportRequestListOut, SupportStatus,
)

router = APIRouter(tags=['Platform connection support'])
TRANSITIONS = {'open': {'in_progress'}, 'in_progress': {'resolved'}, 'resolved': {'in_progress', 'closed'}, 'closed': set()}


def _shop_id(user: User) -> int:
    if user.business_id is None:
        raise HTTPException(403, 'shop_identity_required')
    return user.business_id


def _unavailable(db: Session):
    db.rollback()
    raise HTTPException(503, 'support_requests_unavailable')


def _replay(row, fingerprint, response):
    if row.request_fingerprint != fingerprint:
        raise HTTPException(409, 'idempotency_payload_conflict')
    response.status_code = 200
    return row


def _channel_limit(db, business_id):
    snapshot = quota_snapshot(db, business_id)
    if snapshot['plan_code'] is None:
        return 0
    limit = snapshot['resources']['connected_channels']['limit']
    return 6 if limit is None else min(6, max(0, int(limit)))


@router.post('/support/requests', response_model=SupportRequestOut, status_code=201)
def create_support_request(payload: SupportRequestCreate, response: Response,
                           user: User = Depends(get_current_user),
                           db: Session = Depends(get_platform_db), legacy_db: Session = Depends(get_db)):
    business_id = _shop_id(user)
    channels = {'provider': payload.provider} if len(payload.providers) == 1 else {'providers': payload.providers}
    fingerprint = hashlib.sha256(json.dumps({**channels, 'description': payload.description},
                                           sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    lookup = select(PlatformSupportRequest).where(PlatformSupportRequest.business_id == business_id,
                                                PlatformSupportRequest.idempotency_key == payload.idempotency_key)
    try:
        row = db.scalar(lookup)
        if row is not None:
            return _replay(row, fingerprint, response)
        _sync_platform_business(db, legacy_db, business_id)
        channel_limit = _channel_limit(db, business_id)
        if len(payload.providers) > channel_limit:
            raise HTTPException(422, {'code': 'support_channel_limit', 'limit': channel_limit})
        row = PlatformSupportRequest(business_id=business_id, created_by_user_id=user.id,
                                     provider=payload.provider, providers=payload.providers, description=payload.description,
                                     idempotency_key=payload.idempotency_key, request_fingerprint=fingerprint,
                                     status='open')
        row.history.append(PlatformSupportRequestHistory(actor_user_id=user.id, from_status=None, to_status='open'))
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        # A concurrent submission may win either the identity or ticket insert.
        try:
            row = db.scalar(lookup)
            if row is not None:
                return _replay(row, fingerprint, response)
        except SQLAlchemyError:
            _unavailable(db)
        raise HTTPException(409, 'support_request_retry')
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        _unavailable(db)


def _list(db, business_id, status, limit, offset):
    filters = []
    if business_id is not None:
        filters.append(PlatformSupportRequest.business_id == business_id)
    if status is not None:
        filters.append(PlatformSupportRequest.status == status)
    try:
        total = db.scalar(select(func.count()).select_from(PlatformSupportRequest).where(*filters))
        items = db.scalars(select(PlatformSupportRequest).where(*filters)
                           .order_by(PlatformSupportRequest.id.desc()).limit(limit).offset(offset)).all()
        return {'items': items, 'total': total, 'limit': limit, 'offset': offset}
    except SQLAlchemyError:
        _unavailable(db)


@router.get('/support/requests', response_model=SupportRequestListOut)
def list_own_support_requests(status: SupportStatus | None = None,
                              limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                              user: User = Depends(get_current_user), db: Session = Depends(get_platform_db)):
    business_id = _shop_id(user)
    result = _list(db, business_id, status, limit, offset)
    try:
        result['channel_limit'] = _channel_limit(db, business_id)
    except SQLAlchemyError:
        _unavailable(db)
    return result


@router.get('/platform/support-requests', response_model=SupportRequestListOut)
def list_platform_support_requests(status: SupportStatus | None = None,
                                   limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                                   admin: User = Depends(require_platform_admin), db: Session = Depends(get_platform_db)):
    return _list(db, None, status, limit, offset)


@router.patch('/platform/support-requests/{request_id}', response_model=SupportRequestOut)
def update_support_request(request_id: int, payload: SupportRequestUpdate,
                           admin: User = Depends(require_platform_admin), db: Session = Depends(get_platform_db)):
    changes = payload.model_dump(exclude_unset=True)
    if changes.get('assigned_admin_id') not in (None, admin.id):
        raise HTTPException(403, 'assignment_must_match_current_admin')
    try:
        row = db.scalar(select(PlatformSupportRequest).where(PlatformSupportRequest.id == request_id).with_for_update())
        if row is None:
            raise HTTPException(404, 'support_request_not_found')
        previous = row.status
        next_status = changes.get('status', previous)
        if next_status != previous and next_status not in TRANSITIONS[previous]:
            raise HTTPException(409, 'invalid_support_status_transition')
        for field, value in changes.items():
            setattr(row, field, value)
        row.history.append(PlatformSupportRequestHistory(actor_user_id=admin.id, from_status=previous,
            to_status=row.status, response=row.response, assigned_admin_id=row.assigned_admin_id))
        db.commit()
        db.refresh(row)
        return row
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        _unavailable(db)
