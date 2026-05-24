"""
Database access layer usando el Supabase Python SDK.
Mismas firmas públicas que la versión asyncpg; solo cambian los internos.

Nota: maybe_single().execute() devuelve None (no un objeto) cuando no hay fila.
Usar siempre el patrón: `if res and res.data` / `return res.data if res else None`.
"""

from typing import Optional

# pyright: ignore [reportMissingImports]
from dotenv import load_dotenv

from core.supabase_client import get_supabase

load_dotenv()


# ============================================================================
# Usuarios
# ============================================================================


async def get_user_by_username(username: str) -> Optional[dict]:
    client = get_supabase()
    res = await client.table("users").select("*").eq("username", username).maybe_single().execute()
    return res.data if res else None


async def get_user_by_email(email: str) -> Optional[dict]:
    client = get_supabase()
    res = await client.table("users").select("*").eq("email", email).maybe_single().execute()
    return res.data if res else None


async def get_user_by_id(user_id: str) -> Optional[dict]:
    client = get_supabase()
    res = await client.table("users").select("*").eq("id", user_id).maybe_single().execute()
    return res.data if res else None


async def create_user(username: str, email: Optional[str] = None, **kwargs) -> str:
    client = get_supabase()
    preferences = kwargs.get("preferences", {})
    res = await client.table("users").insert({
        "username": username,
        "email": email,
        "preferences": preferences,
    }).execute()
    return str(res.data[0]["id"])


# ============================================================================
# Canales de notificación
# ============================================================================


async def get_user_channels(user_id: str, verified_only: bool = True) -> list[dict]:
    client = get_supabase()
    q = (
        client.table("user_channels")
        .select("channel, notify_id, verified, is_primary, receive_reminders, metadata")
        .eq("user_id", user_id)
    )
    if verified_only:
        q = q.eq("verified", True)
    res = await q.order("is_primary", desc=True).order("created_at").execute()
    return res.data or []


async def upsert_user_channel(
    user_id: str,
    channel: str,
    notify_id: str,
    verified: bool = False,
    is_primary: bool = False,
    receive_reminders: bool = True,
    metadata: Optional[dict] = None,
) -> None:
    client = get_supabase()
    await client.table("user_channels").upsert(
        {
            "user_id": user_id,
            "channel": channel,
            "notify_id": notify_id,
            "verified": verified,
            "is_primary": is_primary,
            "receive_reminders": receive_reminders,
            "metadata": metadata or {},
        },
        on_conflict="user_id,channel",
    ).execute()


async def get_notification_channels(user_id: str) -> list[dict]:
    """Canales verificados con receive_reminders=True."""
    client = get_supabase()
    res = await (
        client.table("user_channels")
        .select("channel, notify_id, metadata")
        .eq("user_id", user_id)
        .eq("verified", True)
        .eq("receive_reminders", True)
        .order("is_primary", desc=True)
        .order("created_at")
        .execute()
    )
    return res.data or []


async def get_primary_channel(user_id: str) -> Optional[dict]:
    """Deprecated: usar get_notification_channels."""
    client = get_supabase()
    res = await (
        client.table("user_channels")
        .select("channel, notify_id, metadata")
        .eq("user_id", user_id)
        .eq("verified", True)
        .order("is_primary", desc=True)
        .order("created_at")
        .limit(1)
        .maybe_single()
        .execute()
    )
    return res.data if res else None


# ============================================================================
# Sesiones y mensajes
# ============================================================================


async def get_or_create_session(
    user_id: str, session_id: str, metadata: Optional[dict] = None
) -> str:
    client = get_supabase()
    res = await client.table("sessions").select("id").eq("session_id", session_id).maybe_single().execute()
    if res and res.data:
        await client.table("sessions").update({"last_message_at": "now()"}).eq("session_id", session_id).execute()
        return str(res.data["id"])

    res2 = await client.table("sessions").insert({
        "user_id": user_id,
        "session_id": session_id,
        "metadata": metadata or {},
        "last_message_at": "now()",
    }).execute()
    return str(res2.data[0]["id"])


async def load_messages(session_id: str) -> list[dict]:
    client = get_supabase()
    sess = await client.table("sessions").select("id").eq("session_id", session_id).maybe_single().execute()
    if not (sess and sess.data):
        return []

    session_uuid = sess.data["id"]
    res = await (
        client.table("messages")
        .select("role, content, tool_calls")
        .eq("session_id", session_uuid)
        .order("sequence_num")
        .execute()
    )
    messages = []
    for row in (res.data or []):
        msg = {"role": row["role"], "content": row["content"]}
        if row.get("tool_calls"):
            msg["tool_calls"] = row["tool_calls"]
        messages.append(msg)
    return messages


