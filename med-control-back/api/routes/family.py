import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core import db
from core.email import send_invitation_existing_user, send_invitation_new_user
from deps import CurrentUser, get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

_APP_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# ── Modelos ──────────────────────────────────────────────────────────────────


class InviteRequest(BaseModel):
    email: str


class InvitationOut(BaseModel):
    id: str
    invited_email: str
    status: str
    expires_at: str
    created_at: str


class FamilyMemberOut(BaseModel):
    caregiver_id: str
    email: Optional[str] = None
    name: Optional[str] = None


class LinkedPatientOut(BaseModel):
    patient_id: str
    email: Optional[str] = None
    name: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _validate_invitation(invitation: Optional[dict]) -> None:
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")
    if invitation["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Invitación ya {invitation['status']}")
    exp_raw = str(invitation["expires_at"]).replace("Z", "+00:00")
    exp = datetime.fromisoformat(exp_raw)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > exp:
        raise HTTPException(status_code=410, detail="Invitación expirada")


def _extract_user_info(row: dict, id_key: str) -> tuple[str, Optional[str], Optional[str]]:
    """Extrae id, email y name de una fila con FK join de users."""
    user_data = row.get("users") or {}
    if isinstance(user_data, list):
        user_data = user_data[0] if user_data else {}
    uid = row.get(id_key, "")
    email = user_data.get("email")
    name = (user_data.get("preferences") or {}).get("name")
    return uid, email, name


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/family/invite", tags=["Family"])
async def invite_family_member(
    payload: InviteRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Envía una invitación de cuidador/a al email indicado."""
    inviter = await db.get_user_by_id(current_user.user_id)
    inviter_name = (inviter or {}).get("preferences", {}).get("name") or "Un usuario de MedControl"

    # Bloquear auto-invitación
    if inviter and inviter.get("email", "").lower() == payload.email.lower():
        raise HTTPException(status_code=400, detail="No puedes invitarte a ti mismo")

    token = secrets.token_urlsafe(64)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()

    await db.create_family_invitation(
        inviter_id=current_user.user_id,
        invited_email=payload.email,
        token=token,
        expires_at=expires_at,
    )

    invited_user = await db.get_user_by_email(payload.email)

    if invited_user:
        accept_url = f"{_APP_URL}/family/accept/{token}"
        reject_url = f"{_APP_URL}/family/reject/{token}"
        background_tasks.add_task(
            send_invitation_existing_user,
            to=payload.email,
            inviter_name=inviter_name,
            accept_url=accept_url,
            reject_url=reject_url,
        )
    else:
        register_url = f"{_APP_URL}/register?caregiver_token={token}"
        background_tasks.add_task(
            send_invitation_new_user,
            to=payload.email,
            inviter_name=inviter_name,
            register_url=register_url,
        )

    logger.info(f"Invitación enviada por {current_user.user_id} a {payload.email}")
    return {"ok": True}


@router.get("/family/invitations", response_model=list[InvitationOut], tags=["Family"])
async def list_invitations(
    current_user: CurrentUser = Depends(get_current_user),
):
    """Lista las invitaciones enviadas por el usuario actual."""
    rows = await db.get_pending_invitations_by_inviter(current_user.user_id)
    return [
        InvitationOut(
            id=str(r["id"]),
            invited_email=r["invited_email"],
            status=r["status"],
            expires_at=str(r["expires_at"]),
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]


@router.get("/family/members", response_model=list[FamilyMemberOut], tags=["Family"])
async def list_family_members(
    current_user: CurrentUser = Depends(get_current_user),
):
    """Lista los cuidadores vinculados al usuario actual (paciente)."""
    rows = await db.get_family_members_of_patient(current_user.user_id)
    result = []
    for r in rows:
        cid, email, name = _extract_user_info(r, "caregiver_id")
        result.append(FamilyMemberOut(caregiver_id=cid, email=email, name=name))
    return result


@router.delete("/family/members/{caregiver_id}", tags=["Family"])
async def remove_family_member(
    caregiver_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Elimina la vinculación con un cuidador."""
    await db.remove_family_member(patient_id=current_user.user_id, caregiver_id=caregiver_id)
    return {"ok": True}


@router.get("/family/linked-patients", response_model=list[LinkedPatientOut], tags=["Family"])
async def list_linked_patients(
    current_user: CurrentUser = Depends(get_current_user),
):
    """Lista los pacientes que vincularon al usuario actual como cuidador (Tab Dashboard)."""
    rows = await db.get_linked_patients(current_user.user_id)
    result = []
    for r in rows:
        pid, email, name = _extract_user_info(r, "patient_id")
        result.append(LinkedPatientOut(patient_id=pid, email=email, name=name))
    return result


@router.post("/family/accept/{token}", tags=["Family"])
async def accept_invitation(
    token: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Acepta la invitación: crea la vinculación y cambia el rol a CAREGIVER."""
    invitation = await db.get_invitation_by_token(token)
    _validate_invitation(invitation)

    await db.create_family_member(
        patient_id=invitation["inviter_id"],
        caregiver_id=current_user.user_id,
    )
    await db.update_invitation_status(token, "accepted")

    logger.info(f"Invitación aceptada: cuidador {current_user.user_id} → paciente {invitation['inviter_id']}")
    return {"ok": True}


@router.post("/family/reject/{token}", tags=["Family"])
async def reject_invitation(
    token: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Rechaza la invitación."""
    invitation = await db.get_invitation_by_token(token)
    _validate_invitation(invitation)
    await db.update_invitation_status(token, "rejected")
    logger.info(f"Invitación rechazada por {current_user.user_id}")
    return {"ok": True}


@router.post("/family/invitations/{invitation_id}/resend", tags=["Family"])
async def resend_invitation(
    invitation_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Reenvía una invitación pendiente con un nuevo token y expiración renovada."""
    invitation = await db.get_invitation_by_id(invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")
    if invitation["inviter_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="No autorizado")
    if invitation["status"] not in ("pending", "expired"):
        raise HTTPException(status_code=409, detail=f"No se puede reenviar una invitación en estado '{invitation['status']}'")

    new_token = secrets.token_urlsafe(64)
    new_expires = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
    await db.refresh_invitation_token(invitation_id, new_token, new_expires)

    inviter = await db.get_user_by_id(current_user.user_id)
    inviter_name = (inviter or {}).get("preferences", {}).get("name") or "Un usuario de MedControl"
    invited_email = invitation["invited_email"]

    invited_user = await db.get_user_by_email(invited_email)
    if invited_user:
        accept_url = f"{_APP_URL}/family/accept/{new_token}"
        reject_url = f"{_APP_URL}/family/reject/{new_token}"
        background_tasks.add_task(
            send_invitation_existing_user,
            to=invited_email,
            inviter_name=inviter_name,
            accept_url=accept_url,
            reject_url=reject_url,
        )
    else:
        register_url = f"{_APP_URL}/register?caregiver_token={new_token}"
        background_tasks.add_task(
            send_invitation_new_user,
            to=invited_email,
            inviter_name=inviter_name,
            register_url=register_url,
        )

    logger.info(f"Invitación {invitation_id} reenviada por {current_user.user_id}")
    return {"ok": True}


@router.post("/family/invitations/{invitation_id}/revoke", tags=["Family"])
async def revoke_invitation(
    invitation_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Revoca una invitación pendiente (no aceptada)."""
    invitation = await db.get_invitation_by_id(invitation_id)
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")
    if invitation["inviter_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="No autorizado")
    if invitation["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Solo se pueden revocar invitaciones pendientes (estado actual: '{invitation['status']}')")
    await db.update_invitation_status_by_id(invitation_id, "revoked")
    logger.info(f"Invitación {invitation_id} revocada por {current_user.user_id}")
    return {"ok": True}


class DelayedReminderOut(BaseModel):
    reminder_id: str
    medication: str
    scheduled_at: str
    manual_reminder_sent: bool


@router.get("/family/patients/{patient_id}/delayed-reminders", response_model=list[DelayedReminderOut], tags=["Family"])
async def get_patient_delayed_reminders(
    patient_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Lista dosis retrasadas (>20 min, no tomadas, no privadas) del paciente para el caregiver."""
    if not await db.is_caregiver_of(current_user.user_id, patient_id):
        raise HTTPException(status_code=403, detail="No eres cuidador de este paciente")

    rows = await db.get_delayed_reminders_for_caregiver(patient_id)
    # Comprobar cuáles ya tienen recordatorio manual enviado por este caregiver
    sent_ids = await db.get_manual_reminder_sent_ids(current_user.user_id, [r["reminder_id"] for r in rows])

    return [
        DelayedReminderOut(
            reminder_id=r["reminder_id"],
            medication=r["medication"],
            scheduled_at=str(r["scheduled_at"]),
            manual_reminder_sent=r["reminder_id"] in sent_ids,
        )
        for r in rows
    ]


@router.post("/family/patients/{patient_id}/reminders/{reminder_id}/manual-reminder", tags=["Family"])
async def send_manual_reminder(
    patient_id: str,
    reminder_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
):
    """El caregiver dispara un recordatorio manual al paciente. Máximo 1 por dosis por caregiver."""
    if not await db.is_caregiver_of(current_user.user_id, patient_id):
        raise HTTPException(status_code=403, detail="No eres cuidador de este paciente")

    reminder = await db.get_reminder_for_caregiver(patient_id, reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Recordatorio no encontrado")
    if reminder.get("taken"):
        raise HTTPException(status_code=409, detail="La dosis ya fue marcada como tomada")
    if reminder.get("is_private"):
        raise HTTPException(status_code=403, detail="No tienes acceso a este recordatorio")

    # Insertar en manual_reminder_sends (UNIQUE constraint actúa como rate-limit)
    try:
        await db.insert_manual_reminder_send(reminder_id, current_user.user_id, patient_id)
    except Exception:
        raise HTTPException(status_code=409, detail="Ya enviaste un recordatorio para esta dosis")

    # Obtener canales del paciente y disparar notificación
    caregiver = await db.get_user_by_id(current_user.user_id)
    caregiver_name = (caregiver or {}).get("preferences", {}).get("name", "Tu cuidador/a")
    message = (
        f"📌 {caregiver_name} te recuerda que tienes una dosis pendiente: "
        f"{reminder['medication']} (programada a las {str(reminder['scheduled_at'])[:16].replace('T', ' ')})."
    )

    background_tasks.add_task(
        _dispatch_manual_reminder,
        patient_id=patient_id,
        reminder_id=reminder_id,
        message=message,
        scheduled_at=str(reminder["scheduled_at"]),
        medication=reminder["medication"],
    )

    logger.info(f"Recordatorio manual enviado por caregiver {current_user.user_id} para paciente {patient_id}")
    return {"ok": True}


async def _dispatch_manual_reminder(
    patient_id: str,
    reminder_id: str,
    message: str,
    scheduled_at: str,
    medication: str,
) -> None:
    from core.supabase_client import create_temp_client

    webhook_url = os.getenv("N8N_WEBHOOK_URL", "")
    if not webhook_url:
        return

    client = await create_temp_client()
    try:
        res = await (
            client.table("user_channels")
            .select("channel, notify_id, metadata")
            .eq("user_id", patient_id)
            .eq("verified", True)
            .eq("receive_reminders", True)
            .execute()
        )
        channels = res.data or []
    finally:
        await client.aclose()

    async with httpx.AsyncClient(timeout=10) as http:
        for ch in channels:
            payload = {
                "reminder_id": f"{reminder_id}_manual",
                "user_id": patient_id,
                "medication": medication,
                "message": message,
                "notes": "",
                "channel": ch["channel"],
                "notify_id": ch["notify_id"],
                "scheduled_at": scheduled_at,
                "metadata": ch.get("metadata") or {},
                "alert_type": "manual_reminder_caregiver",
            }
            try:
                await http.post(webhook_url, json=payload)
            except Exception as e:
                logger.error(f"Error al enviar recordatorio manual: {e}")


@router.get("/family/linked-patient-ids", tags=["Family"])
async def get_linked_patient_ids(
    user_id: str,
    x_auth_secret: Optional[str] = Header(None),
):
    """Server-to-server: devuelve los IDs de pacientes vinculados a este cuidador.
    Usado por el frontend para refrescar la sesión tras aceptar una invitación."""
    expected = os.getenv("AUTH_SECRET_INTERNAL")
    if expected and x_auth_secret != expected:
        raise HTTPException(status_code=401, detail="No autorizado")
    ids = await db.get_linked_patient_ids(user_id)
    return ids
