from datetime import datetime

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    legacy_user_id: str | None = None
    device_name: str | None = Field(default=None, max_length=160)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    device_name: str | None = Field(default=None, max_length=160)


class AuthUserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    email_verified: bool


class AuthResponse(BaseModel):
    user: AuthUserResponse


class AuthSessionResponse(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    current: bool
    device_name: str | None = None
    ip_address: str | None = None
    ip_region: str | None = None


class AuthSessionListResponse(BaseModel):
    sessions: list[AuthSessionResponse]


class TokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class PasswordResetConfirmRequest(TokenRequest):
    new_password: str = Field(min_length=12, max_length=128)


class AccountDeletionRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    confirmation: str = Field(pattern=r"^DELETE$")


class MessageResponse(BaseModel):
    message: str
