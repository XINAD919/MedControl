import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.db import (
    get_reminders_for_adherence,
    get_latest_adherence_analysis,
    save_adherence_analysis,
    is_caregiver_of,
)
from deps import CurrentUser, get_current_user

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AdherenceMetrics(BaseModel):
    total_due: int
    total_taken: int
    adherence_rate: float
    punctuality_rate: float
    avg_delay_minutes: float
    recent_adherence_rate: float
    medications: list[str]
    trend: str  # "mejorando" | "estable" | "empeorando"
    streak_days: int = 0


class AdherenceAnalysisResponse(BaseModel):
    id: str
    score: float
    metrics: AdherenceMetrics
    llm_comment: str
    period_days: int
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_metrics(reminders: list[dict], period_days: int) -> AdherenceMetrics:
    now = datetime.now(timezone.utc)

    past = [
        r for r in reminders
        if r.get("status") in ("completed", "failed", "cancelled")
        or (r.get("scheduled_at") and _parse_dt(r["scheduled_at"]) < now)
    ]

    total_due = len(past)
    total_taken = sum(1 for r in past if r.get("taken"))

    adherence_rate = (total_taken / total_due) if total_due > 0 else 0.0

    # Puntualidad: % tomados dentro de 30 min del horario programado
    taken_with_times = [
        r for r in past
        if r.get("taken") and r.get("taken_at") and r.get("scheduled_at")
    ]
    if taken_with_times:
        delays = []
        on_time = 0
        for r in taken_with_times:
            sched = _parse_dt(r["scheduled_at"])
            taken = _parse_dt(r["taken_at"])
            diff_min = (taken - sched).total_seconds() / 60
            delays.append(max(diff_min, 0))
            if diff_min <= 30:
                on_time += 1
        avg_delay = sum(delays) / len(delays)
        punctuality_rate = on_time / len(taken_with_times)
    else:
        avg_delay = 0.0
        punctuality_rate = adherence_rate  # fallback

    # Tendencia: últimos 7 días vs período completo
    from datetime import timedelta
    cutoff_7d = now - timedelta(days=7)
    recent = [r for r in past if _parse_dt(r["scheduled_at"]) >= cutoff_7d]
    if len(recent) >= 3:
        recent_taken = sum(1 for r in recent if r.get("taken"))
        recent_rate = recent_taken / len(recent)
    else:
        recent_rate = adherence_rate

    if recent_rate > adherence_rate + 0.05:
        trend = "mejorando"
    elif recent_rate < adherence_rate - 0.05:
        trend = "empeorando"
    else:
        trend = "estable"

    medications = list({r["medication"] for r in reminders if r.get("medication")})

    # Racha: días consecutivos hasta hoy con 100% de dosis tomadas
    from collections import defaultdict
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in past:
        day_key = _parse_dt(r["scheduled_at"]).strftime("%Y-%m-%d")
        by_day[day_key].append(r)

    streak_days = 0
    check_date = now - timedelta(days=1)  # empieza ayer (hoy puede estar incompleto)
    while True:
        key = check_date.strftime("%Y-%m-%d")
        day_reminders = by_day.get(key)
        if not day_reminders:
            break
        if all(r.get("taken") for r in day_reminders):
            streak_days += 1
            check_date -= timedelta(days=1)
        else:
            break

    return AdherenceMetrics(
        total_due=total_due,
        total_taken=total_taken,
        adherence_rate=round(adherence_rate, 4),
        punctuality_rate=round(punctuality_rate, 4),
        avg_delay_minutes=round(avg_delay, 1),
        recent_adherence_rate=round(recent_rate, 4),
        medications=medications,
        trend=trend,
        streak_days=streak_days,
    )


def _compute_score(m: AdherenceMetrics) -> float:
    adherence_w = 0.45
    punctuality_w = 0.25
    consistency_w = 0.20
    trend_w = 0.10

    trend_score = {"mejorando": 1.0, "estable": 0.7, "empeorando": 0.3}[m.trend]
    consistency = 1.0 - abs(m.recent_adherence_rate - m.adherence_rate)

    raw = (
        m.adherence_rate * adherence_w
        + m.punctuality_rate * punctuality_w
        + consistency * consistency_w
        + trend_score * trend_w
    )
    score = round(raw * 4 + 1, 1)
    return max(1.0, min(5.0, score))


