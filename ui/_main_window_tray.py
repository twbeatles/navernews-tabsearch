# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import inspect
import logging
import os
import traceback
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtWidgets import QMenu, QMessageBox, QStyle, QSystemTrayIcon

from core.constants import APP_NAME

if TYPE_CHECKING:
    from ui.main_window import MainApp


logger = logging.getLogger(__name__)


class _MainWindowTrayMixin:
    def _cleanup_open_tabs_for_shutdown(self: MainApp) -> None:
        for _index, tab in self._iter_news_tabs():
            try:
                tab.cleanup()
            except Exception as e:
                logger.warning("탭 종료 정리 오류 (%s): %s", getattr(tab, "keyword", "?"), e)

    def setup_system_tray(self: MainApp):
        """시스템 트레이 아이콘 설정"""
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                logger.warning("시스템 트레이를 사용할 수 없습니다.")
                self.tray = None
                return

            self.tray = QSystemTrayIcon(self)

            icon_path = self._resolve_icon_path()

            if icon_path and os.path.exists(icon_path):
                self.tray.setIcon(QIcon(icon_path))
            else:
                self.tray.setIcon(self._style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))

            tray_menu = QMenu(self)

            action_show = self._add_menu_action(tray_menu, "📰 열기")
            action_show.triggered.connect(self.show_window)

            action_refresh = self._add_menu_action(tray_menu, "🔄 새로고침")
            action_refresh.triggered.connect(self._safe_refresh_all)

            tray_menu.addSeparator()

            action_settings = self._add_menu_action(tray_menu, "⚙ 설정")
            action_settings.triggered.connect(self.open_settings)

            tray_menu.addSeparator()

            action_quit = self._add_menu_action(tray_menu, "❌ 종료")
            action_quit.triggered.connect(self.real_quit)

            self.tray.setContextMenu(tray_menu)
            self.tray.activated.connect(self.on_tray_activated)
            self.update_tray_tooltip()
            self.tray.show()

            logger.info("시스템 트레이 아이콘 설정 완료")
        except Exception as e:
            logger.error(f"시스템 트레이 설정 오류: {e}")
            self.tray = None

    def on_tray_activated(self: MainApp, reason):
        """트레이 아이콘 활성화 이벤트 처리"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.update_tray_tooltip()

    def update_tray_tooltip(self: MainApp):
        """트레이 아이콘 툴팁 업데이트 (읽지 않은 기사 수 표시)"""
        if not hasattr(self, "tray") or not self.tray:
            return

        try:
            if self.is_maintenance_mode_active():
                self.tray.setToolTip(f"{APP_NAME}\nDB ?좎?蹂댁닔 以?..")
                return

            unread_count = int(self.db.get_total_unread_count()) if self.db else 0

            if unread_count > 0:
                tooltip = f"{APP_NAME}\n📬 읽지 않은 기사: {unread_count:,}개"
            else:
                tooltip = f"{APP_NAME}\n✅ 모든 기사를 읽었습니다"

            self.tray.setToolTip(tooltip)
        except Exception as e:
            logger.warning(f"트레이 툴팁 업데이트 오류: {e}")
            self.tray.setToolTip(APP_NAME)

    def show_window(self: MainApp):
        """창 표시 (트레이에서 복원)"""
        if self.isHidden():
            self.show()
        if self.isMinimized():
            self.setWindowState(
                (self.windowState() & ~Qt.WindowState.WindowMinimized)
                | Qt.WindowState.WindowActive
            )
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.update_tray_tooltip()

    def real_quit(self: MainApp):
        """프로그램 완전 종료 (트레이 메뉴에서 호출)"""
        logger.info("사용자가 트레이 메뉴에서 종료 요청")
        self._user_requested_close = True
        self._force_close = True

        try:
            self.save_config()
        except Exception as e:
            logger.error(f"종료 전 설정 저장 오류: {e}")

        if hasattr(self, "tray") and self.tray:
            self.tray.hide()

        self.close()

    def show_tray_notification(
        self: MainApp,
        title: str,
        message: str,
        icon_type=None,
    ):
        """시스템 트레이 알림 표시 (새 뉴스 도착 등)"""
        if not hasattr(self, "tray") or not self.tray:
            fallback = getattr(self, "show_desktop_notification", None)
            if callable(fallback):
                fallback(title, message)
            return

        try:
            if icon_type is None:
                icon_type = QSystemTrayIcon.MessageIcon.Information

            self.tray.showMessage(
                title,
                message,
                icon_type,
                5000
            )
        except Exception as e:
            logger.warning(f"트레이 알림 표시 오류: {e}")

    def changeEvent(self: MainApp, a0):
        super().changeEvent(a0)
        try:
            if a0 is None or a0.type() != QEvent.Type.WindowStateChange:
                return
            if self._force_close:
                return
            if not self.isMinimized():
                return
            if not self.minimize_to_tray:
                return
            if not hasattr(self, "tray") or not self.tray:
                return

            QTimer.singleShot(0, self.hide)
            if not hasattr(self, "_tray_minimize_notified") or not self._tray_minimize_notified:
                self.show_tray_notification(APP_NAME, "프로그램이 트레이로 최소화되었습니다.")
                self._tray_minimize_notified = True
            self.update_tray_tooltip()
        except Exception as e:
            logger.warning(f"최소화 이벤트 처리 오류: {e}")

    def closeEvent(self: MainApp, a0: QCloseEvent | None):
        """종료 이벤트 - 트레이 최소화 지원 버전"""
        if a0 is None:
            return
        if not hasattr(self, "_system_shutdown"):
            self._system_shutdown = False
        if not hasattr(self, "_force_close"):
            self._force_close = False
        if not hasattr(self, "_user_requested_close"):
            self._user_requested_close = False

        caller_info = self._get_close_caller_info() if hasattr(self, "_get_close_caller_info") else "Unknown"
        logger.info(f"closeEvent 호출됨 (호출 원인: {caller_info})")

        if self._system_shutdown or self._force_close:
            if self._system_shutdown:
                logger.warning("시스템 종료로 인한 프로그램 종료")
            self._perform_real_close(a0)
            return

        if hasattr(self, "tray") and self.tray and self.close_to_tray:
            logger.info("창을 트레이로 최소화")
            a0.ignore()
            self.hide()

            if not hasattr(self, "_tray_hide_notified") or not self._tray_hide_notified:
                self.show_tray_notification(
                    APP_NAME,
                    "프로그램이 시스템 트레이에서 계속 실행됩니다.\n트레이 아이콘을 더블클릭하여 창을 열 수 있습니다."
                )
                self._tray_hide_notified = True

            self.update_tray_tooltip()
            return

        if not self._user_requested_close:
            reply = QMessageBox.question(
                self,
                "프로그램 종료",
                "정말로 프로그램을 종료하시겠습니까?\n\n"
                "종료하면 뉴스 자동 새로고침이 중지됩니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply != QMessageBox.StandardButton.Yes:
                logger.info("사용자가 종료를 취소함")
                a0.ignore()
                return

            self._user_requested_close = True
            logger.info("사용자가 종료 확인함")

        self._perform_real_close(a0)

    def _perform_real_close(self: MainApp, event: QCloseEvent):
        """프로그램 실제 종료 처리"""
        logger.info("프로그램 실제 종료 시작...")

        try:
            self._shutdown_in_progress = True
            if hasattr(self, "timer") and self.timer:
                self.timer.stop()
            if hasattr(self, "_countdown_timer") and self._countdown_timer:
                self._countdown_timer.stop()
            if hasattr(self, "_tab_badge_timer") and self._tab_badge_timer:
                self._tab_badge_timer.stop()
            logger.info("타이머 중지됨")

            self._cleanup_open_tabs_for_shutdown()
            logger.info("열린 탭 정리 완료")

            if hasattr(self, "_worker_registry"):
                for handle in list(self._worker_registry.all_handles()):
                    try:
                        self.cleanup_worker(
                            keyword=handle.tab_keyword,
                            request_id=handle.request_id,
                            only_if_active=False,
                        )
                    except Exception as e:
                        logger.error(f"워커 종료 오류 ({handle.tab_keyword}, rid={handle.request_id}): {e}")

            self.workers.clear()
            logger.info("워커 정리 완료")

            export_worker = getattr(self, "_export_worker", None)
            if export_worker is not None and export_worker.isRunning():
                try:
                    export_worker.requestInterruption()
                    export_worker.wait(1000)
                except Exception as e:
                    logger.error(f"CSV export worker 종료 오류: {e}")

            try:
                self.save_config()
                logger.info("설정 저장 완료")
            except Exception as e:
                logger.error(f"설정 저장 오류: {e}")

            if self.db is not None:
                try:
                    self.db.close()
                    logger.info("DB 연결 종료")
                except Exception as e:
                    logger.error(f"DB 종료 오류: {e}")

            if self.session is not None:
                try:
                    self.session.close()
                    logger.info("HTTP 세션 종료")
                except Exception as e:
                    logger.error(f"세션 종료 오류: {e}")

            logger.info("프로그램 종료 처리 완료")
            self._app_instance().quit()

        except Exception as e:
            logger.error(f"종료 처리 중 오류: {e}")
            traceback.print_exc()
            self._app_instance().quit()
        finally:
            self._shutdown_in_progress = False

        event.accept()

    def _get_close_caller_info(self: MainApp) -> str:
        """종료 호출 원인을 분석하여 반환"""
        try:
            stack = inspect.stack()
            caller_info = []

            for frame_info in stack[2:8]:
                func_name = frame_info.function
                filename = os.path.basename(frame_info.filename)
                lineno = frame_info.lineno

                if func_name not in ["closeEvent", "_get_close_caller_info"]:
                    caller_info.append(f"{func_name}@{filename}:{lineno}")

            if not caller_info:
                return "Unknown"

            return " <- ".join(caller_info[:3])
        except Exception as e:
            return f"Error analyzing stack: {e}"

    def request_close(self: MainApp, confirmed: bool = False):
        """트레이 메뉴 등에서 종료 요청 시 사용"""
        if confirmed:
            self._user_requested_close = True
            self._force_close = True
        self.close()
