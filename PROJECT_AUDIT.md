# Project Audit

- 감사 일자: 2026-09-20
- 감사 대상: `main` 브랜치, commit `791707a`, `core.constants.VERSION = "32.8.0"`
- 감사 범위: 기능 구현 정확성 · 런타임 안정성 · 데이터 무결성
- 조치 상태: **전 항목 구현 완료 (v32.9.0)** — 0절 참조. 1~9절은 감사 시점의 근거를 그대로 보존한다.
- 감사 방식: CodeGraph 인덱스 기반 구조 분석 + 직접 코드 열람 + 실제 계측(합성 DB) + 부분 테스트 실행

> 이 문서는 2026-08-23자 이전 감사 문서를 대체한다. 이전 감사에서 Resolved로 표시된 항목들(스냅샷 격리 범위, maintenance force detach 제거, CSV formula 중화, 기사 단위 transaction)은 이번 감사에서 **독립적으로 재확인했고 실제로 해결되어 있다.** 아래 내용은 그 위에서 새로 발견한 것만 다룬다.

---

## 0. Remediation Status (2026-09-20, v32.9.0)

이 감사의 **13개 항목을 모두 구현했다.** 구현 중 감사 본문의 오류 1건도 발견해 정정한다.

### 감사 본문 정정

> **ISSUE-001의 "정답 구현" 서술은 틀렸다.** 감사는 `restore_deleted_link`를 스코프 한정 재계산의 올바른 예시로 들었으나, 구현 중 실제로 검증해 보니 **그 함수 자체가 깨져 있었다.** `_collect_affected_query_key_hashes`가 `COALESCE(n.is_deleted,0)=0`으로 필터링하는데 복구 대상 행은 그 시점에 `is_deleted=1`이므로, 수집 결과가 항상 비어 재계산이 전혀 일어나지 않았다. 즉 기사를 복구해도 같은 제목의 다른 기사에 낡은 중복 플래그가 남았다. 저렴했던 이유는 올바라서가 아니라 아무 일도 하지 않았기 때문이다. 두 함수를 모두 고쳤고(`include_deleted=True`), 회귀 테스트로 고정했다.

### 조치 내역

| 항목 | 상태 | 결과 |
|---|---|---|
| ISSUE-001 삭제 시 전체 재계산 | **Fixed** | 12만 행 기준 **0.80초 → 0.2ms**. `CROSS JOIN` 순서 힌트로 쿼리도 61.7ms → 0.01ms |
| ISSUE-001b 복구 시 플래그 미갱신 | **Fixed** (신규 발견) | `include_deleted=True`로 수집해 복구 후 재계산 |
| ISSUE-002 매 실행 O(아카이브) 시작 작업 | **Fixed** | `SCHEMA_REPAIR_REVISION` 1회성 전환 + 정상 종료 시 `quick_check`. **2.33초 → 0.37~0.49초** |
| ISSUE-003 tombstone 회수 불가 | **Fixed** | 보존 기간(기본 90일) 경과분 회수 + 설정 노출 + 정리 전 건수 안내 |
| GAP-001 미사용 FTS backfill | **Fixed** | 기본 OFF, `NEWS_SCRAPER_ENABLE_FTS_BACKFILL=1`로 활성화. 스키마는 유지 |
| GAP-002 비원자적 설정 내보내기 | **Fixed** | `_write_text_atomic` 사용 |
| GAP-003 비상 커넥션 TOCTOU | **Fixed** | 락 안에서 슬롯 선예약 |
| GAP-004 테스트 collection 중단 | **Fixed** | 의존성 부재 시 skip으로 강등 + 사유 표시 |
| GAP-005 Markdown 링크 이스케이프 | **Fixed** | 제목 `[]` 이스케이프, URL `<>` 래핑 |
| GAP-006 reparse point 미해소 | **Fixed** | `realpath` 재검증. 실제 junction으로 차단 확인 |
| GAP-007 저장소 가시성 없음 | **Fixed** | 통계 화면 `💾 저장소` 패널 |
| GAP-008 닫은 탭 스코프 잔존 | **Fixed** | 설계는 유지하되 `검색 범위 수`를 지표로 노출. 미리보기·확정형 수동 정리로 해소 (v32.10.0). 고아 기사 행 유지, tombstone 제외, 스코프 한정 중복 재계산 |
| MISMATCH-001 README FTS 문구 | **Fixed** | 실제 동작(토큰 AND 부분일치)으로 정정 |
| MISMATCH-002 LICENSE 누락 | **Fixed** | MIT `LICENSE` 추가 |
| 항목 11 전체 재계산 API 오용 방지 | **Fixed** | `_recalculate_duplicate_flags_for_entire_database`로 개명 + docstring 경고 |

### 검증

- **437 passed, 1 skipped, 0 failed, 10 subtests passed** (신규 회귀 21건 포함) — 릴리즈 전 재검증(2026-09-20, Python 3.14/Windows). `python -m pyright`는 0 errors.
- **450 passed, 1 skipped, 0 failed, 10 subtests passed** (scope cleanup 10건 포함) — v32.10.0 릴리즈 전 재검증(2026-09-22, Python 3.14/Windows). `python -m pyright`는 0 errors.
- `python -m pytest -q`가 더 이상 중단되지 않는다: 이전 `44 errors during collection` → **238 passed, 21 skipped**
- 비용 회귀 테스트는 원래 버그를 재도입해 실제로 잡히는지 확인했다(`401 not less than 100`, `0 != 1`)
- 감사 당시 부재했던 PyQt6가 이후 설치되어, UI·워커 테스트를 이번에는 실제로 실행했다. `cryptography`는 Windows ARM64 휠이 없어 여전히 부재하며 해당 2개 모듈만 미실행이다.

---

## 1. Executive Summary

### 전체 상태

성숙하고 방어적으로 작성된 코드베이스다. 이번 감사에서 세운 가설 대부분이 **반증되었다** — 워커 취소 경로, SQL 식별자 처리, CSV 내보내기, zip 추출, 설정 파일 원자적 쓰기, 클라우드 병합 롤백, 커넥션 풀 반환 균형은 모두 이미 올바르게 보호되어 있다. 자격증명은 DPAPI로 보관되고, 자동 업데이트는 Ed25519 서명 + SHA-256 + HTTPS 강제 + 스모크 테스트 + 롤백까지 갖췄다.

발견된 실제 결함은 **소수이고 성격이 한 가지로 수렴한다: 중복 플래그 재계산 범위의 불일치.** 스코프 한정 재계산(`_recalculate_duplicates_for_affected`, `_recalculate_duplicate_flags_for_query_key_hashes`)이 존재하고 대부분의 경로가 그것을 쓰는데, 두 곳이 전체 테이블 재계산(`_recalculate_duplicate_flags_with_conn`)을 호출한다.

### 전체 위험도

**Medium.** 데이터 파괴나 보안 노출 경로는 발견되지 않았다. 발견된 결함은 성능/응답성 저하와 저장공간 회수 누락이며, 모두 아카이브 크기에 비례해 악화된다. 제품의 핵심 약속이 "영구 보관"이므로 시간이 갈수록 심해지는 성질이 문제다.

### 가장 중요한 문제

1. **[ISSUE-001] 기사 1건 삭제가 전체 아카이브를 재계산한다** — UI 스레드에서 동기 실행. 120,000행 기준 **측정 0.80초**, 같은 파일의 형제 함수 `restore_deleted_link`는 **0.003초**. 250배 차이.
2. **[ISSUE-002] 매 실행마다 아카이브 전체에 비례하는 시작 작업** — 창이 뜨기 전 동기 블로킹. 120,000건/93MB 기준 **측정 2.3초**, 진행 표시 없음.
3. **[ISSUE-003] soft-delete된 기사는 어떤 경로로도 회수되지 않는다** — "전체 기사 정리"조차 tombstone을 남긴다. 본문·메모가 그대로 보존된 채 무한 누적.
4. **[GAP-001] FTS5 인덱스를 만들고 계속 backfill하지만 어떤 질의도 사용하지 않는다** — `_fts_match_expression()`이 무조건 `""`를 반환. 의도된 선택이지만 비용만 지불 중이며 README는 이를 기능으로 광고한다.

### 데이터 손상/유실 가능성

**발견되지 않았다.** 확인한 보호 장치:

