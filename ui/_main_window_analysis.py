# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.content_filters import normalize_publisher_filter_lists
from core.query_parser import build_fetch_key, parse_search_query, parse_tab_query
from core.workers import InterruptibleReadWorker, retain_worker_until_finished

if TYPE_CHECKING:
    from ui.main_window import MainApp


class _MainWindowAnalysisMixin:
    def _cleanup_analysis_worker(self: MainApp, worker: Optional[Any], wait_ms: int = 600) -> bool:
        if worker is None:
            return True
        try:
            worker.finished.disconnect()
        except Exception:
            pass
        try:
            worker.error.disconnect()
        except Exception:
            pass
        try:
            worker.cancelled.disconnect()
        except Exception:
            pass
        try:
            if worker.isRunning():
                worker.stop()
        except Exception:
            pass
        try:
            finished = not worker.isRunning() or worker.wait(max(0, int(wait_ms)))
        except Exception:
            finished = False
        if finished:
            try:
                worker.deleteLater()
            except Exception:
                pass
            return True
        try:
            worker.setParent(None)
        except Exception:
            pass
        retain_worker_until_finished(worker)
        return False

    def show_statistics(self: MainApp):
        """통계 정보 표시"""
        if self.should_block_db_action("통계 보기"):
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("통계 정보")
        dialog.resize(350, 350)

        layout = QVBoxLayout(dialog)
        loading_label = QLabel("통계 정보를 불러오는 중...")
        layout.addWidget(loading_label)

        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)

        def load_stats(conn) -> Dict[str, int]:
            return self._require_db().get_statistics(
                blocked_publishers=getattr(self, "blocked_publishers", []),
                conn=conn,
            )

        worker = InterruptibleReadWorker(self._require_db(), load_stats, parent=dialog)

        def render_stats(stats: Dict[str, int]) -> None:
            if not dialog.isVisible():
                return
            loading_label.deleteLater()
            if stats["total"] > 0:
                read_count = stats["total"] - stats["unread"]
                read_percent = (read_count / stats["total"]) * 100
            else:
                read_percent = 0

            group = QGroupBox("표시 기준 전체 통계")
            grid = QGridLayout()
            items = [
                ("총 기사 수:", f"{stats['total']:,}개"),
                ("미읽음 기사:", f"{stats['unread']:,}개"),
                ("읽은 기사:", f"{stats['total'] - stats['unread']:,}개"),
                ("북마크:", f"{stats['bookmarked']:,}개"),
                ("메모 작성:", f"{stats['with_notes']:,}개"),
                ("중복 기사:", f"{stats['duplicates']:,}개"),
                ("읽음 비율:", f"{read_percent:.1f}%"),
                ("탭 개수:", f"{self.tabs.count() - 1}개"),
            ]
            for i, (label, value) in enumerate(items):
                lbl = QLabel(label)
                lbl.setStyleSheet("font-weight: bold;")
                val = QLabel(value)
                val.setStyleSheet("color: #007AFF;" if self.theme_idx == 0 else "color: #0A84FF;")
                grid.addWidget(lbl, i, 0, Qt.AlignmentFlag.AlignRight)
                grid.addWidget(val, i, 1, Qt.AlignmentFlag.AlignLeft)
            group.setLayout(grid)
            layout.insertWidget(0, group)

        def handle_error(error_msg: str) -> None:
            if not dialog.isVisible():
                return
            QMessageBox.warning(
                dialog,
                "통계 오류",
                f"통계 정보를 불러오지 못했습니다.\n\n{error_msg}",
            )
            dialog.reject()

        worker.finished.connect(render_stats)
        worker.error.connect(handle_error)
        dialog.finished.connect(lambda _result: self._cleanup_analysis_worker(worker))
        worker.start()
        dialog.exec()

    def show_stats_analysis(self: MainApp):
        """통계 및 분석 통합 다이얼로그"""
        if self.should_block_db_action("통계/분석 보기"):
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("통계 및 분석")
        dialog.resize(550, 500)

        main_layout = QVBoxLayout(dialog)
        tab_widget = QTabWidget()

        stats_widget = QWidget()
        stats_layout = QVBoxLayout(stats_widget)
        stats_loading = QLabel("통계 정보를 불러오는 중...")
        stats_layout.addWidget(stats_loading)
        stats_layout.addStretch()

        analysis_widget = QWidget()
        analysis_layout = QVBoxLayout(analysis_widget)
        tab_label = QLabel("분석할 탭을 선택하세요")
        analysis_layout.addWidget(tab_label)

        tab_combo = QComboBox()
        tab_combo.addItem("전체", None)
        for _index, w in self._iter_news_tabs(start_index=1):
            db_kw = w.db_keyword
            if not db_kw:
                continue
            tab_combo.addItem(w.keyword, w.keyword)
        analysis_layout.addWidget(tab_combo)

        result_label = QLabel("상위 언론사 기사 수")
        result_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        analysis_layout.addWidget(result_label)

        result_list = QListWidget()
        result_list.addItem("불러오는 중...")
        analysis_layout.addWidget(result_list)

        tag_widget = QWidget()
        tag_layout = QVBoxLayout(tag_widget)
        tag_label = QLabel("상위 태그 기사 수")
        tag_label.setStyleSheet("font-weight: bold;")
        tag_layout.addWidget(tag_label)
        tag_list = QListWidget()
        tag_list.addItem("불러오는 중...")
        tag_layout.addWidget(tag_list)

        simulation_widget = QWidget()
        simulation_layout = QVBoxLayout(simulation_widget)
        sim_tab_label = QLabel("시뮬레이션할 탭을 선택하세요")
        simulation_layout.addWidget(sim_tab_label)
        sim_tab_combo = QComboBox()
        sim_tab_combo.addItem("전체", None)
        for _index, w in self._iter_news_tabs(start_index=1):
            if getattr(w, "db_keyword", ""):
                sim_tab_combo.addItem(w.keyword, w.keyword)
        simulation_layout.addWidget(sim_tab_combo)

        blocked_input = QLineEdit()
        blocked_input.setPlaceholderText("차단 출처 예: example.com, 언론사")
        preferred_input = QLineEdit()
        preferred_input.setPlaceholderText("선호 출처 예: example.com, 언론사")
        only_preferred_chk = QCheckBox("선호 출처만")
        simulation_layout.addWidget(blocked_input)
        simulation_layout.addWidget(preferred_input)
        sim_controls = QHBoxLayout()
        sim_controls.addWidget(only_preferred_chk)
        btn_simulate = QPushButton("시뮬레이션")
        sim_controls.addWidget(btn_simulate)
        sim_controls.addStretch()
        simulation_layout.addLayout(sim_controls)

        sim_result_list = QListWidget()
        sim_result_list.addItem("시뮬레이션 버튼을 누르세요.")
        simulation_layout.addWidget(sim_result_list)

        tab_widget.addTab(stats_widget, "전체 통계")
        tab_widget.addTab(analysis_widget, "언론사 분석")
        tab_widget.addTab(tag_widget, "태그 통계")
        tab_widget.addTab(simulation_widget, "출처 필터 시뮬레이션")
        main_layout.addWidget(tab_widget)

        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        main_layout.addWidget(btn_close)

        state: Dict[str, Any] = {
            "stats_worker": None,
            "publisher_worker": None,
            "tag_worker": None,
            "sim_worker": None,
            "publisher_request_id": 0,
            "tag_request_id": 0,
            "sim_request_id": 0,
        }

        def clear_worker_state(key: str, worker_ref: Any) -> None:
            if state.get(key) is worker_ref:
                state[key] = None

        def load_stats(conn) -> Dict[str, int]:
            return self._require_db().get_statistics(
                blocked_publishers=getattr(self, "blocked_publishers", []),
                conn=conn,
            )

        def render_stats(stats: Dict[str, int]) -> None:
            if not dialog.isVisible():
                return
            stats_loading.deleteLater()
            if stats["total"] > 0:
                read_percent = ((stats["total"] - stats["unread"]) / stats["total"]) * 100
            else:
                read_percent = 0

            group = QGroupBox("표시 기준 전체 통계")
            grid = QGridLayout()
            items = [
                ("총 기사 수:", f"{stats['total']:,}개"),
                ("미읽음 기사:", f"{stats['unread']:,}개"),
                ("읽은 기사:", f"{stats['total'] - stats['unread']:,}개"),
                ("북마크:", f"{stats['bookmarked']:,}개"),
                ("메모 작성:", f"{stats['with_notes']:,}개"),
                ("중복 기사:", f"{stats['duplicates']:,}개"),
                ("읽음 비율:", f"{read_percent:.1f}%"),
                ("탭 개수:", f"{self.tabs.count() - 1}개"),
            ]
            for i, (label, value) in enumerate(items):
                lbl = QLabel(label)
                lbl.setStyleSheet("font-weight: bold;")
                val = QLabel(value)
                val.setStyleSheet("color: #007AFF;" if self.theme_idx == 0 else "color: #0A84FF;")
                grid.addWidget(lbl, i, 0, Qt.AlignmentFlag.AlignRight)
                grid.addWidget(val, i, 1, Qt.AlignmentFlag.AlignLeft)
            group.setLayout(grid)
            stats_layout.insertWidget(0, group)

        def render_publishers(publishers: List[tuple[str, int]], request_id: int) -> None:
            if not dialog.isVisible() or request_id != state["publisher_request_id"]:
                return
            result_list.clear()
            if publishers:
                for i, (pub, count) in enumerate(publishers, 1):
                    result_list.addItem(f"{i}. {pub}: {count:,}개")
            else:
                result_list.addItem("데이터가 없습니다.")

        def render_tags(tags: List[tuple[str, int]], request_id: int) -> None:
            if not dialog.isVisible() or request_id != state["tag_request_id"]:
                return
            tag_list.clear()
            if tags:
                for i, (tag, count) in enumerate(tags, 1):
                    tag_list.addItem(f"{i}. {tag}: {count:,}개")
            else:
                tag_list.addItem("태그 데이터가 없습니다.")

        def render_simulation(publishers: List[tuple[str, int]], request_id: int) -> None:
            if not dialog.isVisible() or request_id != state["sim_request_id"]:
                return
            sim_result_list.clear()
            if publishers:
                for i, (pub, count) in enumerate(publishers, 1):
                    sim_result_list.addItem(f"{i}. {pub}: {count:,}개")
            else:
                sim_result_list.addItem("해당 조건의 데이터가 없습니다.")

        def _split_publishers(raw: str) -> List[str]:
            return [part.strip() for part in str(raw or "").split(",") if part.strip()]

        def load_publishers(
            conn,
            tab_query: Optional[str],
            blocked_publishers: Optional[List[str]] = None,
            preferred_publishers: Optional[List[str]] = None,
            only_preferred_publishers: bool = False,
        ) -> List[tuple[str, int]]:
            blocked = getattr(self, "blocked_publishers", []) if blocked_publishers is None else blocked_publishers
            preferred = (
                getattr(self, "preferred_publishers", [])
                if preferred_publishers is None
                else preferred_publishers
            )
            if isinstance(tab_query, str) and tab_query.strip():
                db_keyword, exclude_words = parse_tab_query(tab_query)
                search_keyword, _ = parse_search_query(tab_query)
                query_key = build_fetch_key(search_keyword, exclude_words)
                return self._require_db().get_top_publishers(
                    db_keyword,
                    exclude_words=exclude_words,
                    blocked_publishers=blocked,
                    preferred_publishers=preferred,
                    only_preferred_publishers=only_preferred_publishers,
                    limit=20,
                    query_key=query_key,
                    conn=conn,
                )
            return self._require_db().get_top_publishers(
                None,
                blocked_publishers=blocked,
                preferred_publishers=preferred,
                only_preferred_publishers=only_preferred_publishers,
                limit=20,
                conn=conn,
            )

        def load_tags(conn) -> List[tuple[str, int]]:
            return self._require_db().get_top_tags(
                limit=20,
                blocked_publishers=getattr(self, "blocked_publishers", []),
                preferred_publishers=getattr(self, "preferred_publishers", []),
                conn=conn,
            )

        def update_analysis() -> None:
            state["publisher_request_id"] += 1
            request_id = int(state["publisher_request_id"])
            result_list.clear()
            result_list.addItem("불러오는 중...")
            self._cleanup_analysis_worker(state["publisher_worker"])
            tab_query = tab_combo.currentData()
            worker = InterruptibleReadWorker(self._require_db(), load_publishers, tab_query, parent=dialog)
            state["publisher_worker"] = worker
            worker.finished.connect(lambda publishers, rid=request_id: render_publishers(publishers, rid))
            worker.error.connect(
                lambda error_msg, rid=request_id: (
                    rid == state["publisher_request_id"]
                    and dialog.isVisible()
                    and (
                        result_list.clear(),
                        result_list.addItem("언론사 분석 데이터를 불러오지 못했습니다."),
                        QMessageBox.warning(
                            dialog,
                            "분석 오류",
                            f"언론사 분석 데이터를 불러오지 못했습니다.\n\n{error_msg}",
                        ),
                    )
                )
            )
            worker.finished.connect(lambda *_args, worker_ref=worker: clear_worker_state("publisher_worker", worker_ref))
            worker.error.connect(lambda *_args, worker_ref=worker: clear_worker_state("publisher_worker", worker_ref))
            worker.cancelled.connect(lambda *_args, worker_ref=worker: clear_worker_state("publisher_worker", worker_ref))
            worker.start()

        def update_tags() -> None:
            state["tag_request_id"] += 1
            request_id = int(state["tag_request_id"])
            tag_list.clear()
            tag_list.addItem("불러오는 중...")
            self._cleanup_analysis_worker(state["tag_worker"])
            worker = InterruptibleReadWorker(self._require_db(), load_tags, parent=dialog)
            state["tag_worker"] = worker
            worker.finished.connect(lambda tags, rid=request_id: render_tags(tags, rid))
            worker.error.connect(
                lambda error_msg, rid=request_id: (
                    rid == state["tag_request_id"]
                    and dialog.isVisible()
                    and (
                        tag_list.clear(),
                        tag_list.addItem("태그 통계를 불러오지 못했습니다."),
                        QMessageBox.warning(
                            dialog,
                            "분석 오류",
                            f"태그 통계를 불러오지 못했습니다.\n\n{error_msg}",
                        ),
                    )
                )
            )
            worker.finished.connect(lambda *_args, worker_ref=worker: clear_worker_state("tag_worker", worker_ref))
            worker.error.connect(lambda *_args, worker_ref=worker: clear_worker_state("tag_worker", worker_ref))
            worker.cancelled.connect(lambda *_args, worker_ref=worker: clear_worker_state("tag_worker", worker_ref))
            worker.start()

        def update_simulation() -> None:
            state["sim_request_id"] += 1
            request_id = int(state["sim_request_id"])
            sim_result_list.clear()
            sim_result_list.addItem("불러오는 중...")
            self._cleanup_analysis_worker(state["sim_worker"])
            blocked, preferred = normalize_publisher_filter_lists(
                _split_publishers(blocked_input.text()),
                _split_publishers(preferred_input.text()),
            )
            worker = InterruptibleReadWorker(
                self._require_db(),
                load_publishers,
                sim_tab_combo.currentData(),
                blocked,
                preferred,
                only_preferred_chk.isChecked(),
                parent=dialog,
            )
            state["sim_worker"] = worker
            worker.finished.connect(lambda publishers, rid=request_id: render_simulation(publishers, rid))
            worker.error.connect(
                lambda error_msg, rid=request_id: (
                    rid == state["sim_request_id"]
                    and dialog.isVisible()
                    and (
                        sim_result_list.clear(),
                        sim_result_list.addItem("시뮬레이션 데이터를 불러오지 못했습니다."),
                        QMessageBox.warning(
                            dialog,
                            "분석 오류",
                            f"시뮬레이션 데이터를 불러오지 못했습니다.\n\n{error_msg}",
                        ),
                    )
                )
            )
            worker.finished.connect(lambda *_args, worker_ref=worker: clear_worker_state("sim_worker", worker_ref))
            worker.error.connect(lambda *_args, worker_ref=worker: clear_worker_state("sim_worker", worker_ref))
            worker.cancelled.connect(lambda *_args, worker_ref=worker: clear_worker_state("sim_worker", worker_ref))
            worker.start()

        stats_worker = InterruptibleReadWorker(self._require_db(), load_stats, parent=dialog)
        state["stats_worker"] = stats_worker
        stats_worker.finished.connect(render_stats)
        stats_worker.error.connect(
            lambda error_msg: dialog.isVisible()
            and QMessageBox.warning(
                dialog,
                "분석 오류",
                f"통계 및 분석 정보를 불러오지 못했습니다.\n\n{error_msg}",
            )
        )
        stats_worker.finished.connect(lambda *_args, worker_ref=stats_worker: clear_worker_state("stats_worker", worker_ref))
        stats_worker.error.connect(lambda *_args, worker_ref=stats_worker: clear_worker_state("stats_worker", worker_ref))
        stats_worker.cancelled.connect(lambda *_args, worker_ref=stats_worker: clear_worker_state("stats_worker", worker_ref))

        def cleanup_workers(_result: int) -> None:
            self._cleanup_analysis_worker(state.get("stats_worker"))
            self._cleanup_analysis_worker(state.get("publisher_worker"))
            self._cleanup_analysis_worker(state.get("tag_worker"))
            self._cleanup_analysis_worker(state.get("sim_worker"))
            state["stats_worker"] = None
            state["publisher_worker"] = None
            state["tag_worker"] = None
            state["sim_worker"] = None

        dialog.finished.connect(cleanup_workers)
        tab_combo.currentIndexChanged.connect(lambda _index: update_analysis())
        btn_simulate.clicked.connect(update_simulation)
        sim_tab_combo.currentIndexChanged.connect(lambda _index: update_simulation())

        stats_worker.start()
        update_analysis()
        update_tags()
        dialog.exec()

    def show_analysis(self: MainApp):
        """언론사별 분석 (호환성 유지)"""
        self.show_stats_analysis()
