"""WebSocket endpoint for streaming Terraform operation output.

The frontend connects to ``/ws/terraform/{operation_id}?token=<jwt>``
and receives every stdout/stderr line published by the ``TerraformRunner``
via Redis Pub/Sub.  When the subprocess exits the runner publishes a
sentinel ``__EXIT:<code>`` message; the server forwards it and closes
the socket.

The ``token`` query parameter is required because browsers cannot send
``Authorization`` headers on WebSocket connections.
"""

import asyncio
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis

from app.auth.keycloak import validate_ws_token
from app.config import settings
from app.core.tf_runner import log_channel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/terraform/{operation_id}")
async def terraform_ws(
    websocket: WebSocket,
    operation_id: str,
    token: str = Query(default=""),
):
    # --- Authenticate via query-param token ---
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        user = await validate_ws_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    logger.info("WS connected: user=%s operation=%s", user.username, operation_id)
    await websocket.accept()

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    channel = log_channel(operation_id)

    try:
        await pubsub.subscribe(channel)

        while True:
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if msg is not None and msg["type"] == "message":
                data: str = msg["data"]
                await websocket.send_text(data)

                # Runner publishes __EXIT:<code> when the process ends.
                if data.startswith("__EXIT:"):
                    break
            else:
                # Yield control so we don't spin; also lets us detect
                # a client disconnect on the next iteration.
                await asyncio.sleep(0.05)

    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await redis.aclose()
