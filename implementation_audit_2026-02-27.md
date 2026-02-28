# 기능 구현 점검 리포트 (2026-02-27)

- 기준 문서: `README.md`, `claude.md`
- 점검 범위: `core/*`, `ui/*`, `tests/*`, 실행/테스트 동선
- 실행 검증:
  - `python -m pytest -q` -> `70 passed`
  - `pytest -q` -> import 경로 오류로 수집 실패 (아래 이슈 8)

## 핵심 잠재 이슈 (우선순위순)

### 1) [High] 취소된 API 워커가 네트워크 완료 후 DB를 건드릴 수 있는 구조
- 근거 코드:
  - `ui/main_window.py:1699-1707` (정리 시 `stop()` + `wait(1000)`만 수행)
  - `core/workers.py:270-273` (`ApiWorker.stop()`은 플래그만 변경)
  - `core/workers.py:141` (블로킹 `session.get(...)`)
  - `core/workers.py:222-223` (`upsert_news` 호출)
- 영향:
  - 같은 탭에서 빠르게 연속 조회 시, 이전 요청이 "취소된 것처럼 보여도" 늦게 돌아와 DB에 반영될 여지가 있습니다.
  - UI 콜백은 stale 방어가 있으나 DB 반영 자체는 완전히 차단되지 않습니다.
- 권장:
  - 취소 시 네트워크 요청 자체를 중단할 수 있도록 워커별 세션을 닫거나 인터럽트 가능한 요청 경로를 사용.
  - `resp` 수신 직후/DB 저장 직전에도 취소 플래그 재검사.

### 2) [High] `requests.Session` 단일 인스턴스를 여러 워커 스레드가 공유
- 근거 코드:
  - `ui/main_window.py:150-154` (앱 단일 세션 생성)
  - `ui/main_window.py:1434-1437` (동일 탭만 이전 워커 정리)
  - `ui/main_window.py:1453` (모든 워커에 동일 세션 주입)
- 영향:
  - 서로 다른 탭 동시 조회 시 세션 공유 경쟁 상태 가능성이 있습니다.
  - 드물게 헤더/커넥션 상태 이상, 예측 불가 오류가 발생할 수 있습니다.
- 권장:
  - 워커별 독립 세션 사용(가장 단순), 혹은 thread-local 세션 풀 적용.

### 3) [Medium] 백업 폴더명이 초 단위라 같은 초에 백업 충돌 가능
- 근거 코드:
  - `core/backup.py:69` (타임스탬프 `%Y%m%d_%H%M%S`)
  - `core/backup.py:71-72` (`backup_path` + `os.makedirs(..., exist_ok=True)`)
- 영향:
  - 같은 초에 자동/수동 백업이 겹치면 같은 디렉터리를 공유해 백업 이력이 섞일 수 있습니다.
- 권장:
  - 밀리초/UUID suffix 추가.
  - `exist_ok=False`로 충돌 시 재시도.

### 4) [Medium] `restore_backup()`와 pending restore의 DB sidecar 처리 정책 불일치
- 근거 코드:
  - `core/backup.py:194-198` (`restore_backup`는 DB 본체만 복사)
  - `core/backup.py:260-266` (`apply_pending_restore_if_any`는 `-wal/-shm` 처리)
- 영향:
  - 즉시 복원 API 사용 시 WAL/SHM 정합성이 깨질 수 있습니다.
- 권장:
  - `restore_backup()`도 sidecar 정책을 동일하게 맞추거나, 사용 금지/내부 전용으로 명확히 제한.

### 5) [Medium] `더 불러오기` 종료 조건이 `1000` 상한만 보고 `total` 기반 종료를 사용하지 않음
- 근거 코드:
  - `ui/main_window.py:1416-1425` (start index 증가 + 1000 제한)
  - `ui/main_window.py:1527` (`result['total']`은 저장하지만 종료 판단에 미사용)
  - `ui/main_window.py:1531-1532` (완료 후 버튼 다시 활성화)
- 영향:
  - 결과가 더 이상 없는데도 "더 불러오기"가 계속 가능해 UX 혼선 및 불필요 API 호출이 생길 수 있습니다.
- 권장:
  - `start_idx > total`이면 버튼 비활성화/상태 메시지 표시.

### 6) [Low] 제외어 필터링의 대소문자 처리 일관성 부족
- 근거 코드:
  - `core/workers.py:179-184` (수집 시 `ex in title/desc`, case-sensitive)
  - `core/database.py:660-666` (조회 시 SQL `LIKE` 기반)
