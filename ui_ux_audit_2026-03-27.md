# UI/UX Audit Follow-up (2026-03-27)

## 범위

- `README.md`
- `claude.md`
- `gemini.md`
- `project_structure_analysis.md`
- `update_history.md`
- `news_scraper_pro.spec`
- `.gitignore`

## 코드베이스 정합성 확인 결과

- `SettingsDialog`는 현재 `help_mode` / `initial_tab`을 지원하며, 도움말은 저장 가능한 설정 창이 아니라 read-only 다이얼로그로 열립니다.
- `NewsTab`은 기간 필터를 즉시 반영형에서 `적용` / `해제` 흐름으로 전환했고, 역전된 날짜 범위는 자동 정규화합니다.
- 기사 외부 열기 실패 시 읽음 처리하지 않으며, 탭 하단 unread 수치는 현재 로드된 slice가 아니라 현재 DB scope 전체 기준으로 계산됩니다.
- 자동 새로고침 카운트다운은 전용 상태바 라벨로 분리되었고, 트레이 미지원 환경에서도 완료 알림 fallback이 유지됩니다.
- `KeywordGroupDialog`는 staged save/cancel 모델로 바뀌었고, `LogViewerDialog`는 debounce 검색을 사용합니다.
- 백업 목록은 metadata-first로 로드되고, 무거운 백업 검증은 사용자 트리거형으로 실행됩니다.

## 문서/패키징 반영 내용

- `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`를 현재 구현 상태와 최신 검증 기준에 맞게 갱신했습니다.
- `news_scraper_pro.spec`에는 2026-03-27 재검토 메모를 추가했고, 이번 패스에서도 hidden import/exclude/data 수정이 필요 없음을 기록했습니다.
- `.gitignore`는 build/dist/runtime/test 부산물을 이미 충분히 무시하고 있어 추가 수정 없이 유지했습니다.

## 최신 검증 기준

- `python -m pytest -q` => `188 passed, 5 subtests passed`
- `pyinstaller --noconfirm --clean news_scraper_pro.spec` => 성공
- 산출물: `dist/NewsScraperPro_Safe.exe`
- `pyright`는 `pyrightconfig.json` 기준 품질 게이트로 유지하되, 이번 세션에서는 로컬 PyQt6 import resolution 환경 차이로 재검증 기준에서 제외했습니다.
