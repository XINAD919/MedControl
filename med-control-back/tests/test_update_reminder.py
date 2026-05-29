import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_update_includes_recurrence_type():
    """_update_user_reminder must include recurrence_type in the DB update dict."""
    from core.tools import _update_user_reminder

    mock_client = MagicMock()
    mock_exec = AsyncMock(return_value=MagicMock(data=[]))
    mock_client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute = mock_exec
    mock_client.aclose = AsyncMock()

    async def mock_create_temp_client():
        return mock_client

    with patch("core.supabase_client.create_temp_client", side_effect=mock_create_temp_client):
        await _update_user_reminder(
            reminder_id="rem_abc_001",
            user_id="11111111-1111-1111-1111-111111111111",
            recurrence_type="daily",
        )

    mock_client.table.return_value.update.assert_called_once()
    update_arg = mock_client.table.return_value.update.call_args[0][0]
    assert "recurrence_type" in update_arg
    assert update_arg["recurrence_type"] == "daily"


@pytest.mark.asyncio
async def test_update_sets_is_recurring_true_when_recurrence_type_set():
    """When recurrence_type is provided, is_recurring must be set to True."""
    from core.tools import _update_user_reminder

    mock_client = MagicMock()
    mock_exec = AsyncMock(return_value=MagicMock(data=[]))
    mock_client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute = mock_exec
    mock_client.aclose = AsyncMock()

    async def mock_create_temp_client():
        return mock_client

    with patch("core.supabase_client.create_temp_client", side_effect=mock_create_temp_client):
        await _update_user_reminder(
            reminder_id="rem_abc_001",
            user_id="11111111-1111-1111-1111-111111111111",
            recurrence_type="weekly",
            recurrence_days=["monday", "thursday"],
            recurrence_end_date="2025-12-31",
        )

    mock_client.table.return_value.update.assert_called_once()
    update_arg = mock_client.table.return_value.update.call_args[0][0]
    assert update_arg.get("is_recurring") is True


def test_update_reminder_schema_has_recurrence_type():
    """The update_reminder TOOLS schema must include recurrence_type in properties."""
    from core.tools import TOOLS
    update_tool = next(t for t in TOOLS if t["function"]["name"] == "update_reminder")
    props = update_tool["function"]["parameters"]["properties"]
    assert "recurrence_type" in props
    assert "recurrence_end_date" in props
