# 코드 감사 보고서 — 뉴스 스크래퍼 Pro

> 작성일: 2026-03-16
> 기준 버전: v32.7.2
> 검증 기준: `pytest -q` → `146 passed`, `pyright` → `0 errors`

이 문서는 현재 구현에서 잠재적으로 문제가 되거나 추가/보완이 필요한 항목을 심층 분석한 결과다.
`README.md`와 `CLAUDE.md`의 설계 의도 대비 실제 구현 코드를 대조해 항목별로 심각도를 분류했다.

---

## 심각도 범례

| 심각도 | 의미 |
|--------|------|
| 🔴 HIGH | 데이터 손실 · 크래시 · 보안 위험 가능성 |
| 🟠 MEDIUM | 논리 불일치 · 재현 가능 버그 · UX 오작동 |
| 🟡 LOW | 코드 품질 · 성능 경고 · 잠재적 엣지 케이스 |
| 🔵 INFO | 기능 갭 · 향후 고려 사항 |

---

## 1. 스레드 안전성

### 1-1. `WorkerRegistry` 무잠금 딕셔너리 접근 🟠 MEDIUM

**파일**: [core/worker_registry.py](core/worker_registry.py)
**관련 라인**: 전체

`_handles_by_request_id`와 `_active_request_id_by_tab_keyword` 딕셔너리에 대한 모든 접근에 잠금이 없다.
`register`, `pop_by_request_id`, `get_active_handle` 등의 메서드가 메인 스레드에서만 호출된다면 현재는 안전하지만, 향후 멀티스레드 호출 경로가 추가되면 즉시 경쟁 조건이 발생한다.

```python
# 현재: 잠금 없음
def register(self, handle: WorkerHandle) -> None:
    self._handles_by_request_id[handle.request_id] = handle
    self._active_request_id_by_tab_keyword[handle.tab_keyword] = handle.request_id
```

**권고**: 최소한 `threading.Lock`을 추가하거나 모든 호출이 Qt 메인 루프에서만 이루어진다는 제약을 주석으로 명시할 것.

---

### 1-2. `ApiWorker._safe_emit` 의 이중 잠금 위험 🟡 LOW

**파일**: [core/workers.py:115-122](core/workers.py)

```python
def _safe_emit(self, signal, value):
    try:
        if not self._destroyed and self.is_running:   # is_running이 내부적으로 _lock 획득
            signal.emit(value)
    ...
```

`is_running` 프로퍼티(line 107)가 `with self._lock`을 사용하므로 `_safe_emit` 자체도 락을 잡는다.
현재는 재귀적 락 획득이 없어 안전하지만, 향후 `signal.emit` 내부에서 같은 스레드가 `is_running` setter를 호출하는 슬롯이 연결되면 `threading.Lock`의 비재진입 특성으로 데드락이 발생할 수 있다.

**권고**: `threading.RLock`으로 변경하거나, `_safe_emit` 내에서 `_lock`을 먼저 확보한 후 조건 검사 + emit을 원자적으로 처리할 것.

---

### 1-3. `config_store` 설정 딕셔너리 동시 접근 🟡 LOW

**파일**: [core/config_store.py](core/config_store.py)

`load_config_file()` 이후 반환된 `AppConfig` 딕셔너리는 공유 상태로 사용된다.
설정 저장 시 `save_config_file_atomic`을 호출하지만, 읽기 경로(e.g. 다수 탭의 `api_timeout` 조회)에 대한 동시성 보장이 없다.
Python `dict` 단일 키 읽기는 GIL 덕분에 사실상 안전하나, `setdefault` / `update` 등 복합 연산이 섞이면 문제가 생긴다.

**권고**: 설정 객체를 불변 `dataclass`나 `read-only view`로 래핑하거나, 쓰기 경로를 전담 스레드로 제한할 것.

---

## 2. 데이터베이스

### 2-1. `mark_query_as_read` SELECT–UPDATE 원자성 부재 🟠 MEDIUM

