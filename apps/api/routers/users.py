"""Endpoints de usuario autenticado."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from apps.api.core.security import AuthContext, get_auth_context
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/users", tags=["users"])

AuthDep = Annotated[AuthContext, Depends(get_auth_context)]


class CurrentUserResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID | None
    role: str
    email: str


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Identidad del usuario autenticado — role, tenant_id, email",
)
async def get_current_user(auth: AuthDep) -> CurrentUserResponse:
    return CurrentUserResponse(
        user_id=auth.user_id,
        tenant_id=auth.tenant_id,
        role=auth.role,
        email=auth.email,
    )
