import asyncio
import concurrent.futures
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

_TZ = ZoneInfo(os.getenv("TIMEZONE", "UTC"))


def _generate_reminder_id(user_id: str) -> str:
    uid_prefix = user_id.replace("-", "")[:8]
    suffix = secrets.token_hex(6)
    return f"rem_{uid_prefix}_{suffix}"


# ── Async helpers for new tools ────────────────────────────────────────────


async def _search_chunks(user_id: str, query_embedding: list[float]) -> list[dict]:
    from core.supabase_client import create_temp_client

    client = await create_temp_client()
    try:
        res = await client.rpc(
            "search_similar_chunks",
            {
                "p_user_id": user_id,
                "p_embedding": query_embedding,
                "p_top_k": 3,
            },
        ).execute()
        return [
            {
                "filename": row["filename"],
                "chunk_text": row["chunk_text"],
                "metadata": row["metadata"],
                "distance": float(row["distance"]),
            }
            for row in (res.data or [])
        ]
    finally:
        await client.aclose()


async def _fetch_reminders(
    user_id: str,
    status: Optional[str] = None,
    date: Optional[str] = None,
    medication: Optional[str] = None,
) -> list[dict]:
    from core.supabase_client import create_temp_client

    client = await create_temp_client()
    try:
        res = await client.rpc(
            "get_user_reminders_grouped",
            {
                "p_user_id": user_id,
                "p_status": status,
                "p_date": date,
                "p_medication": medication,
            },
        ).execute()
        return res.data or []
    finally:
        await client.aclose()


async def _delete_reminders(user_id: str, reminder_ids: list[str]) -> None:
    from core.supabase_client import create_temp_client

    client = await create_temp_client()
    try:
        await client.table("reminders").delete().eq("user_id", user_id).in_(
            "reminder_id", reminder_ids
        ).execute()
    finally:
        await client.aclose()


async def _fetch_notification_channels(user_id: str) -> list[dict]:
    """Cliente temporal — seguro para llamar desde cualquier thread/loop."""
    from core.supabase_client import create_temp_client

    client = await create_temp_client()
    try:
        res = await (
            client.table("user_channels")
            .select("channel, notify_id, metadata")
            .eq("user_id", user_id)
            .eq("receive_reminders", True)
            .order("is_primary", desc=True)
            .order("created_at")
            .execute()
        )
        return res.data or []
    finally:
        await client.aclose()


async def _insert_all_reminders_local(tasks: list[dict]) -> None:
    """Inserta los recordatorios directamente en Supabase sin pasar por n8n."""
    from core.supabase_client import create_temp_client

    client = await create_temp_client()
    try:
        session_cache: dict[str, str | None] = {}
        reminder_rows = []
        notification_rows = []

        for p in tasks:
            sid_str = p["session_id"]
            if sid_str not in session_cache:
                if sid_str and sid_str != "unknown":
                    res = (
                        await client.table("sessions")
                        .select("id")
                        .eq("session_id", sid_str)
                        .execute()
                    )
                    session_cache[sid_str] = res.data[0]["id"] if res.data else None
                else:
                    session_cache[sid_str] = None
            session_uuid = session_cache[sid_str]

            reminder_rows.append(
                {
                    "reminder_id": p["reminder_id"],
                    "user_id": p["user_id"],
                    "session_id": session_uuid,
                    "medication": p["medication"],
                    "schedule": p["schedule"],
                    "message": p["message"],
                    "notes": p["notes"] or None,
                    "scheduled_at": p["scheduled_at"],
                    "status": "scheduled",
                    "is_recurring": p["is_recurring"],
                    "recurrence_type": p["recurrence_type"] or None,
                    "recurrence_days": (
                        json.dumps(p["recurrence_days"])
                        if p["recurrence_days"]
                        else None
                    ),
                    "recurrence_interval": p["recurrence_interval"] or 1,
                    "recurrence_end_date": p["recurrence_end_date"] or None,
                }
            )

            for ch in p["channels"]:
                notification_rows.append(
                    {
                        "reminder_id": p["reminder_id"],
                        "user_id": p["user_id"],
                        "channel": ch["channel"],
                        "notify_id": ch["notify_id"],
                        "status": "scheduled",
                        "metadata": ch.get("metadata") or {},
                    }
                )

        if reminder_rows:
            await client.table("reminders").upsert(
                reminder_rows, on_conflict="reminder_id"
            ).execute()
        if notification_rows:
            await client.table("reminder_notifications").upsert(
                notification_rows, on_conflict="reminder_id,channel"
            ).execute()
    finally:
        await client.aclose()