**파일**: [core/_db_mutations.py:393-437](core/_db_mutations.py)

```python
conn = self.get_connection()
try:
    # ① SELECT: 트랜잭션 외부 (autocommit 상태)
    links = [row[0] for row in conn.execute(query, params).fetchall() ...]
    if not links:
        return 0
    # ② UPDATE: 별도 with conn: 트랜잭션
    with conn:
        return self._mark_links_as_read_with_conn(conn, links)
```

①과 ② 사이에 다른 스레드나 프로세스가 같은 기사를 삭제/수정하면,
이미 사라진 링크를 UPDATE하거나 새로 추가된 기사가 누락될 수 있다.
현재 단일 인스턴스 구조에서 빈도는 낮으나, 자동 새로고침 + 수동 조작이 겹칠 때 발생할 수 있다.

**권고**: SELECT와 UPDATE를 동일한 `with conn:` 블록 내부로 이동시키거나,
`BEGIN IMMEDIATE`로 시작하는 단일 트랜잭션 내에서 SELECT+UPDATE를 처리할 것.

---

### 2-2. `_check_integrity` 연결 타임아웃 누락 🟡 LOW

**파일**: [core/_db_schema.py:32-43](core/_db_schema.py)

```python
def _check_integrity(self: DatabaseManager) -> bool:
    try:
        conn = sqlite3.connect(self.db_file)   # timeout 인자 없음
        ...
```

메인 풀이 WAL 모드 연결을 열고 있는 상태에서 integrity check용 연결도 `timeout` 없이 `connect`하면,
DB 잠금 경합 시 무한 대기가 발생할 수 있다.
앱 시작 시 호출되는 경로이므로 UI 응답 불가 상태가 지속될 수 있다.

**권고**: `sqlite3.connect(self.db_file, timeout=10.0)` 으로 타임아웃을 명시할 것.

---

### 2-3. `upsert_news` 동시 upsert 격리 수준 🟡 LOW

**파일**: [core/_db_mutations.py](core/_db_mutations.py)

여러 탭의 `ApiWorker`가 거의 동시에 완료될 때 각 워커의 DB 저장은 별도 `with conn:` 블록에서 진행된다.
SQLite WAL 모드는 다중 리더를 허용하지만 단일 라이터 제약이 있으므로, 순차 처리는 보장된다.
그러나 duplicate hash 재계산(`_db_duplicates.py`)이 각 upsert 직후 실행되는 구조에서,
두 워커가 거의 동시에 같은 기사(hash 충돌)를 저장하면 `is_duplicate` 플래그가 최종 upsert 기준으로만 재계산될 수 있다.

**권고**: duplicate 재계산을 단일 트랜잭션 내에서 upsert와 묶어 처리하거나,
재계산을 `AFTER INSERT/UPDATE` 트리거로 DB 내부에서 처리하는 방안 검토.

---

### 2-4. `delete_old_news` 의 `pubDate_ts` 조건과 미래 날짜 🟡 LOW

**파일**: [core/_db_mutations.py](core/_db_mutations.py)

`pubDate_ts <= 0` 레코드를 삭제 제외하는 로직은 구현되어 있다(README v32.7.2 항목).
하지만 네이버 API가 **미래 날짜**(e.g. 잘못된 pubDate)를 내려주는 엣지 케이스에서는
정리 기준(`days` 파라미터) 대비 기준선이 과거로 계산되어 미래 날짜 기사가 영구 보존되는 문제가 있다.

**권고**: 삭제 쿼리에 `AND pubDate_ts > 0` 외에 `AND pubDate_ts <= strftime('%s', 'now') + 86400` 같은 미래 날짜 상한선 조건을 추가할 것.

---

## 3. 워커 수명 주기

### 3-1. 워커 등록 후 시그널 연결 순서 🟡 LOW

**파일**: [ui/_main_window_fetch.py:302-339](ui/_main_window_fetch.py)

