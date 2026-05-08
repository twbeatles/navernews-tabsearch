# 구현 후속 검토 메모 (2026-05-07)

> 본 문서는 `claude.md`, `README.md`에 정리된 v32.7.3 안정화 결과를 기준으로
> 추가로 점검이 필요하거나 잠재적으로 문제 소지가 있다고 판단되는 항목을
> 면밀히 정리한 것이다. 즉시 회귀가 발생한 영역이 아니라, 다음 안정화 패스에서
> 검토하거나 회귀 가드를 보강할 후보 목록으로 활용한다.

본 문서에서 사용한 약식 우선순위 표기는 다음과 같다.

- **[High]**: 사용자 영향이 크거나 보안/데이터 무결성 영역
- **[Medium]**: 기능 정확성 또는 UX 영향이 명확한 영역
- **[Low]**: 코드 품질/유지보수성 또는 잠재적 회귀 가드 강화 후보

---

## 1. 보안 / 데이터 노출

### 1.1 [High] HTTP 리다이렉트 시 API Secret 헤더 노출 가능성
- 위치: `core/workers.py::ApiWorker.run()` (`session.get(url, headers=headers, ...)`).
- 이슈:
  - `requests`는 기본적으로 모든 리다이렉트(최대 30회)를 따라가며,
    `X-Naver-Client-Secret`, `X-Naver-Client-Id` 등 사용자 정의 헤더는
    리다이렉트 후에도 동일하게 전송된다.
  - `openapi.naver.com`이 정상 응답만 보낼 것이라는 가정에 의존하고 있어,
    DNS hijack/MITM/응답 변조 시 시크릿이 외부 호스트로 유출될 위험이 있다.
- 권장 조치:
  - `session.get(..., allow_redirects=False)`로 고정하고, 3xx 응답 시 명시적으로
    `error` 경로로 처리.
  - 또는 `Session.send` 단계에서 동일 호스트 검증 후 리다이렉트를 허용.
- 현재 검증 자산: 직접적인 회귀 테스트 없음.

### 1.2 [Medium] `_normalized_http_url`가 사설/로컬 주소를 차단하지 않음
- 위치: `core/workers.py::_normalized_http_url`, `_publisher_from_url`.
- 이슈:
  - scheme/netloc만 확인하고 SSRF 관점의 호스트 필터링은 없다.
  - `originallink`/`link`가 `http://127.0.0.1`, `http://10.0.0.1`,
    `http://localhost` 등을 가리킬 경우 그대로 DB에 저장되며,
    이후 외부 열기(`http`/`https`만 허용)로 노출된다.
- 권장 조치:
  - DB 저장 전 host가 IP 사설 대역 / 로컬 hostname / 내부 도메인이면
    drop하고 `filtered_count`를 증가시키는 정규화 단계 추가.

### 1.3 [Low] Retry-After 값 상한 없음
- 위치: `core/workers.py::_parse_retry_after_seconds`.
- 이슈:
  - `max(0, int(raw_value))`로만 보정해 `Retry-After: 9999999999`처럼
    비정상적으로 큰 값이 그대로 cooldown으로 사용된다.
  - 현재 `MAX_INLINE_RETRY_AFTER_SECONDS` 30초는 inline retry에만 적용되고,
    cooldown 자체에는 상한이 없어 UI가 영구 락 상태처럼 보일 수 있다.
- 권장 조치:
  - `_set_fetch_cooldown(...)` 또는 `_emit_error(...)` 단계에서 상한
    (예: 6시간 = 21600s)을 적용하고, 초과 시 `허용 한도 이상 cooldown` 경고를 로깅.

### 1.4 [Low] DPAPI 마이그레이션은 Windows에서만 동작
- 위치: `core/config_store_impl.py::resolve_client_secret_for_runtime`,
  `encode_client_secret_for_storage`.
- 이슈:
  - macOS/Linux에서는 `client_secret`이 평문으로 그대로 저장된다.
  - claude.md에는 "Windows에서 DPAPI 우선"이라고 명시되어 있지만,
    비-Windows 환경에서 동등한 보호 수단이 없다는 점은 README/claude.md에
    명시적으로 안내되어 있지 않다.
