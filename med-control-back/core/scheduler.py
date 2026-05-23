import asyncio
import json
import os
from datetime import datetime, timedelta

import httpx
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.recurrence import calculate_next_occurrence
from core.supabase_client import create_temp_client

_LOOKAHEAD_SECONDS = 60

log = structlog.get_logger()
scheduler = AsyncIOScheduler(timezone="UTC")


async def check_due_reminders() -> None:
    now = datetime.utcnow()
    lookahead = now + timedelta(seconds=_LOOKAHEAD_SECONDS)
    client = await create_temp_client()
    try:
        res_reminders = await (
            client.table("reminders")
            .select("*")
            .eq("status", "scheduled")
            .lte("scheduled_at", lookahead.isoformat())
            .execute()
        )
        due_reminders: list[dict] = res_reminders.data or []

        if not due_reminders:
            return

        reminder_ids = [r["reminder_id"] for r in due_reminders]
        res_notifs = await (
            client.table("reminder_notifications")
            .select("*")
            .in_("reminder_id", reminder_ids)
            .execute()
        )
        notifs_by_reminder: dict[str, list[dict]] = {}
        for n in res_notifs.data or []:
            notifs_by_reminder.setdefault(n["reminder_id"], []).append(n)
    finally:
        await client.aclose()

    webhook_url = os.getenv("N8N_WEBHOOK_URL", "")
    log.info("scheduler.due_reminders", count=len(due_reminders))

    # Marcar como firing antes de los sleeps para evitar re-pickup en el próximo tick
    for reminder in due_reminders:
        await _update_status_bulk(reminder["reminder_id"], "firing")

    tasks = [
        asyncio.create_task(
            _process_group(reminder, notifs_by_reminder.get(reminder["reminder_id"], []), webhook_url)
        )
        for reminder in due_reminders
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _process_group(reminder: dict, notifs: list[dict], webhook_url: str) -> None:
    scheduled_at = datetime.fromisoformat(reminder["scheduled_at"].replace("Z", ""))
    wait = (scheduled_at - datetime.utcnow()).total_seconds()
    if wait > 0:
        await asyncio.sleep(wait)

    reminder_id = reminder["reminder_id"]

    if webhook_url:
        async with httpx.AsyncClient(timeout=10) as http:
            for notif in notifs:
                payload = {
                    "reminder_id": reminder_id,
                    "user_id": reminder["user_id"],
                    "medication": reminder["medication"],
                    "message": reminder["message"],
                    "notes": reminder.get("notes") or "",
                    "channel": notif["channel"],
                    "notify_id": notif["notify_id"],
                    "scheduled_at": reminder["scheduled_at"],
                }
                try:
                    await http.post(webhook_url, json=payload)
                    log.info("scheduler.n8n_triggered", channel=notif["channel"], reminder_id=reminder_id)
                except Exception as e:
                    log.error("scheduler.n8n_trigger_failed", channel=notif["channel"], error=str(e))
    else:
        log.warning("scheduler.n8n_not_configured", reminder_id=reminder_id)

    if reminder.get("is_recurring"):
        await _schedule_next(reminder, notifs)

    await _update_status_bulk(reminder_id, "completed")


async def _schedule_next(reminder: dict, notifs: list[dict]) -> None:
    end_date_str = reminder.get("recurrence_end_date")
    end_date = (
        datetime.fromisoformat(end_date_str.replace("Z", ""))
        if end_date_str else None
    )

    recurrence_days: list = []
    if reminder.get("recurrence_days"):
        try:
            recurrence_days = json.loads(reminder["recurrence_days"])
        except Exception:
            pass

    current_dt = datetime.fromisoformat(reminder["scheduled_at"].replace("Z", ""))
    next_dt = calculate_next_occurrence(
        current=current_dt,
        recurrence_type=reminder["recurrence_type"],
        recurrence_days=recurrence_days,
        recurrence_interval=reminder.get("recurrence_interval") or 1,
        recurrence_end_date=end_date,
    )

    if not next_dt:
        log.info("scheduler.recurrence_ended", reminder_id=reminder["reminder_id"])
        return

    uid = reminder["user_id"].replace("-", "")[:8]
    new_reminder_id = f"rem_{uid}_{int(next_dt.timestamp())}"

    new_reminder = {
        "reminder_id": new_reminder_id,
        "user_id": reminder["user_id"],
        "session_id": reminder.get("session_id"),
        "medication": reminder["medication"],
        "schedule": reminder["schedule"],
        "message": reminder["message"],
        "notes": reminder.get("notes"),
        "scheduled_at": next_dt.isoformat(),
        "status": "scheduled",
        "is_recurring": True,
        "recurrence_type": reminder["recurrence_type"],
        "recurrence_days": reminder.get("recurrence_days"),
        "recurrence_interval": reminder.get("recurrence_interval") or 1,
        "recurrence_end_date": reminder.get("recurrence_end_date"),
    }

    new_notifs = [
        {
            "reminder_id": new_reminder_id,
            "user_id": notif["user_id"],
            "channel": notif["channel"],
            "notify_id": notif["notify_id"],
            "status": "scheduled",
        }
        for notif in notifs
    ]

    client = await create_temp_client()
    try:
        await client.table("reminders").upsert([new_reminder], on_conflict="reminder_id").execute()
        if new_notifs:
            await client.table("reminder_notifications").upsert(
                new_notifs, on_conflict="reminder_id,channel"
            ).execute()
        log.info("scheduler.next_occurrence_inserted", new_reminder_id=new_reminder_id, scheduled_at=next_dt.isoformat())
    finally:
        await client.aclose()


async def _update_status_bulk(reminder_id: str, status: str) -> None:
    client = await create_temp_client()
    try:
        await client.table("reminders").update({"status": status}).eq("reminder_id", reminder_id).execute()
        await client.table("reminder_notifications").update({"status": status}).eq("reminder_id", reminder_id).execute()
    finally:
        await client.aclose()


def start_scheduler() -> None:
    scheduler.add_job(check_due_reminders, "interval", seconds=60, id="due_reminders")
    scheduler.start()
    log.info("scheduler.started", interval_seconds=60)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
