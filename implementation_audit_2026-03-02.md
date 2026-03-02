# Implementation Audit (2026-03-02)

## 범위
- 코드 기준: `core/`, `ui/`, `tests/`
- 참조 문서: `README.md`, `claude.md`
- 실행 검증: `pytest -q` (`87 passed`)

## 요약
- 즉시 보완 권장: 3건
- 중기 개선 권장: 4건
- 문서/테스트 품질 개선: 2건

---

## 주요 이슈 (우선순위순)

### 1) 재실행 시 stale lock 복구 경로 부재 (High)
- 근거:
  - `core/bootstrap.py:154` `instance_lock.setStaleLockTime(30000)`
  - `core/bootstrap.py:155` `tryLock(0)` 실패 시
  - `core/bootstrap.py:156-166` 기존 인스턴스 IPC 실패해도 stale lock 제거/재시도 없이 종료
- 영향:
  - 앱 크래시 직후 재실행 시 실제 인스턴스가 없어도 최대 30초 동안 "이미 실행 중"으로 차단될 수 있음.
- 권장 조치:
  - `_notify_existing_instance()` 실패 시 `removeStaleLockFile()` + `tryLock()` 재시도 1회 추가.
  - stale lock 시간을 30초보다 짧게 조정(예: 5~10초) 검토.

### 2) 트레이 미지원 환경에서 시작 최소화 시 창 접근 불가 가능성 (High)
- 근거:
  - `ui/main_window.py:312-315` 트레이 불가 시 `self.tray = None`
  - `ui/main_window.py:244-245` 트레이 가능 여부와 무관하게 `self.hide()` 예약
- 영향:
  - 트레이가 없는 환경에서 `--minimized` 또는 `start_minimized=true`면 창이 숨겨지고 복구 경로가 없어질 수 있음.
- 권장 조치:
  - `start_minimized` 실행은 `self.tray`가 유효할 때만 허용.
  - 트레이 미지원 시 강제로 `show()`하고 상태바/토스트로 이유 안내.

### 3) 탭 검색어 파싱 정책과 UI 안내 문구 불일치 (Medium)
- 근거:
  - `core/query_parser.py:5-17` 양(+) 키워드는 첫 토큰만 검색어로 사용
  - `ui/main_window.py:1009` 안내 문구 예시: `"인공지능 AI -광고"` (다중 양키워드 지원처럼 보임)
- 영향:
  - 사용자가 `"인공지능 AI"`를 넣어도 실제 API 검색어는 `"인공지능"`만 사용됨.
  - 검색 결과가 기대와 달라지는 UX 오해 발생.
- 권장 조치:
  - 둘 중 하나로 정책 통일:
  - 파서 확장: 양(+) 토큰 전체를 합쳐 검색어로 사용.
  - 문구 수정: "첫 번째 일반 키워드만 검색어로 사용"을 명시.

### 4) 삭제 실패 메시지 한글 깨짐 (Medium)
- 근거:
  - `ui/news_tab.py:890` `" ?ㅻ쪟", "??젣?좎긽 ..."` 문자열 깨짐
- 영향:
  - 사용자 오류 메시지 이해 불가, 품질 저하.
- 권장 조치:
  - UTF-8 정상 문자열로 교체(예: `"오류"`, `"삭제 대상 기사를 찾을 수 없습니다."`).

### 5) 단일 인스턴스 IPC 수신 처리의 UI 스레드 blocking 호출 (Low-Medium)
- 근거:
  - `core/bootstrap.py:67` `socket.waitForReadyRead(200)`를 `newConnection` 슬롯에서 실행
- 영향:
  - 접속 이벤트당 최대 200ms UI 정지 가능성.
- 권장 조치:
  - `waitForReadyRead` 제거 후 `readyRead` 시그널 기반 비동기 처리.

### 6) SettingsDialog 백그라운드 작업 종료 제어 부재 (Low)
- 근거:
  - `ui/settings_dialog.py:590-595`, `ui/settings_dialog.py:697-702` 비동기 워커 시작
  - `ui/settings_dialog.py`에 `closeEvent`/종료 시 워커 취소 처리 없음