async def save_message(
    session_id: str, role: str, content: str, tool_calls: Optional[list] = None
) -> None:
    client = get_supabase()
    sess = await client.table("sessions").select("id").eq("session_id", session_id).maybe_single().execute()
    if not (sess and sess.data):
        raise ValueError(f"Session {session_id} not found")
    session_uuid = sess.data["id"]

    seq_res = await (
        client.table("messages")
        .select("sequence_num")
        .eq("session_id", session_uuid)
        .order("sequence_num", desc=True)
        .limit(1)
        .execute()
    )
    next_seq = (seq_res.data[0]["sequence_num"] + 1) if seq_res.data else 0

    await client.table("messages").insert({
        "session_id": session_uuid,
        "role": role,
        "content": content,
        "tool_calls": tool_calls,
        "sequence_num": next_seq,
    }).execute()

    await client.table("sessions").update({"last_message_at": "now()"}).eq("id", session_uuid).execute()


async def clear_session_messages(session_id: str) -> None:
    client = get_supabase()
    sess = await client.table("sessions").select("id").eq("session_id", session_id).maybe_single().execute()
    if sess and sess.data:
        await client.table("messages").delete().eq("session_id", sess.data["id"]).execute()


# ============================================================================
# Recordatorios
# ============================================================================


async def create_reminder(
    reminder_id: str,
    user_id: str,
    session_id: Optional[str],
    medication: str,
    schedule: str,
    message: str,
    notes: str,
    channels: list[dict],  # [{"channel": "telegram", "notify_id": "..."}]
    scheduled_at: str,
    metadata: Optional[dict] = None,
) -> str:
    client = get_supabase()
    session_uuid = None
    if session_id:
        sess = await client.table("sessions").select("id").eq("session_id", session_id).maybe_single().execute()
        if sess and sess.data:
            session_uuid = sess.data["id"]

    res = await client.table("reminders").insert({
        "reminder_id": reminder_id,
        "user_id": user_id,
        "session_id": session_uuid,
        "medication": medication,
        "schedule": schedule,
        "message": message,
        "notes": notes,
        "scheduled_at": scheduled_at,
        "metadata": metadata or {},
    }).execute()

    if channels:
        notif_rows = [
            {
                "reminder_id": reminder_id,
                "user_id": user_id,
                "channel": ch["channel"],
                "notify_id": ch["notify_id"],
                "status": "scheduled",
            }
            for ch in channels
        ]
        await client.table("reminder_notifications").upsert(
            notif_rows, on_conflict="reminder_id,channel"
        ).execute()

    return str(res.data[0]["id"])


async def update_reminder_status(
    reminder_id: str, status: str, error_message: Optional[str] = None
) -> None:
    client = get_supabase()
    await client.rpc("update_reminder_status", {
        "p_reminder_id": reminder_id,
        "p_status": status,
        "p_error_message": error_message,
    }).execute()


async def get_user_reminders(
    user_id: str,
    status: Optional[str] = None,
    date: Optional[str] = None,
    medication: Optional[str] = None,
) -> list[dict]:
    client = get_supabase()
    res = await client.rpc("get_user_reminders_grouped", {
        "p_user_id": user_id,
        "p_status": status,
        "p_date": date,
        "p_medication": medication,
    }).execute()
    return res.data or []


async def delete_user_reminders(user_id: str, reminder_ids: list[str]) -> None:
    client = get_supabase()
    await client.table("reminders").delete().eq("user_id", user_id).in_("reminder_id", reminder_ids).execute()


# ============================================================================
# Documentos (RAG)
# ============================================================================


async def create_document(
    user_id: str,
    filename: str,
    file_type: str,
    file_path: str,
    file_size: int,
    document_type: str = "other",
) -> str:
    client = get_supabase()
    res = await client.table("documents").insert({
        "user_id": user_id,
        "filename": filename,
        "file_type": file_type,
        "file_path": file_path,
        "file_size": file_size,
        "document_type": document_type,
    }).execute()
    return str(res.data[0]["id"])


async def update_document_processing(
    doc_id: str, extracted_text: str, chunk_count: int
) -> None:
    client = get_supabase()
    await client.table("documents").update({
        "extracted_text": extracted_text,
        "processed": True,
        "embeddings_generated": True,
        "chunk_count": chunk_count,
        "processed_at": "now()",
    }).eq("id", doc_id).execute()


async def save_document_embedding(
    document_id: str,
    user_id: str,
    chunk_text: str,
    chunk_index: int,
    embedding: list[float],
    metadata: Optional[dict] = None,
) -> None:
    client = get_supabase()
    await client.table("document_embeddings").insert({
        "document_id": document_id,
        "user_id": user_id,
        "chunk_text": chunk_text,
        "chunk_index": chunk_index,
        "embedding": embedding,
        "metadata": metadata or {},
    }).execute()