- 권장 조치 (단계적):
  - Linux: libsecret(`SecretService`), macOS: keyring 백엔드 활용.
  - 즉시 도입이 어렵다면 README의 데이터/설정 섹션에 비-Windows 환경에서의
    저장 방식과 권장 권한(예: chmod 600)을 명시.

---

## 2. 데이터베이스 / 영속성

### 2.1 [Medium] `mark_query_as_read_chunked`가 진행 보장 없이 루프 가능
- 위치: `core/_db_mutations.py::mark_query_as_read_chunked`.
- 이슈:
  - SELECT scope_query → `_mark_links_as_read_with_conn` 패턴인데,
    `_mark_links_as_read_with_conn`는 `is_read = 0` 조건으로 UPDATE한다.
  - 만약 SELECT 결과가 동일한 링크들을 반복적으로 반환하지만 다른 트랜잭션이
    `is_read`를 다시 0으로 되돌리는 경합 상황이 발생하면 진행이 멈추지 않는다.
  - 현재 단일 인스턴스 가드가 있으니 외부 라이터는 없지만, 백그라운드 worker가
    같은 행을 다시 0으로 만드는 경로가 추가될 경우 회귀 위험이 있다.
- 권장 조치:
  - 처리한 `link` 집합을 누적해 다음 chunk 쿼리에서 `link NOT IN (...)`로 제외.
  - 또는 `updated_total` 변동이 없는 chunk가 연속 N회 발생하면 중단.

### 2.2 [Low] `delete_old_news`가 `pubDate_ts == 0` 행을 무시하는 정책의 부작용
- 위치: `core/_db_mutations.py::delete_old_news_chunked`
  (`pubDate_ts > 0 AND pubDate_ts < ?`).
- 이슈:
  - 의도적으로 `pubDate_ts <= 0` 레코드를 삭제 대상에서 제외해 두었지만,
    `parse_date_to_ts` 실패로 0이 된 잘못된 pubDate 행이 영구히 남는다.
  - 시간이 지날수록 "정리되지 않는 좀비 행"이 누적될 수 있다.
- 권장 조치:
  - 별도 점검 잡(또는 설정 창의 데이터 정리 화면)에서
    `pubDate_ts == 0` 행을 따로 노출하거나, `created_at` 기준으로 동일 cutoff을
    적용하는 옵션을 제공.

### 2.3 [Low] `apply_pending_restore_if_any` 적용 후 `.applied` 잔여 파일
- 위치: `core/backup.py::apply_pending_restore_if_any`.
- 이슈:
  - 정상 적용 후 `pending_restore.json` → `pending_restore.json.applied`로
    rename, 그 다음 `os.remove(applied_file)`. 삭제 실패 시 그대로 남는다.
  - `.gitignore`에는 포함되어 있지만, 사용자 데이터 디렉터리(`DATA_DIR`)에서는
    영구히 누적될 수 있다.
- 권장 조치:
  - 다음 시작 시 `*.applied` 패턴을 best-effort 정리하는 부팅 단계 추가
    (이미 적용된 것이므로 안전하게 제거 가능).

### 2.4 [Low] `init_db` 중 `IF NOT EXISTS` 누락 / try-except 패턴 혼재
- 위치: `core/_db_schema.py::init_db` (다중 `ALTER TABLE` + `OperationalError` 무시).
- 이슈:
  - 같은 컬럼이 두 번 추가 시도되는 코드 (`pubDate_ts` 등)가 있으며,
    `OperationalError`를 모두 무시한다.
  - 의도와 다르게 `OperationalError`가 발생하면(예: 권한 문제), 디버깅 시
    원인을 추적하기 어렵다.
- 권장 조치:
  - 컬럼 존재 여부를 `PRAGMA table_info(news)`로 명시적으로 검사한 뒤
    필요한 경우만 `ALTER TABLE` 실행.

### 2.5 [Low] SQLite VACUUM / PRAGMA optimize 누락
- 이슈:
  - 장기간 사용 시 DB 파일이 커지고 인덱스가 단편화될 수 있다.
  - 현재 별도 maintenance task에서 VACUUM이나 `PRAGMA optimize` 실행 경로가
    없다.
- 권장 조치:
  - 일정 사용 횟수 또는 데이터 정리 직후 `PRAGMA optimize` 실행.
  - 사용자 명시적 트리거(예: 설정 창의 "DB 최적화" 버튼)로 VACUUM 제공.

