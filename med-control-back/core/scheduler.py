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
        res = await (
            client.table("reminders")
            .select("*")
            .eq("status", "scheduled")
            .lte("scheduled_at", lookahead.isoformat())
            .execute()
        )
        rows = res.data or []
    finally:
        await client.aclose()

    if not rows:
        return

    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["reminder_id"], []).append(row)

    webhook_url = os.getenv("N8N_WEBHOOK_URL", "")
    log.info("scheduler.due_reminders", count=len(rows), groups=len(groups))

    # Marcar todos como firing antes de los sleeps para evitar re-pickup en el próximo tick
    for reminder_id in groups:
        await _update_status_bulk(reminder_id, "firing")

    # Procesar cada grupo en paralelo — cada uno espera hasta su scheduled_at exacto
    tasks = [
        asyncio.create_task(_process_group(reminder_id, group_rows, webhook_url))
        for reminder_id, group_rows in groups.items()
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _process_group(reminder_id: str, rows: list[dict], webhook_url: str) -> None:
    # Esperar hasta el momento exacto programado
    scheduled_at = datetime.fromisoformat(rows[0]["scheduled_at"].replace("Z", ""))
    wait = (scheduled_at - datetime.utcnow()).total_seconds()
    if wait > 0:
        await asyncio.sleep(wait)

    if webhook_url:
        async with httpx.AsyncClient(timeout=10) as http:
            for row in rows:
                payload = {
                    "reminder_id": row["reminder_id"],
                    "user_id": row["user_id"],
                    "medication": row["medication"],
                    "message": row["message"],
                    "notes": row.get("notes") or "",
                    "channel": row["channel"],
                    "notify_id": row["notify_id"],
                    "scheduled_at": row["scheduled_at"],
                }
                try:
                    await http.post(webhook_url, json=payload)
                    log.info("scheduler.n8n_triggered", channel=row["channel"], reminder_id=reminder_id)
                except Exception as e:
                    log.error("scheduler.n8n_trigger_failed", channel=row["channel"], error=str(e))
    else:
        log.warning("scheduler.n8n_not_configured", reminder_id=reminder_id)

    first = rows[0]
    if first.get("is_recurring"):
        await _schedule_next(rows, first)

    await _update_status_bulk(reminder_id, "completed")


async def _schedule_next(rows: list[dict], template: dict) -> None:
    end_date_str = template.get("recurrence_end_date")
    end_date = (
        datetime.fromisoformat(end_date_str.replace("Z", ""))
        if end_date_str else None
    )

    recurrence_days: list = []
    if template.get("recurrence_days"):
        try:
            recurrence_days = json.loads(template["recurrence_days"])
        except Exception:
            pass

    current_dt = datetime.fromisoformat(template["scheduled_at"].replace("Z", ""))
    next_dt = calculate_next_occurrence(
        current=current_dt,
        recurrence_type=template["recurrence_type"],
        recurrence_days=recurrence_days,
        recurrence_interval=template.get("recurrence_interval") or 1,
        recurrence_end_date=end_date,
    )

    if not next_dt:
        log.info("scheduler.recurrence_ended", reminder_id=template["reminder_id"])
        return

    uid = template["user_id"].replace("-", "")[:8]
    new_reminder_id = f"rem_{uid}_{int(next_dt.timestamp())}"

    new_rows = [
        {
            "reminder_id": new_reminder_id,
            "user_id": row["user_id"],
            "session_id": row.get("session_id"),
            "medication": row["medication"],
            "schedule": row["schedule"],
            "message": row["message"],
            "notes": row.get("notes"),
            "channel": row["channel"],
            "notify_id": row["notify_id"],
            "scheduled_at": next_dt.isoformat(),
            "status": "scheduled",
            "is_recurring": True,
            "recurrence_type": row["recurrence_type"],
            "recurrence_days": row.get("recurrence_days"),
            "recurrence_interval": row.get("recurrence_interval") or 1,
            "recurrence_end_date": row.get("recurrence_end_date"),
        }
        for row in rows
    ]

    client = await create_temp_client()
    try:
        await client.table("reminders").upsert(new_rows, on_conflict="reminder_id,channel").execute()
        log.info("scheduler.next_occurrence_inserted", new_reminder_id=new_reminder_id, scheduled_at=next_dt.isoformat())
    finally:
        await client.aclose()


async def _update_status_bulk(reminder_id: str, status: str) -> None:
    client = await create_temp_client()
    try:
        await client.table("reminders").update({"status": status}).eq("reminder_id", reminder_id).execute()
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
