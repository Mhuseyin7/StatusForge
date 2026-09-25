import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import MonitorStatus, MonitorType, Role


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    organization_name: str = Field(min_length=2, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(ORMModel):
    id: uuid.UUID
    email: EmailStr
    is_verified: bool
    created_at: datetime


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9-]+$")


class OrganizationResponse(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class MembershipResponse(ORMModel):
    organization_id: uuid.UUID
    user_id: uuid.UUID
    role: Role


class MonitorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=2, max_length=160, pattern=r"^[a-z0-9-]+$")
    type: MonitorType
    interval_seconds: int = Field(default=60, ge=30, le=86400)
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    retry_count: int = Field(default=3, ge=1, le=10)
    config: dict = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict) -> dict:
        if len(value) > 30:
            raise ValueError("configuration has too many keys")
        return value


class MonitorResponse(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    type: MonitorType
    status: MonitorStatus
    interval_seconds: int
    timeout_seconds: int
    retry_count: int
    enabled: bool
    config: dict
    created_at: datetime
    updated_at: datetime


class CheckResponse(ORMModel):
    id: uuid.UUID
    checked_at: datetime
    status: MonitorStatus
    response_time_ms: int | None
    status_code: int | None
    error_code: str | None
    error_message: str | None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    scopes: list[str] = Field(default_factory=list, max_length=20)


class ApiKeyCreated(BaseModel):
    id: uuid.UUID
    key: str
    prefix: str
    scopes: list[str]


class HeartbeatResponse(BaseModel):
    accepted: bool
