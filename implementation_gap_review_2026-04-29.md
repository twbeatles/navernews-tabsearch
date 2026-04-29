# 구현 갭 점검 및 완료 기록 (2026-04-29)

## 검토 기준

- 참조 문서: `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`
- 검토 범위: `core/`, `ui/`, 설정 import/export, fetch/페이지네이션, 태그/출처 필터, 저장된 검색, 백업/복원, 자동 새로고침 흐름
- 최종 검증:
  - `python -m pytest -q` => `272 passed, 5 subtests passed`
  - `pyright` => `0 errors, 0 warnings, 0 informations`
  - `python -m pytest tests/test_encoding_smoke.py -q` => `2 passed`

## 구현 완료 항목

1. `core/bootstrap.py`의 pending restore 적용 순서를 단일 인스턴스 guard 이후, `MainApp`/DB 생성 이전으로 이동했다.
2. `query_key`가 있는 DB 조회/읽음/분석 경로에서 대표 keyword 조건을 제거하고 `query_key`만 기준으로 동작하도록 수정했다.
3. 태그 필터 변경이 텍스트 필터 조기 return에 막히지 않도록 `NewsTab` reload 판단을 전체 scope signature 기준으로 변경했다.
4. 차단/선호 출처 목록 정규화 helper를 추가하고, 선호 출처 추가 시 같은 차단 출처가 제거되도록 했다.
5. 출처 필터는 도메인 suffix match를 지원한다. `example.com`은 `example.com`, `news.example.com`과 매칭되며 `badexample.com`과는 매칭되지 않는다.
6. 탭 배지, 트레이 총 미읽음, 전체 통계/분석이 차단 출처를 제외한 표시 기준으로 계산되도록 맞췄다.
7. 저장된 검색 적용은 저장된 `keyword` 탭으로 이동하거나 새로 만든 뒤 payload를 적용한다.
8. 저장된 검색 삭제 버튼과 `delete_saved_search(name)` 경로를 추가하고 열린 탭의 콤보 동기화를 보장했다.
9. 설정 import stage에서 `saved_searches`와 `tab_refresh_policies`를 즉시 정규화하도록 했다.
10. import로 차단/선호 출처가 바뀌면 기존 열린 탭도 즉시 DB reload하도록 했다.
11. 자동 새로고침 due timestamp는 due 판정 시점이 아니라 fetch 성공 callback에서만 갱신되도록 했다.

## 추가 회귀 테스트

- `tests/test_implementation_plan_20260429.py`
- `tests/test_fetch_cooldown.py`
- `tests/test_import_refresh_prompt.py`
- `tests/test_risk_fixes.py`

## 문서 및 저장소 정합성

- `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`를 2026-04-29 구현 상태에 맞게 갱신했다.
- `.gitignore`는 `git status --ignored --short`와 runtime/test/build 산출물 기준으로 재검토했다. 기존 규칙이 `.pytest_cache/`, `.pytest_tmp/`, `build/`, `dist/`, 로그, `__pycache__/`, runtime DB/config/backup/pending restore 잔여물을 모두 덮고 있어 추가 수정은 필요하지 않았다.
- `implementation_risk_review_2026-04-27.md`는 현재 작업트리의 삭제 상태를 유지한다.
