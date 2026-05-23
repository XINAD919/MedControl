from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.db import get_user_notifications
from deps import CurrentUser, get_current_user

router = APIRouter()


class NotificationResponse(BaseModel):
    id: str
    reminder_id: str
    channel: str
    notify_id: str
    status: str
    fired_at: Optional[str]
    completed_at: Optional[str]
    failed_at: Optional[str]
    error_message: Optional[str]
    created_at: str
    updated_at: str
    medication: Optional[str]
    scheduled_at: Optional[str]


@router.get("/users/{user_id}/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    user_id: str,
    status: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    if user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="No autorizado")
    try:
        rows = await get_user_notifications(user_id, status=status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    def fmt(dt) -> Optional[str]:
        if dt is None:
            return None
        if isinstance(dt, datetime):
            return dt.isoformat()
        return str(dt)

    return [
        NotificationResponse(
            id=str(r["id"]),
            reminder_id=r["reminder_id"],
            channel=str(r["channel"]),
            notify_id=r["notify_id"],
            status=str(r["status"]),
            fired_at=fmt(r.get("fired_at")),
            completed_at=fmt(r.get("completed_at")),
            failed_at=fmt(r.get("failed_at")),
            error_message=r.get("error_message"),
            created_at=fmt(r["created_at"]),
            updated_at=fmt(r["updated_at"]),
            medication=(r.get("reminders") or {}).get("medication"),
            scheduled_at=fmt((r.get("reminders") or {}).get("scheduled_at")),
        )
        for r in rows
    ]
