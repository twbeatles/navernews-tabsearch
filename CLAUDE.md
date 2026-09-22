# Claude Assistant Guide - 뉴스 스크래퍼 Pro

이 문서는 현재 코드베이스를 기준으로 한 작업 가이드입니다. 과거 날짜별 구현 로그는 유지하지 않습니다.

## 프로젝트 요약

- PyQt6 데스크톱 앱
- **NAVER API HUB** 뉴스 검색 API + 로컬 SQLite DB
- 핵심 진입점: `news_scraper_pro.py`
- 앱 부팅: `core.bootstrap.main()`
- 메인 UI: `ui.main_window.MainApp`
- DB facade: `core.database.DatabaseManager`
- API 연동: `core.naver_api` + `core.workers_support.api_worker.ApiWorker`
- 현재 버전: `core.constants.VERSION`

## 기본 원칙

- root compatibility wrapper와 facade import를 깨지 않습니다.
- 검색 의미는 canonical query / fetch key 기준입니다.
- 사용자-visible 필터 의미를 바꿀 때는 fetch, count, badge, tray, export, archive를 같이 확인합니다.
- FTS hard prefilter는 false negative 방지를 위해 다시 켜지 않습니다.
- DB write/query 실패는 각각 `DatabaseWriteError`, `DatabaseQueryError`로 드러내는 방향을 유지합니다.
- 단일 탭 fetch, 더 불러오기, 순차 fetch는 모두 `fetch_news()`의 API 자격증명 guard를 통과해야 합니다.
- 탭 닫기/이름 변경은 active worker cleanup 실패 시 상태 변경을 진행하지 않습니다.
- 메모는 저장 전 10,000자로 제한하고, import/export 문서 계약과 테스트를 같이 유지합니다.
- destructive backup 경로는 backup root 아래의 단일 이름만 허용하고, `realpath`로 reparse point까지 확인합니다.
- **중복 플래그 재계산은 스코프 한정이 기본입니다.** per-article·startup 경로에서 `_recalculate_duplicate_flags_for_entire_database(...)`를 부르지 않습니다. 전체 재계산은 수동 복구·클라우드 병합·스키마 마이그레이션 전용입니다.
- soft-delete(tombstone)는 클라우드 삭제 전파용이며, 보존 기간이 지난 것만 정리 작업에서 회수합니다. 보존 기간 `0`은 "영구 보존"입니다.
- `news_fts`는 어떤 질의도 사용하지 않습니다. backfill은 기본 꺼짐이며 `NEWS_SCRAPER_ENABLE_FTS_BACKFILL=1`로만 켭니다.
- 문서는 현재 코드 상태를 우선하고, 오래된 변경 누적 로그를 다시 붙이지 않습니다.
- **네이버 API 호출 URL/헤더는 `core/naver_api.py`에만 둡니다.** `ApiWorker`와 설정 검증이 동일 헬퍼를 사용해야 합니다.
- 레거시 Developers Center (`openapi.naver.com`, `X-Naver-Client-*`) 엔드포인트로 되돌리지 않습니다.

## 현재 구조

```text
core/
  bootstrap.py
  naver_api.py
  database.py
  db_schema_support/
  db_queries_support/
  db_mutations_support/
  workers_support/
  cloud_sync_support/
  backup_support/
  runtime_support/
ui/
  main_window.py
  main_window_support/
  main_window_fetch_support/
  main_window_io_support/
  news_tab.py
  news_tab_support/
  dialogs_support/
tests/
```

## 주요 작업 위치

| 작업 | 위치 |
|---|---|
| API HUB 상수/오류 파싱 | `core/naver_api.py` |
| API fetch | `core/workers_support/api_worker.py` |
| 설정 API 키 검증 | `ui/_settings_dialog_tasks.py` |
| 설정 API UI/도움말 | `ui/_settings_dialog_content.py`, `ui/_settings_dialog_docs.py` |
| DB list/count | `core/db_queries_support/fetch.py` |
| DB upsert | `core/db_mutations_support/news_upsert.py` |
| DBWorker | `core/workers_support/db_worker.py` |
| 탭 로딩 | `ui/news_tab_support/loading_support/db_loading.py` |
| 탭 렌더링 | `ui/news_tab_support/rendering.py` |
| badge/tray | `ui/main_window_support/ui_shell_support/` |
| settings import/export | `ui/main_window_io_support/` |
| cloud sync | `core/cloud_sync_support/`, `core/db_cloud_sync_support/` |
| 중복 플래그 재계산 | `core/_db_duplicates.py` |
| tombstone 회수/보존 | `core/db_mutations_support/maintenance_support/deletion.py` |
| 저장소 지표 | `core/_db_analytics.py` (`get_storage_metrics`) |
| packaging | `news_scraper_pro.spec` |