### 2.6 [Low] `news.is_duplicate` 컬럼이 사실상 사용되지 않음
- 위치: `core/_db_queries.py::fetch_news`.
- 이슈:
  - 비-북마크 뷰는 `nk.is_duplicate`를 직접 사용하고, 북마크 뷰는
    `EXISTS (SELECT 1 FROM news_keywords ...)`를 사용한다.
  - `news.is_duplicate` 컬럼은 schema에 남아 있지만 현재 조회 경로에서
    소비되지 않는다.
- 권장 조치:
  - 컬럼을 정식으로 deprecate하고 `delete_link`/`upsert_news` 등에서 갱신을
    제거하거나, 반대로 단일 진실 원본으로 만들고 mixin 경로를 통일.

---

## 3. 페치 / API 워커

### 3.1 [Medium] `final_link` 결정 후 `org_link` 우선 publisher 추출 시 host 충돌
- 위치: `core/workers.py::ApiWorker.run`.
- 동작:
  - `final_link`는 `news.naver.com`이 포함된 쪽을 우선.
  - `publisher`는 `org_link or final_link`로 host 추출.
- 이슈:
  - 일부 응답에서 `originallink`도 `news.naver.com`인 경우 publisher가
    원래 언론사 host가 아니라 `news.naver.com`으로 기록된다.
  - 출처 차단/선호 필터가 의도치 않게 "네이버 뉴스" 전체를 차단하는 효과를
    낼 수 있음.
- 권장 조치:
  - `org_link` host가 `news.naver.com`이면 publisher 추출에서 의도적으로
    제외하고, `final_link`에서도 동일한 경우 "정보 없음"으로 두기.
  - 또는 응답 본문에서 별도 publisher 필드를 채굴(가능한 경우).

### 3.2 [Medium] `ApiWorker.stop()`이 worker thread 외부에서 session.close() 호출
- 위치: `core/workers.py::ApiWorker.stop`.
- 이슈:
  - `stop()`은 UI 스레드에서 호출되며, 동일 시점에 worker 스레드에서
    `session.get(...)`이 진행 중일 수 있다. requests 세션은 일반적으로
    이런 경합에 안전하지 않다.
  - 현재 cancellation은 `_destroyed` 플래그 + session.close()로 강제하지만
    드물게 `RuntimeError`/segfault 위험이 있다.
- 권장 조치:
  - `stop()`에서는 플래그만 세팅하고, 워커 스레드 자체에서 try/finally로
    session을 닫도록 일원화.
  - 즉시 인터럽트가 필요하면 `urllib3` 레벨의 `pool_manager.clear()` 등을
    명시적으로 사용.

### 3.3 [Low] `_fetch_dedupe_window_sec = 10s`가 사용자에게 invisible
- 위치: `ui/main_window.py`, `_main_window_fetch.py::fetch_news`.
- 이슈:
  - 수동/자동 새로고침이 10초 이내 동일 fetch_key로 재요청되면 silent하게
    skip된다. 사용자는 "왜 안 되는지" 알기 어렵다.
- 권장 조치:
  - 첫 dedupe 발생 시 한 번만 status bar/toast로 안내.
  - 최소한 PERF 로그 외에 DEBUG 레벨 이상의 메시지에 표기.

### 3.4 [Low] 자동 새로고침 due timestamp 갱신 시점 미세 차이
- 위치: `ui/_main_window_fetch.py::on_fetch_done`.
- 이슈:
  - `_sequential_refresh_is_auto`일 때만 `_last_auto_refresh_by_keyword`를
    갱신한다. 수동 새로고침이 자동 due 직전에 성공해도 due 타임스탬프는
    그대로이므로, 자동 새로고침이 곧바로 한 번 더 트리거될 수 있다.
- 권장 조치:
  - 수동 새로고침 성공 시에도 해당 keyword의 last_auto_refresh를 같이
    갱신하거나, 자동 due 판정 시 "수동 새로고침이 X분 안에 있었는지" 가드 추가.

