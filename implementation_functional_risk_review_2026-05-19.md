# 기능 리스크 전체 확장 구현 완료 리뷰

작성일: 2026-05-19

## 결론

`implementation_functional_risk_review_2026-05-19.md` 계획의 권장 구현 1-5와 추가 후보 중 cloud 삭제 tombstone, 수동 병합 preview를 코드에 반영했다. 삭제 동기화는 사용자가 명시적으로 단건 삭제한 기사에만 적용하고, 오래된 기사 정리/전체 정리는 tombstone 없는 로컬 유지보수 삭제로 유지했다.

## 구현 완료 항목

| 항목 | 상태 | 반영 위치 |
| --- | --- | --- |
| 삭제 tombstone schema | 구현 완료 / 검증 완료 | `core/_db_schema.py`, `core/db_mutations_support/state_tags.py` |
| 기본 조회에서 삭제 row 숨김 | 구현 완료 / 검증 완료 | `core/_db_queries.py`, `core/_db_analytics.py`, `core/_db_duplicates.py`, export/tray 호출 경로 |
| 단건 삭제 soft-delete / 복구 | 구현 완료 / 검증 완료 | `DatabaseManager.delete_link(link)`, `DatabaseManager.restore_deleted_link(link)`, archive dialog |
| no-op 상태/태그 timestamp 보존 | 구현 완료 / 검증 완료 | `update_status(...)`, `set_tags(...)` |
| cloud tombstone latest-wins 병합 | 구현 완료 / 검증 완료 | `core/_db_cloud_sync.py`, `core/cloud_sync.py` |
| 수동 cloud 병합 preview | 구현 완료 / 검증 완료 | `preview_cloud_snapshots_for_import(...)`, `ui/main_window_io_support/cloud.py` |
| snapshot 크기 제한 / invalid 격리 | 구현 완료 / 검증 완료 | `core/cloud_sync.py`, `.gitignore` |
| LIKE literal 검색 통일 | 구현 완료 / 검증 완료 | `core/_db_queries.py`, `core/_db_analytics.py` |
| 자동화 규칙 transaction 적용 | 구현 완료 / 검증 완료 | `DatabaseManager.apply_automation_actions(...)`, `ui/_main_window_analysis.py`, fetch worker flow |
| 문서/spec/.gitignore 동기화 | 구현 완료 / 검증 완료 | `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`, `news_scraper_pro.spec`, `.gitignore` |

## 핵심 정책

- `news.is_deleted=1` row는 기본 UI, 통계, export, tray count, query count에서 제외한다.
- 아카이브 검색은 `include_deleted=True`일 때만 삭제 row를 노출하며, 이 경로에서 복구할 수 있다.
- `delete_link(link)`는 명시 단건 삭제만 cloud tombstone으로 기록한다.
- `delete_old_news(...)`, `delete_old_news_chunked(...)`, `delete_all_news(...)`는 tombstone 없이 실제 row를 정리한다.
- cloud merge는 `delete_updated_at`이 더 최신인 쪽의 삭제/복구 상태를 따른다.
- API 재수집 또는 오래된 active snapshot은 더 최신 삭제 tombstone을 자동 복구하지 않는다.
- 수동 cloud import는 preview 확인을 요구하고, 주기 동기화는 자동 병합을 유지한다.
- cloud sync enable 체크박스는 timer만 제어한다. 수동 export/import는 폴더와 runtime path 검증을 통과하면 실행된다.
- `%`, `_`, `\`는 검색 wildcard가 아니라 literal 사용자 입력으로 처리한다.

## 검증 완료 항목

- no-op read/bookmark/note/tag 저장 시 timestamp 미변경.
- 명시 단건 삭제 soft-delete, 기본 조회 숨김, archive 삭제 포함 조회, 복구.
- cloud tombstone 전파와 복구 latest-wins 병합.
- 오래된 기사 정리/전체 정리는 tombstone을 만들지 않음.
- `%`, `_`, `\` 포함 filter/exclude/note 검색과 mark-read scope.
- 자동화 규칙 DB 실패 시 사용자 경고/상태 반영 및 알림 억제 유지.
- snapshot 크기 초과/손상 quarantine과 반복 import 방지.
- 수동 cloud 병합 preview 확인 흐름 및 주기 checkbox 분리.

## 실행한 검증

```text
python -m pytest tests/test_cloud_sync.py tests/test_functional_risk_20260511.py tests/test_db_queries.py -q
=> 56 passed

python -m pytest -q
=> 329 passed, 7 warnings, 5 subtests passed

pyright
=> 0 errors, 0 warnings, 0 informations

python -m pytest tests/test_encoding_smoke.py -q
=> 2 passed

git diff --check
=> pass
```

## Spec / .gitignore 재검토

- `news_scraper_pro.spec`: 이번 변경은 stdlib `json`, `zipfile`, `tempfile`, `shutil`, `uuid`, SQLite backup API, 기존 PyQt6 UI 경로만 사용한다. 새 hidden import, data file, optional dependency exclude는 필요하지 않다.
- `.gitignore`: `news_scraper_sync_*.zip`, `.news_scraper_sync_*.zip.tmp`, `.invalid/`, build/dist/cache/log/runtime DB/config 산출물 ignore를 확인했다.

## 원 계획 외 범위

- PyInstaller 빌드, commit, push는 원 구현 계획에는 포함하지 않았다. 후속 사용자 요청에 따른 publish/build 결과는 작업 완료 보고에서 별도 보고한다.
