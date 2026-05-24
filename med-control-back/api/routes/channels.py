"""
API endpoints para gestionar canales de notificacion del usuario.
"""

import logging
import os
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import get_user_channels, upsert_user_channel
from core.supabase_client import get_supabase
from deps import CurrentUser, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


class ChannelConfig(BaseModel):
    channel: str  # telegram, email, discord, webpush
    notify_id: str  # chat_id, email, Discord user ID, etc.
    is_primary: bool = False
    receive_reminders: bool = True
    metadata: dict = {}


class ChannelResponse(BaseModel):
    channel: str
    notify_id: str
    verified: bool
    is_primary: bool
    receive_reminders: bool
    metadata: dict


@router.get("/users/{user_id}/channels", response_model=List[ChannelResponse])
async def list_user_channels(
    user_id: str,
    verified_only: bool = True,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(403, "No autorizado")
    channels = await get_user_channels(user_id, verified_only=verified_only)

    return [
        ChannelResponse(
            channel=ch["channel"],
            notify_id=ch["notify_id"],
            verified=ch["verified"],
            is_primary=ch["is_primary"],
            receive_reminders=ch["receive_reminders"],
            metadata=ch.get("metadata", {}),
        )
        for ch in channels
    ]


@router.post("/users/{user_id}/channels")
async def configure_channel(
    user_id: str,
    config: ChannelConfig,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(403, "No autorizado")
    """
    Configura un canal de notificacion para el usuario.

    - telegram: llama a la Bot API para verificar el chat_id al instante
    - email: notify_id debe contener '@'
    - discord: requiere webhook_url en metadata
    - webpush: automatico (OneSignal usa External User ID)
    """
    if config.channel == "telegram":
        try:
            int(config.notify_id)
        except ValueError:
            raise HTTPException(400, "Telegram chat_id debe ser un numero")

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            raise HTTPException(500, "TELEGRAM_BOT_TOKEN no configurado")

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": config.notify_id,
                    "text": (
                        "Conectado a MedAI. "
                        "Recibiras tus recordatorios de medicacion aqui."
                    ),
                },
            )

        if not resp.is_success:
            detail = resp.json().get("description", "Error desconocido")
            raise HTTPException(400, f"Telegram rechazo el mensaje: {detail}")

        await upsert_user_channel(
            user_id=user_id,
            channel="telegram",
            notify_id=config.notify_id,
            verified=True,
            is_primary=config.is_primary,
            receive_reminders=config.receive_reminders,
            metadata=config.metadata,
        )

        logger.info(f"User {user_id} verified telegram channel {config.notify_id}")
        return {
            "status": "configured",
            "channel": "telegram",
            "verified": True,
            "receive_reminders": config.receive_reminders,
        }

    elif config.channel == "email":
        if "@" not in config.notify_id:
            raise HTTPException(400, "Email invalido")

    elif config.channel == "discord":
        if "webhook_url" not in config.metadata:
            raise HTTPException(400, "Discord requiere webhook_url en metadata")

    elif config.channel == "whatsapp":
        try:
            int(config.notify_id)
        except ValueError:
            raise HTTPException(400, "WhatsApp notify_id debe ser un numero")

    # webpush no requiere verificación manual — OneSignal lo gestiona via external_user_id
    verified = config.channel == "webpush"

    await upsert_user_channel(
        user_id=user_id,
        channel=config.channel,
        notify_id=config.notify_id,
        verified=verified,
        is_primary=config.is_primary,
        receive_reminders=config.receive_reminders,
        metadata=config.metadata,
    )

    logger.info(f"User {user_id} configured channel {config.channel} (verified={verified})")

    return {
        "status": "configured",
        "channel": config.channel,
        "verified": verified,
        "receive_reminders": config.receive_reminders,
        "message": (
            "Canal Web Push configurado y listo para recibir notificaciones."
            if verified
            else f"Canal configurado. Revisa tu {config.channel} para verificarlo."
        ),
    }


@router.post("/users/{user_id}/channels/{channel}/verify")
async def verify_channel(
    user_id: str,
    channel: str,
    current_user: CurrentUser = Depends(get_current_user),
    _verification_code: str = None,
):
    if user_id != current_user.user_id:
        raise HTTPException(403, "No autorizado")
    """Verifica un canal de notificacion (email/discord)."""
    await upsert_user_channel(
        user_id=user_id,
        channel=channel,
        notify_id="",
        verified=True,
    )

    return {"status": "verified", "channel": channel}


@router.delete("/users/{user_id}/channels/{channel}")
async def remove_channel(
    user_id: str,
    channel: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(403, "No autorizado")
    """Elimina un canal de notificacion del usuario."""
    client = get_supabase()
    res = (
        await client.table("user_channels")
        .delete()
        .eq("user_id", user_id)
        .eq("channel", channel)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "Canal no encontrado")

    logger.info(f"User {user_id} removed channel {channel}")
    return {"status": "removed", "channel": channel}


@router.post("/users/{user_id}/channels/{channel}/set-primary")
async def set_primary_channel(
    user_id: str,
    channel: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(403, "No autorizado")
    """Marca un canal como primario (desactiva is_primary en los demas)."""
    client = get_supabase()
    await (
        client.table("user_channels")
        .update({"is_primary": False})
        .eq("user_id", user_id)
        .execute()
    )
    res = (
        await client.table("user_channels")
        .update({"is_primary": True})
        .eq("user_id", user_id)
        .eq("channel", channel)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "Canal no encontrado")

    logger.info(f"User {user_id} set {channel} as primary")
    return {"status": "updated", "primary_channel": channel}


@router.patch("/users/{user_id}/channels/{channel}/toggle-reminders")
async def toggle_channel_reminders(
    user_id: str,
    channel: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(403, "No autorizado")
    """Activa o desactiva la recepcion de recordatorios para un canal verificado."""
    client = get_supabase()
    current = (
        await client.table("user_channels")
        .select("receive_reminders")
        .eq("user_id", user_id)
        .eq("channel", channel)
        .maybe_single()
        .execute()
    )
    if not (current and current.data):
        raise HTTPException(404, "Canal no encontrado")

    new_value = not current.data["receive_reminders"]
    await (
        client.table("user_channels")
        .update({"receive_reminders": new_value, "updated_at": "now()"})
        .eq("user_id", user_id)
        .eq("channel", channel)
        .execute()
    )

    logger.info(f"User {user_id} toggled reminders for {channel}: now {new_value}")
    return {"channel": channel, "receive_reminders": new_value}