### 3.5 [Low] 5xx 재시도가 항상 1초 fixed sleep
- 위치: `core/workers.py::ApiWorker.run` (5xx 분기).
- 이슈:
  - 5xx에서는 `time.sleep(1)`만 수행해 backoff가 없다. timeout/RequestException과
    동일하게 1초 고정.
- 권장 조치:
  - `attempt`에 비례한 지수 backoff(`1s -> 2s -> 4s ...`) 적용.

---

## 4. UI 응답성 / 상태 일관성

### 4.1 [Medium] 유지보수 모드 종료 후 일부 탭의 hydration이 누락 가능
- 위치: `ui/main_window_support/base.py::end_database_maintenance` /
  `_schedule_tab_hydration`.
- 이슈:
  - `end_database_maintenance`가 `_schedule_tab_hydration(50)`을 호출하지만,
    `_is_tab_hydration_paused`는 활성 worker가 있으면 paused로 처리한다.
  - 유지보수 직후 다른 fetch worker가 시작되면 hydration이 큐에는 남아 있어도
    실제 시작이 지연되며, 큐가 비어 있는 채로 hydration_inflight도 비어 있는
    "잠긴" 상태가 잠시 유지될 수 있다.
- 권장 조치:
  - 모든 worker cleanup 콜백에서 `_schedule_tab_hydration(0)` 호출이 누락되지
    않도록 보강(현재 일부 경로에서만 호출).
  - hydration queue 상태를 status bar에 노출할 수 있는 디버그 토글 추가.

### 4.2 [Medium] `_request_scope_signatures` 누수 가능성
- 위치: `ui/news_tab_support/loading.py`.
- 이슈:
  - `cancel_initial_hydration`이 wait timeout(False) 시 `request_id`를
    `_cancelled_initial_request_ids`에 추가하지만, `_request_scope_signatures`에
    있는 동일 id 항목은 `on_data_loaded`/`on_data_error`가 도달해야 비로소 정리된다.
  - 워커가 영구 멈춘 경우(예: SQLite interrupt 미지원 환경에서 timeout) 항목이
    누적될 수 있다.
- 권장 조치:
  - `_finalize_cancelled_initial_request` 내부에서 무조건 `pop` 시도 + 실패시
    별도 timeout 정리 타이머에서 batch 클린업.

### 4.3 [Medium] 카운트다운 라벨 권한과 자동 새로고침 비활성화 표시 분리 필요
- 위치: `ui/main_window_support/base.py::_update_countdown`,
  `_main_window_fetch.py::_safe_refresh_all`.
- 이슈:
  - 자동 새로고침 비활성화(`refresh_interval_index == 5`)나 네트워크 오류
    누적으로 자동 새로고침이 멈춘 상태에서 카운트다운 라벨이 비어 있어
    사용자에게 "비활성"인지 "곧 새로고침"인지 구분되지 않는다.
- 권장 조치:
  - 비활성/일시 중단 상태에 따라 카운트다운 라벨에 명시적인 안내 노출
    (예: "자동 새로고침 끔", "네트워크 오류로 일시 중지").

### 4.4 [Low] 외부 링크 열기 실패 시 토스트와 status bar가 같은 메시지
- 위치: `ui/news_tab_support/actions.py::_emit_local_action_failure`.
- 이슈:
  - status bar와 toast에 같은 문자열이 반복 노출돼 시각적으로 redundant.
- 권장 조치:
  - status bar에는 `⚠️ 기사 열기 실패`, toast에는 상세 안내 분리.

### 4.5 [Low] `update_tray_tooltip` 레이스
- 위치: `ui/_main_window_tray.py::update_tray_tooltip`.
- 이슈:
  - `self.db.get_total_unread_count(...)`을 UI 스레드에서 동기 호출.
  - DB 락이 걸린 시점이면 UI가 잠깐 정지할 수 있다.
- 권장 조치:
  - `DBQueryScope`/`AsyncJobWorker` 기반으로 비동기화하거나, 마지막 결과를
    캐시해 재사용.

---

## 5. 설정 / Import-Export

### 5.1 [Medium] `_canonicalize_tab_refresh_policies`의 주석과 실제 동작 불일치
- 위치: `ui/_main_window_settings_io.py::_canonicalize_tab_refresh_policies`.
- 코드:
  ```python
  if known_keys and canonical_key not in known_keys and "|" not in key_text:
      # Keep canonical/imported keys even when their tab is not open yet, but drop
      # invalid raw labels that cannot be matched to a query identity.
      pass
  ```
