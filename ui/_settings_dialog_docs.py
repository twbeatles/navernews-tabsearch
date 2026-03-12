# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.settings_dialog import SettingsDialog


class _SettingsDialogDocsMixin:
    def get_help_html(self: SettingsDialog) -> str:
        return """
        <html>
        <body style="font-family:'맑은 고딕',sans-serif; padding:15px; line-height:1.6;">
            <h2 style="color:#007AFF;">빠른 시작</h2>
            <h3>API 키 설정</h3>
            <ul>
                <li>네이버 개발자센터에서 뉴스 검색 API 앱을 등록합니다.</li>
                <li>Client ID / Client Secret을 입력한 뒤 검증 버튼으로 확인합니다.</li>
            </ul>
            <h3>탭 검색</h3>
            <ul>
                <li><code>주식</code></li>
                <li><code>주식 -코인</code></li>
                <li><code>인공지능 AI -광고 -채용</code></li>
            </ul>
            <h3>기사 관리</h3>
            <ul>
                <li>제목 클릭 시 읽음 처리</li>
                <li>북마크, 메모, 공유, 미리보기 지원</li>
            </ul>
            <h3>데이터 관리</h3>
            <ul>
                <li>CSV 내보내기, 통계, 언론사 분석</li>
                <li>30일 이전 기사 정리 (북마크 제외)</li>
            </ul>
            <p><strong>참고:</strong> 더 자세한 조작법은 단축키 탭을 확인하세요.</p>
        </body>
        </html>
        """

    def get_shortcuts_html(self: SettingsDialog) -> str:
        return """
        <html>
        <body style="font-family:'맑은 고딕',sans-serif; padding:15px; line-height:1.6;">
            <h2 style="color:#007AFF;">키보드 단축키</h2>
            <h3>새로고침 / 탭</h3>
            <ul>
                <li><strong>Ctrl+R</strong> 또는 <strong>F5</strong>: 모든 탭 새로고침</li>
                <li><strong>Ctrl+T</strong>: 새 탭 추가</li>
                <li><strong>Ctrl+W</strong>: 현재 탭 닫기</li>
                <li><strong>Alt+1~9</strong>: 탭 전환</li>
            </ul>
            <h3>검색 / 설정</h3>
            <ul>
                <li><strong>Ctrl+F</strong>: 필터 입력창 포커스</li>
                <li><strong>Ctrl+S</strong>: 현재 탭 CSV 내보내기</li>
                <li><strong>Ctrl+,</strong>: 설정 창 열기</li>
                <li><strong>F1</strong>: 도움말 열기</li>
            </ul>
            <h3>마우스 동작</h3>
            <ul>
                <li>제목 클릭: 기사 열기 및 읽음 처리</li>
                <li>제목 호버: 미리보기</li>
                <li>탭 더블클릭: 탭 이름 변경</li>
            </ul>
        </body>
        </html>
        """
