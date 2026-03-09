import html
from typing import Dict, Optional

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QContextMenuEvent, QCursor, QMouseEvent, QTextDocument, QWheelEvent
from PyQt6.QtWidgets import QComboBox, QMenu, QTextBrowser, QToolTip

class NoScrollComboBox(QComboBox):
    """마우스 휠로 값이 변경되지 않는 콤보박스 (설정창 UX 개선)"""
    
    def wheelEvent(self, e: Optional[QWheelEvent]):
        """휠 이벤트 무시 - 부모 위젯으로 전달"""
        if e is not None:
            e.ignore()


class NewsBrowser(QTextBrowser):
    """링크 클릭 시 페이지 이동 차단, 호버 시 미리보기 표시"""
    action_triggered = pyqtSignal(str, str) # action, link_hash
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)  
        self.setOpenLinks(False)
        self.setMouseTracking(True)
        self.preview_data: Dict[str, str] = {}
        
    def setSource(
        self,
        name: QUrl,
        type: QTextDocument.ResourceType = QTextDocument.ResourceType.UnknownResource,
    ):
        if name.scheme() == 'app':
            return
        super().setSource(name, type=type)
    
    def set_preview_data(self, data: Dict[str, str]):
        """미리보기 데이터 설정"""
        self.preview_data = data
    
    def mouseMoveEvent(self, ev: Optional[QMouseEvent]):
        """마우스 호버 시 미리보기 표시"""
        if ev is None:
            return

        anchor = self.anchorAt(ev.pos())
        
        if anchor and anchor.startswith('app://open/'):
            link_hash = anchor.split('/')[-1]
            if link_hash in self.preview_data:
                preview_text = self.preview_data[link_hash]
                if len(preview_text) > 200:
                    preview_text = preview_text[:200] + "..."
                
                QToolTip.showText(
                    ev.globalPosition().toPoint(),
                    f"<div style='max-width: 400px;'>{html.escape(preview_text)}</div>",
                    self
                )
        else:
            QToolTip.hideText()
        
        super().mouseMoveEvent(ev)

    def contextMenuEvent(self, e: Optional[QContextMenuEvent]):
        # 마우스오버 또는 클릭 위치의 링크 확인
        if e is None:
            return

        anchor = self.anchorAt(e.pos())
        
        link_hash = ""
        if anchor:
            url = QUrl(anchor)
            if url.scheme() == 'app':
                link_hash = url.path().lstrip('/')
        
        # 링크 위가 아니라면 기본 메뉴 사용 (복사 등)
        if not link_hash:
            super().contextMenuEvent(e)
            return
            
        # 커스텀 메뉴 생성
        menu = QMenu(self)
        
        act_open = menu.addAction("🌐 브라우저로 열기")
        act_copy = menu.addAction("📋 제목 및 링크 복사")
        menu.addSeparator()
        act_bm = menu.addAction("⭐ 북마크 토글")
        act_read = menu.addAction("👁 읽음/안읽음 토글")
        act_note = menu.addAction("📝 메모 편집")
        menu.addSeparator()
        act_del = menu.addAction("🗑 목록에서 삭제")
        
        # 메뉴 실행
        action = menu.exec(e.globalPos())
        
        if action == act_open:
            self.emit_action("ext", link_hash)
        elif action == act_copy:
            self.emit_action("share", link_hash)
        elif action == act_bm:
            self.emit_action("bm", link_hash)
        elif action == act_read:
            self.emit_action("toggle_read", link_hash)
        elif action == act_note:
            self.emit_action("note", link_hash)
        elif action == act_del:
            self.emit_action("delete", link_hash)
            
    def emit_action(self, action: str, link_hash: str):
        self.action_triggered.emit(action, link_hash)
