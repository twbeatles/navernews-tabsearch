# 런타임 안정성 계약

## 작업 종료

- 결과 신호와 `settled`는 `run()` 반환 전에 발행될 수 있다. 결과 수신만으로 QThread·부모 QObject·사용 중인 DB를 파괴하지 않는다.
- `core.workers_support.lifecycle.request_background_shutdown`이 중단을 요청하고 하나의 시간 예산 안에서 네이티브 스레드 종료를 확인한다. named worker, QObject 자식, 분리 보관된 worker도 확인한다.
- `_perform_real_close`는 생산 타이머를 중단하고 API worker를 정지시킨다. 작업이 남으면 close event를 무시하고 이벤트 루프를 유지한 채 재시도한다. 대기 timeout을 완료로 처리하거나 스레드를 강제 terminate하지 않는다.
- 종료 요청 후에는 새 fetch·cloud cycle과 완료 콜백의 새 UI 작업을 시작하지 않는다. 작업이 공유 폴더 I/O에 걸린 경우 안전한 경계까지 종료가 지연될 수 있다.
- 새 백그라운드 작업은 QObject 부모 또는 기존 retain helper로 수명을 추적해야 한다. DB를 사용하는 작업을 추적 없이 detach하지 않는다.

## 전역 기사와 검색 범위

- `news`의 제목/hash는 link별 전역 값이다. `news_keywords.is_duplicate`는 query key별 파생 값이다.
- `upsert_news_detailed`는 `BEGIN IMMEDIATE`로 읽기 전 writer 예약을 잡고, 제목이 바뀌는 링크의 모든 소속 범위에서 이전/새 hash 그룹을 같은 transaction으로 재계산한다.
- 일반 저장은 영향 범위만 재계산한다. 전체 재계산은 수동 복구·클라우드 병합·스키마 마이그레이션에만 사용한다.
- 기존 잘못된 표시의 수동 복구는 설정 → 데이터 → 도구 → 중복 표시 복구에서 수행한다. 기사·북마크·메모를 삭제하지 않는다.

## 업데이트와 내보내기

- 업데이트는 앱 종료 전에 대상 디렉터리에 파일을 독점 생성·복사·fsync·해시 검증한다. 실행 파일과 동일 볼륨의 파일로 rename swap하며, 원본 실행 파일 위에 직접 복사하지 않는다.
- `--smoke`는 `core` import 이전에 임시 runtime 경로를 설정한다. 실제 QApplication/MainApp/SQLite 및 이벤트 루프를 사용하며 네트워크·트레이·자동 시작·정기 작업을 실행하지 않는다.
- smoke 실패 시 이전 실행 파일로 복구하고, helper는 실패 결과를 기록한 뒤 이전 앱을 다시 실행한다. 전원 중단으로 원본 exe가 사라진 경우의 수동 복구는 README를 따른다.
- JSON 출력은 기존 keyword/exported_at/count/items 계약을 유지하면서 batch 단위로 기록한다. 취소·실패 시 기존 출력 파일을 보존하고 snapshot iterator 및 임시 파일 핸들을 닫는다.

## 검증 범위

- 기준 CI는 Windows x64/Python 3.14와 pinned dependencies다. 로컬 Windows ARM64/Python 3.15 검증 결과를 x64 검증으로 표현하지 않는다.
- quality/release CI는 source/frozen 부팅 검사를 수행하며, optional UI/crypto가 없는 별도 core 테스트 job도 둔다.
- 실제 API HUB·클라우드 업체·물리 볼륨·전원 차단 검증은 mock/fault injection과 구별해 기록한다.
