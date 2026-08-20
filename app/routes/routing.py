"""Routing configuration — single row for the lite workspace."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cache_invalidation_bus
from app.deps import get_db, get_key_context
from app.seed import DEFAULT_WORKSPACE_ID
from packages.auth.types import KeyContext
from packages.db.models.routing_config import RoutingConfig

router = APIRouter(prefix="/v1/routing", tags=["routing"])

VALID_STRATEGIES = {"balanced", "cheapest", "fastest", "quality"}


class UpdateRouting(BaseModel):
    strategy: str | None = None
    preferred_models: list[str] | None = None

    @field_validator("strategy")
    @classmethod
    def _validate_strategy(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_STRATEGIES:
            raise ValueError(f"strategy must be one of {sorted(VALID_STRATEGIES)}")
        return v


@router.get("")
async def get_routing(
    _kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(RoutingConfig).where(
                RoutingConfig.workspace_id == DEFAULT_WORKSPACE_ID,
                RoutingConfig.is_deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Routing config not found")
    return {
        "strategy": row.strategy,
        "preferred_models": row.preferred_models or [],
    }


@router.put("")
async def update_routing(
    body: UpdateRouting,
    _kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = (
        await db.execute(
            select(RoutingConfig).where(
                RoutingConfig.workspace_id == DEFAULT_WORKSPACE_ID,
                RoutingConfig.is_deleted == 0,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Routing config not found")

    if body.strategy is not None:
        row.strategy = body.strategy
    if body.preferred_models is not None:
        row.preferred_models = body.preferred_models

    await db.commit()
    await cache_invalidation_bus.broadcast_router_cache_invalidation()

    return {
        "strategy": row.strategy,
        "preferred_models": row.preferred_models or [],
    }
