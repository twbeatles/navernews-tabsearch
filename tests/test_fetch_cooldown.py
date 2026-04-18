import time
import unittest
from unittest import mock
from typing import Any, cast

from PyQt6.QtCore import QMutex

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

    def _schedule_tab_hydration(self, _delay_ms=0):
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
        self.value = 0

    def setVisible(self, value):
        self.visible = bool(value)

    def setRange(self, start, end):
        self.range = (int(start), int(end))

    def setValue(self, value):
        self.value = int(value)


class _DummyLabel:
    def __init__(self):
        self.text = ""

    def setText(self, value):
        self.text = str(value)


class _DummyTab:
    def __init__(self, keyword: str):
        self.keyword = keyword
        self.total_api_count = 0
        self.lbl_status = _DummyLabel()
        self.load_calls = 0
        self.update_timestamp_calls = 0

    def update_timestamp(self):
        self.update_timestamp_calls += 1

    def load_data_from_db(self):
        self.load_calls += 1


class _DummyFetchState:
    def __init__(self):
        self.last_api_start_index = 0


class _DummyFetchDoneMain(_DummyFetchMain):
    def on_fetch_done(self, result, keyword, is_more, is_sequential=False, request_id=None):
        return cast(Any, _MainWindowFetchMixin).on_fetch_done(
            cast(Any, self),
            result,
            keyword,
            is_more,
            is_sequential=is_sequential,
            request_id=request_id,
        )

    def _finish_sequential_refresh(self):
        return cast(Any, _MainWindowFetchMixin)._finish_sequential_refresh(cast(Any, self))

    def _build_fetch_summary_message(self, keyword, *, new_count, dup_count, filtered_count=0):
        return cast(Any, _MainWindowFetchMixin)._build_fetch_summary_message(
            cast(Any, self),
            keyword,
            new_count=new_count,
            dup_count=dup_count,
            filtered_count=filtered_count,
        )

    def _notify_fetch_new_items(self, keyword, *, new_count, new_items):
        return cast(Any, _MainWindowFetchMixin)._notify_fetch_new_items(
            cast(Any, self),
            keyword,
            new_count=new_count,
            new_items=new_items,
        )

    def __init__(self):
        super().__init__()
        self.visible = False
        self._tab = _DummyTab("AI launch")
        self.tray_notifications = []
        self.tooltip_updates = 0
        self.alert_inputs = []
        self._sequential_refresh_done_keywords = []
        self.badge_updates = []
        self._fetch_total_by_key = {}
        self._fetch_cursor_by_key = {}
        self._tab_fetch_state = {}
        self._sequential_new_count = 0
        self._sequential_added_count = 0
        self._sequential_dup_count = 0
        self._sequential_refresh_active = True
        self._pending_refresh_keywords = ["AI launch"]
        self._total_refresh_count = 1
        self._refresh_in_progress = True
        self._refresh_mutex = QMutex()
        self.notify_on_refresh = True
        self.apply_refresh_calls = 0
        self._fts_resume_delays = []
        self.hydration_delays = []

    def isVisible(self):
        return self.visible

    def _find_news_tab(self, keyword):
        if keyword == self._tab.keyword:
            return 1, self._tab
        return None

    def _make_tab_fetch_state(self):
        return _DummyFetchState()

    def _apply_load_more_button_state(self, *_args, **_kwargs):
        return True

    def show_tray_notification(self, title, message):
        self.tray_notifications.append((title, message))

    def update_tray_tooltip(self):
        self.tooltip_updates += 1

    def check_alert_keywords(self, items):
        items_list = list(items)
        self.alert_inputs.append(items_list)
        return [(item, "alert") for item in items_list if "alert" in item.get("title", "").lower()]

    def _on_sequential_fetch_done(self, keyword):
        self._sequential_refresh_done_keywords.append(keyword)

    def update_tab_badge(self, keyword):
        self.badge_updates.append(keyword)

    def apply_refresh_interval(self):
        self.apply_refresh_calls += 1

    def _request_fts_backfill_resume(self, delay_ms=250):
        self._fts_resume_delays.append(delay_ms)

    def _schedule_tab_hydration(self, delay_ms=0):
        self.hydration_delays.append(delay_ms)


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

    def test_on_fetch_done_uses_new_count_for_notifications_and_alerts(self):
        dummy = _DummyFetchDoneMain()
        result = {
            "new_items": [
                {
                    "title": "alert duplicate item",
                    "description": "desc",
                    "link": "https://example.com/new-1",
                }
            ],
            "new_count": 1,
            "added_count": 0,
            "dup_count": 1,
            "total": 5,
            "filtered": 0,
        }

        dummy.on_fetch_done(result, "AI launch", is_more=False, is_sequential=False)

        self.assertEqual(dummy._tab.lbl_status.text, "✅ 'AI launch' 업데이트 완료 (1건 새 링크, 1건 중복)")
        self.assertEqual(dummy.toasts, ["✅ 'AI launch' 업데이트 완료 (1건 새 링크, 1건 중복)"])
        self.assertEqual(dummy.desktop_notifications[0], ("📰 AI launch", "1건의 새 뉴스가 있습니다."))
        self.assertEqual(dummy.tray_notifications[0], ("📰 AI launch", "1건의 새 뉴스가 도착했습니다."))
        self.assertEqual(dummy.alert_inputs, [[result["new_items"][0]]])
        self.assertEqual(dummy.desktop_notifications[1], ("🔔 알림 키워드: alert", "alert duplicate item"))

    def test_sequential_fetch_emits_immediate_notifications_and_accumulates_new_count(self):
        dummy = _DummyFetchDoneMain()
        result = {
            "new_items": [
                {
                    "title": "alert sequential item",
                    "description": "desc",
                    "link": "https://example.com/new-2",
                }
            ],
            "new_count": 1,
            "added_count": 0,
            "dup_count": 1,
            "total": 5,
            "filtered": 0,
        }

        dummy.on_fetch_done(result, "AI launch", is_more=False, is_sequential=True)

        self.assertEqual(dummy.toasts, [])
        self.assertEqual(dummy._sequential_refresh_done_keywords, ["AI launch"])
        self.assertEqual(dummy._sequential_new_count, 1)
        self.assertEqual(dummy._sequential_added_count, 0)
        self.assertEqual(dummy._sequential_dup_count, 1)
        self.assertEqual(dummy.desktop_notifications[0], ("📰 AI launch", "1건의 새 뉴스가 있습니다."))
        self.assertEqual(dummy.tray_notifications[0], ("📰 AI launch", "1건의 새 뉴스가 도착했습니다."))
        self.assertEqual(dummy.alert_inputs, [[result["new_items"][0]]])

    def test_finish_sequential_refresh_summarizes_new_link_count(self):
        dummy = _DummyFetchDoneMain()
        dummy._sequential_new_count = 2
        dummy._sequential_added_count = 1
        dummy._sequential_dup_count = 1

        dummy._finish_sequential_refresh()

        self.assertFalse(dummy._sequential_refresh_active)
        self.assertEqual(dummy.toasts[-1], "총 1개 탭 새로고침 완료 (2건 새 링크, 1건 중복)")
        self.assertEqual(dummy.status_bar.messages[-1], "총 1개 탭 새로고침 완료 (2건 새 링크, 1건 중복)")
        self.assertEqual(dummy.desktop_notifications[-1], ("뉴스 자동 새로고침 완료", "2건의 새 기사가 업데이트되었습니다."))
        self.assertEqual(dummy.apply_refresh_calls, 1)
        self.assertEqual(dummy._fts_resume_delays, [250])
        self.assertIn(50, dummy.hydration_delays)


if __name__ == "__main__":
    unittest.main()
