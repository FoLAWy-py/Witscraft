from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_verified_user_id
from app.config import Settings, get_settings
from app.db.models import ModelHealthCheck, UserModelRoute
from app.db.session import get_session
from app.llm.audit import CallAuditor
from app.llm.model_registry import PURPOSE_DEFAULTS, get_model, list_models
from app.llm.router import LLMGateway
from app.schemas.llm import ChatMessage, LLMRequest, ProviderName, StoryPurpose
from app.services.quota_service import QuotaExceededError

router = APIRouter(prefix="/providers", tags=["providers"])
HEALTH_FRESHNESS = timedelta(hours=6)


class ProviderTestRequest(BaseModel):
    provider: ProviderName
    model: str
    max_output_tokens: int = Field(default=128, ge=32, le=512)


class ModelRoutesRequest(BaseModel):
    routes: dict[StoryPurpose, str]

    @model_validator(mode="after")
    def validate_complete_routes(self):
        missing = set(PURPOSE_DEFAULTS) - set(self.routes)
        if missing:
            raise ValueError(f"Missing model routes: {', '.join(sorted(missing))}")
        unknown_models = [model for model in self.routes.values() if get_model(model) is None]
        if unknown_models:
            raise ValueError(f"Unknown model: {unknown_models[0]}")
        return self


async def _load_routes(session: AsyncSession, user_id: UUID) -> dict[str, str]:
    result = await session.execute(
        select(UserModelRoute).where(UserModelRoute.user_id == user_id)
    )
    return {
        route.purpose: route.model
        for route in result.scalars().all()
        if get_model(route.model) is not None
    }


def _health_is_fresh(checked_at: datetime, now: datetime | None = None) -> bool:
    reference = now or datetime.now(timezone.utc)
    normalized = checked_at if checked_at.tzinfo else checked_at.replace(tzinfo=timezone.utc)
    return reference - normalized <= HEALTH_FRESHNESS


def _serialize_health(check: ModelHealthCheck) -> dict:
    return {
        "provider": check.provider,
        "model": check.model,
        "status": check.status,
        "latency_ms": check.latency_ms,
        "error": check.error,
        "checked_at": check.checked_at.isoformat(),
        "fresh": _health_is_fresh(check.checked_at),
    }


async def _load_health(session: AsyncSession) -> dict[str, dict]:
    result = await session.execute(select(ModelHealthCheck))
    return {check.model: _serialize_health(check) for check in result.scalars().all()}


async def _record_health(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    status: str,
    latency_ms: int | None,
    error: str | None,
) -> ModelHealthCheck:
    result = await session.execute(
        select(ModelHealthCheck).where(ModelHealthCheck.model == model)
    )
    check = result.scalar_one_or_none()
    if check is None:
        check = ModelHealthCheck(model=model, provider=provider, status=status)
        session.add(check)
    check.provider = provider
    check.status = status
    check.latency_ms = latency_ms
    check.error = error
    check.checked_at = datetime.now(timezone.utc)
    await session.commit()
    return check


@router.get("")
async def providers(
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> dict:
    return {
        "models": [model.model_dump() for model in list_models()],
        "purpose_defaults": PURPOSE_DEFAULTS,
        "purpose_routes": await _load_routes(session, user_id),
        "availability": {
            "openai": bool(settings.openai_api_key),
            "deepinfra": bool(settings.deepinfra_api_key),
            "database": bool(settings.database_url),
        },
        "model_health": await _load_health(session),
        "deepinfra_base_url": settings.deepinfra_base_url,
    }


@router.put("/routes")
async def update_routes(
    request: ModelRoutesRequest,
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> dict:
    health_result = await session.execute(
        select(ModelHealthCheck).where(ModelHealthCheck.model.in_(request.routes.values()))
    )
    unavailable = [
        check.model
        for check in health_result.scalars().all()
        if check.status == "unavailable" and _health_is_fresh(check.checked_at)
    ]
    if unavailable:
        model = get_model(unavailable[0])
        raise HTTPException(
            status_code=409,
            detail=f"{model.label if model else unavailable[0]} was recently confirmed unavailable. Run its health check again before selecting it.",
        )
    await session.execute(delete(UserModelRoute).where(UserModelRoute.user_id == user_id))
    for purpose, model_slug in request.routes.items():
        model = get_model(model_slug)
        if model is None:
            raise ValueError(f"Unknown model: {model_slug}")
        session.add(
            UserModelRoute(
                user_id=user_id,
                purpose=purpose,
                provider=model.provider,
                model=model.model,
            )
        )
    await session.commit()
    return {"purpose_routes": await _load_routes(session, user_id)}


@router.post("/test")
async def test_provider(
    request: ProviderTestRequest,
    http_request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> dict:
    option = get_model(request.model)
    if option is None or option.provider != request.provider:
        raise HTTPException(status_code=400, detail="Model is not registered for this provider")
    configured = {
        "openai": bool(settings.openai_api_key),
        "deepinfra": bool(settings.deepinfra_api_key),
    }[request.provider]
    if not configured:
        raise HTTPException(status_code=409, detail=f"{request.provider} is not configured")

    test_request = LLMRequest(
        provider=request.provider,
        model=request.model,
        messages=[
            ChatMessage(role="system", content="You are a concise health-check responder."),
            ChatMessage(
                role="user",
                content="Reply with one short sentence confirming the model is reachable.",
            ),
        ],
        max_output_tokens=max(128, request.max_output_tokens),
        temperature=0.2,
        top_p=0.9,
    )
    auditor = CallAuditor(
        settings,
        user_id=user_id,
        request_id=getattr(http_request.state, "request_id", None),
    )
    gateway = LLMGateway(settings, auditor=auditor)
    try:
        response = await gateway.generate(gateway.normalize_request(test_request))
    except QuotaExceededError:
        raise
    except Exception as caught:
        message = str(caught).strip() or caught.__class__.__name__
        check = await _record_health(
            session,
            provider=request.provider,
            model=request.model,
            status="unavailable",
            latency_ms=None,
            error=message[:500],
        )
        return {"ok": False, "health": _serialize_health(check)}

    check = await _record_health(
        session,
        provider=response.provider,
        model=response.model,
        status="available",
        latency_ms=response.latency_ms,
        error=None,
    )
    return {
        "ok": True,
        "provider": response.provider,
        "model": response.model,
        "text": response.text,
        "latency_ms": response.latency_ms,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "health": _serialize_health(check),
    }