```python
self._worker_registry.register(handle)     # line 313: 먼저 등록
self.workers[keyword] = (worker, thread)   # line 314

worker.finished.connect(...)               # line 316: 그 다음 시그널 연결
...
thread.started.connect(worker.run)         # line 339: 마지막 스레드 시작
```

현재 순서는 안전하다 — 등록 후 시그널 연결, 시그널 연결 후 스레드 시작.
그러나 `thread.start()`가 없고 `thread.started.connect(worker.run)` + `thread.start()`가 분리된 구조인지
확인이 필요하다. `thread.start()`가 line 339 이후 어딘가에서 실제로 호출되는지 추적 필요.

**권고**: 워커 시작 흐름 전체를 명시적으로 주석으로 문서화하고,
`thread.start()` 누락 시 무한 대기 진단을 위한 assertion을 개발 빌드에 추가할 것.

---

### 3-2. 세션 공유 제거 후 세션 소유권 추적 🟡 LOW

**파일**: [core/workers.py:140-143](core/workers.py)

```python
session: RequestGetProtocol = self.session or requests.Session()
owns_session = self.session is None
self._request_session = cast(ClosableProtocol, session) if hasattr(session, "close") else None
self._owns_request_session = owns_session
```

CLAUDE.md(2026-02-28 Addendum)에서 세션 공유가 제거됐음을 명시하고 있다.
`self.session`에 외부 세션이 전달된 경우 `owns_session = False`이므로 워커 종료 시 세션을 닫지 않는다.
이는 의도적인 설계이지만, 외부 세션 전달 경로가 다시 생기면 누수로 이어진다.

**권고**: `ApiWorker.__init__` 시그니처에서 `session` 파라미터를 명시적으로 제거하거나
`# 외부 세션 전달 금지` 주석을 달아 계약을 코드 수준에서 강제할 것.

---

### 3-3. `AsyncJobWorker` 예외 정보 유실 🟡 LOW

**파일**: [core/workers.py:54-58](core/workers.py)

```python
def run(self):
    result = self.job_func(*self.args, **self.kwargs)
    self.finished.emit(result)
```

예외를 잡는 구조가 없어, `job_func` 실패 시 `QThread`에서 처리되지 않은 예외가 발생한다.
`try/except`가 없으므로 일부 플랫폼에서는 스레드가 silently 종료된다.

**권고**: `try/except Exception as e` 블록으로 감싸고 `self.error.emit(str(e))`를 추가할 것.
콜스택 보존이 필요하면 `traceback.format_exc()`를 함께 emit할 것.

---

## 4. 백업 · 복원

### 4-1. `-wal/-shm` 사이드카 잔류 시 integrity check 오탐 🟠 MEDIUM

**파일**: [core/backup.py](core/backup.py), [core/_db_schema.py](core/_db_schema.py)

pending restore 적용 후 `-wal`/`-shm` 파일이 정상 적용되면 삭제되지만,
비정상 종료로 인해 스테이징 디렉토리에 잔류 파일이 남는 경우 다음 `_check_integrity` 호출에서
복원된 DB와 이전 WAL 파일이 충돌해 integrity check가 실패할 수 있다.

**권고**: `apply_pending_restore_if_any` 완료 후 명시적으로 `-wal`/`-shm`을 삭제하고,
integrity check를 복원 직후 한 번 더 실행하는 검증 단계를 추가할 것.

---

### 4-2. `get_backup_list` 손상 메타 항목의 복원 경로 차단 불완전 🟡 LOW

**파일**: [core/backup.py](core/backup.py), [ui/dialogs.py](ui/dialogs.py)

`is_corrupt=True` 항목에 대해 UI는 `삭제/무시` 선택을 제공한다.
그러나 `is_corrupt` 판정이 `backup_info.json` 파싱 실패만으로 이루어지고,
실제 DB/설정 파일의 물리적 손상 여부는 검증하지 않는다.
메타 파일만 깨진 경우, 사용자가 "무시"를 선택하면 복원 시도 후 실패하는 흐름이 발생할 수 있다.

