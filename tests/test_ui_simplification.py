"""Regression tests for the 005 UI simplification (specs/005-ui-simplification)."""

import ast
import inspect
import os
import textwrap
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainApp
from ui.news_tab import NewsTab
from ui.settings_dialog import SettingsDialog
from ui.styles import AppStyle
from ui.styles_support import DARK_PALETTE, LIGHT_PALETTE
from ui.styles_support.icons import glyph_qss


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeDb:
    def fetch_news(self, **kwargs):
        return []

    def get_known_tags(self):
        return ["중요"]


def _item(**overrides):
    item = {
        "link": "https://example.com/1",
        "title": "제목",
        "description": "요약",
        "publisher": "example.com",
        "pubDate": "",
    }
    item.update(overrides)
    return item


class _TabTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_tab(self, keyword: str = "AI -coin") -> NewsTab:
        with mock.patch.object(NewsTab, "load_data_from_db", autospec=True):
            tab = NewsTab(keyword, cast(Any, _FakeDb()), theme_mode=0)
        self.addCleanup(tab.cleanup)
        self.addCleanup(tab.deleteLater)
        return tab


class TestArticleCard(_TabTestCase):
    def test_inline_actions_are_bookmark_and_share_only(self):
        tab = self._make_tab()
        html = tab._render_single_item(_item(is_read=1), "")

        self.assertIn("app://open/", html)
        self.assertIn("app://bm/", html)
        self.assertIn("app://share/", html)
        for hidden_action in ("app://ext/", "app://tag/", "app://unread/", "app://note/"):
            self.assertNotIn(hidden_action, html)

    def test_tab_keyword_is_not_repeated_as_a_badge(self):
        tab = self._make_tab("AI -coin")
        html = tab._render_single_item(_item(title="plain", description="plain"), "")

        self.assertNotIn("keyword-tag", html)
        self.assertNotIn(">AI<", html)

    def test_note_link_and_user_tags_stay_visible(self):
        tab = self._make_tab()
        html = tab._render_single_item(_item(notes="확인 필요", tags="중요, 정책", is_duplicate=1), "")

        self.assertIn("app://note/", html)
        self.assertIn("#중요", html)
        self.assertIn("#정책", html)
        self.assertIn("유사", html)

    def test_read_and_bookmarked_items_are_marked_without_unsupported_css(self):
        tab = self._make_tab()
        unread = tab._render_single_item(_item(link="https://example.com/u"), "")
        read = tab._render_single_item(_item(link="https://example.com/r", is_read=1, is_bookmarked=1), "")

        self.assertIn('class="title-link"', unread)
        self.assertIn('class="title-link-read"', read)
        self.assertIn("북마크 해제", read)
        self.assertIn("★", read)
        # QTextBrowser가 무시하는 속성에 읽음 표현을 맡기지 않는다.
        self.assertNotIn("opacity", AppStyle.HTML_TEMPLATE)

    def test_every_link_action_is_still_handled(self):
        handler_src = inspect.getsource(NewsTab.on_link_clicked)
        for action in ("open", "bm", "share", "unread", "note", "tag", "ext", "load_more"):
            self.assertIn(f'"{action}"', handler_src)


class TestTabStatusAndFilters(_TabTestCase):
    def _seed(self, tab: NewsTab, count: int, unread: int):
        rows = [
            tab._prepare_item(_item(link=f"https://example.com/{i}", is_read=0 if i < unread else 1))
            for i in range(count)
        ]
        tab.news_data_cache = rows
        tab.filtered_data_cache = list(rows)
        tab._total_filtered_count = count
        tab._recount_unread_cache()

    def test_status_is_a_short_sentence(self):
        tab = self._make_tab()
        self._seed(tab, count=3, unread=2)
        cast(Any, tab).last_update = "10:32:00"

        tab.update_status_label()

        self.assertEqual(tab.lbl_status.text(), "기사 3개 · 안 읽음 2 · 10:32:00 업데이트")

    def test_status_reports_matches_when_filtered(self):
        tab = self._make_tab()
        self._seed(tab, count=2, unread=0)
        tab.total_api_count = 10
        with mock.patch.object(NewsTab, "load_data_from_db", autospec=True):
            tab.chk_hide_dup.setChecked(True)

        tab.update_status_label()

        self.assertEqual(tab.lbl_status.text(), "2개 일치 (전체 10개)")

    def test_collapsed_advanced_filters_are_flagged_and_resettable(self):
        tab = self._make_tab()
        self.assertEqual(tab.btn_advanced.text(), "필터 ▾")
        self.assertTrue(tab.btn_reset_filters.isHidden())

        with mock.patch.object(NewsTab, "load_data_from_db", autospec=True):
            tab.chk_preferred_publishers.setChecked(True)
            tab.update_status_label()

        self.assertEqual(tab.btn_advanced.text(), "필터 ● ▾")
        self.assertFalse(tab.btn_reset_filters.isHidden())

    def test_reset_clears_every_filter_with_a_single_reload(self):
        tab = self._make_tab()
        with mock.patch.object(NewsTab, "load_data_from_db", autospec=True):
            tab.inp_filter.setText("반도체")
            tab.filter_timer.stop()
            tab.chk_unread.setChecked(True)
            tab.chk_hide_dup.setChecked(True)
            tab.chk_preferred_publishers.setChecked(True)
            tab.combo_tag_filter.setCurrentIndex(1)
            tab.filter_timer.stop()
            tab.btn_date_toggle.setChecked(True)
            tab._apply_date_filter()
        self.assertTrue(tab._has_active_filters())

        with mock.patch.object(NewsTab, "load_data_from_db", autospec=True) as load_mock:
            tab._reset_filters()

        self.assertFalse(tab._has_active_filters())
        self.assertFalse(tab._date_filter_active)
        self.assertEqual(tab.inp_filter.text(), "")
        self.assertFalse(tab.btn_date_toggle.isChecked())
        self.assertEqual(load_mock.call_count, 1)

    def test_empty_state_blames_filters_before_missing_bookmarks(self):
        tab = self._make_tab("북마크")
        self.assertIn("북마크한 기사가 없습니다", tab._empty_state_html())

        tab.inp_filter.setText("없는단어")
        tab.filter_timer.stop()
        self.assertIn("조건에 맞는 기사가 없습니다", tab._empty_state_html())

    def test_reset_button_follows_maintenance_mode(self):
        tab = self._make_tab()
        tab.set_maintenance_mode(True)
        self.assertFalse(tab.btn_reset_filters.isEnabled())
        tab.set_maintenance_mode(False)
        self.assertTrue(tab.btn_reset_filters.isEnabled())