async def _update_user_reminder(
    reminder_id: str,
    user_id: Optional[str] = None,
    medication: Optional[str] = None,
    schedule: Optional[str] = None,
    message: Optional[str] = None,
    notes: Optional[str] = None,
    recurrence_type: Optional[str] = None,
    recurrence_days: Optional[list[int]] = None,
    recurrence_interval: Optional[int] = None,
    recurrence_end_date: Optional[str] = None,
    scheduled_date: Optional[str] = None,
) -> None:

    updates = {}

    # fix: is not None en todos para permitir limpiar campos con ""
    if medication is not None:
        updates["medication"] = medication
    if message is not None:
        updates["message"] = message
    if notes is not None:
        updates["notes"] = notes
    if recurrence_type is not None:
        updates["recurrence_type"] = recurrence_type
        updates["is_recurring"] = True
    if recurrence_days is not None:
        updates["recurrence_days"] = recurrence_days  # fix: list directo, no json.dumps
    if recurrence_interval is not None:
        updates["recurrence_interval"] = recurrence_interval
    if recurrence_end_date is not None:
        updates["recurrence_end_date"] = recurrence_end_date

    from core.supabase_client import create_temp_client

    client = await create_temp_client()

    try:
        if schedule or scheduled_date:
            # Siempre fetch el reminder existente para preservar la parte no cambiada
            res = await (
                client.table("reminders")
                .select("scheduled_at")
                .eq("user_id", user_id)
                .eq("reminder_id", reminder_id)
                .maybe_single()
                .execute()
            )

            # fix: error explícito, nunca fallback silencioso a fecha/hora actual
            if not res or not res.data:
                raise ValueError(
                    f"No se encontró el recordatorio '{reminder_id}'. "
                    "Verifica que el reminder_id sea correcto."
                )

            existing_sat_str = res.data.get("scheduled_at")
            if not existing_sat_str:
                raise ValueError(
                    f"El recordatorio '{reminder_id}' no tiene scheduled_at registrado."
                )

            # fix: soporte para timestamps con y sin timezone (registros legacy)
            try:
                existing_dt = datetime.fromisoformat(
                    existing_sat_str.replace("Z", "+00:00")
                ).astimezone(_TZ)
            except Exception:
                raise ValueError(
                    f"No se pudo parsear la fecha existente: '{existing_sat_str}'"
                )

            # Determinar fecha: nueva o existente
            if scheduled_date:
                sd = datetime.strptime(scheduled_date, "%Y-%m-%d")
                yr, mo, dy = sd.year, sd.month, sd.day
            else:
                yr, mo, dy = existing_dt.year, existing_dt.month, existing_dt.day

            # Determinar hora: nueva o existente
            if schedule:
                t = datetime.strptime(schedule.strip(), "%H:%M")
                hr, mn = t.hour, t.minute
            else:
                hr, mn = existing_dt.hour, existing_dt.minute

            _UTC = ZoneInfo("UTC")
            now = datetime.now(_TZ)
            target = datetime(yr, mo, dy, hr, mn, 0, tzinfo=_TZ)

            # Ajustar a mañana solo si no hay fecha explícita y la hora ya pasó hoy
            if not scheduled_date and target <= now:
                target += timedelta(days=1)

            updates["scheduled_at"] = target.astimezone(_UTC).isoformat()
            updates["status"] = (
                "scheduled"  # fix: resetear status al cambiar fecha/hora
            )

        if not updates:
            return

        await (
            client.table("reminders")
            .update(updates)
            .eq("user_id", user_id)
            .eq("reminder_id", reminder_id)
            .execute()
        )

    finally:
        await client.aclose()