- 영향:
  - 다이얼로그를 닫아도 작업이 백그라운드에서 계속 수행될 수 있음.
- 권장 조치:
  - `closeEvent`에서 실행 중 워커의 시그널 정리 + 종료 대기(짧은 timeout) 처리.

---

## 테스트/품질 리스크

### 7) 핵심 흐름의 문자열 기반 테스트 비중 과다 (Medium)
- 근거:
  - `tests/test_single_instance_guard.py:7-18` 코드 문자열 포함 여부 검증 중심
  - `tests/test_risk_fixes.py:16-113` 다수 케이스가 소스 문자열 단위 검증
- 영향:
  - 런타임 동작이 깨져도(시그널 연결 누락, 실제 복원 실패 등) 테스트가 통과할 수 있음.
- 권장 조치:
  - `QApplication` + `QSignalSpy` 기반 동작 테스트 추가.
  - 최소 1개 E2E: "2nd launch -> 1st window restore" 검증.

### 8) 문서상 체크리스트(버전/히스토리)와 실제 변경 프로세스 연결 약함 (Low)
- 근거:
  - `claude.md`의 체크리스트는 존재하나 자동 검증 훅은 없음.
- 영향:
  - 기능 변경 대비 버전/히스토리 누락 가능성.
- 권장 조치:
  - CI 또는 pre-commit에서 `core/constants.py`의 `VERSION`과 `update_history.md` 변경 동시성 체크.

---

## 추가 권장 작업 (기능/운영)

1. 단일 인스턴스 복원 실패 시 사용자 메시지 고도화
- "기존 창 복원 요청 실패(잠금 파일 가능성)"를 구체적으로 안내하고 재시도 버튼 제공.

2. 시작 최소화 안전장치
- 트레이 미사용 환경 자동 감지 시 `start_minimized` 옵션 UI 비활성화.

3. 검색어 정책 명시
- 설정/도움말에 "검색어 파싱 규칙"을 명확히 표기(현재는 코드 지식 필요).

4. 오류 메시지 품질 점검 자동화
- 깨진 문자열(인코딩 문제) 감지를 위한 간단한 스모크 테스트 추가.

---

## 빠른 실행 제안

1. Hotfix 우선순위
- `news_tab.py` 깨진 문자열 수정
- `start_minimized` + tray availability 조건 가드 추가
- stale lock 복구 재시도 로직 추가

2. 테스트 보강
- 단일 인스턴스 동작 테스트(E2E) 1개
- start_minimized/tray unavailable 케이스 테스트 1개


---

## 2026-03-02 Implementation Status Update

- All items in this audit plan were implemented in code/tests/docs.
- Key outcomes:
  - single-instance stale lock recovery + explicit status logging
  - tray-aware startup minimized guard + settings UI disablement
  - API query parsing (`parse_search_query`) separated from DB key parsing (`parse_tab_query`)
  - `ApiWorker` query/DB keyword split constructor contract
  - corrupted delete warning string restored in `ui/news_tab.py`
  - SettingsDialog worker shutdown guards on close
  - restored `update_history.md` + VERSION/history guard test
  - added parser/tray/single-instance/encoding/version guard tests

## 2026-03-02 Follow-up (Spec/Docs/Gitignore)

- `.spec` verification:
  - `core/bootstrap.py` uses `PyQt6.QtNetwork` (`QLocalServer`, `QLocalSocket`).
  - `news_scraper_pro.spec` was updated to include `PyQt6.QtNetwork` in `hiddenimports` and remove it from `excludes`.
- `.md` consistency updates:
  - `README.md`, `claude.md`, `update_history.md` synchronized for parsing policy, tray/minimized guard, version-history guard, and spec sync note.
  - completion section added to this audit document.
- `.gitignore` review:
  - current ignore rules already cover local runtime artifacts (`*.db`, `*.json`, `dist/`, `build/`, logs/cache).
  - no additional `.gitignore` changes required for this pass.
