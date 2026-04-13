# 기능 구현 리스크 점검 보고서

작성일: 2026-04-13

참조 기준:
- `README.md`
- `claude.md`
- `core/`, `ui/`, `tests/` 실제 구현
- 실행 검증: `python -m pytest -q`, `pyright`

## 검토 요약

- `pytest`는 현재 통과한다: `203 passed, 5 subtests passed`
- 하지만 구현 관점에서 바로 손봐야 할 리스크가 몇 개 남아 있다.
- 특히 아래 4가지는 기능 신뢰도에 직접 영향을 준다.
  1. DB 저장 실패가 fetch 성공처럼 처리될 수 있음
  2. 구버전 대용량 DB 마이그레이션이 일부 행만 backfill 하고 끝남
  3. UI에 깨진 문자열이 실제로 남아 있는데 현재 인코딩 스모크 테스트가 이를 못 잡음
  4. 설정 창 API 검증 경로가 실제 fetch 경로와 다른 HTTP 정책을 사용함

## 주요 발견 사항

### 1. `upsert_news()` DB 쓰기 실패가 fetch 성공으로 오인될 수 있음

심각도: 높음

문제:
- DB 저장이 실제로 실패해도 사용자는 fetch가 정상 완료된 것으로 보게 된다.
- `new_items`는 API 응답 기준으로 이미 계산되어 있으므로, UI 메시지와 DB 실제 상태가 어긋날 수 있다.

권장 조치:
- `upsert_news()`에서 write 실패를 더 이상 `(0, 0)`으로 삼키지 말고 명시적 예외나 구조화된 실패 결과로 올릴 것
- `ApiWorker`는 DB 저장 실패를 `error` 경로로 보내고 성공 토스트를 띄우지 않도록 할 것

### 2. 구버전 대용량 DB 마이그레이션 backfill 이 일부 행만 처리하고 끝남

심각도: 높음

문제:
- 기존 사용자의 DB가 충분히 크면, 마이그레이션 직후 일부 레코드만 보정되고 나머지는 영구적으로 남는다.
- 그 결과 중복 기사 판정, 날짜 필터, 정렬, 통계/언론사 분석 결과가 일부 오래된 데이터에서 틀어질 수 있다.

권장 조치:
- `NULL` 행이 없어질 때까지 batch loop 로 반복 backfill 하도록 변경
- 마이그레이션 후 `remaining NULL count`를 로그로 남기고, 0이 아니면 경고하도록 변경

### 3. 깨진 UI 문자열이 실제 소스에 남아 있고, 현재 인코딩 테스트가 이를 놓치고 있음

심각도: 중간

문제:
- UTF-8 decode 성공 여부만으로는 사용자 노출 문자열 품질을 보장하지 못한다.
- 운영에서 오류가 났을 때 핵심 안내 문구가 깨지면 사용자 지원 비용이 커진다.

권장 조치:
- 깨진 literal 을 즉시 교체
- `test_encoding_smoke.py`를 다중 토큰/정규식 패턴 감시 수준으로 강화

### 4. 설정 창의 API 키 검증 경로가 실제 fetch 경로와 다른 HTTP 정책을 사용함

심각도: 중간

문제:
- 설정 창에서 “검증 성공/실패”한 결과와 실제 기사 fetch 동작이 완전히 같은 조건이 아니다.
- 사용자 설정 `api_timeout`이 검증 경로에는 반영되지 않는다.

권장 조치:
- 설정 검증도 `HttpClientConfig` + 공통 session factory 를 사용하도록 통합
- timeout 은 `api_timeout` 또는 설정 창 현재 값과 일치시킬 것

## 검증 메모

실행 결과:
- `python -m pytest -q` => `203 passed, 5 subtests passed`
- `pyright` => `55 errors, 5 warnings`

## 우선순위 제안

1. `upsert_news()` 실패 전파 구조 수정
2. schema backfill loop 화
3. 깨진 UI 문자열 정리 + encoding smoke 강화
4. 설정 창 API 검증 경로를 공통 HTTP 설정으로 통합

---

## 후속 반영 상태 (2026-04-13 작업 완료)

위 리스크 항목은 같은 날짜의 후속 구현 패스에서 모두 반영되었다.

- `DatabaseWriteError`를 추가하고 `upsert_news()` write failure를 더 이상 성공처럼 삼키지 않도록 수정
- `ApiWorker`가 DB 조회/저장 실패를 error 경로로 올리고, fetch 성공 토스트/알림은 DB upsert 성공 후에만 발생하도록 정리
- `title_hash`, `pubDate_ts` startup backfill을 반복 배치 루프로 변경하고 대용량 legacy DB 회귀 테스트 추가
- 저장소의 mojibake 문자열을 정리하고 `tests/test_encoding_smoke.py`를 다중 suspicious token/패턴 가드로 강화
- 설정 창 API 검증을 `HttpClientConfig` + 현재 timeout 기반 공용 session 정책으로 통합

후속 검증 결과:
- `python -m pytest -q` => `209 passed, 5 subtests passed`
- `pyright` => `55 errors, 5 warnings`
- `pyinstaller --noconfirm --clean news_scraper_pro.spec` => 성공 (`dist/NewsScraperPro_Safe.exe`)