- 이슈:
  - 주석은 "invalid raw labels 제거"라고 하지만 `pass`라 사실상 모두 통과한다.
  - 결과적으로 잘못된 raw label이 canonical key로 변환되어 영구 남는다.
- 권장 조치:
  - 의도가 keep이면 주석을 정정. drop이 맞다면 `continue` 추가 + 회귀 테스트.

### 5.2 [Medium] Settings export 시 자동 시작 옵션 + 머신 종속성
- 위치: `ui/_main_window_settings_io.py::export_settings`.
- 이슈:
  - `auto_start_enabled`는 export에 포함되지만, 다른 머신에서 import하면
    `StartupManager.is_available()` / 실행 경로 차이로 의도치 않은 등록/해제가
    발생할 수 있다.
  - 현재 `_reconcile_startup_state_from_import`에서 안전화하지만, 사용자가
    "설정 가져오기로 다른 PC의 자동 시작이 켜졌다"고 인지하기 어렵다.
- 권장 조치:
  - export 시 `auto_start_enabled`를 머신 식별자와 함께 저장하고,
    일치하지 않으면 import 시 `False`로 강제하는 정책 추가.
  - 최소한 import 직후 status bar/toast에서 "자동 시작 상태가 변경되었습니다"
    안내.

### 5.3 [Low] `merge_keyword_groups` 빈 그룹 처리 정책
- 위치: `core/keyword_groups.py::merge_keyword_groups`.
- 이슈:
  - import payload에 빈 그룹(`{"임시": []}`)이 들어오면 그대로 추가된다.
  - 사용자에게는 "빈 폴더가 갑자기 생긴" 인상.
- 권장 조치:
  - 빈 그룹은 기본적으로 drop하거나, "import에 포함된 빈 그룹은 N개"라고
    경고 토스트.

### 5.4 [Low] `_to_saved_searches`의 100개 cap이 silent
- 위치: `core/config_store_impl.py::_to_saved_searches`.
- 이슈:
  - 100개 초과 시 잔여 항목을 잘라내지만 사용자에게 알리지 않는다.
- 권장 조치:
  - normalize 단계에서 잘린 개수를 warning으로 반환하고, import flow에서
    토스트로 노출.

---

## 6. 백업 / 복원

### 6.1 [Medium] `AutoBackup.create_backup`의 1차 backup_info.json 작성이 비원자적
- 위치: `core/backup.py::create_backup`.
- 동작:
  - 1차: 일반 `open(...).write(...)`로 `backup_info.json` 작성.
  - 2차: `verify_backup_payload` 결과를 `_write_backup_info`로 atomic 갱신.
- 이슈:
  - 1차 작성 직후 프로세스가 강제 종료되면 partial JSON이 남고,
    `_read_backup_info`에서 `is_corrupt=True`로 표기되면서 사용자가 "백업이
    손상됐다"고 인식한다.
- 권장 조치:
  - 1차도 `_write_backup_info` 경로(원자적 임시파일 + replace)로 일원화.

### 6.2 [Medium] 자동 백업 빈도가 부팅 시 1회로 한정
- 위치: `ui/main_window.py::__init__` (`QTimer.singleShot(2000, ...)`).
- 이슈:
  - 부팅 직후 단 한 번만 자동 백업이 생성된다(설정만).
  - 장시간 실행 후 사용자가 설정/탭/그룹을 대규모로 변경한 뒤 강제 종료되면
    중간 상태에 대한 fallback이 없다.
- 권장 조치:
  - N분 주기 또는 "주요 변경(탭 추가/제거, 설정 저장) X회"마다
    설정-only 자동 백업을 추가.

### 6.3 [Low] 손상 백업 자동 정리 정책 부재
- 위치: `core/backup.py::get_backup_list`, `_cleanup_old_backups`.
- 이슈:
  - 손상 백업도 retention(`MAX_AUTO_BACKUPS`/`MAX_MANUAL_BACKUPS`) 카운트에
    그대로 포함되어 보존된다. 의도된 동작이지만, 사용자가 손상 백업만 따로
    cleanup할 명령이 없다.
