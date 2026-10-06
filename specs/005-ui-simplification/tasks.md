# Tasks: UI 간소화

**Input**: `spec.md`

## Phase 1: 스타일 기반

- [x] T001 `ui/styles_support/tokens.py`에서 그라데이션 전용 팔레트 슬롯 제거, `on_primary` 추가, 라이트 muted 대비 보정
- [x] T002 `ui/styles_support/app_style.py` QSS를 단색·축소 padding/radius로 재작성하고 `QMenu`, `QToolTip`, `QLabel#Hint` 규칙 추가
- [x] T003 `ui/styles_support/app_style.py`의 기사 HTML 템플릿을 납작한 목록형으로 재작성

## Phase 2: User Story 1 — 첫 화면 (P1)

- [x] T004 [US1] `ui/main_window_support/ui_shell_support/setup.py` 툴바를 4개 버튼 + 더보기 메뉴로 재구성
- [x] T005 [US1] `ui/main_window_support/base_support/maintenance.py`의 내보내기 비활성화 경로를 메뉴 액션으로 이전
- [x] T006 [US1] `ui/news_tab_support/rendering.py` 카드 마크업 간소화(키워드 배지 제거, 인라인 액션 2개, 읽음 표현)
- [x] T007 [US1] `ui/widgets.py` 우클릭 메뉴 문구 정리
- [x] T008 [US1] `ui/_main_window_tabs.py` 탭 우클릭 메뉴·새 탭 대화상자 정리, `ui/_main_window_tray.py` 메뉴 문구 정리

## Phase 3: User Story 2 — 필터 가시성 (P1)

- [x] T009 [US2] `ui/news_tab_support/ui_controls_support/layout.py`에 `초기화` 버튼과 필터 활성 표시 추가
- [x] T010 [US2] `ui/news_tab_support/ui_controls_support/filter_events.py`에 `_reset_filters`, `_update_filter_indicator` 구현
- [x] T011 [US2] `ui/news_tab_support/loading_support/lifecycle.py` 유지보수 제어 목록에 초기화 버튼 추가

## Phase 4: User Story 3 — 상태 표시 (P2)

- [x] T012 [US3] `ui/news_tab_support/rendering.py`의 `update_status_label` 문구 단순화
- [x] T013 [US3] 하단 바에서 "맨 위로" 제거, API 추가 수집 버튼 문구 변경(`worker_flow_support/state.py`)

## Phase 5: User Story 4 — 설정 (P2)

- [x] T014 [US4] `ui/_settings_dialog_content.py`·`ui/settings_dialog.py`를 탭 구성으로 분리하고 하드코딩 색상 제거
- [x] T015 [US4] `ui/_settings_dialog_docs.py` 도움말·단축키 내용을 새 화면 구성에 맞게 갱신

## Phase 6: 검증·문서

- [x] T016 `tests/test_risk_fixes.py` 툴바 단언 갱신, `tests/test_ui_simplification.py` 회귀 테스트 추가
- [x] T017 오프스크린 렌더로 라이트/다크 메인 창·설정 창 육안 확인
- [x] T018 `python -m pytest -q` 새 실패 0건(변경 전부터 실패하던 `test_update_installer` 1건은 그대로), `python -m pyright` 오류 0건 확인
- [x] T019 README의 화면 설명 갱신

## 구현 메모

- 콤보 화살표·탭 닫기·체크 표시는 플랫폼 기본 글리프가 테마 색을 따르지 않아 `ui/styles_support/icons.py`에서 팔레트 색으로 그려 QSS에 연결했다(`AppStyle.for_theme`). 생성 실패 시 기본 글리프로 동작한다.
- 목록 끝 "더 보기"(저장된 기사 추가 표시)와 하단 "이전 기사 가져오기"(API 추가 수집)는 서로 다른 동작이라 둘 다 유지하고 문구로 구분했다.
- 빈 상태 안내는 필터가 원인인 경우를 먼저 알린다(북마크 탭에서 필터 때문에 비어 보일 때 "북마크 없음"으로 잘못 안내하던 문제).
