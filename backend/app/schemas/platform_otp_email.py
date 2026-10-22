from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.shop_otp_email import _EMAIL_RE


class PlatformOtpEmailUpdate(BaseModel):
    enabled: bool = False
    host: Literal["smtp.gmail.com"] = "smtp.gmail.com"
    port: Literal[587] = 587
    security: Literal["starttls"] = "starttls"
    username: str = Field(default="", max_length=255)
    from_email: str = Field(default="", max_length=255)
    from_name: str = Field(default="Smart Merchant Hub", min_length=1, max_length=120)
    password: str = Field(default="", max_length=200, repr=False)

    @field_validator("username", "from_email", "from_name")
    @classmethod
    def safe_header(cls, value):
        if "\r" in value or "\n" in value:
            raise ValueError("Invalid email header")
        return value.strip()

    @model_validator(mode="after")
    def gmail_sender(self):
        if self.enabled:
            if not _EMAIL_RE.fullmatch(self.username) or not self.username.lower().endswith("@gmail.com"):
                raise ValueError("Use a Gmail sender account")
            if self.from_email.lower() != self.username.lower():
                raise ValueError("Sender email must match the Gmail account")
        if not self.from_name:
            raise ValueError("Sender name is required")
        return self


class PlatformOtpEmailOut(BaseModel):
    enabled: bool
    host: str = "smtp.gmail.com"
    port: int = 587
    security: str = "starttls"
    username: str
    from_email: str
    from_name: str
    password_configured: bool


class PlatformOtpEmailTest(BaseModel):
    email: str = Field(min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def recipient(cls, value):
        value = value.strip().lower()
        if not _EMAIL_RE.fullmatch(value):
            raise ValueError("Invalid recipient email")
        return value
