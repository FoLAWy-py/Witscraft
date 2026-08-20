import asyncio
import json
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_verified_user_id
from app.config import Settings, get_settings
from app.db.session import get_session
from app.llm.audit import CallAuditor, TurnCallBudgetExceededError
from app.llm.router import LLMGateway, PurposeInputBudgetExceededError
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.story_engine import StoryEngine
from app.services.style_profiles import StyleReproductionError
from app.services.quota_service import QuotaExceededError
from app.services.model_route_service import load_user_purpose_routes

router = APIRouter(prefix="/chat", tags=["chat"])


def _with_idempotency_header(payload: ChatRequest, request: Request) -> ChatRequest:
    header_key = request.headers.get("Idempotency-Key")
    if not header_key:
        return payload
    if payload.idempotency_key and payload.idempotency_key != header_key:
        raise HTTPException(status_code=409, detail="Idempotency key header and body do not match")
    return ChatRequest.model_validate({**payload.model_dump(), "idempotency_key": header_key})


async def get_story_engine(
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    user_id: UUID = Depends(get_verified_user_id),
) -> StoryEngine:
    auditor = CallAuditor(
        settings,
        user_id=user_id,
        request_id=getattr(request.state, "request_id", None),
    )
    purpose_routes = await load_user_purpose_routes(session, user_id)
    return StoryEngine(
        LLMGateway(settings, auditor=auditor, purpose_routes=purpose_routes),
        session,
        user_id,
    )


@router.post("/send", response_model=ChatResponse)
async def send_chat(
    payload: ChatRequest,
    request: Request,
    engine: StoryEngine = Depends(get_story_engine),
) -> ChatResponse:
    payload = _with_idempotency_header(payload, request)
    try:
        return await engine.send(payload)
    except asyncio.CancelledError as error:
        with anyio.CancelScope(shield=True):
            await engine.fail_active_generation(error, cancelled=True)
        raise
    except PurposeInputBudgetExceededError as error:
        await engine.fail_active_generation(error)
        raise HTTPException(status_code=413, detail=str(error)) from error
    except StyleReproductionError as error:
        await engine.fail_active_generation(error)
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        await engine.fail_active_generation(error)
        raise


@router.post("/context-preview")
async def context_preview(
    request: ChatRequest,
    engine: StoryEngine = Depends(get_story_engine),
) -> dict:
    return await engine.preview_context(request)


@router.post("/stream")
async def stream_chat(
    payload: ChatRequest,
    request: Request,
    engine: StoryEngine = Depends(get_story_engine),
) -> StreamingResponse:
    payload = _with_idempotency_header(payload, request)

    async def events():
        try:
            async for event in engine.stream(payload):
                event_type = event.get("type", "message")
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError as error:
            with anyio.CancelScope(shield=True):
                await engine.fail_active_generation(error, cancelled=True)
            raise
        except QuotaExceededError as error:
            await engine.fail_active_generation(error)
            event = {
                "type": "error",
                "status": 429,
                "detail": str(error),
                "scope": error.scope,
            }
            yield f"event: error\ndata: {json.dumps(event)}\n\n"
        except PurposeInputBudgetExceededError as error:
            await engine.fail_active_generation(error)
            event = {"type": "error", "status": 413, "detail": str(error)}
            yield f"event: error\ndata: {json.dumps(event)}\n\n"
        except TurnCallBudgetExceededError as error:
            await engine.fail_active_generation(error)
            event = {
                "type": "error",
                "status": 429,
                "detail": "Per-turn external model call limit reached",
                "limit": error.limit,
            }
            yield f"event: error\ndata: {json.dumps(event)}\n\n"
        except StyleReproductionError as error:
            await engine.fail_active_generation(error)
            event = {"type": "error", "status": 422, "detail": str(error)}
            yield f"event: error\ndata: {json.dumps(event)}\n\n"
        except Exception as error:
            await engine.fail_active_generation(error)
            event = {"type": "error", "status": 500, "detail": "Generation failed"}
            yield f"event: error\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
