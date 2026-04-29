# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.query_parser import build_fetch_key, parse_search_query, parse_tab_query
from core.workers import InterruptibleReadWorker

if TYPE_CHECKING:
    from ui.main_window import MainApp


class _MainWindowAnalysisMixin:
    def _cleanup_analysis_worker(self: MainApp, worker: Optional[Any]) -> None:
        if worker is None:
            return
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

        tab_widget.addTab(stats_widget, "전체 통계")
        tab_widget.addTab(analysis_widget, "언론사 분석")
        main_layout.addWidget(tab_widget)

        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        main_layout.addWidget(btn_close)

        state: Dict[str, Any] = {
            "stats_worker": None,
            "publisher_worker": None,
            "publisher_request_id": 0,
        }

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

        def load_publishers(conn, tab_query: Optional[str]) -> List[tuple[str, int]]:
            if isinstance(tab_query, str) and tab_query.strip():
                db_keyword, exclude_words = parse_tab_query(tab_query)
                search_keyword, _ = parse_search_query(tab_query)
                query_key = build_fetch_key(search_keyword, exclude_words)
                return self._require_db().get_top_publishers(
                    db_keyword,
                    exclude_words=exclude_words,
                    blocked_publishers=getattr(self, "blocked_publishers", []),
                    preferred_publishers=getattr(self, "preferred_publishers", []),
                    limit=20,
                    query_key=query_key,
                    conn=conn,
                )
            return self._require_db().get_top_publishers(
                None,
                blocked_publishers=getattr(self, "blocked_publishers", []),
                preferred_publishers=getattr(self, "preferred_publishers", []),
                limit=20,
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
            worker.finished.connect(lambda *_args: state.__setitem__("publisher_worker", None))
            worker.error.connect(lambda *_args: state.__setitem__("publisher_worker", None))
            worker.cancelled.connect(lambda *_args: state.__setitem__("publisher_worker", None))
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
        stats_worker.finished.connect(lambda *_args: state.__setitem__("stats_worker", None))
        stats_worker.error.connect(lambda *_args: state.__setitem__("stats_worker", None))
        stats_worker.cancelled.connect(lambda *_args: state.__setitem__("stats_worker", None))

        def cleanup_workers(_result: int) -> None:
            self._cleanup_analysis_worker(state.get("stats_worker"))
            self._cleanup_analysis_worker(state.get("publisher_worker"))
            state["stats_worker"] = None
            state["publisher_worker"] = None

        dialog.finished.connect(cleanup_workers)
        tab_combo.currentIndexChanged.connect(lambda _index: update_analysis())

        stats_worker.start()
        update_analysis()
        dialog.exec()

    def show_analysis(self: MainApp):
        """언론사별 분석 (호환성 유지)"""
        self.show_stats_analysis()