**권고**: `is_corrupt` 항목에 대해 물리 파일 존재 여부와 DB 파일의 기본 헤더(`SQLite format 3`) 검사를
복원 시도 전에 수행하고, 실패 시 명확한 에러 메시지를 제공할 것.

---

### 4-3. 자동 백업 보존 정책의 설정 부재 🔵 INFO

**파일**: [core/backup.py](core/backup.py)

`trigger=auto` / `trigger=manual` 보존 정책이 분리되어 있으나,
각 정책의 보존 기간/개수가 하드코딩되어 있고 사용자가 설정에서 변경할 수 없다.
장기간 실행 시 백업 디렉토리가 누적될 수 있으며, 사용자 제어권이 없다.

**권고**: `app_settings`에 `auto_backup_keep_count`, `manual_backup_keep_count` 필드를 추가하고
설정 창에서 조정 가능하게 할 것.

---

## 5. 설정 · 데이터 무결성

### 5-1. DPAPI 마이그레이션 실패 시 평문 키 그대로 유지 🟠 MEDIUM

**파일**: [core/config_store.py:641-649](core/config_store.py)

```python
if needs_migration and secret_value and _is_windows_platform():
    ...
    try:
        save_config_file_atomic(path, cfg)
    except Exception as e:
        logger.warning("DPAPI 마이그레이션 저장 실패: %s", e)
        # → 예외 무시 후 평문 키로 계속 동작
```

DPAPI 마이그레이션 저장이 실패해도 앱은 평문 키로 계속 동작한다.
이는 기능적으로는 안전하지만, 사용자에게 키가 암호화되지 않았음을 알리지 않는다.
토스트 알림이 없으므로 사용자는 보안 상태를 알 수 없다.

**권고**: 마이그레이션 저장 실패 시 `logger.warning` 외에 `ToastType.WARNING`으로 UI 알림을 추가할 것.

---

### 5-2. `window_geometry` 역직렬화 시 범위 검증 없음 🟡 LOW

**파일**: [core/config_store.py](core/config_store.py)

`window_geometry` 필드의 `x`, `y`, `width`, `height`를 로드할 때 값 범위 검증이 없다.
음수 좌표나 극단적으로 작은/큰 크기가 저장된 경우 창이 화면 밖에 위치하거나 렌더링 문제가 생긴다.

**권고**: `normalize_loaded_config` 내에서 `x >= -screen_width`, `width >= MIN_WIDTH` 등의
범위 클램핑 로직을 추가할 것. 화면 경계 밖이면 기본 위치로 리셋.

---

### 5-3. `pagination_totals` 무한 누적 🟡 LOW

**파일**: [core/config_store.py](core/config_store.py)

`pagination_totals`는 `fetch_key → last_api_total` 맵이다.
탭이 삭제되거나 리네임되어도 이전 `fetch_key`에 해당하는 항목이 정리되지 않아
장기 사용 시 설정 파일 크기가 지속적으로 증가한다.
(동일한 문제가 `pagination_state`에도 존재)

**권고**: 탭 삭제/리네임 시 해당 `fetch_key`를 `pagination_state`와 `pagination_totals` 모두에서 제거할 것.

---

### 5-4. `search_history` 크기 제한 없음 🟡 LOW

**파일**: [core/config_store.py](core/config_store.py), [ui/main_window.py](ui/main_window.py)

`search_history` 리스트가 무제한으로 누적된다.
설정 내보내기/가져오기 시 대용량 히스토리가 JSON 파일에 포함되어 성능 저하 및 파일 크기 증가로 이어질 수 있다.

**권고**: `normalize_loaded_config`에서 `search_history`를 최대 N개(예: 200)로 트리밍할 것.

---

## 6. UI · UX

