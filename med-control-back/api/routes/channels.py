"""
API endpoints para gestionar canales de notificacion del usuario.
"""

import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.db import (
    get_channel_row,
    get_user_channels,
    set_channel_metadata,
    set_channel_verified,
    upsert_user_channel,
)
from core.email import send_verification_email
from core.supabase_client import get_supabase
from deps import CurrentUser, get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

_VERIFICATION_KEYS = {"verification_code", "verification_expires_at", "verification_attempts"}


def _sanitize_metadata(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if k not in _VERIFICATION_KEYS}


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


class VerifyEmailRequest(BaseModel):
    code: str


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
            metadata=_sanitize_metadata(ch.get("metadata", {})),
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


@router.post("/users/{user_id}/channels/{channel}/send-verification")
async def send_channel_verification(
    user_id: str,
    channel: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(403, "No autorizado")
    if channel not in ("email", "whatsapp"):
        raise HTTPException(400, "Solo se puede verificar email o whatsapp")

    row = await get_channel_row(user_id, channel)
    if not row:
        raise HTTPException(404, "Canal no encontrado")
    if row["verified"]:
        raise HTTPException(400, "El canal ya está verificado")

    notify_id = row["notify_id"]

    if channel == "email":
        code = str(secrets.randbelow(900000) + 100000)
    else:
        code = secrets.token_hex(3).upper()

    expiry = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    await set_channel_metadata(user_id, channel, {
        "verification_code": code,
        "verification_expires_at": expiry,
        "verification_attempts": 0,
    })

    if channel == "email":
        send_verification_email(notify_id, code)
        logger.info(f"Verification email sent to {notify_id} for user {user_id}")
    else:
        n8n_url = os.getenv("N8N_WHATSAPP_VERIFY_URL", "")
        waha_session = os.getenv("WAHA_SESSION", "default")
        webhook_secret = os.getenv("WEBHOOK_SECRET", "")
        if not n8n_url:
            logger.warning("N8N_WHATSAPP_VERIFY_URL no configurado — mensaje WhatsApp no enviado")
        else:
            try:
                headers = {"X-Api-Key": webhook_secret} if webhook_secret else {}
                with httpx.Client(timeout=15) as client:
                    client.post(n8n_url, json={
                        "notify_id": notify_id,
                        "code": code,
                        "session": waha_session,
                    }, headers=headers)
            except Exception as exc:
                logger.error(f"Error enviando verificación WhatsApp a {notify_id}: {exc}")

    return {"status": "sent", "expires_in_seconds": 900}


@router.post("/users/{user_id}/channels/email/verify")
async def verify_email_channel(
    user_id: str,
    req: VerifyEmailRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(403, "No autorizado")

    row = await get_channel_row(user_id, "email")
    if not row:
        raise HTTPException(404, "Canal de email no encontrado")
    if row["verified"]:
        raise HTTPException(400, "El canal ya está verificado")

    meta = row.get("metadata") or {}
    stored_code = meta.get("verification_code")
    expires_at = meta.get("verification_expires_at")
    attempts = meta.get("verification_attempts", 0)

    if not stored_code or not expires_at:
        raise HTTPException(400, "No hay código de verificación pendiente")

    if attempts >= 5:
        raise HTTPException(429, "Demasiados intentos. Solicita un nuevo código.")

    if datetime.now(timezone.utc) > datetime.fromisoformat(expires_at):
        raise HTTPException(400, "Código expirado. Solicita uno nuevo.")

    if not hmac.compare_digest(stored_code, req.code.strip()):
        await set_channel_metadata(user_id, "email", {
            **meta,
            "verification_attempts": attempts + 1,
        })
        raise HTTPException(400, "Código incorrecto")

    await set_channel_verified(user_id, "email")
    logger.info(f"User {user_id} verified email channel")
    return {"status": "verified", "channel": "email"}


_CHANNELS_WITHOUT_OTP = {"discord", "webpush", "telegram"}


@router.post("/users/{user_id}/channels/{channel}/verify")
async def verify_channel(
    user_id: str,
    channel: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(403, "No autorizado")
    if channel not in _CHANNELS_WITHOUT_OTP:
        raise HTTPException(400, "Usa el endpoint de verificación con código para este canal")
    row = await get_channel_row(user_id, channel)
    if not row:
        raise HTTPException(404, "Canal no encontrado")

    await set_channel_verified(user_id, channel)
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
