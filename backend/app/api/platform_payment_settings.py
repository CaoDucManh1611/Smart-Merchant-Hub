from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from app.auth.platform import require_platform_admin
from app.db.dependencies import get_db
from app.services import vietqr_payment_service as service

class PaymentValidationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def redacted(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={'detail': 'Cấu hình thanh toán không hợp lệ. Kiểm tra ngân hàng, số tài khoản và thông tin người nhận.'})
        return redacted


router = APIRouter(prefix='/platform/payment-settings', route_class=PaymentValidationRoute,
                   dependencies=[Depends(require_platform_admin)])


@router.get('')
def get_settings(db=Depends(get_db)):
    return service.read(db)


@router.put('')
def put_settings(payload: service.PaymentSettingsUpdate, db=Depends(get_db)):
    try:
        result = service.save(db, payload)
        db.commit()
        return result
    except ValueError:
        db.rollback()
        raise HTTPException(422, 'Cấu hình VietQR chưa đủ hoặc không hợp lệ.')
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, 'Chưa lưu được cấu hình thanh toán.')


@router.post('/test')
def check_settings(db=Depends(get_db)):
    service.configured(db)
    return {'status': 'configured', 'message': 'Cấu hình VietQR hợp lệ về định dạng; admin phải đối soát tiền thực nhận.'}
