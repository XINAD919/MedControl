"""
Webhooks endpoint para recibir eventos de n8n.

Este módulo maneja:
- reminder.fired: cuando n8n envía una notificación exitosamente
- reminder.failed: cuando falla el envío de una notificación

El registro de canales (Telegram, email, etc.) se gestiona desde
el frontend a través de api/routes/channels.py.
"""

import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from core.db import get_channel_by_notify_id, set_channel_metadata, set_channel_verified, update_reminder_status

logger = logging.getLogger(__name__)
router = APIRouter()


def verify_api_key(x_api_key: str | None = Header(None)) -> None:
    """Verifica que la request venga de n8n con API key válida."""
    expected_key = os.getenv("WEBHOOK_SECRET")

    if not expected_key:
        # Si no hay API key configurada, permitir (solo para desarrollo)
        logger.warning("WEBHOOK_SECRET no configurada. Permitiendo acceso sin autenticación.")
        return

    if x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post("/webhooks/n8n")
async def n8n_webhook(
    payload: Dict[str, Any],
    x_api_key: str | None = Header(None),
):
    """
    Recibe eventos de n8n.

    Eventos soportados:
    - reminder.fired: notificación enviada exitosamente
    - reminder.failed: error al enviar notificación
    - telegram.registered: usuario registró su chat_id de Telegram
    """
    verify_api_key(x_api_key)

    event = payload.get("event")
    data = payload.get("data", {})

    logger.info(f"Received n8n webhook: event={event}, data={data}")

    if event == "reminder.fired":
        # n8n notifica que la notificación fue enviada
        reminder_id = data.get("reminder_id")
        if not reminder_id:
            raise HTTPException(400, "Missing reminder_id in payload")

        # Actualizar estado en DB (redundante, n8n ya lo hizo, pero por si acaso)
        await update_reminder_status(reminder_id, "completed")

        logger.info(f"Reminder {reminder_id} marked as completed")

        # TODO: Si el usuario está conectado por WebSocket, notificar
        # user_id = data.get("user_id")
        # if user_id in active_websockets:
        #     await active_websockets[user_id].send_json({
        #         "type": "reminder_sent",
        #         "reminder_id": reminder_id
        #     })

        return {"status": "received", "reminder_id": reminder_id}

    elif event == "reminder.failed":
        # n8n notifica que falló el envío
        reminder_id = data.get("reminder_id")
        error = data.get("error", "Unknown error")

        if not reminder_id:
            raise HTTPException(400, "Missing reminder_id in payload")

        await update_reminder_status(reminder_id, "failed", error_message=error)

        logger.error(f"Reminder {reminder_id} failed: {error}")

        return {"status": "received", "reminder_id": reminder_id}

    else:
        logger.warning(f"Unknown event type: {event}")
        raise HTTPException(400, f"Unknown event type: {event}")


class ChannelVerifyPayload(BaseModel):
    notify_id: str
    code: Optional[str] = None  # No requerido en flujo por poll; sí en flujo por texto


@router.post("/webhooks/channel-verify")
async def channel_verify_webhook(
    payload: ChannelVerifyPayload,
    x_api_key: str | None = Header(None),
):
    """
    Recibe confirmación de verificación de WhatsApp desde n8n.
    - Flujo por poll: solo envía notify_id (el voto en la encuesta prueba posesión del teléfono)
    - Flujo por texto: envía notify_id + code para validación explícita
    """
    verify_api_key(x_api_key)

    row = await get_channel_by_notify_id("whatsapp", payload.notify_id)
    if not row:
        raise HTTPException(404, "Canal no encontrado o ya verificado")

    user_id = row["user_id"]
    meta = row.get("metadata") or {}
    stored_code = meta.get("verification_code")
    expires_at = meta.get("verification_expires_at")
    attempts = meta.get("verification_attempts", 0)

    if not expires_at:
        raise HTTPException(400, "No hay verificación pendiente")

    if datetime.now(timezone.utc) > datetime.fromisoformat(expires_at):
        raise HTTPException(400, "Código expirado")

    if payload.code is not None:
        # Flujo por texto: validar código explícitamente
        if not stored_code:
            raise HTTPException(400, "No hay código de verificación pendiente")
        if attempts >= 5:
            raise HTTPException(429, "Demasiados intentos")
        if not hmac.compare_digest(stored_code, payload.code.strip()):
            await set_channel_metadata(user_id, "whatsapp", {
                **meta,
                "verification_attempts": attempts + 1,
            })
            raise HTTPException(400, "Código incorrecto")

    await set_channel_verified(user_id, "whatsapp")
    logger.info(f"User {user_id} verified whatsapp channel {payload.notify_id}")
    return {"status": "verified", "channel": "whatsapp", "user_id": user_id}


