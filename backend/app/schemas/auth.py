"""Pydantic schemas for the host auth API (M3).

Passwords are constrained to bcrypt's 72-byte limit to avoid silent
truncation. ``EmailStr`` requires the ``email-validator`` package.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.core.security import BCRYPT_MAX_BYTES

#: Minimum password length for host accounts.
MIN_PASSWORD_LENGTH = 8


class HostRegisterRequest(BaseModel):
    """Request body for ``POST /api/v1/auth/host/register``."""

    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=BCRYPT_MAX_BYTES)


class HostLoginRequest(BaseModel):
    """Request body for ``POST /api/v1/auth/host/login``."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=BCRYPT_MAX_BYTES)


class HostResponse(BaseModel):
    """Public view of a host account."""

    id: uuid.UUID
    email: EmailStr
    created_at: datetime


class AuthResponse(BaseModel):
    """Response body for a successful login: bearer token + host."""

    token: str
    token_type: Literal["bearer"] = "bearer"
    host: HostResponse