async def search_similar_chunks(
    user_id: str, query_embedding: list[float], top_k: int = 3
) -> list[dict]:
    client = get_supabase()
    res = await client.rpc("search_similar_chunks", {
        "p_user_id": user_id,
        "p_embedding": query_embedding,
        "p_top_k": top_k,
    }).execute()
    return [
        {
            "filename": row["filename"],
            "chunk_text": row["chunk_text"],
            "metadata": row["metadata"],
            "distance": float(row["distance"]),
        }
        for row in (res.data or [])
    ]


async def get_user_documents(user_id: str) -> list[dict]:
    client = get_supabase()
    res = await (
        client.table("documents")
        .select("id, filename, file_type, document_type, file_size, processed, chunk_count, uploaded_at")
        .eq("user_id", user_id)
        .order("uploaded_at", desc=True)
        .execute()
    )
    return res.data or []


async def get_document_by_id(user_id: str, doc_id: str) -> dict | None:
    client = get_supabase()
    res = await (
        client.table("documents")
        .select("id, filename, file_type, document_type, file_size, processed, chunk_count, uploaded_at")
        .eq("user_id", user_id)
        .eq("id", doc_id)
        .maybe_single()
        .execute()
    )
    return res.data or None


# ============================================================================
# Notificaciones de recordatorios
# ============================================================================


# ============================================================================
# Adherencia
# ============================================================================


async def save_adherence_analysis(
    user_id: str,
    score: float,
    metrics: dict,
    llm_comment: str,
    period_days: int = 30,
) -> str:
    client = get_supabase()
    res = await client.table("adherence_analyses").insert({
        "user_id": user_id,
        "score": score,
        "metrics": metrics,
        "llm_comment": llm_comment,
        "period_days": period_days,
    }).execute()
    return str(res.data[0]["id"])