### 6-1. 트레이 미지원 환경 설정창 `start_minimized` 비활성화 누락 가능성 🟠 MEDIUM

**파일**: [ui/settings_dialog.py](ui/settings_dialog.py), [ui/_settings_dialog_content.py](ui/_settings_dialog_content.py)

CLAUDE.md(2026-03-02 Addendum)에 "Settings dialog must disable `start_minimized` option when tray is unavailable" 명시되어 있다.
설정창이 열릴 때 트레이 지원 여부를 실시간으로 확인하고 해당 옵션을 비활성화하는지 검증이 필요하다.
특히 트레이 지원 상태가 앱 실행 중 변경될 수 있는 환경(원격 데스크톱 세션 전환 등)에서 동기화가 누락될 수 있다.

**권고**: `SettingsDialog` 열릴 때마다 트레이 가용성을 재확인하고, 비가용 시 `start_minimized` 체크박스를
즉시 비활성화 + 해제하는 로직이 포함되어 있는지 확인할 것.

---

### 6-2. 필터 변경 후 `더 불러오기` 버튼 상태 복원 정확도 🟡 LOW

**파일**: [ui/news_tab.py](ui/news_tab.py)

필터 텍스트가 변경되면 `load_data_from_db()`가 재호출되고 `more_btn` 상태가 갱신된다.
그러나 필터 적용 시 DB에서 가져오는 총량(`total_api_count`)은 필터 이전 API 전체 결과 수이므로
필터 후 남은 결과가 적어도 `더 불러오기`가 활성화된 것처럼 보이는 UX 불일치가 발생한다.

**권고**: 로컬 필터 적용 후 표시 결과 수와 API 커서 상태를 구분하여,
필터 중에는 "전체 N건 중 표시 M건" 형태로 안내하거나 `더 불러오기`의 의미를 재정의할 것.

---

### 6-3. 토스트 메시지 동시 표시 개수 제한 없음 🟡 LOW

**파일**: [ui/toast.py](ui/toast.py)

여러 탭이 거의 동시에 완료될 때 토스트가 연달아 쌓일 수 있다.
`ToastQueue`가 큐잉 방식으로 순차 표시한다면 괜찮지만,
동시에 여러 토스트가 화면에 겹쳐 표시되는 케이스에서 레이아웃 충돌이 발생할 수 있다.

**권고**: `ToastQueue`에 동시 표시 최대 개수(`max_visible`)를 설정하고,
초과 시 오래된 토스트를 즉시 페이드아웃하거나 큐잉 처리할 것.

---

### 6-4. 북마크 탭의 키워드 필터 동작 🟡 LOW

**파일**: [ui/news_tab.py](ui/news_tab.py)

북마크 탭(`keyword == "북마크"`)에서 키워드 필터 텍스트박스가 표시되는지,
그리고 필터가 `is_bookmark_tab = True` 경로에서 올바르게 동작하는지 확인 필요.
`query_key` 기반 범위 조회 로직이 북마크 탭에서는 `only_bookmark=True`로 분기되는데,
필터 조건과의 조합이 예상대로 동작하는지 통합 테스트가 부족하다.

**권고**: `tests/`에 북마크 탭 + 키워드 필터 조합 케이스를 커버하는 테스트를 추가할 것.

---

## 7. 테스트 갭

### 7-1. `mark_query_as_read` SELECT–UPDATE 원자성 회귀 테스트 부재 🟠 MEDIUM

**파일**: [tests/test_db_queries.py](tests/test_db_queries.py), [tests/test_risk_fixes.py](tests/test_risk_fixes.py)

현재 테스트에서 `mark_query_as_read`의 TOCTOU 시나리오(SELECT 후 UPDATE 전에 상태 변경)를
시뮬레이션하는 케이스가 없다.

**권고**: `mark_query_as_read` 호출 중간에 다른 연결이 해당 링크를 삭제하는 시나리오를 테스트할 것.

---

