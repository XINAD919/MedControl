from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.db import get_user_reminders
from core.supabase_client import get_supabase
from deps import CurrentUser, get_current_user

router = APIRouter()


class ReminderResponse(BaseModel):
    reminder_id: str
    medication: str
    schedule: str
    message: str
    notes: Optional[str]
    channels: list[str]
    scheduled_at: str
    fired_at: Optional[str]
    status: str
    created_at: str
    taken: bool = False
    taken_at: Optional[str] = None


@router.get("/users/{user_id}/reminders", response_model=list[ReminderResponse])
async def list_reminders(
    user_id: str,
    status: Optional[str] = None,
    date: Optional[str] = None,
    medication: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="No autorizado")
    try:
        rows = await get_user_reminders(user_id, status=status, date=date, medication=medication)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    def fmt(dt) -> Optional[str]:
        if dt is None:
            return None
        if isinstance(dt, datetime):
            return dt.isoformat()
        return str(dt)

    return [
        ReminderResponse(
            reminder_id=r["reminder_id"],
            medication=r["medication"],
            schedule=r["schedule"],
            message=r["message"],
            notes=r.get("notes"),
            channels=list(r["channels"]),
            scheduled_at=fmt(r["scheduled_at"]),
            fired_at=fmt(r.get("fired_at")),
            status=str(r["status"]),
            created_at=fmt(r["created_at"]),
            taken=bool(r.get("taken", False)),
            taken_at=fmt(r.get("taken_at")),
        )
        for r in rows
    ]


@router.patch("/users/{user_id}/reminders/{reminder_id}/taken")
async def mark_reminder_taken(
    user_id: str,
    reminder_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="No autorizado")
    try:
        db = get_supabase()
        row = await db.table("reminders").select("scheduled_at").eq("reminder_id", reminder_id).eq("user_id", user_id).maybe_single().execute()
        if not row or not row.data:
            raise HTTPException(status_code=404, detail="Recordatorio no encontrado")

        raw = str(row.data["scheduled_at"]).replace("Z", "+00:00")
        scheduled_at = datetime.fromisoformat(raw)
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)

        if (scheduled_at - now_utc) >= timedelta(hours=2):
            raise HTTPException(
                status_code=422,
                detail="No puedes marcar este medicamento como tomado hasta que falten menos de 2 horas para la toma.",
            )

        now = now_utc.isoformat()
        await db.table("reminders").update({"taken": True, "taken_at": now}).eq("reminder_id", reminder_id).eq("user_id", user_id).execute()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}
