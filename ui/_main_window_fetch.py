# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import html
import logging
import time
import traceback
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional

from PyQt6.QtCore import QMutexLocker, QThread, QTimer
from PyQt6.QtWidgets import QMessageBox

from core.query_parser import build_fetch_key, has_positive_keyword, parse_search_query, parse_tab_query
from core.text_utils import RE_HTML_TAGS
from core.worker_registry import WorkerHandle
from core.workers import ApiWorker

if TYPE_CHECKING:
    from ui.main_window import MainApp


logger = logging.getLogger(__name__)


class _MainWindowFetchMixin:
    def _safe_refresh_all(self: MainApp):
        """안전한 자동 새로고침 래퍼 (타이머에서 호출)"""
        if self._network_error_count >= self._max_network_errors:
            if self._network_available:
                logger.warning(f"네트워크 연속 오류 {self._network_error_count}회. 자동 새로고침 일시 중지.")
                self._network_available = False
                self._status_bar().showMessage("⚠ 네트워크 오류로 자동 새로고침 일시 중지 (수동 새로고침으로 재개)")
            return

        with QMutexLocker(self._refresh_mutex):
            if self._refresh_in_progress or self._sequential_refresh_active:
                logger.warning("새로고침이 이미 진행 중입니다. 건너킵니다.")
                return
            self._refresh_in_progress = True

        started = False
        try:
            started = self.refresh_all()
        except Exception as e:
            logger.error(f"자동 새로고침 오류: {e}")
        finally:
            if not started:
                with QMutexLocker(self._refresh_mutex):
                    self._refresh_in_progress = False

    def refresh_all(self: MainApp) -> bool:
        """모든 탭 새로고침 - 완전한 순차 새로고침 버전"""
        logger.info("전체 새로고침 시작")

        if self._sequential_refresh_active:
            logger.warning("순차 새로고침이 이미 진행 중입니다. 건너킵니다.")
            return False

        try:
            valid, msg = self._validate_api_credentials()
            if not valid:
                self._status_bar().showMessage(f"⚠ {msg}")
                logger.warning(f"API 자격증명 오류: {msg}")
                return False

            self._network_error_count = 0
            self._network_available = True

            try:
                self.bm_tab.load_data_from_db()
            except Exception as e:
                logger.error(f"북마크 탭 로드 오류: {e}")

            self._pending_refresh_keywords = []
            for _i, widget in self._iter_news_tabs(start_index=1):
                try:
                    if has_positive_keyword(widget.keyword):
                        self._pending_refresh_keywords.append(widget.keyword)
                except Exception as e:
                    logger.error(f"탭 접근 오류: {e}")

            if not self._pending_refresh_keywords:
                self._status_bar().showMessage("새로고침할 탭이 없습니다.")
                return False

            self._sequential_refresh_active = True
            self._current_refresh_idx = 0
            self._total_refresh_count = len(self._pending_refresh_keywords)
            self._sequential_added_count = 0
            self._sequential_dup_count = 0

            self.progress.setVisible(True)
            self.progress.setRange(0, self._total_refresh_count)
            self.progress.setValue(0)
            self._status_bar().showMessage(f"🔄 순차 새로고침 중... (0/{self._total_refresh_count})")
            self.btn_refresh.setEnabled(False)

            logger.info(f"순차 새로고침 시작: {self._total_refresh_count}개 탭")

            self._process_next_refresh()
            return True

        except Exception as e:
            logger.error(f"refresh_all 오류: {e}")
            traceback.print_exc()
            self._status_bar().showMessage(f"⚠ 새로고침 오류: {str(e)}")
            self._finish_sequential_refresh()
            return False

    def _process_next_refresh(self: MainApp):
        """순차 새로고침 체인: 다음 탭 처리"""
        if not self._sequential_refresh_active:
            return

        if self._current_refresh_idx >= len(self._pending_refresh_keywords):
            self._finish_sequential_refresh()
            return

        keyword = self._pending_refresh_keywords[self._current_refresh_idx]
        logger.info(f"순차 새로고침: [{self._current_refresh_idx + 1}/{self._total_refresh_count}] '{keyword}'")

        self.progress.setValue(self._current_refresh_idx)
        self._status_bar().showMessage(
            f"🔄 '{keyword}' 새로고침 중... ({self._current_refresh_idx + 1}/{self._total_refresh_count})"
        )

        try:
            self.fetch_news(keyword, is_sequential=True)
        except Exception as e:
            logger.error(f"'{keyword}' 새로고침 오류: {e}")
            self._current_refresh_idx += 1
            QTimer.singleShot(500, self._process_next_refresh)

    def _on_sequential_fetch_done(self: MainApp, keyword: str):
        """순차 새로고침에서 하나의 fetch 완료 시 호출"""
        if not self._sequential_refresh_active:
            return

        self._current_refresh_idx += 1
        QTimer.singleShot(300, self._process_next_refresh)

    def _finish_sequential_refresh(self: MainApp):
        """순차 새로고침 완료 처리"""
        self._sequential_refresh_active = False
        self._pending_refresh_keywords = []
        self._last_refresh_time = datetime.now()

        with QMutexLocker(self._refresh_mutex):
            self._refresh_in_progress = False

        self.progress.setValue(self._total_refresh_count)
        self.progress.setVisible(False)
        self.btn_refresh.setEnabled(True)

        added = self._sequential_added_count
        dup = self._sequential_dup_count

        logger.info(f"순차 새로고침 완료 ({self._total_refresh_count}개 탭, {added}건 추가, {dup}건 중복)")

        toast_msg = f"✓ {self._total_refresh_count}개 탭 새로고침 완료 ({added}건 추가"
        if dup > 0:
            toast_msg += f", {dup}건 중복"
        toast_msg += ")"

        self._status_bar().showMessage(toast_msg, 5000)
        self.show_toast(toast_msg)

        if self.notify_on_refresh and added > 0:
            self.show_tray_notification(
                "📰 자동 새로고침 완료",
                f"{added}건의 새 뉴스가 업데이트되었습니다."
            )

        self.apply_refresh_interval()

    def _next_worker_request_id(self: MainApp) -> int:
        self._worker_request_seq += 1
        return self._worker_request_seq

    def _is_active_worker_request(
        self: MainApp,
        keyword: str,
        request_id: Optional[int],
    ) -> bool:
        if request_id is None:
            return True
        return self._worker_registry.is_active(keyword, request_id)

    def _compute_load_more_state(
        self: MainApp,
        total: int,
        last_api_start_index: int,
    ) -> bool:
        total = max(0, int(total or 0))
        last_api_start_index = max(0, int(last_api_start_index or 0))
        next_start = last_api_start_index + 100
        has_more = next_start <= min(1000, total)
        return has_more

    def _apply_load_more_button_state(
        self: MainApp,
        tab_widget,
        total: int,
        last_api_start_index: int,
    ) -> bool:
        has_more = self._compute_load_more_state(total, last_api_start_index)
        if has_more:
            tab_widget.btn_load.setEnabled(True)
            tab_widget.btn_load.setText("📥 더 불러오기")
        else:
            tab_widget.btn_load.setEnabled(False)
            tab_widget.btn_load.setText("✅ 마지막 페이지")
        return has_more

    def fetch_news(
        self: MainApp,
        keyword: str,
        is_more: bool = False,
        is_sequential: bool = False,
    ):
        """뉴스 가져오기 - 순차 새로고침 지원"""
        search_keyword, exclude_words = parse_search_query(keyword)
        if not search_keyword:
            if not is_sequential:
                self.show_warning_toast("탭 키워드에 검색어가 없습니다. 탭 이름을 확인해주세요.")
            return
        db_keyword, _ = parse_tab_query(keyword)
        if not db_keyword:
            db_keyword = search_keyword
        fetch_key = build_fetch_key(search_keyword, exclude_words)

        if not is_more and not is_sequential:
            now_ts = time.time()
            last_ts = self._last_fetch_request_ts.get(fetch_key, 0.0)
            if (now_ts - last_ts) < self._fetch_dedupe_window_sec:
                logger.info(
                    f"PERF|net.fetch_deduped|0.00ms|kw={fetch_key}|window={self._fetch_dedupe_window_sec}s"
                )
                return
            self._last_fetch_request_ts[fetch_key] = now_ts

        fetch_state = self._tab_fetch_state.setdefault(keyword, self._make_tab_fetch_state())
        start_idx = 1
        if is_more:
            persisted_cursor = int(self._fetch_cursor_by_key.get(fetch_key, 0) or 0)
            if persisted_cursor > fetch_state.last_api_start_index:
                fetch_state.last_api_start_index = persisted_cursor
            if fetch_state.last_api_start_index > 0:
                start_idx = fetch_state.last_api_start_index + 100
            else:
                start_idx = 101
            if start_idx > 1000:
                QMessageBox.information(
                    self,
                    "알림",
                    "네이버 검색 API는 최대 1,000개까지만 조회할 수 있습니다.",
                )
                if is_sequential:
                    self._on_sequential_fetch_done(keyword)
                return

        old_handle = self._worker_registry.get_active_handle(keyword)
        if old_handle:
            self.cleanup_worker(keyword=keyword, request_id=old_handle.request_id, only_if_active=True)

        located_tab = self._find_news_tab(keyword)
        if located_tab is not None:
            _tab_index, w = located_tab
            w.btn_load.setEnabled(False)
            w.btn_load.setText("⏳ 로딩 중...")

        worker = ApiWorker(
            self.client_id,
            self.client_secret,
            search_keyword,
            db_keyword,
            exclude_words,
            self._require_db(),
            start_idx,
            timeout=self.api_timeout,
            display_keyword=keyword,
        )
        thread = QThread()
        worker.moveToThread(thread)

        request_id = self._next_worker_request_id()
        handle = WorkerHandle(
            request_id=request_id,
            tab_keyword=keyword,
            search_keyword=search_keyword,
            db_keyword=db_keyword,
            exclude_words=list(exclude_words),
            worker=worker,
            thread=thread,
        )
        self._request_start_index[request_id] = start_idx
        self._worker_registry.register(handle)
        self.workers[keyword] = (worker, thread)

        worker.finished.connect(
            lambda res, rid=request_id: self.on_fetch_done(res, keyword, is_more, is_sequential, rid)
        )
        worker.error.connect(
            lambda err, rid=request_id: self.on_fetch_error(err, keyword, is_sequential, rid)
        )
        if not is_sequential:
            worker.progress.connect(self._status_bar().showMessage)

        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)

        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda rid=request_id, kw=keyword: self.cleanup_worker(
                keyword=kw, request_id=rid, only_if_active=False
            )
        )

        thread.started.connect(worker.run)
        thread.start()

    def on_fetch_done(
        self: MainApp,
        result: Dict,
        keyword: str,
        is_more: bool,
        is_sequential: bool = False,
        request_id: Optional[int] = None,
    ):
        """뉴스 가져오기 완료 - 순차 새로고침 지원"""
        try:
            if not self._is_active_worker_request(keyword, request_id):
                logger.info(f"오래된 완료 콜백 무시 (stale on_fetch_done ignored): kw={keyword}, rid={request_id}")
                return

            search_keyword, exclude_words = parse_search_query(keyword)
            if not search_keyword:
                search_keyword = keyword
            fetch_key = build_fetch_key(search_keyword, exclude_words)

            added_count = result.get("added_count", 0)
            dup_count = result.get("dup_count", 0)
            completed_start_idx = None
            if request_id is not None:
                completed_start_idx = self._request_start_index.get(request_id)
                if completed_start_idx is not None:
                    self._tab_fetch_state.setdefault(keyword, self._make_tab_fetch_state()).last_api_start_index = completed_start_idx
                    if completed_start_idx > 0:
                        self._fetch_cursor_by_key[fetch_key] = int(completed_start_idx)

            located_tab = self._find_news_tab(keyword)
            if located_tab is not None:
                _tab_index, w = located_tab
                w.total_api_count = result["total"]
                w.update_timestamp()
                w.load_data_from_db()

                last_api_start_index = completed_start_idx
                if last_api_start_index is None:
                    last_api_start_index = self._tab_fetch_state.setdefault(
                        keyword,
                        self._make_tab_fetch_state(),
                    ).last_api_start_index
                total = int(result.get("total", 0) or 0)
                self._apply_load_more_button_state(w, total, last_api_start_index)
                if w.worker is not None:
                    w.worker.finished.connect(
                        lambda *_args, tab_ref=w, total_ref=total, start_idx_ref=last_api_start_index:
                        self._apply_load_more_button_state(tab_ref, total_ref, start_idx_ref)
                    )
                    w.worker.error.connect(
                        lambda *_args, tab_ref=w, total_ref=total, start_idx_ref=last_api_start_index:
                        self._apply_load_more_button_state(tab_ref, total_ref, start_idx_ref)
                    )

                if not is_more and not is_sequential:
                    msg = f"✓ '{keyword}' 업데이트 완료 ({added_count}건 추가"
                    if dup_count > 0:
                        msg += f", {dup_count}건 중복"
                    if result.get("filtered", 0) > 0:
                        msg += f", {result['filtered']}건 필터링"
                    msg += ")"
                    w.lbl_status.setText(msg)

            if not is_sequential:
                self.progress.setVisible(False)
                self.progress.setRange(0, 100)
                self.btn_refresh.setEnabled(True)

                if not is_more:
                    toast_msg = f"✓ '{keyword}' 업데이트 완료 ({added_count}건 추가"
                    if dup_count > 0:
                        toast_msg += f", {dup_count}건 유사"
                    toast_msg += ")"
                    self.show_toast(toast_msg)
                    self._status_bar().showMessage(toast_msg, 3000)

                    if added_count > 0:
                        self.show_desktop_notification(
                            f"📰 {keyword}",
                            f"{added_count}건의 새 뉴스가 있습니다."
                        )
                        if not self.isVisible():
                            self.show_tray_notification(
                                f"📰 {keyword}",
                                f"{added_count}건의 새 뉴스가 도착했습니다."
                            )
                        self.update_tray_tooltip()

                    matched = self.check_alert_keywords(result["items"])
                    if matched:
                        for item, kw in matched[:3]:
                            title = html.unescape(RE_HTML_TAGS.sub("", item.get("title", "")))
                            self.show_desktop_notification(
                                f"🔔 알림 키워드: {kw}",
                                title[:50]
                            )
            else:
                self._sequential_added_count += added_count
                self._sequential_dup_count += dup_count
                logger.info(f"순차 새로고침 완료: '{keyword}' ({added_count}건 추가)")
                self._on_sequential_fetch_done(keyword)

            self._network_error_count = 0
            self._network_available = True
            self.update_tab_badge(keyword)

        except Exception as e:
            logger.error(f"가져오기 완료 처리 오류 (Fetch Done Error): {e}")
            traceback.print_exc()
            self._status_bar().showMessage(f"⚠ 처리 중 오류: {str(e)}")
            if not is_sequential:
                self.progress.setVisible(False)
                self.btn_refresh.setEnabled(True)
            else:
                self._on_sequential_fetch_done(keyword)

    def on_fetch_error(
        self: MainApp,
        error_msg: str,
        keyword: str,
        is_sequential: bool = False,
        request_id: Optional[int] = None,
    ):
        """뉴스 가져오기 오류 - 순차 새로고침 지원"""
        if not self._is_active_worker_request(keyword, request_id):
            logger.info(f"오래된 오류 콜백 무시 (stale on_fetch_error ignored): kw={keyword}, rid={request_id}")
            return

        search_keyword, exclude_words = parse_search_query(keyword)
        if not search_keyword:
            search_keyword = keyword
        fetch_key = build_fetch_key(search_keyword, exclude_words)
        self._last_fetch_request_ts.pop(fetch_key, None)
        if request_id is not None:
            self._request_start_index.pop(request_id, None)

        located_tab = self._find_news_tab(keyword)
        if located_tab is not None:
            _tab_index, w = located_tab
            w.btn_load.setEnabled(True)
            w.btn_load.setText("📥 더 불러오기")

        if not is_sequential:
            self.progress.setVisible(False)
            self.progress.setRange(0, 100)
            self.btn_refresh.setEnabled(True)

            self._status_bar().showMessage(f"⚠ '{keyword}' 오류: {error_msg}", 5000)
            QMessageBox.critical(
                self,
                "API 오류",
                f"'{keyword}' 검색 중 오류가 발생했습니다:\n\n{error_msg}\n\n"
                "API 키가 올바른지, 네트워크 연결 상태를 확인해주세요."
            )
        else:
            logger.warning(f"순차 새로고침 중 오류: '{keyword}' - {error_msg}")
            self._on_sequential_fetch_done(keyword)

        network_error_keywords = ["네트워크", "timeout", "연결", "connection", "Timeout", "Network"]
        is_network_error = any(kw in error_msg for kw in network_error_keywords)
        if is_network_error:
            self._network_error_count += 1
            logger.warning(f"네트워크 오류 카운트: {self._network_error_count}/{self._max_network_errors}")
        else:
            self._network_error_count = 0

    def cleanup_worker(
        self: MainApp,
        keyword: Optional[str] = None,
        request_id: Optional[int] = None,
        only_if_active: bool = False,
    ):
        """워커 정리 - request_id 기반 안정성 개선"""
        try:
            if request_id is None and keyword:
                request_id = self._worker_registry.get_active_request_id(keyword)
            if request_id is None:
                return

            handle = self._worker_registry.get_by_request_id(request_id)
            if not handle:
                return

            if only_if_active and keyword and not self._worker_registry.is_active(keyword, request_id):
                return

            handle = self._worker_registry.pop_by_request_id(request_id)
            if not handle:
                return

            worker = handle.worker
            thread = handle.thread

            try:
                worker.finished.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass
            try:
                worker.error.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass
            try:
                worker.progress.disconnect()
            except (TypeError, RuntimeError, AttributeError):
                pass

            try:
                worker.stop()
            except (AttributeError, RuntimeError):
                pass

            try:
                thread.quit()
                thread.wait(1000)
            except (AttributeError, RuntimeError):
                pass

            self.workers.pop(handle.tab_keyword, None)
            self._request_start_index.pop(request_id, None)
            logger.info(f"워커 정리 완료: {handle.tab_keyword} (rid={request_id})")
        except Exception as e:
            logger.error(f"워커 정리 오류 (keyword={keyword}, rid={request_id}): {e}")

    def _validate_api_credentials(self: MainApp):
        from core.validation import ValidationUtils

        return ValidationUtils.validate_api_credentials(self.client_id, self.client_secret)
