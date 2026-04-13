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

    def on_fetch_error(self, error_msg: str, keyword: str, is_sequential: bool = False, request_id=None, error_meta=None):
        return cast(Any, _MainWindowFetchMixin).on_fetch_error(
            cast(Any, self),
            error_msg,
            keyword,
            is_sequential=is_sequential,
            request_id=request_id,
            error_meta=error_meta,
        )

    def __init__(self):
        self._fetch_cooldown_until = 0.0
        self._fetch_cooldown_reason = ""
        self.warning_messages = []
        self.status_bar = _DummyStatusBar()
        self._last_fetch_request_ts = {}
        self._request_start_index = {}
        self._network_error_count = 0
        self._max_network_errors = 3
        self.progress = _DummyProgress()
        self.btn_refresh = _DummyButton()
        self.toasts = []
        self.desktop_notifications = []

    def is_maintenance_mode_active(self):
        return False

    def _maintenance_block_message(self, action):
        return action

    def _status_bar(self):
        return self.status_bar

    def show_warning_toast(self, message):
        self.warning_messages.append(message)

    def show_toast(self, message):
        self.toasts.append(message)

    def show_desktop_notification(self, title, message):
        self.desktop_notifications.append((title, message))

    def sync_tab_load_more_state(self, keyword):
        return None

    def _is_active_worker_request(self, keyword, request_id):
        return True

    def _find_news_tab(self, keyword):
        return None


class _DummyButton:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = bool(value)


class _DummyProgress:
    def __init__(self):
        self.visible = False
        self.range = (0, 0)

    def setVisible(self, value):
        self.visible = bool(value)

    def setRange(self, start, end):
        self.range = (int(start), int(end))


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

    def test_db_fetch_error_does_not_emit_success_notifications(self):
        dummy = _DummyFetchMain()

        with mock.patch("ui._main_window_fetch.QMessageBox.critical") as critical_mock:
            dummy.on_fetch_error(
                "데이터베이스 저장 실패: upsert_news failed: disk full",
                "AI launch",
                request_id=1,
                error_meta={"kind": "db_write_error"},
            )

        critical_mock.assert_called_once()
        self.assertEqual(dummy.toasts, [])
        self.assertEqual(dummy.desktop_notifications, [])
        self.assertTrue(dummy.status_bar.messages)


if __name__ == "__main__":
    unittest.main()
