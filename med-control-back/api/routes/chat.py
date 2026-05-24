import logging

import httpx
from fastapi import APIRouter, HTTPException, Query
from starlette.websockets import WebSocket

from core import db
from deps import get_or_create_agent, validate_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ws",
    tags=["Chat"],
)


@router.websocket("/chat")
async def chat(
    websocket: WebSocket,
    session_id: str | None = None,
    token: str | None = Query(None),
):
    await websocket.accept()
    try:
        current_user = validate_token(token)
    except HTTPException:
        await websocket.close(code=4001)
        return

    data = await websocket.receive_json()
    resolved_session_id = session_id or data.get("session_id", "default")
    agent = await get_or_create_agent(resolved_session_id, current_user.user_id)

    user_msg = data["message"]
    agent.historial.append({"role": "user", "content": user_msg})
    await db.save_message(resolved_session_id, "user", user_msg)

    full_response: list[str] = []
    try:
        async for tok in agent.chat_stream():
            await websocket.send_text(tok)
            if tok != "[DONE]":
                full_response.append(tok)
    except httpx.ConnectError:
        logger.error("LLM provider unreachable", exc_info=True)
        try:
            await websocket.send_text(
                "⚠️ No se pudo conectar al proveedor de IA. "
                "Verifica que el servicio esté disponible."
            )
        except Exception:
            pass
    except Exception as e:
        logger.error("Chat streaming error: %s", e, exc_info=True)
        try:
            await websocket.send_text(
                "⚠️ Error al procesar tu mensaje. Por favor, intenta de nuevo."
            )
        except Exception:
            pass

    await db.save_message(resolved_session_id, "assistant", "".join(full_response))
    await websocket.close()
