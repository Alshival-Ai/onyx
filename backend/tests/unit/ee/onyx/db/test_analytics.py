from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from uuid import uuid4

from ee.onyx.db.analytics import fetch_user_last_login_map


def test_fetch_user_last_login_map_returns_empty_for_no_users() -> None:
    mock_session = MagicMock()

    result = fetch_user_last_login_map([], mock_session)

    assert result == {}
    mock_session.execute.assert_not_called()


def test_fetch_user_last_login_map_merges_access_tokens_with_chat_fallback() -> None:
    user_with_both = uuid4()
    user_chat_only = uuid4()
    user_access_newer = uuid4()

    access_older = datetime(2026, 1, 1, tzinfo=timezone.utc)
    access_newer = datetime(2026, 1, 7, tzinfo=timezone.utc)
    chat_newer = datetime(2026, 1, 5, tzinfo=timezone.utc)
    chat_only = datetime(2026, 1, 4, tzinfo=timezone.utc)
    chat_older = datetime(2025, 12, 31, tzinfo=timezone.utc)

    mock_session = MagicMock()
    mock_session.execute.side_effect = [
        [
            (user_with_both, access_older),
            (user_access_newer, access_newer),
        ],
        [
            (user_with_both, chat_newer),
            (user_chat_only, chat_only),
            (user_access_newer, chat_older),
        ],
    ]

    result = fetch_user_last_login_map(
        [user_with_both, user_chat_only, user_access_newer], mock_session
    )

    assert result == {
        user_with_both: chat_newer,
        user_chat_only: chat_only,
        user_access_newer: access_newer,
    }
    assert mock_session.execute.call_count == 2
