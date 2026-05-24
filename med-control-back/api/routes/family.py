import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
    await db.update_user_role(current_user.user_id, "CAREGIVER")
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