### 7-2. `AsyncJobWorker` 예외 전파 테스트 부재 🟡 LOW

**파일**: [core/workers.py](core/workers.py)

`AsyncJobWorker`가 예외 발생 시 어떻게 동작하는지 테스트가 없다.
현재는 예외가 처리되지 않은 채 스레드가 종료된다.

**권고**: `AsyncJobWorker`에 예외를 throw하는 `job_func`를 전달했을 때
`error` 시그널이 방출되는지 검증하는 테스트를 추가할 것 (기능 구현과 함께).

---

### 7-3. 창 좌표 범위 검증 회귀 테스트 🟡 LOW

**파일**: [core/config_store.py](core/config_store.py)

`window_geometry`에 극단값(`x=-99999`, `width=1`)을 넣었을 때
`normalize_loaded_config`가 어떻게 처리하는지 테스트가 없다.

---

### 7-4. `pagination_state` / `pagination_totals` 탭 삭제 시 정리 테스트 부재 🟡 LOW

탭 삭제/리네임 후 설정 저장을 확인하는 테스트에서 해당 `fetch_key`가 실제로 제거되는지
검증하는 케이스가 필요하다.

---

## 8. 성능 · 리소스

### 8-1. `_check_integrity` 앱 시작 블로킹 🟡 LOW

**파일**: [core/_db_schema.py:32-43](core/_db_schema.py)

`PRAGMA integrity_check`는 DB 크기에 비례해 시간이 걸린다.
대용량 DB(수만 건 이상)에서 앱 시작이 수 초 지연될 수 있다.

**권고**: integrity check를 백그라운드 스레드에서 실행하고, 완료 후 문제가 발견될 때만 사용자에게 알림을 표시할 것.

---

### 8-2. `_css_cache_by_theme` 무한 누적 🟡 LOW

**파일**: [ui/news_tab.py:59](ui/news_tab.py)

`_css_cache_by_theme: Dict[int, str]`는 탭 인스턴스별로 존재하고,
키가 테마 인덱스(0 또는 1)이므로 실질적으로 최대 2개 항목이다.
현재는 문제가 없으나, 향후 테마가 추가되거나 동적 색상 변경이 지원될 경우 캐시 무효화 로직이 없어 오래된 CSS가 사용될 수 있다.

**권고**: 테마 변경 이벤트(`theme_changed` 시그널 등) 시 `_css_cache_by_theme.clear()`를 호출하는 훅을 추가할 것.

---

### 8-3. 대량 탭에서 `update_all_tab_badges` 병렬화 기회 🔵 INFO

**파일**: [ui/main_window.py](ui/main_window.py)

탭 수가 많아지면 각 탭의 unread count 계산을 순차적으로 수행하게 된다.
`get_unread_counts_by_query_keys(...)` 배치 API가 이미 존재하므로 활용 여부를 확인할 것.
배치 API가 활용되지 않고 있다면 단일 쿼리로 모든 탭의 unread count를 가져오도록 개선할 것.

---

## 9. 보안

### 9-1. `client_secret` 로그 노출 위험 🔴 HIGH

**파일**: [core/workers.py](core/workers.py), [core/config_store.py](core/config_store.py)

`logger.error(f"...")` 형태로 포맷 문자열에 직접 변수를 삽입하는 패턴이 많다.
만약 예외 메시지나 `repr()`에 `client_secret`이 포함된 경우(e.g. 요청 파라미터 덤프),
로그 파일에 API 시크릿이 평문으로 기록될 수 있다.

**권고**: API 호출 직전/직후 에러 로깅 시 헤더/파라미터를 마스킹하거나
`X-Naver-Client-Secret` 헤더 값을 `***`로 대체하는 헬퍼를 사용할 것.

---

### 9-2. 임시 파일의 `umask` 미설정 🟡 LOW

**파일**: [core/backup.py:38](core/backup.py), [core/config_store.py](core/config_store.py)

