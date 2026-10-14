from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.auth.platform import require_platform_admin
from app.db.dependencies import get_db
from app.schemas.platform_otp_email import PlatformOtpEmailOut, PlatformOtpEmailTest, PlatformOtpEmailUpdate
from app.services.platform_otp_email import read_platform_otp_email, save_platform_otp_email, get_platform_otp_smtp_config, claim_test_email_slot
from app.services.otp_delivery import OtpDeliveryError, OtpDeliveryNotConfigured, send_smtp_test_email

class RedactedValidationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def redacted(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "Cấu hình chưa hợp lệ. Dùng cùng tài khoản Gmail cho tên đăng nhập và email gửi, tên người gửi hợp lệ, máy chủ smtp.gmail.com cổng 587 STARTTLS; kiểm tra email nhận thử."})

        return redacted


router = APIRouter(prefix="/platform/otp-email", route_class=RedactedValidationRoute,
                   dependencies=[Depends(require_platform_admin)])


@router.get("", response_model=PlatformOtpEmailOut)
def get_settings(db=Depends(get_db)):
    return read_platform_otp_email(db)


@router.put("", response_model=PlatformOtpEmailOut)
def put_settings(payload: PlatformOtpEmailUpdate, db=Depends(get_db)):
    try:
        result = save_platform_otp_email(db, payload)
        db.commit()
        return result
    except ValueError as error:
        db.rollback()
        raise HTTPException(422, "Nhập tài khoản Gmail và mật khẩu ứng dụng Gmail để bật gửi OTP. Mật khẩu để trống chỉ được giữ lại khi đã lưu trước đó.") from error
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(503, "Chưa lưu được cấu hình OTP. Kiểm tra kết nối cơ sở dữ liệu và thử lại.") from error


@router.post("/test")
def test_email(payload: PlatformOtpEmailTest, db=Depends(get_db)):
    try:
        config = get_platform_otp_smtp_config(db)
        if config is None:
            raise OtpDeliveryNotConfigured("Enable the platform sender first")
        if not claim_test_email_slot(db):
            raise HTTPException(429, "Vui lòng chờ 60 giây trước khi gửi email thử tiếp theo.", headers={"Retry-After": "60"})
        send_smtp_test_email(destination=payload.email, smtp_config=config)
    except (OtpDeliveryError, OtpDeliveryNotConfigured, ValueError, OSError, SQLAlchemyError) as error:
        raise HTTPException(503, "Chưa gửi được email thử. Bật cấu hình, kiểm tra tài khoản Gmail, mật khẩu ứng dụng và kết nối SMTP rồi thử lại.") from error
    return {"status": "smtp_accepted", "email": payload.email}
