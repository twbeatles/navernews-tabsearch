from collections import deque

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel

from ui.styles import ToastType, UIConstants

class ToastQueue:
    """토스트 메시지 큐 관리 - 유형별 스타일 지원"""
    def __init__(self, parent):
        self.parent = parent
        self.queue = deque()
        self.current_toast = None
        self.y_offset = 100
        
    def add(self, message: str, toast_type: ToastType = ToastType.INFO):
        """토스트 메시지 추가"""
        self.queue.append((message, toast_type))
        if self.current_toast is None:
            self._show_next()
    
    def _show_next(self):
        """다음 토스트 표시"""
        if not self.queue:
            self.current_toast = None
            return
        
        message, toast_type = self.queue.popleft()
        self.current_toast = ToastMessage(self.parent, message, self, toast_type)
        
    def on_toast_finished(self):
        """토스트 종료 시 호출"""
        self.current_toast = None
        self._show_next()


class ToastMessage(QLabel):
    """화면에 잠시 나타났다 사라지는 알림 메시지 - 유형별 스타일 지원"""
    
    # 유형별 스타일 정의 - 현대화된 디자인
    STYLES = {
        ToastType.INFO: """
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 rgba(30, 41, 59, 245), stop:1 rgba(51, 65, 85, 245));
            color: #F1F5F9;
            border: 1px solid rgba(148, 163, 184, 0.2);
        """,
        ToastType.SUCCESS: """
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 rgba(5, 150, 105, 245), stop:1 rgba(16, 185, 129, 245));
            color: #FFFFFF;
            border: 1px solid rgba(255, 255, 255, 0.2);
        """,
        ToastType.WARNING: """
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 rgba(217, 119, 6, 245), stop:1 rgba(245, 158, 11, 245));
            color: #FFFFFF;
            border: 1px solid rgba(255, 255, 255, 0.2);
        """,
        ToastType.ERROR: """
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 rgba(185, 28, 28, 245), stop:1 rgba(239, 68, 68, 245));
            color: #FFFFFF;
            border: 1px solid rgba(255, 255, 255, 0.2);
        """,
    }
    
    # 유형별 아이콘
    ICONS = {
        ToastType.INFO: "ℹ️",
        ToastType.SUCCESS: "✓",
        ToastType.WARNING: "⚠️",
        ToastType.ERROR: "✗",
    }
    
    def __init__(self, parent, message: str, queue: ToastQueue, toast_type: ToastType = ToastType.INFO):
        # 아이콘 추가 (SUCCESS 메시지에는 이미 ✓가 있을 수 있으므로 조건부)
        display_message = message
        if toast_type == ToastType.ERROR and not message.startswith("✗"):
            display_message = f"✗ {message}"
        elif toast_type == ToastType.WARNING and not message.startswith("⚠"):
            display_message = f"⚠️ {message}"
            
        super().__init__(display_message, parent)
        self.queue = queue
        self.toast_type = toast_type
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # 유형별 스타일 적용
        base_style = self.STYLES.get(toast_type, self.STYLES[ToastType.INFO])
        self.setStyleSheet(f"""
            {base_style}
            padding: 14px 28px;
            border-radius: 24px;
            font-family: '맑은 고딕';
            font-size: 14px;
            font-weight: bold;
        """)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.adjustSize()
        
        self.update_position()
        
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
        self.anim_in = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.anim_in.setDuration(UIConstants.ANIMATION_DURATION)
        self.anim_in.setStartValue(0.0)
        self.anim_in.setEndValue(1.0)
        self.anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim_in.start()
        
        self.show()
        
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fade_out)
        self.timer.start(UIConstants.TOAST_DURATION)
    
    def update_position(self):
        """부모 크기 변경에 대응하는 위치 업데이트"""
        if self.parent():
            p_rect = self.parent().rect()
            self.move(
                p_rect.center().x() - self.width() // 2,
                p_rect.bottom() - self.queue.y_offset
            )

    def fade_out(self):
        """페이드 아웃 애니메이션"""
        self.anim_out = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.anim_out.setDuration(400)
        self.anim_out.setStartValue(1.0)
        self.anim_out.setEndValue(0.0)
        self.anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self.anim_out.finished.connect(self.on_finished)
        self.anim_out.start()
    
    def on_finished(self):
        """애니메이션 종료 후 정리 - 메모리 누수 방지 개선"""
        try:
            # 타이머 정리
            if hasattr(self, 'timer') and self.timer and self.timer.isActive():
                self.timer.stop()
            # 애니메이션 정리
            if hasattr(self, 'anim_out'):
                self.anim_out.stop()
                self.anim_out.deleteLater()
            if hasattr(self, 'anim_in'):
                self.anim_in.stop()
                self.anim_in.deleteLater()
            # opacity_effect 정리
            if hasattr(self, 'opacity_effect') and self.opacity_effect:
                self.opacity_effect.deleteLater()
        except RuntimeError:
            pass  # 이미 삭제된 경우
        finally:
            queue = self.queue  # 참조 미리 저장 (안전성)
            self.close()
            self.deleteLater()
            if queue:
                queue.on_toast_finished()