class TestToolbarAndMaintenance(unittest.TestCase):
    def test_tab_titles_drop_the_decorative_icon(self):
        dummy = type("Dummy", (), {"_tab_icon_for_keyword": MainApp._tab_icon_for_keyword})()
        format_title = cast(Any, MainApp._format_tab_title)

        self.assertEqual(format_title(dummy, "AI -광고", unread_count=3), "AI -광고 (3)")
        self.assertEqual(format_title(dummy, "AI"), "AI")
        self.assertTrue(format_title(dummy, "-광고").startswith("🚫"))

    def test_export_menu_action_follows_maintenance_mode(self):
        src = inspect.getsource(MainApp._set_fetch_controls_enabled)
        self.assertIn("self.action_export.setEnabled(enabled)", src)
        self.assertNotIn("btn_save", src)


class TestSettingsLayout(unittest.TestCase):
    def test_settings_are_split_into_tabs_and_help_mode_keeps_help_first(self):
        src = inspect.getsource(SettingsDialog.setup_ui)
        add_tab_calls = sorted(
            (
                node
                for node in ast.walk(ast.parse(textwrap.dedent(src)))
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "addTab"
            ),
            key=lambda node: node.lineno,
        )
        labels = [cast(ast.Constant, node.args[1]).value for node in add_tab_calls]
        self.assertEqual(labels, ["일반", "알림·트레이", "데이터", "도움말", "단축키"])
        self.assertLess(src.index("if not self._help_mode:"), src.index('"일반"'))
        self.assertLess(src.index('"데이터"'), src.index("self._build_help_tab()"))

    def test_get_data_contract_is_unchanged(self):
        module = ast.parse(Path("ui/settings_dialog.py").read_text(encoding="utf-8"))
        cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "SettingsDialog")
        get_data = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "get_data")
        return_dict = next(n.value for n in ast.walk(get_data) if isinstance(n, ast.Return))
        assert isinstance(return_dict, ast.Dict)
        keys = {k.value for k in return_dict.keys if isinstance(k, ast.Constant)}

        self.assertEqual(
            keys,
            {
                "id", "secret", "interval", "theme", "auto_backup_minutes", "notification_enabled",
                "alert_keywords", "sound_enabled", "minimize_to_tray", "close_to_tray",
                "auto_start_enabled", "start_minimized", "notify_on_refresh", "api_timeout",
                "blocked_publishers", "preferred_publishers", "cloud_sync_enabled", "cloud_sync_dir",
                "cloud_sync_interval_minutes", "tombstone_retention_days",
            },
        )

    def test_every_widget_read_by_get_data_is_still_built(self):
        get_data_src = inspect.getsource(SettingsDialog.get_data)
        content_src = Path("ui/_settings_dialog_content.py").read_text(encoding="utf-8")
        widget_names = {
            node.attr
            for node in ast.walk(ast.parse(textwrap.dedent(get_data_src)))
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        }
        self.assertGreaterEqual(len(widget_names), 15)
        for name in widget_names:
            self.assertIn(f"self.{name} = ", content_src, name)


class TestStyleSheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_stylesheet_has_no_gradients_or_hardcoded_hint_colors(self):
        for sheet in (AppStyle.LIGHT, AppStyle.DARK):
            self.assertNotIn("qlineargradient", sheet)
        for path in Path("ui").rglob("*.py"):
            self.assertNotIn("#666", path.read_text(encoding="utf-8"), str(path))

    def test_themed_stylesheet_adds_glyphs_that_exist_on_disk(self):
        for palette, base in ((LIGHT_PALETTE, AppStyle.LIGHT), (DARK_PALETTE, AppStyle.DARK)):
            glyphs = glyph_qss(palette)
            self.assertIn("QComboBox::down-arrow", glyphs)
            self.assertEqual(AppStyle.for_theme(palette.name == "dark"), base + glyphs)
            for chunk in glyphs.split("url(")[1:]:
                self.assertTrue(os.path.isfile(chunk.split(")")[0]), chunk)


if __name__ == "__main__":
    unittest.main()
