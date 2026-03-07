# 기능 구현 감사 리포트 (2026-03-07)

## 검토 범위
- 문서 기준: `README.md`, `claude.md`
- 코드 기준: `core/*.py`, `ui/*.py`, `news_scraper_pro.py`
- 테스트 기준: `tests/*.py` 전체
- 기준선 확인: `python -m pytest -q` 실행 결과 `112 passed, 5 subtests passed`

## 잠재 이슈 (우선순위순)

### 1) 탭 종료/리네임 시 진행 중 API 워커가 취소되지 않음 (중간~높음)
- 근거:
  - 워커 등록/실행: `ui/main_window.py:1556-1617`
  - 탭 종료 경로에서 워커 정리 호출 없음: `ui/main_window.py:1154-1177`
  - 탭 리네임 경로에서도 기존 워커 취소 호출 없음: `ui/main_window.py:1179-1265`
- 영향:
  - 닫힌/이름 변경된 탭에 대해 네트워크+DB 작업이 계속 진행될 수 있음
  - 리네임 타이밍에 따라 완료 콜백이 새 탭 상태와 어긋나는(stale) 상황 발생 가능
- 권장:
  - `close_tab`, `rename_tab` 진입 시 `cleanup_worker(...)`로 활성 요청을 선취소
  - 리네임은 기존 요청 정리 후 키워드 전환하도록 순서 고정

### 2) pending restore 적용이 비원자적(부분 적용 가능) (중간~높음)
- 근거:
  - 설정 파일 먼저 복사, 이후 DB 복사: `core/backup.py:297-302`
  - 중간 실패 시 pending 유지하고 종료: `core/backup.py:313-315`
- 영향:
  - 설정은 복원되고 DB는 미복원인 부분 적용 상태가 생길 수 있음
  - 다음 실행까지 설정/DB 정합성 깨질 위험
- 권장:
  - 임시 파일에 모두 복원 성공 후 `os.replace`로 일괄 스위치
  - 실패 시 롤백(원본 유지) 보장

### 3) 백업 목록 로드 내구성 부족(단일 손상 파일이 전체 목록을 막음) (중간)
- 근거:
  - `get_backup_list()`가 전체 루프를 단일 `try`로 감쌈: `core/backup.py:190-211`
  - 한 폴더의 `backup_info.json` 파싱 오류가 전체 리스트 실패로 전파될 수 있음
- 영향:
  - 백업 UI가 빈 목록 또는 일부 누락 상태가 될 가능성
- 권장:
  - 백업 폴더 단위로 `try/except` 분리, 손상 항목만 스킵

### 4) `mark_query_as_read`가 DB 연결을 중첩 획득함 (중간)
- 근거:
  - `mark_query_as_read`에서 연결 획득 후: `core/database.py:1081`
  - 내부에서 `mark_links_as_read` 재호출(다시 연결 획득): `core/database.py:1109`
  - `mark_links_as_read` 자체 연결 획득: `core/database.py:1026`
- 영향:
  - 연결 풀 압박 시 타임아웃/비상 연결(emergency connection) 증가 가능
  - 고부하 시 지연 변동성 확대
- 권장:
  - 동일 연결을 재사용하는 내부 helper(`*_with_conn`)로 단일 트랜잭션 처리

### 5) 트레이 미읽음 집계가 중복 기사/캐시 편향 가능 (낮음~중간)
- 근거:
  - 탭별 캐시를 순회해 단순 합산: `ui/main_window.py:409-416`
- 영향:
  - 동일 링크가 여러 탭에 존재하면 트레이 미읽음 수가 과대집계될 수 있음
  - 탭 캐시 미동기 상태에서는 실제 DB 미읽음과 차이 발생 가능
- 권장:
  - 링크 기준 `distinct` 집계(메모리 set 또는 DB 질의)로 전환

### 6) 배지 갱신 후 탭 아이콘이 사라지는 UI 불일치 (낮음)
- 근거:
  - 탭 생성 시 아이콘 포함 텍스트 설정: `ui/main_window.py:1040-1041`
  - 배지 갱신 시 키워드만으로 탭 텍스트 재설정: `ui/main_window.py:788-793`
- 영향:
  - 초기 탭 라벨과 이후 라벨 스타일이 달라져 일관성 저하
- 권장:
  - 탭 표시 전용 formatter를 두고 아이콘/배지를 함께 구성

### 7) 날짜 파싱 실패 기사(`pubDate_ts=0`)가 정리 작업에서 즉시 삭제될 수 있음 (낮음~중간)
- 근거:
  - 파싱 실패 시 `0.0` 반환: `core/text_utils.py:59-73`
  - 정리 시 `pubDate_ts < cutoff` 조건 삭제: `core/database.py:910-920`
- 영향:
  - 날짜 포맷이 비정상인 기사들이 오래된 기사로 간주되어 조기 삭제될 수 있음
- 권장:
  - 파싱 실패는 `NULL`/별도 플래그로 저장하고 정리 대상에서 제외하거나 정책 분리

## 문서-구현 정합성 포인트

### `claude.md` DB 사용 예시가 현재 API 계약과 어긋남
- 근거:
  - 문서 예시: `with self.db_manager.get_connection() as conn:` (`claude.md:407`)
  - 실제 구현은 `return_connection()` 호출을 통한 풀 반환이 필요 (`core/database.py:52-70`, `core/database.py:1116-1137`)
- 영향:
  - 문서 예시를 그대로 신규 코드에 쓰면 연결 반납 누락 가능
- 권장:
  - 문서 예시 수정 또는 `DatabaseManager.connection()` 컨텍스트 매니저 공식 제공

## 추가 권장(기능/품질)

### A) API 비밀값 저장 강화
- 근거: `client_secret` 평문 저장 경로 존재 (`ui/main_window.py:552-553`)
- 제안: Windows Credential Manager 연동 후 설정 파일에는 키 참조값만 저장

### B) 테스트 전략 보강(문자열 검사 중심 -> 동작 검증 중심)
- 근거: 소스 문자열 포함여부 검사 다수 (`tests/test_risk_fixes.py:19-148`)
- 제안: 핵심 경로(`close/rename during fetch`, `손상 백업 메타`, `부분 복원 실패 롤백`)를 실제 동작 기반 테스트로 추가

### C) 설정/백업 장애 복구 UX
- 제안:
  - `news_scraper_config.json.backup` 자동 복구 fallback
  - 손상 백업 항목을 UI에서 “손상됨”으로 표시하고 삭제/무시 선택 제공

---

## 2026-03-07 Implementation Status Update

This audit plan has been fully implemented in code and tests.

### Completion Summary
- Potential issue fixes 1~7: completed
- Document/implementation consistency updates: completed
- Additional recommendations A/B/C: completed
- Version policy: `VERSION` kept at `32.7.2`, with `update_history.md` expanded under `Unreleased`

### Packaging and Ignore Review
- `news_scraper_pro.spec` reviewed again for this pass; no additional hidden import/exclude changes were required.
- `.gitignore` updated to ignore runtime recovery leftovers:
  - `.restore_stage_*/`
  - `*.db.corrupt_*`

### Validation
- `python -m pytest -q` => `128 passed, 5 subtests passed`
