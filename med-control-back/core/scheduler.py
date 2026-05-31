import asyncio
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from core.recurrence import calculate_next_occurrence

_LOOKAHEAD_SECONDS = 60

log = structlog.get_logger()
scheduler = AsyncIOScheduler(timezone="UTC")


def _generate_next_reminder_id(user_id: str, next_dt: datetime) -> str:
    uid_prefix = user_id.replace("-", "")[:8]
    suffix = secrets.token_hex(6)
    return f"rem_{uid_prefix}_{suffix}"


async def check_due_reminders() -> None:
    from core.supabase_client import create_temp_client
    now = datetime.now(timezone.utc)
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
    scheduled_at = datetime.fromisoformat(reminder["scheduled_at"].replace("Z", "+00:00"))
    wait = (scheduled_at - datetime.now(timezone.utc)).total_seconds()
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
                    "metadata": notif.get("metadata") or {},
                }
                try:
                    await http.post(webhook_url, json=payload)
                    log.info("scheduler.n8n_triggered", channel=notif["channel"], reminder_id=reminder_id)
                except Exception as e:
                    log.error("scheduler.n8n_trigger_failed", channel=notif["channel"], error=str(e))
    else:
        log.warning("scheduler.n8n_not_configured", reminder_id=reminder_id)

    if reminder.get("is_recurring"):
        try:
            await _schedule_next(reminder, notifs)
        except Exception as e:
            log.error(
                "scheduler.schedule_next_failed",
                reminder_id=reminder_id,
                error=str(e),
            )

    await _update_status_bulk(reminder_id, "completed")


async def _schedule_next(reminder: dict, notifs: list[dict]) -> None:
    end_date_str = reminder.get("recurrence_end_date")
    end_date = (
        datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        if end_date_str else None
    )

    recurrence_days: list = []
    if reminder.get("recurrence_days"):
        try:
            recurrence_days = json.loads(reminder["recurrence_days"])
        except Exception:
            pass

    current_dt = datetime.fromisoformat(reminder["scheduled_at"].replace("Z", "+00:00"))
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

    new_reminder_id = _generate_next_reminder_id(reminder["user_id"], next_dt)

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

    from core.supabase_client import create_temp_client
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
    from core.supabase_client import create_temp_client
    client = await create_temp_client()
    try:
        await client.table("reminders").update({"status": status}).eq("reminder_id", reminder_id).execute()
        await client.table("reminder_notifications").update({"status": status}).eq("reminder_id", reminder_id).execute()
    finally:
        await client.aclose()


_MISSED_DOSE_WINDOW_MINUTES = 20


async def check_missed_doses() -> None:
    """Detecta dosis no tomadas 20 min después de su hora y alerta a los caregivers."""
    from core.supabase_client import create_temp_client
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=_MISSED_DOSE_WINDOW_MINUTES)

    client = await create_temp_client()
    try:
        # Recordatorios completados (disparados) hace >20 min sin marcar como tomados y no privados
        res = await (
            client.table("reminders")
            .select("reminder_id, user_id, medication, scheduled_at")
            .eq("status", "completed")
            .eq("taken", False)
            .eq("is_private", False)
            .lte("scheduled_at", cutoff.isoformat())
            .execute()
        )
        missed: list[dict] = res.data or []
        if not missed:
            return

        log.info("scheduler.missed_doses_found", count=len(missed))

        for reminder in missed:
            await _alert_caregivers_for_missed_dose(client, reminder)
    finally:
        await client.aclose()


async def _alert_caregivers_for_missed_dose(client, reminder: dict) -> None:
    patient_id = reminder["user_id"]
    reminder_id = reminder["reminder_id"]

    # Buscar caregivers vinculados al paciente
    res_caregivers = await (
        client.table("family_members")
        .select("caregiver_id")
        .eq("patient_id", patient_id)
        .execute()
    )
    caregiver_ids = [r["caregiver_id"] for r in (res_caregivers.data or [])]
    if not caregiver_ids:
        return

    # Nombre del paciente
    res_patient = await (
        client.table("users")
        .select("preferences")
        .eq("id", patient_id)
        .maybe_single()
        .execute()
    )
    patient_name = (
        (res_patient.data or {}).get("preferences", {}).get("name", "Tu familiar")
        if res_patient else "Tu familiar"
    )
    scheduled_str = reminder["scheduled_at"][:16].replace("T", " ")

    webhook_url = os.getenv("N8N_WEBHOOK_URL", "")

    async with httpx.AsyncClient(timeout=10) as http:
        for caregiver_id in caregiver_ids:
            # Comprobar si ya se envió esta alerta
            existing = await (
                client.table("caregiver_missed_dose_alerts")
                .select("id")
                .eq("reminder_id", reminder_id)
                .eq("caregiver_id", caregiver_id)
                .maybe_single()
                .execute()
            )
            if existing and existing.data:
                continue

            # Marcar como enviada ANTES de enviar (evitar re-envíos si n8n tarda)
            try:
                await client.table("caregiver_missed_dose_alerts").insert(
                    {"reminder_id": reminder_id, "caregiver_id": caregiver_id}
                ).execute()
            except Exception:
                continue  # UNIQUE violation: ya fue enviada

            # Obtener canales del caregiver
            res_channels = await (
                client.table("user_channels")
                .select("channel, notify_id, metadata")
                .eq("user_id", caregiver_id)
                .eq("verified", True)
                .eq("receive_reminders", True)
                .execute()
            )
            channels = res_channels.data or []

            if not webhook_url or not channels:
                log.warning("scheduler.caregiver_alert_no_webhook_or_channels", caregiver_id=caregiver_id)
                continue

            message = (
                f"⚠️ {patient_name} no ha marcado {reminder['medication']} "
                f"como tomado (programado a las {scheduled_str})."
            )
            for ch in channels:
                payload = {
                    "reminder_id": f"{reminder_id}_alert_{caregiver_id[:8]}",
                    "user_id": caregiver_id,
                    "medication": reminder["medication"],
                    "message": message,
                    "notes": "",
                    "channel": ch["channel"],
                    "notify_id": ch["notify_id"],
                    "scheduled_at": reminder["scheduled_at"],
                    "metadata": ch.get("metadata") or {},
                    "alert_type": "missed_dose_caregiver",
                }
                try:
                    await http.post(webhook_url, json=payload)
                    log.info("scheduler.caregiver_alert_sent", caregiver_id=caregiver_id, channel=ch["channel"])
                except Exception as e:
                    log.error("scheduler.caregiver_alert_failed", caregiver_id=caregiver_id, error=str(e))


def start_scheduler() -> None:
    scheduler.add_job(check_due_reminders, "interval", seconds=60, id="due_reminders")
    scheduler.add_job(check_missed_doses, "interval", seconds=120, id="missed_doses")
    scheduler.start()
    log.info("scheduler.started", interval_seconds=60)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")
