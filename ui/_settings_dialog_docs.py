# pyright: reportGeneralTypeIssues=false, reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.settings_dialog import SettingsDialog


class _SettingsDialogDocsMixin:
    def get_help_html(self: SettingsDialog) -> str:
        return """
        <html>
        <body style="font-family:'맑은 고딕',sans-serif; line-height:1.6;">
            <h3>시작하기</h3>
            <ul>
                <li>네이버 클라우드 플랫폼 콘솔에서 NAVER API HUB 이용을 신청하고, 검색(뉴스) API가 포함된 Application을 등록합니다.</li>
                <li>발급된 Client ID / Client Secret을 <b>더보기 → 설정 → 일반</b>에 입력하고 <b>키 확인</b>으로 검증합니다.</li>
                <li>기존 네이버 개발자센터 키는 사용할 수 없습니다. API HUB에서 새로 발급받아야 합니다.</li>
            </ul>
            <h3>탭 만들기</h3>
            <ul>
                <li><b>+ 새 탭</b>에 검색어를 입력하면 그 키워드의 뉴스 탭이 생깁니다.</li>
                <li>단어 앞에 <code>-</code>를 붙이면 제외어입니다. 예: <code>인공지능 AI -광고 -채용</code></li>
                <li>탭을 더블클릭하면 검색어를 바꿀 수 있고, 우클릭하면 탭별 자동 새로고침을 정할 수 있습니다.</li>
            </ul>
            <h3>기사 읽기</h3>
            <ul>
                <li>제목을 누르면 브라우저에서 열리고 읽음으로 표시됩니다.</li>
                <li>기사 아래의 <b>북마크</b>, <b>공유</b>(제목과 링크 복사)를 바로 쓸 수 있습니다.</li>
                <li>메모, 태그, 읽음 전환, 출처 차단/선호, 삭제는 기사 제목을 <b>우클릭</b>하면 나옵니다.</li>
                <li><b>더 보기</b>는 이미 저장된 기사를 더 표시하고, <b>이전 기사 가져오기</b>는 네이버에서 더 오래된 기사를 받아옵니다.</li>
            </ul>
            <h3>필터</h3>
            <ul>
                <li>탭 위의 입력창으로 제목·내용을 찾고, <b>필터</b>를 펼치면 선호 출처·태그·기간·저장 검색을 쓸 수 있습니다.</li>
                <li>접힌 영역에 조건이 걸려 있으면 <b>필터 ●</b>로 표시되며, <b>초기화</b>로 한 번에 해제합니다.</li>
            </ul>
            <h3>데이터</h3>
            <ul>
                <li><b>더보기 → 현재 탭 내보내기</b>는 현재 필터 조건의 전체 결과를 CSV로 저장합니다.</li>
                <li>30일 지난 기사 정리는 북마크를 지우지 않습니다.</li>
                <li>자동 백업은 설정만 저장하며, DB 복원 지점은 수동 백업(DB 포함)으로 만듭니다.</li>
                <li>설정 내보내기/가져오기는 API 자격증명을 제외하고, 자동 시작 설정은 포함합니다.</li>
                <li>트레이/자동 시작 미지원 환경에서 가져온 설정은 안전한 값으로 자동 보정됩니다.</li>
            </ul>
        </body>
        </html>
        """

    def get_shortcuts_html(self: SettingsDialog) -> str:
        return """
        <html>
        <body style="font-family:'맑은 고딕',sans-serif; line-height:1.6;">
            <h3>새로고침 / 탭</h3>
            <ul>
                <li><b>Ctrl+R</b> 또는 <b>F5</b>: 모든 탭 새로고침</li>
                <li><b>Ctrl+T</b>: 새 탭 추가</li>
                <li><b>Ctrl+W</b>: 현재 탭 닫기</li>
                <li><b>Alt+1~9</b>: 탭 전환</li>
            </ul>
            <h3>찾기</h3>
            <ul>
                <li><b>Ctrl+F</b>: 현재 탭 필터 입력창</li>
                <li><b>Ctrl+Shift+F</b>: 저장된 전체 기사 검색</li>
            </ul>
            <h3>관리</h3>
            <ul>
                <li><b>Ctrl+S</b>: 현재 탭 결과 CSV 내보내기</li>
                <li><b>Ctrl+Shift+T</b>: 태그 관리</li>
                <li><b>Ctrl+Shift+A</b>: 자동화 규칙</li>
                <li><b>Ctrl+,</b>: 설정</li>
                <li><b>F1</b>: 도움말</li>
            </ul>
            <h3>마우스</h3>
            <ul>
                <li>제목 클릭: 기사 열기 및 읽음 처리</li>
                <li>제목에 마우스 올리기: 요약 미리보기</li>
                <li>제목 우클릭: 메모·태그·삭제 등 기사 메뉴</li>
                <li>탭 더블클릭: 검색어 변경</li>
            </ul>
        </body>
        </html>
        """
