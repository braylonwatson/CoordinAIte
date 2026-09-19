"""Optional live prediction transport. PostgreSQL remains the state authority."""
import asyncio
import json
import logging
from time import monotonic, perf_counter
from typing import Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import Field, ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import authenticate_access_token
from app.api.routes.inference import make_prediction
from app.schemas import PredictRequest, StrictRequest
from app.services.game_sessions import GameAccess


router = APIRouter()
logger = logging.getLogger(__name__)
FIRST_COMMAND_TIMEOUT = 10


class PredictionCommand(StrictRequest):
    id: str = Field(min_length=1, max_length=64)
    type: Literal["predict", "predict-tier2"]
    payload: PredictRequest
    access_token: str | None = Field(default=None, max_length=4096)
    guest_token: str | None = Field(default=None, max_length=128)


def execute_command(application, command: PredictionCommand) -> dict:
    # Create/use/close each ORM session within the same worker thread. Never
    # retain a DB connection, ORM object, or mutable tracker on an idle socket.
    with application.state.session_factory() as db:
        session = (
            authenticate_access_token(command.access_token, db, application.state.settings)
            if command.access_token else None
        )
        access = GameAccess(user=session.user if session else None, guest_token=command.guest_token)
        return make_prediction(
            command.payload, tier=2 if command.type == "predict-tier2" else 1,
            db=db, model_bundle=application.state.model_bundle, access=access,
        )


@router.websocket("/ws/predictions")
async def predictions(websocket: WebSocket):
    settings = websocket.app.state.settings
    # CORS middleware does not protect WebSocket upgrades. Explicitly reject
    # cross-site sockets; native callers can supply an approved Origin too.
    if not settings.realtime_enabled or websocket.headers.get("origin") not in settings.cors_origins:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    window, count = monotonic(), 0
    authentication_deadline = window + FIRST_COMMAND_TIMEOUT
    authenticated = False
    try:
        while True:
            # No unlimited idle sessions or unbounded client-side queues.
            # Invalid commands must not reset the initial authentication deadline.
            timeout = 60 if authenticated else authentication_deadline - monotonic()
            if timeout <= 0:
                await websocket.close(code=1008)
                return
            message = await asyncio.wait_for(websocket.receive(), timeout=timeout)
            if message["type"] == "websocket.disconnect":
                return
            raw = message.get("text")
            if raw is None:
                await websocket.close(code=1003)
                return
            if len(raw.encode("utf-8")) > 16384:
                await websocket.close(code=1009)
                return
            if monotonic() - window >= 1:
                window, count = monotonic(), 0
            count += 1
            if count > 10:
                await websocket.close(code=1008)
                return
            request_id = None
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, dict) and isinstance(decoded.get("id"), str):
                    request_id = decoded["id"][:64]
                command = PredictionCommand.model_validate(decoded)
            except (ValueError, ValidationError):
                # Do not echo validation input: it can contain access tokens.
                await websocket.send_json({"id": request_id, "status": 422, "detail": "Invalid prediction command."})
                continue
            started = perf_counter()
            try:
                result = await run_in_threadpool(execute_command, websocket.app, command)
                authenticated = True
                result["timing_ms"]["command_total"] = round((perf_counter() - started) * 1000, 3)
                reply = {"id": command.id, "status": 200, "data": result}
            except HTTPException as exc:
                reply = {"id": command.id, "status": exc.status_code, "detail": exc.detail}
            except Exception:
                logger.exception("Live prediction failed")
                reply = {"id": command.id, "status": 500, "detail": "Prediction failed. Check game state before retrying."}
            await websocket.send_json(reply)
    except asyncio.TimeoutError:
        await websocket.close(code=1000 if authenticated else 1008)
    except WebSocketDisconnect:
        pass
