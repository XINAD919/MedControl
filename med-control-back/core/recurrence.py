import calendar
from datetime import datetime, timedelta
from typing import Optional


def calculate_next_occurrence(
    current: datetime,
    recurrence_type: str,
    recurrence_days: Optional[list] = None,
    recurrence_interval: int = 1,
    recurrence_end_date: Optional[datetime] = None,
) -> Optional[datetime]:
    """Retorna la siguiente datetime de disparo, o None si ya superó end_date."""
    next_dt = _advance(current, recurrence_type, recurrence_days or [], recurrence_interval)
    if recurrence_end_date and next_dt > recurrence_end_date:
        return None
    return next_dt


def _advance(current: datetime, rtype: str, days: list, interval: int) -> datetime:
    if rtype == "daily":
        return current + timedelta(days=1)

    if rtype == "weekdays":
        nxt = current + timedelta(days=1)
        while nxt.weekday() >= 5:  # 5=sábado, 6=domingo
            nxt += timedelta(days=1)
        return nxt

    if rtype == "weekends":
        nxt = current + timedelta(days=1)
        while nxt.weekday() < 5:
            nxt += timedelta(days=1)
        return nxt

    if rtype == "weekly":
        # DB usa 0=Dom, Python weekday() usa 0=Lun → convertir
        nxt = current + timedelta(days=1)
        for _ in range(7):
            db_day = (nxt.weekday() + 1) % 7
            if db_day in days:
                return nxt
            nxt += timedelta(days=1)
        return current + timedelta(weeks=1)

    if rtype == "monthly":
        month = current.month % 12 + 1
        year = current.year + (1 if current.month == 12 else 0)
        day = min(current.day, calendar.monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day)

    if rtype == "interval_days":
        return current + timedelta(days=interval)

    if rtype == "interval_hours":
        return current + timedelta(hours=interval)

    # fallback
    return current + timedelta(days=1)
