import time
import unittest
from unittest import mock
from typing import Any, cast

from ui._main_window_fetch import _MainWindowFetchMixin


class _DummyStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, message, _timeout=0):
        self.messages.append(message)


class _DummyFetchMain:
    def fetch_news(self, keyword: str, is_more: bool = False, is_sequential: bool = False):
        return cast(Any, _MainWindowFetchMixin).fetch_news(
            cast(Any, self),
            keyword,
            is_more=is_more,
            is_sequential=is_sequential,
        )

    def _fetch_cooldown_message(self, action_label: str) -> str:
        return cast(Any, _MainWindowFetchMixin)._fetch_cooldown_message(cast(Any, self), action_label)

    def _current_fetch_cooldown_seconds(self) -> int:
        return cast(Any, _MainWindowFetchMixin)._current_fetch_cooldown_seconds(cast(Any, self))

    def _set_fetch_cooldown(self, seconds: int, *, reason: str) -> None:
        cast(Any, _MainWindowFetchMixin)._set_fetch_cooldown(cast(Any, self), seconds, reason=reason)

    def __init__(self):
        self._fetch_cooldown_until = 0.0
        self._fetch_cooldown_reason = ""
        self.warning_messages = []
        self.status_bar = _DummyStatusBar()

    def is_maintenance_mode_active(self):
        return False

    def _maintenance_block_message(self, action):
        return action

    def _status_bar(self):
        return self.status_bar

    def show_warning_toast(self, message):
        self.warning_messages.append(message)


class TestFetchCooldown(unittest.TestCase):
    def test_fetch_news_blocks_when_global_cooldown_is_active(self):
        dummy = _DummyFetchMain()
        dummy._set_fetch_cooldown(12, reason="rate_limit")

        with mock.patch("ui._main_window_fetch.ApiWorker", side_effect=AssertionError("worker should not start")):
            dummy.fetch_news("AI launch", is_more=False, is_sequential=False)

        self.assertTrue(dummy.warning_messages)
        self.assertIn("API 대기 시간", dummy.warning_messages[0])
        self.assertTrue(dummy.status_bar.messages)

    def test_cooldown_message_clears_after_expiry(self):
        dummy = _DummyFetchMain()
        dummy._fetch_cooldown_until = time.time() - 1
        dummy._fetch_cooldown_reason = "rate_limit"

        self.assertEqual(dummy._fetch_cooldown_message("새로고침"), "")
        self.assertEqual(dummy._fetch_cooldown_reason, "")


if __name__ == "__main__":
    unittest.main()
