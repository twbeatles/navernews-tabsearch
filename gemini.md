# Gemini Assistant Guide - 뉴스 스크래퍼 Pro

이 문서는 현재 저장소 상태를 빠르게 파악하기 위한 AI assistant용 요약입니다. 오래된 addendum과 날짜별 작업 로그는 제거했습니다.

## Project Snapshot

- App: Naver News tab search/management desktop tool
- Runtime: Python 3.14, PySide6, SQLite, requests
- News API: **NAVER API HUB** (not legacy Developers Center)
- Entry point: `news_scraper_pro.py`
- Bootstrap: `core.bootstrap.main()`
- UI facade: `ui.main_window.MainApp`
- DB facade: `core.database.DatabaseManager`
- API helpers: `core.naver_api`
- Packaging: `news_scraper_pro.spec` / PyInstaller onefile
- Version: `core.constants.VERSION`

## Architecture

```text
core/
  naver_api.py             # API HUB URL, auth headers, error parsing
  database.py              # DatabaseManager composition root
  db_schema_support/       # schema and migration helpers
  db_queries_support/      # fetch/count/archive/search queries
  db_mutations_support/    # upsert/state/tag/maintenance writes
  workers_support/         # ApiWorker, DBWorker, job workers
  cloud_sync_support/      # ZIP snapshot I/O and import flow
  backup_support/          # backup/restore implementation
  runtime_support/         # DATA_DIR and legacy migration
ui/
  main_window.py           # MainApp facade
  main_window_support/     # shell/config/badge/tray/maintenance
  main_window_fetch_support/
  main_window_io_support/
  news_tab.py              # NewsTab facade
  news_tab_support/
  dialogs_support/
tests/
```

Root modules such as `database_manager.py`, `query_parser.py`, `workers.py`, and `styles.py` are compatibility wrappers.

## NAVER API HUB

- Endpoint: `GET https://naverapihub.apigw.ntruss.com/search/v1/news`
- Headers: `X-NCP-APIGW-API-KEY-ID`, `X-NCP-APIGW-API-KEY`
- Shared helpers live in `core/naver_api.py` and must be used by both `ApiWorker` and settings validation.
- Do **not** restore legacy `openapi.naver.com` or `X-Naver-Client-*` headers.
- Config still stores `client_id` / `client_secret` field names; values must be API HUB credentials.
- Parse both Search flat errors and API Gateway nested `error` objects via `parse_naver_api_error`.
- Map HTTP 401/403 to `auth_error` for UI messaging.

## Important Contracts

- Query scope uses canonical fetch keys from `core.query_parser`.
- `upsert_news(...) -> tuple[int, int]` remains compatible.
- `upsert_news_detailed(...) -> NewsUpsertResult` is the preferred fetch save path.
- `count_news(...) -> int` remains compatible.
- `count_news_states(...) -> NewsCountSummary` is the preferred full reload count path.
- `ApiWorker.finished` keeps the existing payload keys.
- `DBWorker` full reload calculates total/unread together; append reuses known total.
- FTS schema/backfill exists, but LIKE token-AND remains the search truth.
- Cloud sync exchanges ZIP snapshots, not live cloud-hosted SQLite files.

## Change Guide

| Change | Start Here |
|---|---|
| API endpoint/headers/errors | `core/naver_api.py`, `core/workers_support/api_worker.py` |
| Settings API validation/UI copy | `ui/_settings_dialog_tasks.py`, `ui/_settings_dialog_content.py`, `ui/_settings_dialog_docs.py` |
| Fetch/API behavior | `core/workers_support/api_worker.py` |
| Upsert performance | `core/db_mutations_support/news_upsert.py` |
| List/count semantics | `core/db_queries_support/fetch.py` |
| News tab load/render | `ui/news_tab_support/` |
| Badge/tray counts | `ui/main_window_support/ui_shell_support/` |
| Settings import/export | `ui/main_window_io_support/` |
| Cloud merge | `core/cloud_sync_support/`, `core/db_cloud_sync_support/` |
| Backup/restore | `core/backup_support/`, `ui/dialogs_support/backup_dialog/` |
| Packaging | `news_scraper_pro.spec` |

## Validation

```bash
python -m pytest -q
python -m pyright
```

For document/spec changes:

```bash
python -m pytest tests/test_encoding_smoke.py tests/test_version_history_guard.py tests/test_spec_runtime_tmpdir.py -q
```

For API HUB regression:

```bash
python -m pytest tests/test_naver_api_hub.py tests/test_settings_validation_http_policy.py -q
```

For packaged release checks:

```bash
python -m PyInstaller --noconfirm --clean news_scraper_pro.spec
```

## Repository Hygiene

- Do not commit runtime DB/config/log files, build output, caches, `.codegraph/`, or local scratch folders.
- Keep Markdown concise and current-state oriented.
- Keep `news_scraper_pro.spec` focused on the actual dependency and packaging contract.
- Preserve UTF-8 text files.
- When bumping `VERSION`, add a matching `## v{VERSION}` section to `update_history.md`.

<!-- SPECKIT-AGENT-GUIDE:START -->

## Spec Kit / Spec-Driven Development (AI 에이전트 필독)

> 이 블록은 GitHub Spec Kit 활성화 및 기능 명세 작업 결과를 AI 에이전트가 바로 쓰도록 정리한 안내입니다.
> 수정 시 마커 주석을 유지하세요. 스크립트/후속 세션이 이 구간을 갱신합니다.

### 이 저장소 상태

- **프로젝트**: `navernews-tabsearch`
- **Spec Kit 초기화**: `.specify/ 있음`
- **에이전트 스킬**: Grok=True, Claude=True, Codex/Agy(.agents)=True
- **활성 기능 디렉터리**: `specs/001-news-tabsearch-user-readme` (포인터: `.specify/feature.json`)
- **기능 제목**: 네이버 뉴스 탭 검색 · 사용자 안내
- **산출물**: spec=`yes`, plan=`True`, research/data-model/quickstart=`True`, tasks=`False`, converge=`False`

### 에이전트가 먼저 읽을 파일

1. `specs/001-news-tabsearch-user-readme/spec.md` — 무엇을/왜 (사용자 스토리, FR, 성공 기준)
2. `specs/001-news-tabsearch-user-readme/plan.md` — 기술 컨텍스트·구조 결정
3. `specs/001-news-tabsearch-user-readme/tasks.md` — 실행 가능 작업 목록 (`[x]`=이미 있음, `[ ]`=잔여)
4. `specs/001-news-tabsearch-user-readme/research.md`, `data-model.md`, `quickstart.md`, `contracts/` — 설계 보조
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
read specs/001-news-tabsearch-user-readme/spec.md
read specs/001-news-tabsearch-user-readme/tasks.md
# 잔여 구현
/speckit-implement   # 또는 tasks.md 의 [ ] 항목만 수행
# 구현 후 갭 재점검
/speckit-converge
```

### 관련 링크

- Spec Kit: https://github.com/github/spec-kit
- 로컬 CLI: `specify` (uv tool, 버전은 `specify version`)

<!-- SPECKIT-AGENT-GUIDE:END -->