## NAVER API HUB 계약

- URL: `https://naverapihub.apigw.ntruss.com/search/v1/news`
- 헤더: `X-NCP-APIGW-API-KEY-ID`, `X-NCP-APIGW-API-KEY`
- config 필드: `client_id` / `client_secret` (이름 유지, 값은 API HUB 키)
- 성공 응답 item 필드: `title`, `link`, `originallink`, `description`, `pubDate` (파싱 유지)
- 오류: Search 평면(`errorCode`/`errorMessage`) + Gateway 중첩(`error.message`) → `parse_naver_api_error`
- 401/403 → `auth_error` kind
- UI/도움말 문구는 개발자센터가 아니라 API HUB 기준으로 유지

## 경로/데이터 정책

- cloud sync folder는 core API에서 빈 값을 거부하고, 상대 경로는 절대 경로로 resolve한 뒤 사용합니다.
- CSV/Markdown export 기본 파일명은 `ValidationUtils.safe_filename_component(...)`로 정규화합니다.
- backup delete/restore/schedule/pending restore는 `core.backup_support.fs._safe_backup_child_dir(...)`를 통해 root containment를 확인합니다.

## 현재 성능 계약

- `upsert_news_detailed(...) -> NewsUpsertResult`는 fetch 저장과 신규 link 산출을 한 경로에서 처리합니다.
- `upsert_news(...) -> tuple[int, int]`는 legacy 공개 API로 유지됩니다.
- `count_news_states(...) -> NewsCountSummary`는 total/unread count를 단일 scope query로 계산합니다.
- `ApiWorker.finished` payload shape는 유지합니다.
- `DBWorker` append는 known total을 재사용합니다.
- 탭 badge는 DB load unread count와 local unread cache를 우선 사용합니다.
- `delete_link` / `restore_deleted_link`는 `_collect_affected_query_key_hashes(..., include_deleted=True)` + `_recalculate_duplicates_for_affected(...)` 조합을 씁니다. 두 경로 모두 대상 행이 soft-delete 상태일 수 있어 `include_deleted`가 필수입니다.
- `_recalculate_duplicate_flags_for_query_key_hashes`의 `CROSS JOIN`은 join **순서** 힌트입니다. `JOIN`으로 바꾸면 `idx_title_hash` 대신 scope 전체를 스캔합니다.
- `init_db`의 O(아카이브) 복구 패스는 `SCHEMA_REPAIR_REVISION` 변경 또는 스키마 변경 시에만 실행합니다.
- 시작 시 무결성 검사는 `SHUTDOWN_STATE_KEY` 마커를 보고 `quick_check`/`integrity_check`를 고릅니다.

## 검증

기본:

```bash
python -m pytest -q
python -m pyright
```

문서/spec 변경:

```bash
python -m pytest tests/test_encoding_smoke.py tests/test_version_history_guard.py tests/test_spec_runtime_tmpdir.py -q
```

API HUB 연동:

```bash
python -m pytest tests/test_naver_api_hub.py tests/test_settings_validation_http_policy.py -q
```

감사 후속 회귀(삭제 비용·시작 비용·tombstone 회수):

```bash
python -m pytest tests/test_audit_remediation_20260920.py -q
```

> PyQt6/cryptography가 없는 환경에서는 해당 모듈이 **skip** 되고 요약에 이유가 표시됩니다(collection 중단 아님).

패키징:

```bash
python -m PyInstaller --noconfirm --clean news_scraper_pro.spec
```

## Git/문서 체크리스트

- `.codegraph/`, build, dist, cache, runtime DB/config/log는 커밋하지 않습니다.
- 문서에는 현재 public API와 실제 module 위치만 남깁니다.
- 새 dependency가 생기면 README와 spec hiddenimports/excludes를 같이 확인합니다.
- spec은 `runtime_tmpdir=None`을 유지합니다.
- VERSION 변경 시 `update_history.md`에 `## v{VERSION}` 섹션을 추가합니다.