async def _generate_llm_comment(m: AdherenceMetrics, score: float, period_days: int) -> str:
    try:
        import anthropic
        model = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
        client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        meds_str = ", ".join(m.medications) if m.medications else "varios medicamentos"
        prompt = (
            f"Eres un especialista en adherencia a tratamientos médicos. "
            f"Genera un análisis breve, empático y personalizado en español (3-4 oraciones) "
            f"basado en los siguientes datos del paciente para los últimos {period_days} días:\n\n"
            f"- Recordatorios cumplidos: {m.total_taken} de {m.total_due}\n"
            f"- Tasa de adherencia: {m.adherence_rate:.0%}\n"
            f"- Puntualidad (dentro de 30 min): {m.punctuality_rate:.0%}\n"
            f"- Retraso promedio: {m.avg_delay_minutes:.0f} minutos\n"
            f"- Tendencia reciente: {m.trend}\n"
            f"- Medicamentos: {meds_str}\n"
            f"- Puntuación calculada: {score:.1f}/5.0\n\n"
            f"Interpreta los datos sin repetirlos literalmente. "
            f"Si hay mejoras posibles, mencionarlas constructivamente. "
            f"Tono profesional pero cercano."
        )

        response = await client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        return _fallback_comment(score)


def _fallback_comment(score: float) -> str:
    if score >= 4.5:
        return "Excelente adherencia al tratamiento. El paciente demuestra un compromiso ejemplar con sus medicamentos."
    if score >= 3.5:
        return "Buena adherencia en general. Hay pequeñas oportunidades de mejora en puntualidad."
    if score >= 2.5:
        return "Adherencia regular. Se recomienda reforzar el hábito de toma puntual de medicamentos."
    if score >= 1.5:
        return "Adherencia deficiente. Es importante revisar las barreras que dificultan el cumplimiento del tratamiento."
    return "Adherencia crítica. Se recomienda hablar con el médico para ajustar el plan de tratamiento."


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── Endpoints ─────────────────────────────────────────────────────────────────

async def _assert_can_access_patient(current_user: CurrentUser, patient_id: str) -> bool:
    """Devuelve True si el acceso es como caregiver (para filtrar privados)."""
    if current_user.user_id == patient_id:
        return False
    if await is_caregiver_of(current_user.user_id, patient_id):
        return True
    raise HTTPException(status_code=403, detail="No autorizado")


@router.get("/users/{user_id}/adherence-analysis/latest", response_model=Optional[AdherenceAnalysisResponse])
async def get_latest_analysis(
    user_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    await _assert_can_access_patient(current_user, user_id)
    row = await get_latest_adherence_analysis(user_id)
    if not row:
        return None
    return AdherenceAnalysisResponse(
        id=row["id"],
        score=float(row["score"]),
        metrics=AdherenceMetrics(**row["metrics"]),
        llm_comment=row["llm_comment"],
        period_days=row["period_days"],
        created_at=str(row["created_at"]),
    )


@router.post("/users/{user_id}/adherence-analysis", response_model=AdherenceAnalysisResponse)
async def generate_analysis(
    user_id: str,
    period_days: int = 30,
    current_user: CurrentUser = Depends(get_current_user),
):
    as_caregiver = await _assert_can_access_patient(current_user, user_id)

    reminders = await get_reminders_for_adherence(user_id, period_days, exclude_private=as_caregiver)

    if not reminders:
        raise HTTPException(
            status_code=422,
            detail="No hay historial de recordatorios suficiente para generar un análisis.",
        )

    metrics = _compute_metrics(reminders, period_days)
    score = _compute_score(metrics)
    llm_comment = await _generate_llm_comment(metrics, score, period_days)

    analysis_id = await save_adherence_analysis(
        user_id=user_id,
        score=score,
        metrics=metrics.model_dump(),
        llm_comment=llm_comment,
        period_days=period_days,
    )

    return AdherenceAnalysisResponse(
        id=analysis_id,
        score=score,
        metrics=metrics,
        llm_comment=llm_comment,
        period_days=period_days,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