- 모든 설정/백업/내보내기 쓰기가 `mkstemp` → `fsync` → `os.replace` 원자적 패턴 (`export_settings` 1곳 예외, GAP-002)
- 클라우드 병합은 병합 전 `conn.backup()` 롤백 스냅샷 생성 + 실패 시 복원 + maintenance mode로 동시 쓰기 차단
- 백업 복원은 스테이징 스냅샷 + 실패 시 롤백, destructive 경로는 `_safe_backup_child_dir` containment 검사 통과
- 시작 시 `PRAGMA integrity_check`, 손상 확정 시에만 DB 세트를 `.corrupt_<ts>/`로 이동 보존 후 재생성
- `news_keywords`/`news_tags`/`news_tag_state` 모두 `ON DELETE CASCADE` + 커넥션마다 `PRAGMA foreign_keys=ON` (합성 DB에서 실제 스키마로 확인)

ISSUE-003은 **유실이 아니라 반대 방향(회수 누락)**이므로 데이터 손상 위험은 아니다.

### 가장 먼저 수정해야 할 영역

[core/db_mutations_support/state_tags_support/article_state.py:141](core/db_mutations_support/state_tags_support/article_state.py#L141) 한 줄. 이미 존재하는 스코프 한정 헬퍼로 교체하면 ISSUE-001이 해소되고, 같은 패턴을 [core/db_schema_support/init.py:162](core/db_schema_support/init.py#L162)에 적용하면 ISSUE-002의 큰 부분이 사라진다.

---

## 2. Project Understanding

### 목적

관심 키워드별로 네이버 뉴스를 수집해 로컬 SQLite에 **영구 보관**하고, 읽음/북마크/메모/태그/자동화 규칙으로 관리하는 Windows 데스크톱 뉴스 모니터링 앱. 여러 주제를 탭으로 분리해 각기 다른 주기로 모니터링하며, 클라우드 폴더를 경유해 여러 PC 간 상태를 동기화한다.

### 주요 entrypoint

| 경로 | 역할 |
|---|---|
| [news_scraper_pro.py](news_scraper_pro.py) | 실행 진입점 + 루트 호환성 wrapper(광범위한 re-export) |
| [news_scraper_pro.py:143](news_scraper_pro.py#L143) | `handle_update_helper_args()` → `--smoke` / `--apply-update` 헬퍼 모드 분기 |
| [core/bootstrap.py](core/bootstrap.py) `main()` | 레거시 마이그레이션 → 예외/시그널 훅 → 단일 인스턴스 락 → 예약 복원 → `MainApp` → `app.exec()` |
| [ui/main_window.py](ui/main_window.py) `MainApp` | 메인 윈도우 (mixin 합성) |

### 핵심 모듈

| 영역 | 모듈 |
|---|---|
| DB facade / 커넥션 풀 | [core/database.py](core/database.py) |
| 스키마·마이그레이션 | [core/db_schema_support/](core/db_schema_support/) |
| 조회 / 집계 | [core/db_queries_support/](core/db_queries_support/) |
| 변경 / 유지보수 | [core/db_mutations_support/](core/db_mutations_support/) |
| API HUB 계약 | [core/naver_api.py](core/naver_api.py) |
| 워커 | [core/workers_support/](core/workers_support/) (`ApiWorker`, `DBWorker`, `IterativeJobWorker`) |
| 클라우드 동기화 | [core/cloud_sync_support/](core/cloud_sync_support/), [core/db_cloud_sync_support/](core/db_cloud_sync_support/) |
| 자동 업데이트 | [core/update_manifest.py](core/update_manifest.py), [core/update_installer.py](core/update_installer.py) |
| 백업 | [core/backup_support/](core/backup_support/) |
| 탭 UI | [ui/news_tab.py](ui/news_tab.py) + [ui/news_tab_support/](ui/news_tab_support/) |

### 데이터 저장

`%LOCALAPPDATA%\NaverNewsScraperPro\` (`NEWS_SCRAPER_DATA_DIR` / `NEWS_SCRAPER_PORTABLE`로 재정의 가능)

- `news_database.db` — SQLite, WAL, `synchronous=NORMAL`, 커넥션 풀 10 + 비상 커넥션 최대 2
- `news_scraper_config.json` (+ `.backup` 회전) — client_secret은 Windows DPAPI 암호화
- `backups/`, `updates/`, `news_scraper.log`

테이블: `news`(link PK) / `news_keywords`(link+query_key PK, 탭 스코프 멤버십) / `news_tags` / `news_tag_state` / `app_meta` / `news_fts`(FTS5).

### 외부 의존성

`PyQt6 6.11.0`, `requests 2.34.2`, `cryptography 50.0.0`(Ed25519 매니페스트 검증), `charset-normalizer`. 외부 서비스는 NAVER API HUB(`naverapihub.apigw.ntruss.com`)와 GitHub Releases 두 곳뿐.

### 핵심 실행 흐름

**뉴스 수집 (Entry → Handler → Core → API/DB → Result)**

```text
탭 새로고침 / 자동 타이머 / 순차 새로고침
  → refresh_flow._process_next_refresh()            [maintenance·cooldown 선검사]
  → worker_flow_support/start.py fetch_news()       [maintenance → 키워드 → 자격증명 → cooldown → dedupe guard]
  → QThread + ApiWorker.run()                        [재시도/백오프/429/리다이렉트 차단]
  → GET naverapihub.apigw.ntruss.com/search/v1/news  [X-NCP-APIGW-API-KEY-ID / -API-KEY]
  → 제외어 필터 → link 정규화 → publisher 추출
  → DatabaseManager.upsert_news_detailed()           [단일 transaction, 스코프 한정 dup 재계산]
  → ApiWorker.finished(dict)
  → completion.py on_fetch_done()                    [stale request_id 검사 → 자동화 규칙 → 커서/총계 저장]
  → NewsTab.load_data_from_db() → DBWorker → fetch_news(conn=...) → 렌더 + 배지
```

**기사 상태 변경**

```text
카드 액션 / 우클릭 메뉴 → NewsTab action_triggered
  → _NewsTabArticleActionsMixin._set_read_state / _save_note_state / _delete_target
  → DatabaseManager.update_status / save_note / delete_link     [UI 스레드 동기 호출]
  → 로컬 캐시 갱신 → sync_link_state_across_tabs → 배지 갱신
```

**클라우드 동기화**

```text
타이머/수동 → _cloud_sync_block_reason() → begin_database_maintenance("cloud_sync")
  → [export] create_cloud_snapshot() → zip(manifest + db + settings)
  → [import] read_snapshot_manifest → extract_snapshot(멤버명 검증) → _verify_sqlite_db
  → merge_cloud_snapshot_db(): rollback backup → ATTACH ? AS cloud_src → 행 병합
                                → 전체 dup 재계산 → seen_ids 기록 → DETACH
  → 실패 시 rollback backup 복원
```

---

## 3. Audit Coverage & Limitations

### 실제 확인한 주요 모듈

전문 열람: `core/database.py`, `db_schema_support/{connection,init,keywords,backfill}.py`, `db_queries_support/{fetch,filters}.py`, `db_mutations_support/news_upsert.py`, `db_mutations_support/maintenance_support/{deletion,optimize}.py`, `db_mutations_support/state_tags_support/article_state.py`, `db_cloud_sync_support/{apply,metadata,rollback}.py`, `workers_support/{api_worker,db_worker}.py`, `core/bootstrap.py`, `core/naver_api.py`, `core/query_parser.py`, `core/update_manifest.py`, `core/update_installer.py`, `core/config_store_support/{io,secrets}.py`, `core/backup_support/{fs,restore}.py`, `core/cloud_sync_support/{path_policy,import_flow}.py`, `core/startup.py`, `core/validation.py`, `ui/main_window_update.py`, `ui/main_window_fetch_support/{refresh_flow,worker_flow_support/*}`, `ui/main_window_support/base_support/maintenance.py`, `ui/news_tab_support/loading_support/{db_loading,lifecycle}.py`, `ui/news_tab_support/actions_support/article_state.py`, `ui/main_window_io_support/{cloud,exports,settings_dialogs}.py`, `ui/_main_window_tabs.py`, `ui/_main_window_analysis.py`(발췌), `ui/widgets.py`.

### CodeGraph로 분석한 호출 관계

CodeGraph MCP(`codegraph_explore`)를 사용했다. 구체적으로:

- fetch 파이프라인 전체(`fetch_news` → `ApiWorker` → `DBWorker` → `upsert_news_detailed`)의 심볼·호출 경로와 blast radius
- `delete_link` / `_should_block_local_db_action`의 caller/callee — **동적 디스패치(`getattr(self, "_should_block_db_action")`)를 따라가 후보 4곳을 식별**했고, 이것이 ISSUE-001의 UI 스레드 호출 경로 확정에 직접 기여했다
- `fetch_news`가 동명이인(DB 계층 / UI 계층) 두 개임을 확인하고 각각의 caller를 분리
- 프롬프트 제출 시 세션 훅이 주입한 CodeGraph 사전 컨텍스트

CodeGraph가 커버하지 못한 부분(정규식 패턴 검색, 인덱스/스키마 실물 확인, 수치 계측)은 grep·직접 열람·실행 계측으로 보완했다.

### 실행한 테스트

```bash
python -m pytest -q --continue-on-collection-errors
# → 86 passed, 1 failed, 1 skipped, 5 subtests passed, 44 errors in 4.25s
```

- **44개 테스트 모듈이 collection 단계에서 ImportError**로 실패했다. 원인은 이 감사 환경(Python 3.11.9 ARM64)에 **PyQt6가 설치되어 있지 않기 때문**이며, 제품 결함이 아니다. 유일한 `failed`(`tests/test_entrypoint_bootstrap.py`)도 같은 원인이다.
- **실제로 실행되어 통과한 것은 88개 수집분 중 86개**로, DB 스키마/쿼리·query parser·config 정규화·update manifest/installer·backup fs·cloud snapshot·encoding smoke 등 비-Qt 계층이다.
- 감사 제약상 의존성을 설치하지 않았으므로, **워커 생명주기·탭 UI·maintenance mode 관련 테스트는 실행하지 못했다.** 해당 영역은 코드 열람으로만 검증했다.

```bash
python -m pyright
# → 188 errors (165 = reportMissingImports: PyQt6, 나머지 23 = 그로 인한 파생 오류)
```

PyQt6 부재로 **의미 있는 타입 검증은 수행하지 못했다.** 비-import 오류 23건은 전부 Qt 타입이 `Unknown`/`None`으로 추론된 결과(`QWidget.__init__` "Expected 0 positional arguments" 등)이므로, PyQt6가 있는 환경에서는 깨끗할 가능성이 높으나 이번 감사에서 확인하지 못했다.

### 실행한 계측

제품 데이터는 건드리지 않고, 스크래치패드에 **합성 DB**(기사 120,000건 / `news_keywords` 120,000행 / 93MB, 제목 해시 충돌률 약 50%)를 만들어 측정했다. 환경: Windows 11 ARM64, Python 3.11.9, 웜 캐시.

| 측정 대상 | 결과 |
|---|---|
| `DatabaseManager()` 생성 (= 앱 시작 블로킹 구간) | 2.33 / 2.28 / 2.40 초 |
| ├ `PRAGMA integrity_check` 단독 | 웜 0.8초대, 콜드 측정 시 4.03초 |
| └ `_recalculate_duplicate_flags_with_conn` | 0.79~0.84초 (`PERF` 로그 814ms) |
| `delete_link()` 1건 | 0.782 / 0.783 / 0.825 / 0.825 / 0.856 초 |
| `restore_deleted_link()` 1건 (스코프 한정) | 0.003 / 0.003 / 0.005 초 |
| FTS backfill 전량 + DB 증가 | 0.8초 / +2.7MB (합성 description이 1자라 실데이터 대비 과소) |

`os.kill(pid, 0)`의 Windows 동작은 별도 자식 프로세스로 실제 검증했다(아래 반증 목록 참조).

### 확인하지 못한 환경 / 한계

1. **PyQt6 런타임 전체** — 창 표시, 트레이, 타이머, 시그널/슬롯 실제 동작, 스레드 어피니티를 실행으로 확인하지 못했다. UI 계층 결론은 전부 정적 분석 기반이다.
2. **실제 NAVER API HUB 호출** — 자격증명이 없어 429/5xx/리다이렉트 응답의 실제 처리, Retry-After 파싱을 실측하지 못했다.
3. **frozen(PyInstaller) 빌드** — `sys.frozen` 분기, 자동 업데이트 2-프로세스 교체, `--smoke` 기동 점검을 실행하지 못했다. 업데이트 설치 경로는 코드 열람 + 기존 단위 테스트 통과로만 검증했다.
4. **실제 클라우드 폴더(OneDrive/Google Drive)** — 파일 잠금·지연 동기화·부분 쓰기 상황에서의 스냅샷 교환을 재현하지 못했다.
5. **다중 PC 동시 동기화** — 여러 머신이 같은 폴더에 동시 스냅샷을 쓰는 경합을 재현하지 못했다.
6. **계측 수치의 절대값** — 합성 데이터(짧은 description, 균일한 해시 분포) 기준이다. 실데이터의 절대 시간은 다르겠지만, 병목의 **원인과 O(전체 아카이브) 스케일링 성질**은 SQL 자체에서 확정되므로 결론은 유효하다.
7. **macOS/Linux** — README가 Windows 전용을 명시하므로 대상에서 제외했다. 다만 `core/` 계층 상당수가 플랫폼 독립적으로 작성되어 있다.

### 반증되어 이슈에서 제외한 가설

정확도를 위해, 검토했으나 **근거가 확인되어 기각한** 항목을 남긴다.

| 가설 | 반증 근거 |
|---|---|
| `_wait_for_parent`의 `os.kill(pid, 0)`이 Windows에서 `TerminateProcess`를 호출해 부모 앱을 강제 종료 | **실제 자식 프로세스로 검증**: 예외 없이 반환하고 자식은 생존. 이 Python에서는 생존 확인 프로브로 동작 |
| CSV 내보내기의 스프레드시트 수식 주입 | `_export_row`가 모든 사용자 유래 셀에 `_spreadsheet_safe_csv_cell()` 적용 |
| `f"UPDATE news SET {field} ..."`의 SQL 주입 | `update_status` 진입부에서 `self.ALLOWED_UPDATE_FIELDS` allow-list 검사 후 거부 |
| `PRAGMA {schema}.table_info({table})`의 식별자 주입 | 전 호출부가 `"cloud_src"`, `"news"` 등 코드 내 리터럴만 전달 |
| 순차 새로고침이 `fetch_news`의 early return에서 영구 정지 | maintenance/cooldown은 `_process_next_refresh`가 선검사·재스케줄, 빈 키워드는 `_prepare_refresh_keywords`가 `has_positive_keyword`로 선필터, 나머지 early return은 전부 `_on_sequential_fetch_done()` 호출 |
| 커넥션 누수 → `id()` 재사용 → 풀 영구 축소 | `core/` 전체에서 `get_connection` 41회 : `return_connection` 42회, 전부 `finally` 블록 내부(스크립트로 검증) |
| 클라우드 병합 롤백이 동시 fetch 쓰기를 덮어씀 | `begin_database_maintenance("cloud_sync")`가 선행, 활성 워커가 실제 종료되지 않으면 작업 자체를 거부 |
| 스냅샷 zip의 path traversal (zip slip) | `_validate_zip_member_name()` + 추출 시 `os.path.basename()` 재적용 + `_verify_sqlite_db` |
| 설정 파일 손상 시 시작 불가 | `mkstemp`+`fsync`+`os.replace` 원자적 쓰기 + `.backup` 회전 + 로드 실패 시 backup fallback |
| 매니페스트 URL 리다이렉트로 HTTP 강등 | 요청 전 scheme 검증 + `response.geturl()` 재검증 + Ed25519 서명 + 만료시각 + 크기 상한 |
| `init_db`의 raw 커넥션이 FK를 끄고 마이그레이션 | 해당 커넥션은 DELETE를 수행하지 않음. 풀/읽기 커넥션은 모두 `PRAGMA foreign_keys=ON` |
| 탭 닫기/이름 변경 중 워커 경합 | 두 경로 모두 `_ensure_tab_worker_stopped()` 성공 이후에만 상태 변경 (CLAUDE.md 계약대로 구현됨) |
| `DBWorker` 응답의 stale 적용 | `_load_request_id` 단조 증가 + `on_data_loaded`/`on_data_error` 양쪽에서 `request_id != self._load_request_id` 검사 |

---

## 4. High-Risk Issues

### [ISSUE-001] 기사 1건 삭제가 아카이브 전체의 중복 플래그를 재계산한다 (UI 스레드 동기 실행)

- **위치:** [core/db_mutations_support/state_tags_support/article_state.py:141](core/db_mutations_support/state_tags_support/article_state.py#L141) — `DatabaseManager.delete_link()`
- **우선순위:** High
- **신뢰도:** Confirmed (계측으로 확인)
- **문제:**
  `delete_link()`는 기사 **1건**을 soft-delete한 뒤, 같은 transaction 안에서 `self._recalculate_duplicate_flags_with_conn(conn)`를 호출한다. 이 함수는 `news_keywords ⋈ news` **전체**를 `fetchall()`로 메모리에 적재하고, 파이썬에서 그룹을 만든 뒤, **모든 행에 대해** `UPDATE news_keywords SET is_duplicate=?`를 `executemany`로 실행한다. 값이 바뀌지 않는 행도 SQLite는 그대로 재기록한다.

  바로 아래에 있는 형제 함수 `restore_deleted_link()`([:175](core/db_mutations_support/state_tags_support/article_state.py#L175))는 **같은 문제에 대해 `_collect_affected_query_key_hashes()` + `_recalculate_duplicates_for_affected()`라는 스코프 한정 변형을 올바르게 사용한다.**
- **발생 조건:**
  기사 카드 우클릭 → `🗑 목록에서 삭제` → 확인. 특별한 조건이 전혀 없는 일상적 단일 클릭 동작이다. maintenance mode에 진입하지도, 워커로 오프로딩하지도 않는다.
- **영향:**
  아카이브 크기에 비례해 UI가 프리즈한다. 계측값:

  | `news_keywords` 행 수 | `delete_link()` 1회 | `restore_deleted_link()` 1회 |
  |---|---|---|
  | 120,000 | **0.78 ~ 0.86초** | **0.003 ~ 0.005초** |

  약 **250배** 차이다. 기사 여러 건을 연속 삭제하면 매번 전체 재계산이 반복되어 10건 삭제에 8초 이상 UI가 멈춘다. 추가로 삭제 1회마다 `news_keywords` 전체가 디스크에 재기록되어 쓰기 증폭이 발생한다. 데이터는 정확하게 유지되므로 무결성 문제는 아니다.
- **근거:**
  - 호출: [article_state.py:141](core/db_mutations_support/state_tags_support/article_state.py#L141) — `self._recalculate_duplicate_flags_with_conn(conn)`
  - 구현: [core/_db_duplicates.py:70](core/_db_duplicates.py#L70) — WHERE 절 없는 전체 SELECT, 이어서 전 행 `executemany` UPDATE. 값 변경 여부를 거르는 조건이 없다.
  - 대조군: [article_state.py:175](core/db_mutations_support/state_tags_support/article_state.py#L175), [deletion.py:91](core/db_mutations_support/maintenance_support/deletion.py#L91), [news_upsert.py:257](core/db_mutations_support/news_upsert.py#L257)은 모두 스코프 한정 변형 사용. **전체 재계산을 쓰는 곳은 `delete_link`, `init_db`, 클라우드 전체 병합 세 곳뿐이고, 앞의 두 곳이 부적절하다.**
  - 계측: 합성 DB 120,000행에서 5회 연속 측정, 위 표 참조.
- **반증 확인:**
  - *상위 caller가 워커로 오프로딩하는가?* → 아니다. CodeGraph로 동적 디스패치를 따라 확인한 경로는 [ui/widgets.py:118](ui/widgets.py#L118) `contextMenuEvent` → `action_triggered` 시그널 → [ui/news_tab_support/actions_support/article_state.py:267](ui/news_tab_support/actions_support/article_state.py#L267) `_delete_target` → `self.db.delete_link(link)` **직접 동기 호출**이다. 같은 함수가 `QMessageBox.question()`과 `self.lbl_status.setText()`을 호출하므로 GUI 스레드임이 확정된다.
  - *maintenance mode가 보호하는가?* → 아니다. `_should_block_local_db_action("delete article")`은 **이미 유지보수 중일 때 차단**할 뿐, 자기 자신이 유지보수 모드로 진입하지 않는다. 오히려 이 작업이 유지보수급 비용을 UI 스레드에서 치른다.
  - *chunking/취소가 있는가?* → 없다. `_run_chunked_news_delete`의 청크·진행·취소 인프라는 일괄 삭제 전용이고 단건 삭제는 거치지 않는다.
  - *dead code인가?* → 아니다. README가 우클릭 메뉴의 기본 기능으로 문서화하고 있다.
  - *현실적인가?* → 그렇다. 제품이 무한 아카이브를 전제하므로 `news_keywords` 행 수는 시간에 따라 단조 증가한다. ISSUE-003(회수 안 되는 tombstone) 때문에 더 빨리 증가한다.
- **호출/영향 범위 (CodeGraph 기준):**
  - `delete_link`의 caller는 `ui/news_tab_support/actions_support/article_state.py` 5곳(전부 UI 스레드)
  - 커버 테스트: `tests/test_db_queries.py`, `tests/test_implementation_batch_20260427.py`, `tests/test_cloud_sync.py` — **모두 정확성만 검증하고 비용은 검증하지 않는다**
  - 수정 영향 모듈: `core/_db_duplicates.py`(변경 불필요, 기존 헬퍼 재사용), 삭제 후 배지/필터 갱신 경로(`_refresh_after_local_change`, `_notify_badge_change`)는 영향 없음
- **권장 수정 방향:**
  `restore_deleted_link`와 동일한 형태로 맞춘다 — UPDATE **이전에** `_collect_affected_query_key_hashes(conn, "n.link = ?", [link])`로 영향 해시를 수집하고, UPDATE 이후 `_recalculate_duplicates_for_affected(conn, affected)`를 호출한다. 삭제된 기사와 title_hash가 같은 스코프만 재평가하면 되므로 의미상 완전히 동치다.
- **필요한 회귀 테스트:**
  - 정확성: 같은 `query_key`에 title_hash가 동일한 기사 3건 → 1건 삭제 → 남은 2건의 `is_duplicate`가 여전히 1, 2건 중 1건 더 삭제 → 남은 1건이 0으로 내려감
  - 교차 스코프 격리: 서로 다른 `query_key`에 같은 title_hash가 있을 때, 한쪽 삭제가 다른 쪽 플래그를 바꾸지 않음
  - 비용 회귀(핵심): `news_keywords` 10,000행을 준비하고 `conn.execute`를 카운트하는 스파이로 감싸 **`delete_link()` 1회의 UPDATE 대상 행 수가 전체 행 수에 비례하지 않음**을 단언. 이것이 있어야 회귀가 재발하지 않는다.

---

### [ISSUE-002] 앱 시작 시 아카이브 전체에 비례하는 작업이 창 표시 전에 동기 실행된다

- **위치:** [core/db_schema_support/init.py:162](core/db_schema_support/init.py#L162) (`init_db` 말미의 전체 dup 재계산), [core/database.py:147](core/database.py#L147) (`DatabaseManager.__init__`의 `integrity_check` + `init_db`)
- **우선순위:** Medium (아카이브가 커질수록 High로 악화)
- **신뢰도:** Confirmed (계측으로 확인)
- **문제:**
  `DatabaseManager.__init__`은 매 실행마다 순서대로 (1) DB 파일 전체를 읽는 `PRAGMA integrity_check`, (2) `init_db()` — 스키마 보장 + 컬럼 마이그레이션 + `INSERT OR IGNORE INTO news_keywords ... SELECT ... FROM news` 전체 스캔 + title_hash/pubDate_ts backfill 스캔 + **`_recalculate_duplicate_flags_with_conn()` 전체 재계산**을 수행한다. 모두 동기이며, `MainApp.__init__` 안에서 호출되므로 `window.show()`보다 앞선다. 스플래시나 진행 표시가 없다.

  ISSUE-001과 동일한 전체 재계산이 여기서도 호출된다. 이미 값이 올바른 두 번째 실행부터도 **120,000행 전부를 재기록**한다(측정 시 `is_duplicate=1` 60,000행 / `=0` 60,000행이 모두 그대로였음에도 전 행 UPDATE).
- **발생 조건:** 모든 실행. 조건 없음.
- **영향:**
  창이 뜨기 전 무반응 구간. 계측:

  | 구간 | 120,000건 / 93MB |
  |---|---|
  | `DatabaseManager()` 전체 | **2.28 ~ 2.40초** |
  | ├ `PRAGMA integrity_check` | 웜 캐시 0.8초대 / 콜드 단독 측정 **4.03초** |
  | ├ `news_keywords` backfill INSERT OR IGNORE | 0.12초 |
  | └ 전체 dup 재계산 | **0.81초** |

  선형 스케일이므로 수년 사용한 60만건 아카이브에서는 10초 이상이 되고, HDD·콜드 캐시·실시간 백신 스캔이 겹치면 더 길어진다. 사용자에게는 "실행했는데 아무 반응이 없다"로 보인다. 추가로 매 실행마다 멤버십 테이블 전체가 재기록된다.
- **근거:**
  - [core/database.py:147](core/database.py#L147) — `if os.path.exists(self.db_file): integrity_result = self._check_integrity_with_retry()`
  - [core/db_schema_support/init.py:162](core/db_schema_support/init.py#L162) — `self._recalculate_duplicate_flags_with_conn(conn)` (조건 없이 매번)
  - [core/db_schema_support/init.py:144](core/db_schema_support/init.py#L144) — `INSERT OR IGNORE INTO news_keywords ... SELECT ... FROM news` (조건 없이 매번 전체 스캔)
  - [tests/test_risk_fixes.py:210](tests/test_risk_fixes.py#L210) — `DatabaseManager(self.runtime_paths.db_file)`가 `MainApp.__init__`에 있음을 테스트가 명시. `core/bootstrap.py`에서 `window = MainApp(...)` → `window.show()` 순서 확인.
  - 계측: 위 표. 3회 반복 재현.
- **반증 확인:**
  - *지연/백그라운드 실행인가?* → 아니다. `__init__` 본문에서 직접 호출되고 그 결과로 커넥션 풀을 채운다.
  - *스플래시/진행 표시가 보완하는가?* → 없다. `bootstrap.main()`은 `MainApp` 생성 후에야 `window.show()`를 호출한다.
  - *마이그레이션 1회성인가?* → 아니다. 컬럼 추가(`_ensure_news_column`)는 멱등하게 스킵되지만, **dup 재계산과 `news_keywords` backfill SELECT는 가드 없이 매번 실행된다.**
  - *`integrity_check`가 필요한 안전장치 아닌가?* → 그렇다. 손상 DB를 조용히 쓰는 것보다 낫다. 다만 이것만 남기고 (2)의 불필요한 반복을 제거하면 비용이 크게 준다. 또한 매 실행 전량 검사 대신 비정상 종료 감지 시에만 수행하는 선택지도 있다.
  - *dead code인가?* → 아니다.
- **호출/영향 범위:**
  `DatabaseManager.__init__` → `MainApp.__init__` → `bootstrap.main()`. 단일 진입 경로이며 모든 사용자가 매 실행 통과한다. 탭을 닫아도 `news_keywords` 행은 남으므로(`close_tab`은 인메모리 상태만 정리) 이 비용은 사용 이력과 함께 단조 증가한다.
- **권장 수정 방향:**
  1. `init_db`에서 전체 dup 재계산을 **무조건 호출에서 제외**한다. 정상 경로에서 플래그를 깨뜨리는 곳이 없으므로(upsert·삭제·복원·병합이 각자 스코프 한정으로 유지) 매 실행 전량 재계산은 불필요하다. 필요하면 `app_meta`에 스키마/복구 리비전을 기록해 **마이그레이션이 실제로 일어났을 때만** 1회 수행하고, 수동 트리거는 기존 "DB 최적화" 메뉴에 둔다.
  2. `news_keywords` backfill INSERT도 같은 `app_meta` 플래그로 1회성으로 만든다.
  3. `integrity_check`는 유지하되, 비정상 종료 마커가 있을 때만 전량 검사하고 평시에는 `PRAGMA quick_check`로 낮추는 것을 검토한다.
  4. 어떤 경우든 최소한 스플래시/상태 표시를 붙여 무반응 구간을 감춘다.
- **필요한 회귀 테스트:**
  - 멱등성: 10,000건 DB로 `DatabaseManager()`를 2회 생성 → 두 번째 생성이 `news_keywords`에 대해 UPDATE를 **0건** 실행함을 `conn.execute` 스파이로 단언
  - 정확성 보존: 마이그레이션 1회성 전환 후에도 신규 DB / 구버전 스키마 DB / `title_hash`가 NULL인 DB 세 경우에서 플래그와 컬럼이 올바르게 구성되는지
  - 시작 시간 상한: 50,000건 합성 DB에서 `DatabaseManager()` 생성이 기준 시간 배수를 넘지 않음

---

### [ISSUE-003] soft-delete된 기사는 어떤 삭제 경로로도 회수되지 않는다

- **위치:** [core/db_mutations_support/maintenance_support/deletion.py:115](core/db_mutations_support/maintenance_support/deletion.py#L115) (`delete_old_news_chunked`), [:135](core/db_mutations_support/maintenance_support/deletion.py#L135) (`delete_all_news_chunked`)
- **우선순위:** Medium
- **신뢰도:** Confirmed (코드 경로 전수 확인)
- **문제:**
  `delete_link()`는 행을 지우지 않고 `is_deleted = 1`만 세운다. 제목·본문·메모·태그가 전부 그대로 남는다(클라우드 동기화로 삭제를 전파하기 위한 tombstone 설계이므로 그 자체는 타당하다).

  그런데 `news` 테이블에서 행을 실제로 지우는 **유일한 코드 경로**인 `_run_chunked_news_delete`의 두 WHERE 절이 모두 `COALESCE(is_deleted, 0) = 0`을 포함한다. 즉 **tombstone은 애초에 삭제 대상에서 제외된다.** `DELETE FROM news`를 코드베이스 전체에서 검색한 결과 이 경로 외에 tombstone을 회수하는 곳이 없다.
- **발생 조건:**
  기사를 목록에서 삭제한 사용자가 이후 "오래된 기사 정리" 또는 "전체 기사 정리"를 실행하는 경우. 두 메뉴 모두 README에 문서화된 기능이다.
- **영향:**
  1. **사용자 기대와 불일치** — "전체 기사 정리"를 실행해도 삭제했던 기사들이 DB에 남는다. 아카이브 전체 검색에서 `include_deleted`로 조회하면 여전히 보인다.
  2. **무한 누적** — tombstone에는 보존 정책이 없다. 시간이 갈수록 파일이 커지고, 이것이 ISSUE-002의 `integrity_check` 비용을 직접 키운다.
  3. **저장공간 회수 불가** — 기사를 지워 용량을 줄이려는 사용자의 목적이 달성되지 않는다(VACUUM을 돌려도 마찬가지).
- **근거:**
  - [deletion.py:115](core/db_mutations_support/maintenance_support/deletion.py#L115) — `"is_bookmarked = 0 AND COALESCE(is_deleted, 0) = 0 AND ("`
  - [deletion.py:135](core/db_mutations_support/maintenance_support/deletion.py#L135) — `"is_bookmarked = 0 AND COALESCE(is_deleted, 0) = 0"`
  - [article_state.py:127](core/db_mutations_support/state_tags_support/article_state.py#L127) — `UPDATE news SET is_deleted = 1, ...`, 본문 컬럼을 비우지 않음
  - `grep -rn "DELETE FROM news" core/` 결과 `news` 본체를 지우는 곳은 [deletion.py:86](core/db_mutations_support/maintenance_support/deletion.py#L86) 한 곳뿐(나머지는 `news_tags`/`news_fts`)
- **반증 확인:**
  - *다른 정리 잡이 있는가?* → 없다. `optimize_database`는 `PRAGMA optimize` + 선택적 `VACUUM`만 수행하고 행을 지우지 않는다.
  - *클라우드 병합이 회수하는가?* → 아니다. `merge_rows.py`는 tombstone을 **전파**하며(삭제 상태를 상대 DB에 반영), 제거하지 않는다.
  - *의도된 설계 아닌가?* → tombstone 유지 자체는 의도적이고 올바르다. 문제는 **보존 기간 상한도, 회수 경로도, 사용자 고지도 없다**는 점이다. 동기화가 완료된 오래된 tombstone까지 영구 보존할 이유는 없다.
  - *영향이 현실적인가?* → 그렇다. 제외어로 거르지 못한 기사를 수동 삭제하는 것은 README가 안내하는 일상 사용 패턴이다.
- **호출/영향 범위:**
  `delete_old_news` / `delete_all_news`(설정의 데이터 정리 메뉴) → `_run_chunked_news_delete`. 영향 모듈은 `core/db_queries_support/archive.py`(`include_deleted` 조회), `core/db_cloud_sync_support/merge_rows.py`(삭제 전파), 그리고 파일 크기를 통해 `core/database.py`의 시작 시 무결성 검사.
- **권장 수정 방향:**
  1. `delete_old_news_chunked`의 대상에 **"충분히 오래된 tombstone"**을 포함시킨다 — 예: `COALESCE(is_deleted,0) = 1 AND delete_updated_at < ?`(동기화 여유를 둔 보존 기간, 예: 90일). 북마크 제외 조건은 유지한다.
  2. `delete_all_news_chunked`는 tombstone도 함께 제거하거나, 최소한 "복구 가능한 삭제 기록 N건은 유지됩니다"를 확인 다이얼로그에 표기한다.
  3. 설정에 tombstone 보존 기간을 노출하고, 클라우드 동기화 사용 여부에 따라 기본값을 달리한다(미사용 시 짧게).
- **필요한 회귀 테스트:**
  - `delete_link()`로 tombstone 생성 → `delete_all_news()` → tombstone이 정책대로 제거되거나 의도적으로 보존되는지 명시적으로 단언
  - 보존 기간 경계: `delete_updated_at`이 보존 기간 직전/직후인 두 행을 준비 → 정리 후 하나만 남음
  - 동기화 안전성: tombstone 제거 후 상대 스냅샷을 병합했을 때 삭제된 기사가 되살아나지 **않는지**(seen_snapshot_ids와의 상호작용 포함)
  - 북마크 보호: 북마크된 tombstone은 어떤 정리 경로에서도 제거되지 않음

---

## 5. Potential Functional Gaps

### [GAP-001] FTS5 인덱스를 구축·유지하지만 어떤 질의도 사용하지 않는다 — **Confirmed Gap**

`_fts_match_expression()`([core/db_queries_support/filters.py:37](core/db_queries_support/filters.py#L37))은 주석과 함께 **무조건 `""`를 반환한다.** 호출부 3곳([fetch.py:125](core/db_queries_support/fetch.py#L125), [fetch.py:240](core/db_queries_support/fetch.py#L240), [archive.py:73](core/db_queries_support/archive.py#L73))은 모두 `if fts_match:`로 가드하므로 `news_fts MATCH` 절은 **한 번도 실행되지 않는다.**

한편 `news_fts` 테이블은 `init_db`에서 생성되고, `_MainWindowFtsBackfillMixin`이 백그라운드 워커로 계속 backfill하며, `backfill_news_fts_chunk`가 제목·본문 사본을 FTS content 테이블에 기록한다. 즉 **CPU·디스크·DB 용량·시작 시 무결성 검사 시간을 지불하면서 이득이 0이다.**

CLAUDE.md는 "FTS hard prefilter는 false negative 방지를 위해 다시 켜지 않습니다"라고 명시하고, 코드 주석도 "향후 랭킹/가속 작업을 위해 스키마·backfill 경로를 남겨둔다"고 밝힌다. **따라서 이것은 버그가 아니라 의도된 트레이드오프다.** 다만 (a) 비용이 계속 발생하고, (b) README는 이를 동작하는 기능으로 광고하며(MISMATCH-001), (c) backfill 워커가 maintenance/새로고침마다 일시정지·재개되는 복잡도까지 유지된다는 점에서, 보류 비용을 재평가할 가치가 있다. 실데이터 기준 DB 증가량을 먼저 측정한 뒤, 랭킹 도입 계획이 없다면 스키마만 남기고 backfill 워커를 끄는 선택지를 검토할 만하다.

### [GAP-002] `export_settings`만 원자적 쓰기를 쓰지 않는다 — **Confirmed Gap**

[ui/main_window_io_support/settings_dialogs.py:158](ui/main_window_io_support/settings_dialogs.py#L158)은 `with open(fname, "w", encoding="utf-8") as f: json.dump(...)`로 직접 기록한다. 프로젝트의 다른 모든 파일 쓰기(설정 저장, 백업, CSV/Markdown 내보내기, 업데이트 결과, pending restore)는 `mkstemp` → `fsync` → `os.replace` 패턴을 지킨다. 쓰기 도중 실패하면 잘린 JSON이 남고, 사용자는 정상 파일로 착각할 수 있다(가져오기 시점에야 실패). 영향은 제한적이고 재실행으로 복구되므로 Low이며, `export_items_to_csv`와 같은 패턴으로 맞추면 해소된다.

### [GAP-003] 비상 커넥션 상한 검사에 TOCTOU 경합이 있다 — **Confirmed Gap**

[core/database.py:183](core/database.py#L183)에서 상한 검사(`active_emergency >= self.max_emergency_connections`)는 락 안에서 하지만, 락을 놓은 뒤 커넥션을 만들고 다시 락을 잡아 집합에 추가한다. 세 스레드가 동시에 통과하면 상한 2를 넘는 커넥션이 생길 수 있다. 결과는 SQLite 커넥션 1~2개 초과뿐이고 손상이나 누수로는 이어지지 않으므로(반환 시 즉시 close) 영향은 Low다. 생성까지 락 안에서 수행하거나 카운터를 먼저 예약하면 해소된다.

### [GAP-004] PyQt6 없이는 테스트 스위트가 collection 단계에서 붕괴한다 — **Confirmed Gap**

`tests/` 67개 모듈 중 44개가 `ModuleNotFoundError: No module named 'PyQt6'`로 **collection 에러**를 낸다. skip이 아니라 에러이므로 `python -m pytest -q`(CLAUDE.md의 기본 검증 명령)가 `Interrupted: 44 errors during collection`으로 조기 종료되고, **실행 가능한 86개 테스트 결과조차 보이지 않는다.** `--continue-on-collection-errors` 없이는 비-Qt 계층의 회귀도 확인할 수 없다.

Windows 전용 데스크톱 앱이므로 PyQt6 요구 자체는 정당하다. 다만 `pytest.importorskip("PyQt6")`를 Qt 의존 모듈 상단에 두면 "44 errors"가 "44 skipped"가 되어 헤드리스/CI 환경에서도 코어 계층 회귀를 잡을 수 있다. 이번 감사에서 실제로 UI·워커 생명주기 테스트를 실행하지 못한 원인이기도 하다.

### [GAP-005] Markdown 내보내기가 링크 문법을 이스케이프하지 않는다 — **Likely Gap**

[ui/main_window_io_support/exports.py:83](ui/main_window_io_support/exports.py#L83)의 `title_line = f"### [{title}]({link})"`에서 `title`과 `link`는 `_markdown_escape`를 거치지 않는다(다른 필드는 거친다). 제목에 `]`가 있거나 URL에 `)`가 있으면 링크가 깨진다. 기사 제목에 대괄호가 쓰이는 일은 드물지 않으므로 발생 가능하지만, 결과는 표시 깨짐뿐이고 데이터 손상은 없다. 실제 네이버 기사 제목 분포를 확인하지 않았으므로 Likely로 둔다.

### [GAP-006] 백업 루트의 디렉터리 reparse point를 고려하지 않는다 — **추정**

`_safe_backup_child_dir`는 `os.path.abspath` 기반 containment 검사를 하며 `realpath`로 심볼릭 링크를 해소하지 않는다. Windows junction은 `os.path.islink`가 False를 반환하므로 `shutil.rmtree`가 그 안으로 내려가 대상 폴더 내용을 지울 수 있다. 다만 이를 악용하려면 공격자가 이미 사용자 권한으로 백업 폴더에 junction을 만들 수 있어야 하는데, 그 시점에 동일 권한으로 DB를 직접 지울 수 있으므로 **실질적인 권한 경계가 존재하지 않는다.** 로컬 단일 사용자 데스크톱 앱이라는 위협 모델상 실제 위험은 낮다고 판단해 추정으로 남긴다. 심층 방어를 원한다면 containment 검사에 `os.path.realpath`를 추가하면 된다.

### [GAP-007] 아카이브 성장에 대한 사용자 가시성/관리 수단이 없다 — **Likely Gap**

ISSUE-001·002·003은 모두 같은 뿌리를 공유한다: **아카이브가 무한히 커지는 것을 전제로 하면서 크기를 보여주거나 관리하게 해주는 장치가 없다.** 현재 DB 크기, 기사 수, tombstone 수, 예상 시작 시간 같은 지표가 UI에 노출되지 않고, 보존 정책도 수동 "오래된 기사 정리"뿐이다. 사용자는 앱이 느려지는 이유를 알 수 없다. 통계 화면에 저장소 지표를 추가하고 자동 보존 정책(예: N일 경과 비북마크 기사 자동 정리)을 옵션으로 제공하는 것이 자연스러운 보완이다.

### [GAP-008] `close_tab`이 해당 탭의 `news_keywords` 멤버십을 남긴다 — **추정**

[ui/_main_window_tabs.py:296](ui/_main_window_tabs.py#L296)은 인메모리 상태(`_tab_fetch_state`, 정책, 커서)만 정리하고 DB의 `news_keywords` 행은 남긴다. 아카이브 전체 검색에서 과거 탭의 기사를 계속 찾을 수 있어야 하므로 **의도된 설계로 보인다.** 다만 탭을 자주 만들고 지우는 사용자에게는 죽은 `query_key` 스코프가 누적되어 ISSUE-001/002의 재계산 비용을 직접 키운다. 설계 의도를 확인하지 못했으므로 추정으로 두며, 최소한 "사용되지 않는 검색 스코프 정리" 같은 선택적 정리 수단이 있으면 좋겠다.

---

## 6. Documentation Mismatches

### [MISMATCH-001] README가 FTS 전문 검색을 동작하는 기능으로 기술한다

[README.md](README.md) "데이터 저장 경로 및 기술 스택":

> **Database**: 로컬 SQLite3 (FTS 전문 검색 인덱싱 지원)

실제로는 GAP-001대로 `_fts_match_expression()`이 항상 `""`를 반환해 **FTS MATCH가 질의에 전혀 쓰이지 않는다.** 사용자 대면 검색은 전부 토큰 AND + LIKE 부분일치다. 인덱스는 "구축되지만 사용되지 않는" 상태다.

참고로 **CLAUDE.md와 AGENTS.md는 정확하다** — "FTS hard prefilter는 false negative 방지를 위해 다시 켜지 않습니다"라고 현재 상태를 올바르게 기술한다. 불일치는 README 한 곳이다. "로컬 SQLite3 (토큰 AND 부분일치 검색)" 정도로 고치거나, FTS 언급을 제거하는 것이 정확하다.

### [MISMATCH-002] README가 존재하지 않는 LICENSE 파일을 링크한다

[README.md](README.md) 마지막 줄이 `이 프로젝트는 [MIT License](LICENSE)를 따릅니다.`인데, 저장소 루트에 `LICENSE` 파일이 없다(`ls LICENSE*` → 없음). GitHub에서 깨진 링크가 되고, 라이선스가 실제로 배포물에 포함되지 않는다. MIT 전문을 담은 `LICENSE` 파일을 추가하면 해소된다.

### 확인했으나 불일치가 아닌 항목

- **"Python 3.10 이상"** — 3.11+ 전용 구문(`datetime.UTC`, `typing.Self`, `StrEnum`, `except*`, `tomllib`, `hashlib.file_digest`, `itertools.batched`)을 검색한 결과 없음. `shutil.rmtree(onexc=...)`(3.12+)는 `TypeError` fallback으로 감싸져 있고 `dataclass(slots=True)`는 3.10부터 가능하므로 **주장은 유효하다.**
- **"설정 내보내기 파일에는 API 키가 포함되지 않습니다"** — `export_settings`의 payload에 `client_id`/`client_secret`이 없음을 확인. **정확하다.**
- **"%LOCALAPPDATA%\NaverNewsScraperPro"** — `get_data_dir`이 그대로 구현하고 `tests/test_runtime_storage_paths.py`가 검증. **정확하다.**
- **"API HUB만 지원, 개발자센터 키 미지원"** — `core/naver_api.py`가 `naverapihub.apigw.ntruss.com` + `X-NCP-APIGW-API-KEY-ID`/`-API-KEY`만 정의하고 `openapi.naver.com` 흔적 없음. **정확하다.**
- **"SHA-256 + Ed25519 서명 검증, 실패 시 자동 복구"** — `verify_release_manifest`의 Ed25519 검증, `prepare_staged_update`/`apply_staged_update`의 이중 SHA-256 검증, 스모크 실패 시 `os.replace(backup, target)` 롤백 모두 확인. **정확하다.**
- **"최대 약 1,000건(start=1000)"** — `fetch_news`의 `if start_idx > 1000` 가드와 `_compute_load_more_state`의 `if next_start > 1000` 확인. **정확하다.**
- **CLAUDE.md의 성능/아키텍처 계약** — `upsert_news_detailed -> NewsUpsertResult`, `upsert_news -> tuple[int, int]` 유지, `count_news_states -> NewsCountSummary` 단일 스코프 질의, `ApiWorker.finished` payload shape, `DBWorker` append의 known total 재사용, 탭 badge의 unread 캐시 우선, 탭 닫기/이름 변경의 워커 정리 선행, 메모 10,000자 제한, 백업 root containment — **전부 코드와 일치한다.**

---

## 7. Recommended Fix Plan

### Phase 1 — Immediate

주요 기능의 체감 실패(UI 프리즈)와 사용자 기대 불일치를 제거한다. 세 항목 모두 국소 수정이며 기존 헬퍼를 재사용한다.

1. **ISSUE-001** — `delete_link`의 `_recalculate_duplicate_flags_with_conn`을 `_collect_affected_query_key_hashes` + `_recalculate_duplicates_for_affected`로 교체한다. 바로 아래 `restore_deleted_link`가 정답 형태를 이미 보여준다. **한 줄 수준의 변경으로 250배 차이를 제거한다.**
2. **ISSUE-002** — `init_db`의 전체 dup 재계산과 `news_keywords` backfill INSERT를 `app_meta` 리비전 플래그로 1회성 전환한다. 전량 재계산은 "DB 최적화" 메뉴의 수동 액션으로 남긴다.
3. **ISSUE-003** — tombstone 보존 정책을 정한다. 최소한 `delete_old_news_chunked`가 보존 기간이 지난 tombstone을 회수하게 하고, "전체 기사 정리" 다이얼로그에 tombstone 처리 방침을 명시한다.

### Phase 2 — Stability

예외 처리·입력 검증·transaction·상태 관리·OS 호환성.

4. **GAP-002** — `export_settings`를 `_write_text_atomic` 계열 패턴으로 통일한다.
5. **GAP-003** — 비상 커넥션 생성을 락 구간 안으로 옮기거나 카운터 선예약 방식으로 바꿔 상한을 엄격히 지킨다.
6. **GAP-005** — Markdown 내보내기의 제목/링크에 이스케이프를 적용한다(`[`/`]`는 백슬래시, URL은 `<...>` 또는 퍼센트 인코딩).
7. **GAP-006** — `_safe_backup_child_dir` containment 검사에 `os.path.realpath`를 더해 reparse point를 심층 방어한다.
8. **ISSUE-002 보완** — 시작 구간에 스플래시 또는 상태 표시를 붙여, 남은 비용이 무반응으로 보이지 않게 한다.

### Phase 3 — Structural

구조 개선·테스트 가능성·책임 분리.

9. **GAP-004** — Qt 의존 테스트 모듈에 `pytest.importorskip("PyQt6")`를 도입해 헤드리스 환경에서 collection 에러가 skip이 되게 한다. CLAUDE.md의 검증 절차도 이에 맞춰 갱신한다.
10. **GAP-001** — 실데이터 기준 FTS 저장 비용을 측정하고, 랭킹/가속 도입 계획이 없다면 backfill 워커를 기본 비활성화한다(스키마는 유지). README도 함께 정정한다(MISMATCH-001).
11. **중복 재계산 API의 오용 방지** — `_recalculate_duplicate_flags_with_conn`(전체)을 `_recalculate_duplicate_flags_for_entire_database` 같은 이름으로 바꾸거나 호출부에 명시적 플래그를 요구해, ISSUE-001/002 같은 오용이 리뷰에서 눈에 띄게 한다. 이번 감사의 두 이슈가 **동일한 API 오용**이라는 점이 이 조치의 근거다.
12. **GAP-007 / GAP-008** — 통계 화면에 저장소 지표(DB 크기, 기사 수, tombstone 수, 죽은 `query_key` 스코프 수)를 노출하고, 선택적 자동 보존 정책과 사용되지 않는 스코프 정리 수단을 제공한다.
13. **MISMATCH-002** — `LICENSE` 파일을 추가한다.

---

## 8. Test Recommendations

### ISSUE-001 (단건 삭제 비용)

- **Unit** — `news_keywords` 10,000행, 그중 title_hash가 겹치는 3건을 구성. `conn.execute`를 래핑해 UPDATE 대상 행 수를 집계한 뒤 `delete_link()` 1회 실행. **기대: UPDATE 대상이 전체 행 수가 아니라 영향 해시 그룹 크기(한 자릿수)에 비례.** 이 단언이 회귀 방지의 핵심이다.
- **Unit(정확성)** — 동일 `query_key`·동일 title_hash 3건 → 1건 삭제 → 남은 2건 `is_duplicate == 1`, 1건 더 삭제 → 남은 1건 `is_duplicate == 0`.
- **Unit(스코프 격리)** — `query_key` A와 B에 같은 title_hash 존재 → A에서 1건 삭제 → **B의 플래그 불변.**
- **Regression** — `delete_link`와 `restore_deleted_link`를 번갈아 5회 수행 후 최종 플래그 상태가 아무것도 하지 않은 기준 상태와 동일.

### ISSUE-002 (시작 비용)

- **Integration** — 10,000건 DB로 `DatabaseManager()`를 2회 생성. **기대: 두 번째 생성에서 `news_keywords` 대상 UPDATE 0건, `INSERT OR IGNORE INTO news_keywords` 미실행.**
- **Integration(마이그레이션 보존)** — (a) 신규 빈 DB, (b) `news_keywords` 테이블이 없는 구버전 DB, (c) `title_hash`가 NULL인 DB 세 픽스처에서 초기화 후 스키마·플래그·해시가 모두 올바르게 구성됨.
- **Platform-specific** — Windows에서 DB 파일이 다른 프로세스에 열려 있을 때 `DatabaseManager()` 생성이 `DatabaseConnectionError`로 깨끗하게 실패하고 부분 마이그레이션 상태를 남기지 않음.

### ISSUE-003 (tombstone 회수)

- **Integration** — 기사 5건 중 2건 `delete_link()` → `delete_all_news()` → **결정한 정책대로** 잔존 행 수를 단언(회수 정책이면 0건, 보존 정책이면 2건 + 다이얼로그 문구 테스트).
- **Unit(보존 경계)** — `delete_updated_at`이 보존 기간 직전/직후인 tombstone 2건 → 정리 실행 → 정확히 1건만 제거.
- **Integration(동기화 안전성)** — tombstone 제거 후 해당 기사를 포함한 상대 스냅샷을 병합 → 기사가 되살아나지 않고 `seen_snapshot_ids`가 올바르게 갱신됨.
- **Unit(북마크 보호)** — 북마크된 tombstone은 모든 정리 경로에서 제거되지 않음.

### 핵심 사용자 흐름 (End-to-End)

- **E2E(수집)** — `ApiWorker`에 100건짜리 가짜 응답(제외어 매칭 10건, 링크 없음 5건, 기존 링크 20건 포함) 주입 → 최종 DB 상태가 신규 65건, `new_links` 65건, `filtered == 15`, `dup_count`가 title_hash 중복 수와 일치.
- **E2E(순차 새로고침)** — 탭 5개, 3번째에서 HTTP 429(Retry-After: 2) 응답 → **전체 시퀀스가 정지하지 않고 쿨다운 후 재개되어 5개 모두 완료**, `_refresh_in_progress`와 `_sequential_refresh_active`가 최종적으로 False.
- **E2E(클라우드 왕복)** — 머신 A에서 읽음/북마크/메모/태그/삭제를 각각 설정 → 스냅샷 내보내기 → 머신 B에서 병합 → 5가지 상태가 모두 전파되고, 동일 스냅샷 재병합이 `already_seen`으로 무시됨.

### Concurrency

- **Concurrency(풀 상한)** — 스레드 16개가 동시에 `get_connection()` 호출(풀 10, 비상 2). **기대: 성공 최대 12개, 나머지는 `DatabaseConnectionError(pool_exhausted=True)`, 비상 커넥션 집합이 2를 절대 초과하지 않음** (GAP-003 회귀).
- **Concurrency(워커 취소)** — `DBWorker`가 대량 쿼리 실행 중일 때 `stop()` → `interrupt_connection` 경로로 중단되고 `finished`/`error` 중 어느 것도 발행되지 않으며 커넥션이 풀로 반환됨.
- **Concurrency(stale 응답)** — 필터를 빠르게 3회 변경해 요청 3개를 겹치게 만들고 순서를 뒤섞어 완료 → **마지막 `request_id`의 결과만 화면에 반영**되고 `_request_scope_signatures`가 비워짐.
- **Concurrency(maintenance 진입)** — fetch 워커 실행 중 `begin_database_maintenance()` 호출 → 워커가 실제 종료되면 True, 1.5초 내 종료 실패 시 False를 반환하고 **유지보수 모드로 진입하지 않음**.

### Platform-specific

- **Windows(단일 인스턴스)** — 두 번째 인스턴스 기동 → `QLocalSocket`으로 기존 창 복원 요청 후 exit 0. 락 파일만 남고 프로세스가 없는 stale 상황 → `removeStaleLockFile` 후 정상 기동.
- **Windows(DPAPI)** — `client_secret` 평문이 저장된 구버전 config 로드 → DPAPI 암호화로 마이그레이션되고 평문 필드가 비워짐. 복호화 실패 시 평문 fallback이 동작.
- **Windows(파일 잠금)** — 백업 복원 중 대상 DB가 잠겨 있을 때 `_atomic_copy_replace` 실패 → 스냅샷 롤백으로 원본이 보존되고 pending 파일이 복구됨.
- **경로/인코딩** — 한글·이모지·공백이 포함된 탭 이름으로 CSV/Markdown 내보내기 → `safe_filename_component`가 예약어(`CON`, `NUL` 등)와 제어문자를 처리하고, `utf-8-sig`로 Excel에서 한글이 깨지지 않음.

---

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| **Functional Correctness** | **Good** | 수집→저장→표시 파이프라인의 정확성 결함을 찾지 못했다. upsert의 중복 판정, 스코프 한정 플래그 갱신, stale 응답 차단, 순차 새로고침 진행 보장이 모두 검증을 통과했다. 세운 가설 13건이 모두 반증되었다. 발견된 결함은 결과가 아니라 비용의 문제다. |
| **Runtime Stability** | **Needs Work** | 크래시 위험은 낮다(전역/스레드 예외 훅, 워커별 방어적 예외 처리). 다만 **일상적 단일 클릭(ISSUE-001)과 매 실행(ISSUE-002)에 O(전체 아카이브) 동기 작업이 UI 스레드에 놓여 있고, 그 비용이 시간에 따라 무한 증가한다.** 계측으로 확인된 응답성 결함이라 Acceptable로 올리기 어렵다. |
| **Data Integrity** | **Good** | 손상/유실 경로를 찾지 못했다. WAL + FK CASCADE + 원자적 파일 쓰기 + 클라우드 병합 롤백 스냅샷 + 백업 복원 롤백 + 시작 시 무결성 검사가 계층적으로 갖춰져 있다. ISSUE-003은 회수 누락이지 손상이 아니다. |
| **Error Resilience** | **Good** | `DatabaseQueryError`/`DatabaseWriteError`/`DatabaseConnectionError` 타입 분리가 일관되고, `ApiWorker`가 timeout/429/5xx/리다이렉트/네트워크/DB 오류를 각각 구분해 `kind`·쿨다운·재시도 가능 여부를 UI로 전달한다. 재시도는 지수 백오프에 취소 검사가 삽입되어 있다. 연속 네트워크 오류 시 자동 새로고침 자체를 멈추는 회로 차단기까지 있다. |
| **Cross-platform Robustness** | **Acceptable** | Windows 전용을 명시한 제품으로서는 적절하다. `ntpath` 기반 경로 검증, 예약 파일명 처리, DPAPI, 레지스트리 자동시작, `winreg` 부재 시 graceful degradation이 갖춰져 있다. `core/` 계층 상당수가 플랫폼 독립적이다. 감점 요인은 GAP-006(reparse point 미해소)과, 비-Windows 환경에서 테스트가 아예 수집되지 않는 점(GAP-004). |
| **Test Confidence** | **Acceptable** | 67개 테스트 모듈이 계약 회귀를 폭넓게 방어하고, 이전 감사 항목들이 실제로 테스트로 고정되어 있다. 다만 (a) PyQt6 없이는 44개 모듈이 collection 에러로 붕괴해 이번 감사에서 UI·워커 계층을 실행 검증하지 못했고, (b) **성능/비용 회귀 테스트가 전무하다** — ISSUE-001과 ISSUE-002가 정확성 테스트를 모두 통과하면서도 존재하는 이유가 바로 이것이다. |

### 실제로 먼저 수정할 문제 3개

1. **[ISSUE-001] `delete_link`의 전체 중복 재계산을 스코프 한정으로 교체** — [core/db_mutations_support/state_tags_support/article_state.py:141](core/db_mutations_support/state_tags_support/article_state.py#L141). 바로 아래 `restore_deleted_link`가 정답 구현을 보여주므로 위험이 거의 없는 변경이며, 120,000행 기준 0.80초 → 0.003초(측정값)로 UI 프리즈가 사라진다. **가장 확실하고 가장 값싼 수정이다.**

2. **[ISSUE-002] `init_db`의 무조건 전량 재계산·backfill을 1회성으로 전환** — [core/db_schema_support/init.py:162](core/db_schema_support/init.py#L162) 및 [:144](core/db_schema_support/init.py#L144). `app_meta` 리비전 플래그로 가드하면 매 실행 2.3초(측정값) 중 약 1초와 멤버십 테이블 전량 재기록이 제거된다. 모든 사용자가 매 실행 겪는 문제이므로 영향 범위가 가장 넓다.

3. **[ISSUE-003] tombstone 보존/회수 정책 확정** — [core/db_mutations_support/maintenance_support/deletion.py:115](core/db_mutations_support/maintenance_support/deletion.py#L115), [:135](core/db_mutations_support/maintenance_support/deletion.py#L135). "전체 기사 정리"가 삭제 기록을 남긴다는 사실을 사용자가 알 방법이 없고, 회수 경로가 아예 없어 저장공간이 단조 증가한다. 앞의 두 이슈의 비용을 키우는 뿌리이기도 하므로 함께 정리하는 것이 합리적이다.
