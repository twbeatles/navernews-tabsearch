# navernews-tabsearch 기능 리스크 구현 점검 및 반영 결과 (2026-05-11)

## 요약

`README.md`, `claude.md`, 실제 `core/`, `ui/`, `tests/`, `news_scraper_pro.spec`, `.gitignore`를 다시 대조했다. 이번 배치는 상태 동기화 리스크, 태그/필터 일관성, 내보내기/아카이브, 자동화 규칙, 출처 alias를 한 번에 반영했다.

## 반영된 리스크 수정

- 일괄/범위 읽음 처리 SQL은 `is_read = 1`과 같은 timestamp로 `read_updated_at`을 갱신한다.
- 클라우드 import는 snapshot별 오류를 격리하고 `errors`와 `invalid_count`에 남긴 뒤 다음 snapshot 처리를 계속한다.
- 클라우드 import 후보는 manifest를 먼저 읽어 이미 본 snapshot id를 제외하고, 오래된 unseen snapshot부터 최대 20개 처리한다.
- 클라우드 snapshot의 `settings.json`은 sanitized diagnostic metadata로만 유지한다. import는 DB 상태만 병합하며, 설정 이전은 수동 설정 export/import만 사용한다.
- `automation_rules`, `publisher_aliases`, API 자격증명, 로컬 cloud path는 cloud snapshot settings에서 제외한다.
- SettingsDialog의 수동 cloud export/import는 parent 런타임 필드를 저장 전 직접 바꾸지 않고 override 인자로 실행한다.

## 반영된 신규 기능

- 태그 관리자: 태그 사용량, rename/merge, delete, 현재 탭 전체 필터 범위 bulk add/remove를 제공한다.
- 태그 변경, cloud merge, 교차 탭 상태 동기화 후 tag filter와 tag dropdown 후보를 재계산한다.
- `Ctrl+S` 내보내기는 CSV를 유지하면서 Markdown digest 저장 필터를 추가했다.
- Markdown digest는 현재 탭 전체 필터 범위 기준으로 제목 링크, 날짜, 대표 출처명, 읽음/북마크, 태그, 요약, 메모를 UTF-8 `.md`로 원자 저장한다.
- 전체 아카이브 검색은 제목/요약 FTS, 메모, 태그, 출처 alias, 날짜 범위, 북마크/미읽음 조건을 조합해 페이지 단위 결과를 표시한다.
- 자동화 규칙은 local config의 `automation_rules`에 저장한다. 조건은 키워드/제외어/출처/탭 검색어, 동작은 태그 추가/북마크/읽음/`제외` 태그+읽음으로 제한했다.
- 새 기사 fetch 완료 후 새 링크에 자동화 규칙을 적용하고, 규칙 관리자에서 기존 DB 범위 preview/apply를 제공한다.
- 출처 alias는 원본 `publisher` 값을 보존하고 표시/통계/필터/아카이브/Markdown export에서 대표명을 계산한다.

## 코드 진입점

- `core/automation_rules.py`: 자동화 규칙 정규화와 action 평가
- `core/publisher_aliases.py`: 출처 alias 정규화, 대표명, alias 필터 확장
- `core/_db_mutations.py`: read timestamp 보정, 태그 bulk 작업
- `core/_db_queries.py`: 전체 아카이브 검색/count
- `core/_db_analytics.py`: alias 적용 출처 통계
- `core/cloud_sync.py`: snapshot 선택/오류 격리/sanitized settings
- `core/config_store_impl.py`: `automation_rules`, `publisher_aliases` schema 정규화
- `ui/dialogs.py`: 태그 관리자, 아카이브 검색, 자동화 규칙, 출처 alias 대화상자
- `ui/_main_window_analysis.py`: 신규 대화상자 연결, 자동화 preview/apply
- `ui/_main_window_settings_io.py`: Markdown export, 설정 export/import, cloud override 경로
- `ui/news_tab_support/*`: tag/alias 필터 refresh와 카드 표시

## 문서/spec/.gitignore 정합성

- `README.md`, `claude.md`, `gemini.md`, `update_history.md`, `project_structure_analysis.md`, `feature_enhancement_analysis_2026-05-10.md`를 2026-05-11 구현 상태에 맞춰 갱신했다.
- `news_scraper_pro.spec`는 새 외부 의존성이 없음을 재검토했다. hidden import/exclude/data 추가는 필요하지 않다.
- `.gitignore`는 build/test/runtime 산출물과 cloud snapshot 임시 파일을 이미 무시하고 있었고, `.claude/` 로컬 worktree scratch를 추가로 ignore한다.

## 검증 기준

- `python -m pytest -q` => `315 passed, 7 warnings, 5 subtests passed`
- `pyright` => `0 errors, 0 warnings, 0 informations`
- `python -m pytest tests/test_encoding_smoke.py -q` => `2 passed`
- `git diff --check` => 통과
- `pyinstaller --noconfirm --clean news_scraper_pro.spec` => 통과
- `QT_QPA_PLATFORM=offscreen` + 임시 data dir packaged smoke => 실행 파일이 짧은 구간 정상 기동하고 runtime 파일을 생성함