- 영향:
  - 영문 키워드에서 수집 시점 필터와 조회 시점 필터 결과가 엇갈릴 수 있습니다.
- 권장:
  - 수집/조회 양쪽 모두 소문자 정규화 기준으로 통일.

### 7) [Low] 외부 열기(`ext`) 동작의 읽음 처리 규칙이 경로별로 다름
- 근거 코드:
  - `ui/news_tab.py:731-733` (`on_link_clicked`의 `ext`는 읽음 변경 없음)
  - `ui/news_tab.py:813-821` (`on_browser_action`의 `ext`는 읽음 처리)
- 영향:
  - 사용자 액션이 같아 보이는데 경로에 따라 읽음 상태가 달라집니다.
- 권장:
  - 한 정책으로 통일(둘 다 읽음 처리 또는 둘 다 미처리).

### 8) [Low] 테스트 실행 진입점 혼선 (`pytest -q` 실패, `python -m pytest -q` 성공)
- 관찰:
  - 현재 환경에서 `pytest -q`는 모듈 import 실패.
  - `python -m pytest -q`는 정상 통과.
- 영향:
  - CI/개발자 로컬에서 명령 차이로 불필요한 실패가 발생할 수 있습니다.
- 권장:
  - `README.md`에 테스트 실행 명령을 명시적으로 추가.
  - `pytest.ini`/`pyproject.toml`로 import path를 고정해 진입점 차이를 줄이기.

## 추가 기능 제안

### A) 복수 포함 키워드 검색 지원 강화 (현재는 첫 포함 키워드만 fetch 기준)
- 근거 코드: `core/query_parser.py:8-16`
- 제안:
  - `"AI 반도체 -광고"`처럼 포함 키워드를 조합한 검색식을 fetch query에 직접 반영하는 모드 추가(옵션화 권장).

### B) 백업 목록 로딩 내결함성
- 근거 코드: `core/backup.py:165-178`
- 제안:
  - 백업 하나의 `backup_info.json`이 깨져도 전체 목록 로딩이 멈추지 않도록 항목 단위 예외 처리.

## 테스트 보강 제안

- 워커 취소 후 DB write가 발생하지 않는지 검증 테스트 추가
  - 대상: `ApiWorker.stop()` + `cleanup_worker()` 경합 시나리오
- 동일 초 백업 2회 생성 충돌 테스트 추가
  - 대상: `AutoBackup.create_backup()`
- `더 불러오기` 종료 조건(`total` 기반) 회귀 테스트 추가
  - 대상: `MainApp.fetch_news()/on_fetch_done()`


---

## 구현 반영 상태 (2026-02-28)

- 상태: **핵심+테스트 일괄 반영 완료**
- 반영 범위:
  - 리스크 1~8 수정 구현 완료
  - 회귀 테스트 추가/보강 완료
  - `README.md` 테스트 실행 가이드 반영 완료
  - `pytest.ini` 추가 완료
- 제외 범위:
  - 추가 기능 A/B(복수 포함 키워드 모드, 백업 목록 항목 단위 복구 내결함성) 미반영

### 변경 요약
- `core/workers.py`
  - 취소 경계 재검사(응답 직후/DB 저장 직전)
  - 워커 소유 세션 종료로 취소 강건화
  - 취소 상태 예외 경로에서 `error` emit 억제
  - 제외어 소문자 비교로 수집 경로 일관화
- `ui/main_window.py`
  - 워커 호출에서 공유 `session` 전달 제거
  - total 기반 `더 불러오기` 종료 계산/버튼 갱신 헬퍼 추가
- `core/backup.py`
  - 백업명 충돌 회피(마이크로초 + 충돌 재시도)
  - `restore_backup()` 엄격화(`restore_db=true` + DB 백업 누락 시 실패)
  - DB sidecar(`-wal/-shm`) 복원 정책 통일
- `ui/news_tab.py`
  - `ext` 경로 읽음 처리 정책 공통 헬퍼로 통일(열면 읽음)
- 테스트/실행 경로
  - 신규 테스트 4개 추가 + 안정성 테스트 1개 보강
  - `pytest.ini` 추가로 `pytest -q` / `python -m pytest -q` 동작 일치

### 검증 결과
- `python -m pytest -q`: **83 passed**
- `pytest -q`: **83 passed**

### `.spec` 점검 결과
- `news_scraper_pro.spec` 검토 완료
- 이번 패스는 런타임/테스트/문서 변경만 포함되어 **추가 수정 불필요**