- 권장 조치:
  - BackupDialog에 "손상 백업 일괄 삭제" 버튼 + confirm.

### 6.4 [Low] 복원 시 소스 디렉터리 검증 강화
- 위치: `core/backup.py::apply_pending_restore_if_any`.
- 이슈:
  - `requested_backup_dir`가 임의 경로일 수 있고, 일반 fallback은
    `runtime_backup_dir` 한 곳뿐이다. 사용자가 외부 경로의 백업을 복원 예약한
    뒤 해당 외부 디스크가 사라지면 silent 실패한다.
- 권장 조치:
  - 다이얼로그에서 schedule 시점에 디렉터리 존재/접근 가능 여부를 검증하고
    실패 시 즉시 안내.

---

## 7. 단일 인스턴스 / 부팅

### 7.1 [Low] `INSTANCE_SERVER_NAME`이 DATA_DIR 해시 기반
- 위치: `core/bootstrap.py`.
- 이슈:
  - 다른 OS 사용자가 같은 DATA_DIR을 공유할 경우 같은 server name이 생성되어
    의도치 않게 인스턴스를 한 OS 사용자에 종속시킬 수 있다(주로 portable
    구성에서).
- 권장 조치:
  - `os.getlogin()` / `getuid()` 등을 함께 해시.

### 7.2 [Low] `signal_handler`가 `window`가 아직 없을 때 silent
- 위치: `core/bootstrap.py::signal_handler`.
- 이슈:
  - SIGTERM이 `window` 생성 이전에 도달하면 사실상 무시된다.
  - 부팅 단계에서 종료 신호를 받아도 cleanup 없이 그대로 종료될 수 있다.
- 권장 조치:
  - `window`가 없으면 `app.quit()` 호출 + 로그.

### 7.3 [Low] 레거시 마이그레이션 실패 시 복구 가이드 부족
- 위치: `core/bootstrap.py::main` (`migrate_legacy_runtime_files`).
- 이슈:
  - 실패 시 warning만 남기고 진행. 사용자 입장에서는 자동 복원이 안 됐다는
    것을 인지할 단서가 없다.
- 권장 조치:
  - 마이그레이션 실패 시 부팅 후 첫 번째 status bar/toast로 안내 + 로그 위치
    제공.

---

## 8. 코드 품질 / 유지보수

### 8.1 [Low] `_validate_api_credentials` lazy import
- 위치: `ui/_main_window_fetch.py`.
- 이슈:
  - 매 fetch마다 `from core.validation import ValidationUtils`를 런타임에 수행.
- 권장 조치:
  - 모듈 상단에 정적 import.

### 8.2 [Low] 레거시 호환 wrapper 정리
- 위치: 루트의 `query_parser.py`, `config_store.py`, `backup_manager.py`,
  `worker_registry.py`, `workers.py`, `database_manager.py`, `styles.py`.
- 이슈:
  - 현재 모두 통과하지만, 신규 코드에서 wrapper를 무심코 사용해 직접 의존성이
    생길 수 있다.
- 권장 조치:
  - DeprecationWarning을 추가하거나, lint 룰로 직접 import를 차단.
  - 호환 종료 일정/조건을 README에 명시.

### 8.3 [Low] `news_scraper.log`의 회전(rotation) 정책
- 위치: `core/logging_setup.py` (확인 필요).
- 이슈:
  - 코드베이스 전반에서 logger 사용량이 많은데, 회전/사이즈 제한이 명시적으로
    문서화되지 않음.
- 권장 조치:
  - `RotatingFileHandler`/`TimedRotatingFileHandler` 사용 여부 점검 후 README
    "데이터/설정 파일" 섹션에 명시.

### 8.4 [Low] 한국어 메시지에 일부 영문 혼재
- 위치: `_main_window_fetch.py` (`"Sequential refresh"` 등 logger 메시지).
- 이슈:
  - 사용자에게 노출되는 메시지는 한국어, 로그는 영어 혼재.
  - claude.md에는 "UI 텍스트, 로그, 주석 모두 한국어"라고 명시되어 있어
    가이드라인과 일부 불일치.
- 권장 조치:
  - 로그도 한국어로 통일하거나, 가이드라인을 "사용자 메시지=한국어, 내부 로그=영문 허용"으로 명시.

