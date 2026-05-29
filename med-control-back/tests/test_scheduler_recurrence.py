import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_process_group_marks_completed_even_if_schedule_next_fails():
    """If _schedule_next raises, the reminder must still be marked completed."""
    from core.scheduler import _process_group

    reminder = {
        "reminder_id": "rem_abc12345_ff0011",
        "user_id": "11111111-1111-1111-1111-111111111111",
        "is_recurring": True,
        "scheduled_at": datetime.utcnow().isoformat(),
        "status": "firing",
    }

    with patch("core.scheduler._update_status_bulk", new_callable=AsyncMock) as mock_update:
        with patch("core.scheduler._schedule_next", new_callable=AsyncMock, side_effect=Exception("DB error")):
            await _process_group(reminder, [], "")

    update_args = [str(call) for call in mock_update.call_args_list]
    assert any("completed" in args for args in update_args), (
        "_update_status_bulk must be called with 'completed' even when _schedule_next fails"
    )


def test_generate_next_reminder_id_unique():
    """Two calls with same args must produce different IDs (no timestamp collision)."""
    from core.scheduler import _generate_next_reminder_id

    dt = datetime(2025, 1, 1, 8, 0)
    id1 = _generate_next_reminder_id("11111111-1111-1111-1111-111111111111", dt)
    id2 = _generate_next_reminder_id("11111111-1111-1111-1111-111111111111", dt)
    assert id1 != id2


def test_generate_next_reminder_id_has_rem_prefix():
    from core.scheduler import _generate_next_reminder_id

    dt = datetime(2025, 1, 1, 8, 0)
    rid = _generate_next_reminder_id("11111111-1111-1111-1111-111111111111", dt)
    assert rid.startswith("rem_")
