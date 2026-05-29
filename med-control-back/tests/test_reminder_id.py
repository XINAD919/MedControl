from core.tools import _generate_reminder_id


def test_reminder_id_unique_for_same_user():
    """Two IDs for the same user must differ (random suffix guarantees this)."""
    id1 = _generate_reminder_id("11111111-1111-1111-1111-111111111111")
    id2 = _generate_reminder_id("11111111-1111-1111-1111-111111111111")
    assert id1 != id2


def test_reminder_id_has_rem_prefix():
    rid = _generate_reminder_id("11111111-1111-1111-1111-111111111111")
    assert rid.startswith("rem_")


def test_reminder_id_embeds_user_prefix():
    rid = _generate_reminder_id("11111111-1111-1111-1111-111111111111")
    assert "11111111" in rid