async def get_latest_adherence_analysis(user_id: str) -> Optional[dict]:
    client = get_supabase()
    res = await (
        client.table("adherence_analyses")
        .select("id, score, metrics, llm_comment, period_days, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    return res.data if res else None


async def get_reminders_for_adherence(
    user_id: str,
    period_days: int = 30,
    exclude_private: bool = False,
) -> list[dict]:
    """Retorna recordatorios pasados dentro del período para calcular métricas."""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=period_days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    client = get_supabase()
    q = (
        client.table("reminders")
        .select("medication, scheduled_at, taken, taken_at, status")
        .eq("user_id", user_id)
        .gte("scheduled_at", since)
        .lte("scheduled_at", now)
        .order("scheduled_at", desc=True)
    )
    if exclude_private:
        q = q.eq("is_private", False)
    res = await q.execute()
    return res.data or []


async def is_caregiver_of(caregiver_id: str, patient_id: str) -> bool:
    """Verifica si caregiver_id tiene acceso al paciente patient_id."""
    client = get_supabase()
    res = await (
        client.table("family_members")
        .select("id")
        .eq("caregiver_id", caregiver_id)
        .eq("patient_id", patient_id)
        .maybe_single()
        .execute()
    )
    return bool(res and res.data)


async def get_user_notifications(user_id: str, status: Optional[str] = None) -> list[dict]:
    client = get_supabase()
    q = (
        client.table("reminder_notifications")
        .select("id, reminder_id, channel, notify_id, status, fired_at, completed_at, failed_at, error_message, created_at, updated_at, reminders!fk_rn_reminder_id(medication, scheduled_at)")
        .eq("user_id", user_id)
    )
    if status:
        q = q.eq("status", status)
    res = await q.order("created_at", desc=True).limit(200).execute()
    return res.data or []


# ============================================================================
# Familia / Invitaciones
# ============================================================================


async def create_family_invitation(
    inviter_id: str,
    invited_email: str,
    token: str,
    expires_at: str,
) -> str:
    client = get_supabase()
    res = await client.table("family_invitations").insert({
        "inviter_id": inviter_id,
        "invited_email": invited_email,
        "token": token,
        "status": "pending",
        "expires_at": expires_at,
    }).execute()
    return str(res.data[0]["id"])


async def get_invitation_by_token(token: str) -> Optional[dict]:
    client = get_supabase()
    res = await client.table("family_invitations").select("*").eq("token", token).maybe_single().execute()
    return res.data if res else None


async def get_pending_invitations_by_inviter(inviter_id: str) -> list[dict]:
    client = get_supabase()
    res = await client.table("family_invitations")\
        .select("id, invited_email, status, expires_at, created_at")\
        .eq("inviter_id", inviter_id)\
        .order("created_at", desc=True)\
        .execute()
    return res.data or []


async def update_invitation_status(token: str, status: str) -> None:
    client = get_supabase()
    await client.table("family_invitations").update({"status": status}).eq("token", token).execute()


async def get_invitation_by_id(invitation_id: str) -> Optional[dict]:
    client = get_supabase()
    res = await client.table("family_invitations").select("*").eq("id", invitation_id).maybe_single().execute()
    return res.data if res else None


async def update_invitation_status_by_id(invitation_id: str, status: str) -> None:
    client = get_supabase()
    await client.table("family_invitations").update({"status": status}).eq("id", invitation_id).execute()


async def refresh_invitation_token(invitation_id: str, new_token: str, new_expires: str) -> None:
    client = get_supabase()
    await client.table("family_invitations").update({
        "token": new_token,
        "expires_at": new_expires,
        "status": "pending",
    }).eq("id", invitation_id).execute()


async def create_family_member(patient_id: str, caregiver_id: str) -> None:
    client = get_supabase()
    await client.table("family_members").upsert(
        {"patient_id": patient_id, "caregiver_id": caregiver_id},
        on_conflict="patient_id,caregiver_id",
    ).execute()


async def get_linked_patients(caregiver_id: str) -> list[dict]:
    """Pacientes que vincularon a este usuario como cuidador (Tab 1 Dashboard)."""
    client = get_supabase()
    res = await client.table("family_members")\
        .select("patient_id, users!family_members_patient_id_fkey(id, email, preferences)")\
        .eq("caregiver_id", caregiver_id)\
        .execute()
    return res.data or []


async def get_family_members_of_patient(patient_id: str) -> list[dict]:
    """Cuidadores vinculados a este paciente (Tab 2 Familiares)."""
    client = get_supabase()
    res = await client.table("family_members")\
        .select("caregiver_id, users!family_members_caregiver_id_fkey(id, email, preferences)")\
        .eq("patient_id", patient_id)\
        .execute()
    return res.data or []


async def remove_family_member(patient_id: str, caregiver_id: str) -> None:
    client = get_supabase()
    await client.table("family_members")\
        .delete()\
        .eq("patient_id", patient_id)\
        .eq("caregiver_id", caregiver_id)\
        .execute()


async def update_user_role(user_id: str, role: str) -> None:
    client = get_supabase()
    await client.table("users").update({"role": role}).eq("id", user_id).execute()


async def get_linked_patient_ids(caregiver_id: str) -> list[str]:
    """Devuelve los IDs de los pacientes que vincularon a este usuario como cuidador."""
    client = get_supabase()
    res = await client.table("family_members").select("patient_id").eq("caregiver_id", caregiver_id).execute()
    return [r["patient_id"] for r in (res.data or [])]


async def get_delayed_reminders_for_caregiver(patient_id: str) -> list[dict]:
    """Dosis retrasadas >20 min, no tomadas y no privadas de un paciente."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    client = get_supabase()
    res = await (
        client.table("reminders")
        .select("reminder_id, medication, scheduled_at")
        .eq("user_id", patient_id)
        .eq("status", "completed")
        .eq("taken", False)
        .eq("is_private", False)
        .lte("scheduled_at", cutoff)
        .order("scheduled_at", desc=True)
        .execute()
    )
    return res.data or []


async def get_reminder_for_caregiver(patient_id: str, reminder_id: str) -> Optional[dict]:
    """Obtiene un recordatorio de un paciente para que el caregiver lo valide."""
    client = get_supabase()
    res = await (
        client.table("reminders")
        .select("reminder_id, medication, scheduled_at, taken, is_private")
        .eq("user_id", patient_id)
        .eq("reminder_id", reminder_id)
        .maybe_single()
        .execute()
    )
    return res.data if res else None


async def get_manual_reminder_sent_ids(caregiver_id: str, reminder_ids: list[str]) -> set[str]:
    """IDs de recordatorios a los que el caregiver ya envió recordatorio manual."""
    if not reminder_ids:
        return set()
    client = get_supabase()
    res = await (
        client.table("manual_reminder_sends")
        .select("reminder_id")
        .eq("caregiver_id", caregiver_id)
        .in_("reminder_id", reminder_ids)
        .execute()
    )
    return {r["reminder_id"] for r in (res.data or [])}


async def insert_manual_reminder_send(reminder_id: str, caregiver_id: str, patient_id: str) -> None:
    """Registra el envío de un recordatorio manual. Lanza excepción si ya existe (UNIQUE)."""
    client = get_supabase()
    await client.table("manual_reminder_sends").insert({
        "reminder_id": reminder_id,
        "caregiver_id": caregiver_id,
        "patient_id": patient_id,
    }).execute()