<!-- SPECKIT-AGENT-GUIDE:START -->

## Spec Kit / Spec-Driven Development (AI 에이전트 필독)

> 이 블록은 GitHub Spec Kit 활성화 및 기능 명세 작업 결과를 AI 에이전트가 바로 쓰도록 정리한 안내입니다.
> 수정 시 마커 주석을 유지하세요. 스크립트/후속 세션이 이 구간을 갱신합니다.

### 이 저장소 상태

- **프로젝트**: `navernews-tabsearch`
- **Spec Kit 초기화**: `.specify/ 있음`
- **에이전트 스킬**: Grok=True, Claude=True, Codex/Agy(.agents)=True
- **활성 기능 디렉터리**: `specs/004-unused-scope-cleanup` (포인터: `.specify/feature.json`)
- **기능 제목**: 감사 후속 안정성 강화
- **산출물**: spec=`yes`, plan=`True`, research/data-model/quickstart=`True`, tasks=`True`, converge=`False`

### 에이전트가 먼저 읽을 파일

1. `specs/004-unused-scope-cleanup/spec.md` — 무엇을/왜 (사용자 스토리, FR, 성공 기준)
2. `specs/004-unused-scope-cleanup/plan.md` — 기술 컨텍스트·구조 결정
3. `specs/004-unused-scope-cleanup/tasks.md` — 실행 가능 작업 목록 (`[x]`=이미 있음, `[ ]`=잔여)
4. `specs/004-unused-scope-cleanup/research.md`, `data-model.md`, `quickstart.md`, `contracts/` — 설계 보조
5. `.specify/feature.json` — 현재 활성 feature path
6. `.specify/memory/constitution.md` — 원칙(템플릿이면 advisory)

### 권장 워크플로 (스킬 / 슬래시 커맨드)

| 단계 | 커맨드 (Grok/Claude 등) | 산출 |
|------|-------------------------|------|
| 원칙 | `/speckit-constitution` | `.specify/memory/constitution.md` |
| 명세 | `/speckit-specify` | `specs/<id>/spec.md` |
| 계획 | `/speckit-plan` | `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md` |
| 작업 | `/speckit-tasks` | `tasks.md` |
| 구현 | `/speckit-implement` | 코드 (tasks 순서) |
| 갭점검 | `/speckit-converge` | `tasks.md` 에 Phase Convergence **append-only** |

- Codex skills 모드: `$speckit-specify` 형태일 수 있음
- 스킬 파일: `.grok/skills/speckit-*/SKILL.md`, `.claude/skills/speckit-*/SKILL.md`

### 작업 규칙 (에이전트)

1. **새 기능/큰 변경 전** 활성 `spec.md`·`tasks.md` 를 읽고, 없으면 specify→plan→tasks 순으로 만든다.
2. **구현은 tasks.md 체크리스트**를 따른다. 완료 시 `- [ ]` → `- [x]`.
3. **`/speckit-converge` 는 tasks.md 를 rewrite 하지 않는다** — 잔여 갭만 하단 Phase 로 append.
4. brownfield 프로젝트는 상당 기능이 이미 있을 수 있다. 중복 구현 전에 코드·`[x]` 태스크를 확인한다.
5. 웹/데스크톱 패리티 등 **out-of-scope Assumptions** 는 새 feature 로 분리하는 것을 선호한다.
6. 기본 integration 은 **grok** 이며, 동일 레포에 claude / codex / agy 스킬도 multi-install 되어 있을 수 있다.

### 빠른 경로 예시

```text
# 현재 기능 파악
read specs/004-unused-scope-cleanup/spec.md
read specs/004-unused-scope-cleanup/tasks.md
# 잔여 구현
/speckit-implement   # 또는 tasks.md 의 [ ] 항목만 수행
# 구현 후 갭 재점검
/speckit-converge
```

### 관련 링크

- Spec Kit: https://github.com/github/spec-kit
- 로컬 CLI: `specify` (uv tool, 버전은 `specify version`)

<!-- SPECKIT-AGENT-GUIDE:END -->