def get_current_datetime() -> str:
    return datetime.now(_TZ).strftime("%A, %d de %B de %Y, %H:%M:%S")


def create_reminder(
    medication: str,
    schedule: str,
    message: str,
    notes: str = "",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    recurrence_type: Optional[str] = None,
    recurrence_days: Optional[list[int]] = None,
    recurrence_interval: Optional[int] = None,
    recurrence_end_date: Optional[str] = None,
    scheduled_date: Optional[str] = None,
) -> str:
    if not user_id:
        return "Error: user_id no proporcionado. No se puede crear recordatorio."

    _VALID_RECURRENCE = {
        "daily",
        "weekdays",
        "weekends",
        "weekly",
        "monthly",
        "interval_days",
        "interval_hours",
    }

    # Validar scheduled_date
    if scheduled_date:
        try:
            sd = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            if sd < datetime.now(_TZ).date():
                return f"Error: scheduled_date '{scheduled_date}' es una fecha pasada."
        except ValueError:
            return f"Error: scheduled_date '{scheduled_date}' debe tener formato YYYY-MM-DD."

    # Validar recurrence
    if recurrence_type is not None:
        if recurrence_type not in _VALID_RECURRENCE:
            return (
                f"Error: recurrence_type '{recurrence_type}' no válido. "
                f"Valores aceptados: {', '.join(sorted(_VALID_RECURRENCE))}"
            )
        if not recurrence_end_date:
            return (
                "Error: recurrence_end_date es requerido cuando se especifica recurrence_type. "
                "Formato: YYYY-MM-DD."
            )
        try:
            datetime.strptime(recurrence_end_date, "%Y-%m-%d")
        except ValueError:
            return f"Error: recurrence_end_date '{recurrence_end_date}' debe tener formato YYYY-MM-DD."

    if recurrence_type == "weekly" and not recurrence_days:
        return "Error: recurrence_days es requerido para recurrence_type='weekly'. Ejemplo: [1, 3, 5]"

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            db_channels = executor.submit(
                asyncio.run, _fetch_notification_channels(user_id)
            ).result(timeout=10)
    except Exception as e:
        return f"Error al obtener canales de notificación: {e}"

    webpush_entry = {"channel": "webpush", "notify_id": user_id, "metadata": {}}
    channels_to_notify = [webpush_entry] + [
        ch for ch in db_channels if ch["channel"] != "webpush"
    ]

    schedule_times = [t.strip() for t in schedule.split(",")]
    errors: list[str] = []
    sent_times: list[str] = []
    tasks: list[dict] = []

    channels_array = [
        {
            "channel": ch["channel"],
            "notify_id": ch["notify_id"],
            "metadata": ch.get("metadata") or {},
            "discord_webhook_url": (
                ch.get("metadata", {}).get("webhook_url", "")
                if ch["channel"] == "discord"
                else ""
            ),
            "onesignal_app_id": (
                os.getenv("ONESIGNAL_APP_ID", "") if ch["channel"] == "webpush" else ""
            ),
        }
        for ch in channels_to_notify
    ]
    primary = channels_to_notify[0]

    now = datetime.now(_TZ)
    _UTC = ZoneInfo("UTC")

    for time_str in schedule_times:
        try:
            target_time = datetime.strptime(time_str, "%H:%M")
            if scheduled_date:
                date_obj = datetime.strptime(scheduled_date, "%Y-%m-%d")
                target = datetime(
                    date_obj.year,
                    date_obj.month,
                    date_obj.day,
                    target_time.hour,
                    target_time.minute,
                    0,
                    tzinfo=_TZ,
                )
            else:
                target = now.replace(
                    hour=target_time.hour,
                    minute=target_time.minute,
                    second=0,
                    microsecond=0,
                    tzinfo=_TZ,
                )
                if target <= now:
                    target += timedelta(days=1)
            target_utc = target.astimezone(_UTC)
        except ValueError:
            errors.append(f"Horario '{time_str}': formato inválido (se esperaba HH:MM)")
            continue

        reminder_id = _generate_reminder_id(user_id)

        tasks.append(
            {
                "user_id": user_id,
                "session_id": session_id or "unknown",
                "reminder_id": reminder_id,
                "medication": medication,
                "schedule": time_str,
                "message": message,
                "notes": notes,
                "channel": primary["channel"],
                "notify_id": primary["notify_id"],
                "channels": channels_array,
                # fix: eliminado delay_minutes (dead field con scheduler Opción B)
                "scheduled_at": target_utc.isoformat(),
                "created_at": now.astimezone(_UTC).isoformat(),
                "is_recurring": recurrence_type is not None,
                "recurrence_type": recurrence_type or "",
                "recurrence_days": recurrence_days or [],
                # fix: solo enviar recurrence_interval para tipos que lo usan
                "recurrence_interval": (
                    recurrence_interval
                    if recurrence_type in ("interval_days", "interval_hours")
                    else None
                ),
                "recurrence_end_date": recurrence_end_date or "",
            }
        )

    if tasks:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                ex.submit(asyncio.run, _insert_all_reminders_local(tasks)).result(
                    timeout=15
                )
            sent_times = [p["schedule"] for p in tasks]
        except Exception as e:
            errors.append(str(e))

    if not sent_times:
        return (
            "Error al crear recordatorio en la base de datos. "
            f"Detalles: {'; '.join(errors)}"
        )

    try:
        first_time = sent_times[0]
        t = datetime.strptime(first_time, "%H:%M")
        if scheduled_date:
            sd = datetime.strptime(scheduled_date, "%Y-%m-%d")
            t_target = datetime(
                sd.year, sd.month, sd.day, t.hour, t.minute, 0, tzinfo=_TZ
            )
        else:
            t_target = now.replace(
                hour=t.hour, minute=t.minute, second=0, microsecond=0, tzinfo=_TZ
            )
            if t_target <= now:
                t_target += timedelta(days=1)
        fecha_base = t_target.strftime("%d/%m/%Y")
    except ValueError:
        fecha_base = scheduled_date or "hoy"

    canal_labels = ", ".join(
        sorted({ch["channel"].title() for p in tasks for ch in p["channels"]})
    )
    recurrence_info = (
        f"\nRecurrencia: {recurrence_type} hasta {recurrence_end_date}"
        if recurrence_type
        else ""
    )

    result = (
        f"Recordatorio guardado exitosamente.\n\n"
        f"Medicamento: {medication}\n"
        f"Fecha: {fecha_base}\n"
        f"Horarios creados: {', '.join(sent_times)}\n"
        f"Canales: {canal_labels}"
        f"{recurrence_info}"
    )
    if errors:
        result += f"\n\nHorarios fallidos: {'; '.join(errors)}"
    return result


