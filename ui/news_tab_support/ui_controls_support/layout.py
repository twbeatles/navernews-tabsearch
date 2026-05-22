# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

from PyQt6.QtCore import QDate, QSignalBlocker, Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.styles import Colors
from ui.widgets import NewsBrowser, NoScrollComboBox


class _NewsTabUILayoutMixin:
    def setup_ui(self):
        """UI 설정"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        filter_card = QFrame()
        filter_card.setObjectName("FilterCard")
        is_dark = self.theme == 1
        filter_card.setStyleSheet(
            f"""
            QFrame#FilterCard {{
                background-color: {Colors.DARK_CARD_BG if is_dark else Colors.LIGHT_CARD_BG};
                border: 1px solid {Colors.DARK_BORDER if is_dark else Colors.LIGHT_BORDER};
                border-radius: 10px;
                padding: 8px;
            }}
        """
        )

        filter_layout = QVBoxLayout(filter_card)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        filter_layout.setSpacing(8)

        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(10)

        self.inp_filter = QLineEdit()
        self.inp_filter.setPlaceholderText("🔍 제목 또는 내용으로 필터링...")
        self.inp_filter.setClearButtonEnabled(True)

        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self._apply_filter_debounced)
        self.inp_filter.textChanged.connect(self._on_filter_changed)

        self.combo_sort = NoScrollComboBox()
        self.combo_sort.addItems(["최신순", "오래된순"])
        self.combo_sort.currentIndexChanged.connect(self._on_sort_changed)

        row1_layout.addWidget(self.inp_filter, 4)
        row1_layout.addWidget(self.combo_sort, 1)
        filter_layout.addLayout(row1_layout)

        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(12)

        self.chk_unread = QCheckBox("안 읽은 것만")
        self.chk_unread.stateChanged.connect(self._on_unread_filter_changed)

        self.chk_hide_dup = QCheckBox("중복 숨김")
        self.chk_hide_dup.stateChanged.connect(self._on_hide_duplicates_changed)

        self.chk_preferred_publishers = QCheckBox("선호 출처만")
        self.chk_preferred_publishers.stateChanged.connect(self._on_preferred_publishers_changed)

        self.combo_tag_filter = NoScrollComboBox()
        self.combo_tag_filter.setEditable(True)
        self.combo_tag_filter.setMinimumWidth(130)
        self.combo_tag_filter.currentTextChanged.connect(lambda _text: self._on_tag_filter_changed())
        self._refresh_tag_filter_options()

        row2_layout.addWidget(self.chk_unread)
        row2_layout.addWidget(self.chk_hide_dup)
        row2_layout.addWidget(self.chk_preferred_publishers)
        row2_layout.addWidget(QLabel("태그:"))
        row2_layout.addWidget(self.combo_tag_filter)

        self.btn_date_toggle = QToolButton()
        self.btn_date_toggle.setText("📅 기간")
        self.btn_date_toggle.setCheckable(True)
        self.btn_date_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_date_toggle.toggled.connect(self._toggle_date_filter)

        self.date_container = QWidget()
        date_inner_layout = QHBoxLayout(self.date_container)
        date_inner_layout.setContentsMargins(0, 0, 0, 0)
        date_inner_layout.setSpacing(4)

        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        self.date_start.setMinimumWidth(120)
        self.date_start.setDate(QDate.currentDate().addDays(-7))
        self.date_start.dateChanged.connect(self._on_date_start_changed)

        self.lbl_tilde = QLabel("~")

        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        self.date_end.setMinimumWidth(120)
        self.date_end.setDate(QDate.currentDate())
        self.date_end.dateChanged.connect(self._on_date_end_changed)

        self.btn_apply_date = QPushButton("적용")
        self.btn_apply_date.clicked.connect(self._apply_date_filter)

        self.btn_clear_date = QPushButton("해제")
        self.btn_clear_date.clicked.connect(self._clear_date_filter)

        date_inner_layout.addWidget(self.date_start)
        date_inner_layout.addWidget(self.lbl_tilde)
        date_inner_layout.addWidget(self.date_end)
        date_inner_layout.addWidget(self.btn_apply_date)
        date_inner_layout.addWidget(self.btn_clear_date)

        row2_layout.addWidget(self.btn_date_toggle)
        row2_layout.addWidget(self.date_container)
        row2_layout.addStretch()
        filter_layout.addLayout(row2_layout)

        row3_layout = QHBoxLayout()
        row3_layout.setSpacing(6)
        self.combo_saved_search = NoScrollComboBox()
        self.combo_saved_search.setMinimumWidth(180)
        self.btn_apply_saved_search = QPushButton("적용")
        self.btn_apply_saved_search.clicked.connect(self._apply_saved_search)
        self.btn_save_search = QPushButton("검색 저장")
        self.btn_save_search.clicked.connect(self._save_current_search)
        self.btn_delete_search = QPushButton("삭제")
        self.btn_delete_search.clicked.connect(self._delete_saved_search)
        row3_layout.addWidget(QLabel("저장 검색:"))
        row3_layout.addWidget(self.combo_saved_search)
        row3_layout.addWidget(self.btn_apply_saved_search)
        row3_layout.addWidget(self.btn_save_search)
        row3_layout.addWidget(self.btn_delete_search)
        row3_layout.addStretch()
        filter_layout.addLayout(row3_layout)
        self._refresh_saved_search_combo()

        self.date_container.setVisible(False)
        self._update_date_toggle_style(False)
        self._refresh_date_filter_controls()

        layout.addWidget(filter_card)

        self.browser = NewsBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self.on_link_clicked)
        self.browser.action_triggered.connect(self.on_browser_action)
        layout.addWidget(self.browser)

        btm_layout = QHBoxLayout()

        self.btn_load = QPushButton("📥 더 불러오기")
        self.btn_read_all = QPushButton("✓ 모두 읽음")
        self.btn_top = QPushButton("⬆ 맨 위로")
        self.lbl_status = QLabel("대기 중")

        if self.is_bookmark_tab:
            self.btn_load.hide()

        btm_layout.addWidget(self.btn_load)
        btm_layout.addWidget(self.btn_read_all)
        btm_layout.addWidget(self.btn_top)
        btm_layout.addStretch()
        btm_layout.addWidget(self.lbl_status)
        layout.addLayout(btm_layout)

        self.btn_top.clicked.connect(lambda: self._browser_scroll_bar().setValue(0))
        self.btn_read_all.clicked.connect(self.mark_all_read)