### 8.5 [Low] `parse_tab_query` legacy 정책의 명시적 표기
- 위치: `core/query_parser.py`.
- 이슈:
  - `db_keyword`가 첫 번째 양키워드만 사용한다는 정책은 README/claude.md에
    있지만, 함수 docstring 자체에는 다소 약하게 표현되어 있다.
- 권장 조치:
  - `parse_tab_query` docstring에 "legacy 정책: 첫 양키워드만 db_keyword,
    실제 scope는 query_key" 명시.

---

## 9. 테스트 / 회귀 가드 보강 후보

다음 항목은 직접적인 unit/regression 테스트가 보이지 않아 보강이 필요해 보인다.

| # | 영역 | 현재 검증 자산 | 권장 보강 |
|---|------|--------------|----------|
| 1 | API redirect/secret 헤더 흐름 | 없음 | `requests.Session.send` mocking으로 redirect 시 헤더 누락 확인 |
| 2 | `mark_query_as_read_chunked` 진행 보장 | `tests/test_db_queries.py` 일부 | "동일 링크가 다시 unread로 돌아오는 가짜 시나리오" |
| 3 | `Retry-After` 상한 정책 | `tests/test_fetch_cooldown.py` | 비정상적으로 큰 값 입력 시 cooldown 상한 |
| 4 | `_canonicalize_tab_refresh_policies` raw label drop | `tests/test_implementation_plan_20260429.py` 등 | 잘못된 raw key가 정책 dict에 절대 살아남지 않는지 |
| 5 | publisher 추출이 `news.naver.com` 호스트 폴백 시 동작 | 없음 (직접 검증 필요) | originallink/link 둘 다 naver host인 케이스 |
| 6 | 손상 backup_info.json + atomic write | `test_backup_collision_and_restore.py` 일부 | 1차 write가 atomic이도록 회귀 가드 |
| 7 | hydration queue가 worker cleanup 누락 시에도 재개 | `test_news_tab_performance.py` 일부 | maintenance + sequential refresh 직후 hydration 재개 보장 |

---

## 10. 신규 기능 후보 (UX / 품질)

> 즉시 도입을 제안하는 것은 아니지만, claude.md/README의 사용자 안내와
> 아래 항목을 함께 고려할 수 있다.

- **[Medium] DB 최적화 버튼**: 설정 창의 "데이터 정리" 옆에
  `PRAGMA optimize` + `VACUUM` 트리거 버튼. 진행률은 IterativeJobWorker로 노출.
- **[Medium] 주기 자동 백업**: `app_settings.auto_backup_minutes`(기본 60분).
  off / 30 / 60 / 180 / 360 옵션으로 설정 다이얼로그에 통합.
- **[Medium] 출처/태그 통계 다이얼로그**: 현재 `통계/언론사 분석`과 별도로
  태그별 기사 수와 차단/선호 출처 시뮬레이션을 제공.
- **[Low] 알림 키워드 정규식 모드**: 현재 substring 매칭.
  `regex:^삼성` 형태의 prefix를 도입.
- **[Low] CSV import**: 현재는 export 전용. 사용자 백업/공유 흐름 강화 차원에서
  단방향 CSV import (북마크/메모 한정) 추가.
- **[Low] 다크 모드 자동 전환**: OS 다크 모드를 추적해 자동 적용
  (현재는 수동 토글).

---

## 11. 참고 / 다음 단계 제안

1. **High 항목 우선 적용**:
   - 1.1 (HTTP redirect 시 secret 노출) — 보안 영향이 가장 큼.
   - 6.1 (backup_info.json 1차 atomic write) — 데이터 무결성.
2. **Medium 항목**은 다음 안정화 패스에서 한 묶음으로 다루기 좋다.
   특히 5.1 (`_canonicalize_tab_refresh_policies` 주석/동작 불일치)는
   코드 리뷰 단계에서 빠르게 정리 가능.
3. **Low 항목**은 PR 단위가 아니라 잡(틱) 단위로 모아 처리.

> 본 문서는 정적 코드 리뷰 기반이며, 실제 회귀 여부는 별도 테스트로 검증해야
> 한다. claude.md / README.md / update_history.md의 안정화 흐름 안에서
> 점진적으로 통합하는 것을 권장한다.