def list_reminders(
    status: Optional[str] = None,
    date: Optional[str] = None,
    medication: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """
    Obtiene los recordatorios del usuario.
    Args:
        user_id:  ID del usuario (inyectado automáticamente).
        status: Estado del recordatorio (scheduled, completed, firing, failed). Por defecto 'all'.
        date: Fecha del recordatorio en formato YYYY-MM-DD. Por defecto 'all'.
        medication: Nombre del medicamento. Por defecto 'all'.
    """

    if not user_id:
        return (
            "Error: user_id no proporcionado. No se pueden obtener los recordatorios."
        )

    if status and status.lower() in ("all", "todos", "todas"):
        status = None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            reminders = executor.submit(
                asyncio.run, _fetch_reminders(user_id, status, date, medication)
            ).result(timeout=10)
    except Exception as e:
        return f"Error al obtener recordatorios: {e}"

    if not reminders:
        return "No se encontraron recordatorios."

    lines = []
    for r in reminders:
        canales = ", ".join(ch.title() for ch in (r.get("channels") or []))
        lines.append(
            f"ID: {r['reminder_id']}\n"
            f"Medicamento: {r['medication']}\n"
            f"Programado para: {r['scheduled_at']}\n"
            f"Estado: {r['status']}\n"
            f"Canales: {canales}\n"
        )

    return "\n".join(lines)


def delete_reminders(
    reminder_ids: list[str],
    user_id: Optional[str] = None,
) -> str:
    """
    Elimina los recordatorios suministrados por el usuario.
    Args:
        user_id:  ID del usuario (inyectado automáticamente).
        reminder_ids: Lista de IDs de los recordatorios a eliminar.
    """

    if not user_id:
        return "Error: user_id no proporcionado. No se puede eliminar recordatorio."

    if not reminder_ids:
        return (
            "Error: reminder_ids no proporcionado. No se puede eliminar recordatorio."
        )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(
                asyncio.run, _delete_reminders(user_id, reminder_ids)
            ).result(timeout=10)
    except Exception as e:
        return f"Error al eliminar recordatorio: {e}"

    ids_str = ", ".join(reminder_ids)

    return f"Recordatorios eliminados exitosamente: {ids_str}."


def search_knowledge_base(
    query: str,
    user_id: Optional[str] = None,
) -> str:
    """Search the user's prescription documents using semantic similarity."""
    if not user_id:
        return "Error: user_id no proporcionado. No se puede buscar en la base de conocimiento."

    try:
        from core.embeddings import _embed

        query_embedding = _embed(query)
    except Exception as e:
        return f"Error al generar embedding de búsqueda: {e}"

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            chunks = executor.submit(
                asyncio.run, _search_chunks(user_id, query_embedding)
            ).result(timeout=15)
    except Exception as e:
        return f"Error al buscar en base de conocimiento: {e}"

    if not chunks:
        return (
            "No se encontraron documentos médicos relevantes para esta consulta. "
            "El usuario aún no ha subido ninguna receta."
        )

    sections = []
    for c in chunks:
        sections.append(f"[{c['filename']}]\n{c['chunk_text']}")
    return "\n\n---\n\n".join(sections)


def web_search(query: str) -> str:
    """Search the web for medical information using Tavily."""
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return "Error: TAVILY_API_KEY no está configurado. La búsqueda web no está disponible."

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        results = client.search(
            query=query,
            search_depth="basic",
            max_results=3,
        )
        items = results.get("results", [])
        if not items:
            return "No se encontraron resultados relevantes para la búsqueda."

        sections = []
        for r in items:
            sections.append(f"**{r['title']}**\n{r['content']}\nFuente: {r['url']}")
        return "\n\n---\n\n".join(sections)
    except Exception as e:
        return f"Error en búsqueda web: {e}"


def update_reminder(
    reminder_id: Optional[str] = None,
    user_id: Optional[str] = None,
    medication: Optional[str] = None,
    schedule: Optional[str] = None,
    message: Optional[str] = None,
    notes: Optional[str] = None,
    recurrence_type: Optional[str] = None,
    recurrence_days: Optional[list[int]] = None,
    recurrence_interval: Optional[int] = None,
    recurrence_end_date: Optional[str] = None,
    scheduled_date: Optional[str] = None,
) -> str:

    if not user_id:
        return (
            "Error: user_id no proporcionado. No se puede actualizar el recordatorio."
        )

    if not reminder_id:
        return "Error: reminder_id no proporcionado. No se puede actualizar el recordatorio."

    if not any(
        f is not None
        for f in (
            medication,
            schedule,
            message,
            notes,
            recurrence_type,
            recurrence_days,
            recurrence_interval,
            recurrence_end_date,
            scheduled_date,
        )
    ):
        return (
            "Error: no se proporcionaron campos para actualizar. "
            "Campos aceptados: medication, schedule, scheduled_date, message, notes, "
            "recurrence_type, recurrence_days, recurrence_interval, recurrence_end_date."
        )

    _VALID_RECURRENCE = {
        "daily",
        "weekdays",
        "weekends",
        "weekly",
        "monthly",
        "interval_days",
        "interval_hours",
    }
    if recurrence_type is not None:
        if recurrence_type not in _VALID_RECURRENCE:
            return (
                f"Error: recurrence_type '{recurrence_type}' no válido. "
                f"Valores aceptados: {', '.join(sorted(_VALID_RECURRENCE))}"
            )
        if recurrence_type == "weekly" and not recurrence_days:
            return "Error: recurrence_days es requerido para recurrence_type='weekly'."

    if schedule:
        for time_str in schedule.split(","):
            try:
                datetime.strptime(time_str.strip(), "%H:%M")
            except ValueError:
                return (
                    f"Error: formato de horario inválido '{time_str.strip()}'. "
                    "Se esperaba HH:MM."
                )

    if scheduled_date:
        try:
            sd = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
            if sd < datetime.now(_TZ).date():
                return f"Error: scheduled_date '{scheduled_date}' es una fecha pasada."
        except ValueError:
            return f"Error: scheduled_date '{scheduled_date}' debe tener formato YYYY-MM-DD."

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(
                asyncio.run,
                _update_user_reminder(
                    reminder_id=reminder_id,
                    user_id=user_id,
                    medication=medication,
                    schedule=schedule,
                    message=message,
                    notes=notes,
                    recurrence_type=recurrence_type,
                    recurrence_days=recurrence_days,
                    recurrence_interval=recurrence_interval,
                    recurrence_end_date=recurrence_end_date,
                    scheduled_date=scheduled_date,
                ),
            ).result(timeout=10)
    except Exception as e:
        return f"Error al actualizar recordatorio: {e}"

    return "Recordatorio actualizado exitosamente."


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_datetime",
            "description": "Obtiene la fecha y hora actual del sistema.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": (
                "Crea un recordatorio de salud para el usuario o un familiar. "
                "Úsala para medicamentos, citas médicas, chequeos, análisis u otros eventos de salud. "
                "El recordatorio siempre se registra en la cuenta del usuario autenticado. "
                "Para recordatorios recurrentes, scheduled_date puede usarse como fecha de inicio del ciclo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "medication": {
                        "type": "string",
                        "description": (
                            "Asunto del recordatorio: nombre del medicamento, tipo de cita "
                            "(ej. 'Cita cardiólogo - mamá'), u otro evento de salud."
                        ),
                    },
                    "schedule": {
                        "type": "string",
                        "description": (
                            "Hora(s) de disparo en formato HH:MM. "
                            "Para múltiples horarios separar con coma: '08:00, 14:00, 20:00'."
                        ),
                    },
                    "message": {
                        "type": "string",
                        "description": (
                            "Mensaje personalizado y empático que se enviará al usuario "
                            "cuando llegue la hora del recordatorio."
                        ),
                    },
                    "notes": {
                        "type": "string",
                        "description": (
                            "Instrucciones especiales opcionales, ej. 'tomar con agua', 'antes de comer'."
                        ),
                    },
                    "recurrence_type": {
                        "type": "string",
                        "description": (
                            "Patrón de recurrencia. "
                            "Valores aceptados ÚNICAMENTE: "
                            "'daily' (cada día), "
                            "'weekdays' (lunes a viernes), "
                            "'weekends' (sábado y domingo), "
                            "'weekly' (días específicos, requiere recurrence_days), "
                            "'monthly' (mismo día cada mes), "
                            "'interval_days' (cada N días, requiere recurrence_interval), "
                            "'interval_hours' (cada N horas, requiere recurrence_interval). "
                            "NO uses ningún otro valor — causará error. "
                            "Cuando se especifica, recurrence_end_date es obligatorio."
                        ),
                    },
                    "recurrence_days": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "Solo para recurrence_type='weekly'. "
                            "Días de la semana como enteros (0=Dom, 1=Lun, 2=Mar, 3=Mié, 4=Jue, 5=Vie, 6=Sáb). "
                            "Ejemplo lun/mié/vie: [1, 3, 5]."
                        ),
                    },
                    "recurrence_interval": {
                        "type": "integer",
                        "description": (
                            "Solo para recurrence_type 'interval_days' o 'interval_hours'. "
                            "Número de días u horas entre cada repetición. Debe ser >= 1. "
                            "Ejemplo: cada 8 horas → recurrence_type='interval_hours', recurrence_interval=8."
                        ),
                    },
                    "recurrence_end_date": {
                        "type": "string",
                        "description": (
                            "Fecha de fin de la recurrencia en formato YYYY-MM-DD. "
                            "Obligatorio cuando se especifica recurrence_type."
                        ),
                    },
                    "scheduled_date": {
                        "type": "string",
                        "description": (
                            "Fecha en formato YYYY-MM-DD. Usos: "
                            "Sin recurrence_type: fecha única de disparo "
                            "(ej. 'el 20 de junio', 'el próximo martes'). "
                            "Con recurrence_type: fecha de inicio del ciclo recurrente. "
                            "No puede ser una fecha pasada."
                        ),
                    },
                },
                "required": ["medication", "schedule", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": (
                "Obtén la lista de recordatorios programados y su estado actual. "
                "Estos datos vienen directamente de la base de datos. "
                "Úsala cuando el usuario pida listar o pregunte cuáles son sus recordatorios."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": (
                            "Campo opcional para filtrar por estado. "
                            "Valores válidos: scheduled, firing, completed, failed. "
                            "Omitir para obtener todos."
                        ),
                    },
                    "date": {
                        "type": "string",
                        "description": "Campo opcional para filtrar por fecha (YYYY-MM-DD).",
                    },
                    "medication": {
                        "type": "string",
                        "description": "Campo opcional para filtrar por medicamento.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminders",
            "description": (
                "Elimina uno o más recordatorios del usuario. "
                "Úsala cuando el usuario pida eliminar recordatorios. "
                "SIEMPRE pide confirmación antes de ejecutar. "
                "Si el usuario no especifica cuáles eliminar, "
                "usa list_reminders primero para mostrar los disponibles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista de IDs de los recordatorios a eliminar.",
                    },
                },
                "required": ["reminder_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Busca en los documentos médicos del usuario (recetas, planes de medicación) "
                "usando búsqueda semántica. Úsala cuando el usuario pregunte sobre sus medicamentos, "
                "dosis o información de sus recetas subidas. "
                "No uses esta herramienta para buscar información médica general."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Pregunta o términos de búsqueda sobre los documentos del usuario.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Busca información médica actualizada en internet. "
                "Úsala cuando el usuario pregunte sobre medicamentos, efectos secundarios, "
                "interacciones o condiciones médicas y no haya información en sus documentos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Términos de búsqueda médica en español o inglés.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_reminder",
            "description": (
                "Actualiza uno o más campos de un recordatorio existente. "
                "Úsala cuando el usuario pida modificar la hora, medicamento, mensaje, notas, "
                "fecha o recurrencia de un recordatorio ya creado. "
                "Llama list_reminders primero para obtener el reminder_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {
                        "type": "string",
                        "description": (
                            "ID del recordatorio a actualizar. "
                            "Debe obtenerse de list_reminders — nunca inventes ni adivines este valor."
                        ),
                    },
                    "medication": {
                        "type": "string",
                        "description": (
                            "Nuevo asunto del recordatorio: nombre del medicamento, "
                            "tipo de cita u otro evento de salud."
                        ),
                    },
                    "schedule": {
                        "type": "string",
                        "description": (
                            "Nueva(s) hora(s) en formato HH:MM. "
                            "Para múltiples horarios separar con coma: '08:00, 14:00, 20:00'."
                        ),
                    },
                    "message": {
                        "type": "string",
                        "description": "Nuevo mensaje personalizado y empático para la notificación.",
                    },
                    "notes": {
                        "type": "string",
                        "description": (
                            "Nuevas instrucciones especiales, ej. 'con agua', 'antes de comer'. "
                            "Pasar string vacío para limpiar el campo."
                        ),
                    },
                    "recurrence_type": {
                        "type": "string",
                        "description": (
                            "Nuevo patrón de recurrencia. "
                            "Valores aceptados ÚNICAMENTE: "
                            "'daily' (cada día), "
                            "'weekdays' (lunes a viernes), "
                            "'weekends' (sábado y domingo), "
                            "'weekly' (días específicos, requiere recurrence_days), "
                            "'monthly' (mismo día cada mes), "
                            "'interval_days' (cada N días, requiere recurrence_interval), "
                            "'interval_hours' (cada N horas, requiere recurrence_interval). "
                            "NO uses ningún otro valor — causará error. "
                            "Cuando se especifica, recurrence_end_date es obligatorio."
                        ),
                    },
                    "recurrence_days": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "Solo para recurrence_type='weekly'. "
                            "Enteros: 0=Dom, 1=Lun, 2=Mar, 3=Mié, 4=Jue, 5=Vie, 6=Sáb. "
                            "Ejemplo lun/mié/vie: [1, 3, 5]."
                        ),
                    },
                    "recurrence_interval": {
                        "type": "integer",
                        "description": (
                            "Solo para 'interval_days' o 'interval_hours'. "
                            "Número de días u horas entre repeticiones. Debe ser >= 1."
                        ),
                    },
                    "recurrence_end_date": {
                        "type": "string",
                        "description": (
                            "Nueva fecha de fin de recurrencia en formato YYYY-MM-DD. "
                            "Obligatorio cuando se especifica recurrence_type."
                        ),
                    },
                    "scheduled_date": {
                        "type": "string",
                        "description": (
                            "Nueva fecha en formato YYYY-MM-DD. "
                            "Sin recurrence_type: nueva fecha única de disparo. "
                            "Con recurrence_type: nueva fecha de inicio del ciclo recurrente. "
                            "No puede ser una fecha pasada."
                        ),
                    },
                },
                "required": ["reminder_id"],
            },
        },
    },
]

_REGISTRY = {
    "get_current_datetime": get_current_datetime,
    "create_reminder": create_reminder,
    "list_reminders": list_reminders,
    "delete_reminders": delete_reminders,
    "update_reminder": update_reminder,
    "search_knowledge_base": search_knowledge_base,
    "web_search": web_search,
}


def dispatch(name: str, args: dict) -> str:
    import inspect

    fn = _REGISTRY.get(name)
    if fn is None:
        return f"Tool '{name}' not found."
    sig = inspect.signature(fn)
    valid = sig.parameters
    filtered = {k: v for k, v in args.items() if k in valid}
    missing = [
        p
        for p, param in sig.parameters.items()
        if param.default is inspect.Parameter.empty and p not in filtered
    ]
    if missing:
        return (
            f"Error: {name} requires argument(s) that were not provided: {', '.join(missing)}. "
            "Call list_reminders first to obtain the reminder_id, then retry."
        )
    return fn(**filtered)