`tempfile.mkstemp()`로 생성된 임시 파일이 기본 `umask` 설정을 따른다.
Windows에서는 ACL이 주로 보호하지만, 멀티유저 환경에서 다른 계정이 임시 파일에 접근할 여지가 있다.
특히 백업 임시 파일에는 API 키가 포함된 설정이 들어 있을 수 있다.

**권고**: `os.chmod(tmp_path, 0o600)`을 임시 파일 생성 직후에 추가하거나
Windows에서 ACL을 명시적으로 설정할 것.

---

## 10. 기능 갭 (미구현 또는 문서 대비 누락)

### 10-1. `alert_keywords` 대소문자 처리 일관성 🟡 LOW

**파일**: [core/workers.py](core/workers.py)

`exclude_words` 필터링은 대소문자 무시(case-insensitive)로 구현되어 있다(CLAUDE.md 2026-02-28 Addendum).
그러나 `alert_keywords` 매칭이 동일하게 case-insensitive로 처리되는지 확인이 필요하다.
한글은 대소문자 구분이 없으나 영문 혼용 키워드에서 불일치가 발생할 수 있다.

---

### 10-2. 멀티 키워드 탭의 레거시 마이그레이션 완료 알림 🟡 LOW

**파일**: [ui/news_tab.py](ui/news_tab.py)

README에 "레거시 멀티 키워드 탭은 한 번 새로고침 후 새 `query_key` 범위가 완전히 채워진다"고 명시되어 있다.
이 상태를 감지해 사용자에게 "새로고침이 필요합니다" 토스트를 표시하는 로직이 있는지 확인 필요.
없다면 레거시 탭에서 배지/분석이 잘못 표시될 수 있다.

---

### 10-3. CSV 내보내기의 인코딩 명시 🟡 LOW

**파일**: [ui/main_window.py](ui/main_window.py) 또는 [ui/_main_window_settings_io.py](ui/_main_window_settings_io.py)

CSV 내보내기 시 인코딩(UTF-8 BOM vs UTF-8 vs CP949)을 사용자가 선택할 수 없다.
Excel에서 한글 CSV를 열 때 UTF-8 BOM 없이는 깨지는 문제가 흔하다.

**권고**: CSV 저장 시 `encoding='utf-8-sig'`(UTF-8 with BOM)를 기본으로 사용하거나
인코딩 선택 다이얼로그를 제공할 것.

---

### 10-4. 오프라인 동작 시 에러 피드백 🔵 INFO

네트워크 연결 없는 상태에서 새로고침 시도 시 `requests.ConnectionError`가 발생한다.
현재 재시도 로직은 있으나, 모든 재시도 소진 후 "네트워크 연결을 확인하세요"와 같은
구체적인 안내 메시지가 제공되는지 확인 필요.
현재는 일반 에러 메시지만 표시될 수 있다.

---

## 우선순위 요약

| 우선순위 | 항목 |
|----------|------|
| 🔴 HIGH | 9-1 (로그 시크릿 노출 위험) |
| 🟠 MEDIUM | 2-1 (SELECT–UPDATE 원자성), 4-1 (WAL 잔류 integrity 오탐), 5-1 (DPAPI 실패 무음), 6-1 (트레이 설정 비활성화), 7-1 (원자성 테스트) |
| 🟡 LOW | 1-1 (WorkerRegistry 잠금), 1-2 (이중 잠금), 2-2 (integrity timeout), 2-4 (미래날짜), 3-3 (AsyncJobWorker 예외), 5-2~5-4 (설정 누적), 6-2~6-4 (UX), 8-1~8-3 (성능), 9-2 (umask) |
| 🔵 INFO | 4-3 (백업 개수 설정), 8-3 (배치 배지), 10-4 (오프라인 안내) |

---

*이 문서는 현재 코드 상태를 기준으로 작성되었으며, 향후 수정 시 해당 항목을 체크리스트로 활용할 것.*
