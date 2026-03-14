# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.query_parser import build_fetch_key, parse_search_query, parse_tab_query

if TYPE_CHECKING:
    from ui.main_window import MainApp


class _MainWindowAnalysisMixin:
    def show_statistics(self: MainApp):
        """통계 정보 표시"""
        stats = self._require_db().get_statistics()

        if stats["total"] > 0:
            read_count = stats["total"] - stats["unread"]
            read_percent = (read_count / stats["total"]) * 100
        else:
            read_percent = 0

        dialog = QDialog(self)
        dialog.setWindowTitle("통계 정보")
        dialog.resize(350, 350)

        layout = QVBoxLayout(dialog)

        group = QGroupBox("📊 데이터베이스 통계")
        grid = QGridLayout()

        items = [
            ("총 기사 수:", f"{stats['total']:,}개"),
            ("안 읽은 기사:", f"{stats['unread']:,}개"),
            ("읽은 기사:", f"{stats['total'] - stats['unread']:,}개"),
            ("북마크:", f"{stats['bookmarked']:,}개"),
            ("메모 작성:", f"{stats['with_notes']:,}개"),
            ("중복 기사:", f"{stats['duplicates']:,}개"),
            ("읽은 비율:", f"{read_percent:.1f}%"),
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
        layout.addWidget(group)

        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)

        dialog.exec()

    def show_stats_analysis(self: MainApp):
        """통계 및 분석 통합 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("📊 통계 및 분석")
        dialog.resize(550, 500)

        main_layout = QVBoxLayout(dialog)
        tab_widget = QTabWidget()

        stats_widget = QWidget()
        stats_layout = QVBoxLayout(stats_widget)

        stats = self._require_db().get_statistics()
        if stats["total"] > 0:
            read_percent = ((stats["total"] - stats["unread"]) / stats["total"]) * 100
        else:
            read_percent = 0

        group = QGroupBox("📊 데이터베이스 통계")
        grid = QGridLayout()

        items = [
            ("총 기사 수:", f"{stats['total']:,}개"),
            ("안 읽은 기사:", f"{stats['unread']:,}개"),
            ("읽은 기사:", f"{stats['total'] - stats['unread']:,}개"),
            ("북마크:", f"{stats['bookmarked']:,}개"),
            ("메모 작성:", f"{stats['with_notes']:,}개"),
            ("중복 기사:", f"{stats['duplicates']:,}개"),
            ("읽은 비율:", f"{read_percent:.1f}%"),
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
        stats_layout.addWidget(group)
        stats_layout.addStretch()

        analysis_widget = QWidget()
        analysis_layout = QVBoxLayout(analysis_widget)

        tab_label = QLabel("분석할 탭을 선택하세요:")
        analysis_layout.addWidget(tab_label)

        tab_combo = QComboBox()
        tab_combo.addItem("전체", None)
        for _index, w in self._iter_news_tabs(start_index=1):
            db_kw = w.db_keyword
            if not db_kw:
                continue
            tab_combo.addItem(w.keyword, w.keyword)
        analysis_layout.addWidget(tab_combo)

        result_label = QLabel("📈 언론사별 기사 수:")
        result_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        analysis_layout.addWidget(result_label)

        result_list = QListWidget()
        analysis_layout.addWidget(result_list)

        def update_analysis():
            result_list.clear()
            tab_query = tab_combo.currentData()
            if isinstance(tab_query, str) and tab_query.strip():
                db_keyword, exclude_words = parse_tab_query(tab_query)
                search_keyword, _ = parse_search_query(tab_query)
                query_key = build_fetch_key(search_keyword, exclude_words)
                publishers = self._require_db().get_top_publishers(
                    db_keyword,
                    exclude_words=exclude_words,
                    limit=20,
                    query_key=query_key,
                )
            else:
                publishers = self._require_db().get_top_publishers(None, limit=20)

            if publishers:
                for i, (pub, count) in enumerate(publishers, 1):
                    result_list.addItem(f"{i}. {pub}: {count:,}개")
            else:
                result_list.addItem("데이터가 없습니다.")

        tab_combo.currentIndexChanged.connect(update_analysis)
        update_analysis()

        tab_widget.addTab(stats_widget, "📊 통계")
        tab_widget.addTab(analysis_widget, "📈 언론사 분석")

        main_layout.addWidget(tab_widget)

        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        main_layout.addWidget(btn_close)

        dialog.exec()

    def show_analysis(self: MainApp):
        """언론사별 분석 (호환성 유지)"""
        self.show_stats_analysis()
