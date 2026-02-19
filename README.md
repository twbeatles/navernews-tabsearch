# 뉴스 스크래퍼 Pro v32.7.1 (Stability + Modular Refactor)

네이버 뉴스 API를 활용한 고성능 탭 기반 뉴스 스크래퍼입니다.

> [!NOTE]
> **v32.3.0 변경사항**: **UI/UX 전면 리팩토링** (모던 디자인, 카드형 레이아웃, 툴바 그룹화), CSS 호환성 개선, 성능 최적화.

> [!IMPORTANT]
> **v32.7.1 안정화/확장 개선**:
> - 단일 인스턴스 실행 강제(중복 실행 시 안내 메시지 후 종료)
> - 설정 반영 누락 수정: `sound_enabled`, `api_timeout`
> - 설정 창 API 키 검증/데이터 정리 작업 비동기화로 UI 멈춤 완화
> - 설정 가져오기 탭 병합 dedupe 개선(기존 탭 + 가져온 목록 내부 중복 동시 처리)
> - 자동시작 최소화 옵션 변경 시 레지스트리 재등록으로 즉시 반영
>
> [!IMPORTANT]
> **v32.7.0 통합 안정화/리팩터링**:
> - 워커 수명주기 request_id 기반 정리로 stale 콜백 경쟁 상태 완화
> - fetch dedupe 키를 `검색어 + 제외어` 기준으로 분리
> - 백업 복원을 즉시 덮어쓰기 대신 **재시작 적용(pending restore)** 흐름으로 고정
> - 앱 시작 시 pending restore 자동 적용
> - 설정 로드/저장 스키마 정합성 보강 + 원자 저장(`.tmp` + `os.replace`) 실제 적용
> - 날짜 필터 토글 ON/OFF 시 즉시 DB 재조회
>
> [!IMPORTANT]
> **v32.5.0 안정성 개선사항**:
> - 탭 종료 시 워커/타이머 정리 강화로 종료 안정성 개선
> - DB 백업/복원 무결성 강화 (SQLite backup API 우선, WAL/SHM sidecar 처리)
> - 설정 저장 원자성 강화 (`.tmp` + `os.replace`)
> - 탭 키워드 파싱 로직 통일(`parse_tab_query`)로 조회/배지/리네임 동작 일관성 개선



## v32.7.x Full Split Architecture

This release completes a full project split while preserving runtime compatibility.

- `news_scraper_pro.py` now acts as entrypoint + compatibility re-export layer.
- Core runtime logic is located under `core/`.
- UI classes are located under `ui/`.
- Legacy root module names (`workers.py`, `backup_manager.py`, etc.) are kept as wrappers.
- Existing imports like `import news_scraper_pro as app` remain compatible.

### New Project Layout (v32.7.x)

```text
navernews-tabsearch/
??? news_scraper_pro.py
??? core/
?   ??? constants.py
?   ??? logging_setup.py
?   ??? text_utils.py
?   ??? validation.py
?   ??? startup.py
?   ??? query_parser.py
?   ??? config_store.py
?   ??? backup.py
?   ??? worker_registry.py
?   ??? workers.py
?   ??? database.py
?   ??? notifications.py
?   ??? keyword_groups.py
?   ??? backup_guard.py
?   ??? bootstrap.py
??? ui/
?   ??? styles.py
?   ??? toast.py
?   ??? widgets.py
?   ??? dialogs.py
?   ??? news_tab.py
?   ??? settings_dialog.py
?   ??? main_window.py
??? tests/
```

## 주요 기능

### 🆕 최신 업데이트 기능
- **모던 UI/UX**: 가독성을 높인 카드형 뉴스 리스트와 직관적인 필터 디자인
- **향상된 툴바**: 기능별 버튼 그룹화 및 직관적인 아이콘/라벨 적용
- **최적화된 렌더링**: CSS 호환성 문제를 해결하여 부드러운 뉴스 표시 지원
- **탭 컨텍스트 메뉴**: 탭 우클릭으로 이름 변경, 그룹 추가, 닫기 등 빠른 실행

### 핵심 기능
- **탭 기반 키워드 검색**: 여러 키워드를 독립된 탭으로 관리
- **고급 검색 필터**: 제외 키워드(`-`), 기간 설정, 중복 기사 숨김
- **자동 새로고침**: 백그라운드에서 주기적으로 뉴스 업데이트 (10분~6시간)
- **북마크 & 메모**: 중요 기사 영구 저장 및 메모 작성
- **성능 최적화**: 
  - **네트워크**: 세션 재사용으로 API 통신 속도 향상
  - **UI**: '더 보기' 로딩 시 끊김 없는 렌더링
  - **DB**: 인덱스 기반 정렬 및 멀티스레드 처리

### 알림 및 시스템 통합
- **스마트 알림**: 새 기사 도착, 특정 키워드 감지 시 데스크톱 알림
- **시스템 트레이**: 최소화 시 트레이 아이콘으로 실행
- **단일 인스턴스 실행**: 앱 중복 실행 시 새 인스턴스는 안내 메시지 후 종료
- **윈도우 통합**: 부팅 시 자동 시작, 창 위치/크기 기억

### 설정 확장
- **API 타임아웃 설정**: 설정 창에서 5~60초 범위로 조절 가능
- **알림 소리 설정 저장**: 설정/재시작/가져오기/내보내기 경로 전체에서 일관 반영

### 데이터 관리
- **CSV 내보내기**: 검색 결과를 엑셀 호환 CSV로 저장
- **키워드 그룹**: 주제별 키워드 그룹 관리 (컨텍스트 메뉴 지원)
- **자동 백업**: 설정 및 데이터 자동 백업/복원

## 저장소 구조 (정리 후)

```text
navernews-tabsearch/
├── news_scraper_pro.py
├── styles.py
├── query_parser.py
├── config_store.py
├── backup_manager.py
├── worker_registry.py
├── workers.py
├── database_manager.py
├── tests/
├── dist/
└── backups/
```

### 백업 폴더 정리 반영
- 2026-02-18 기준 불필요 개발 보조 파일/캐시/빌드 산출물은 `backups/repo_cleanup_20260218_222833/`로 이동했습니다.
- 이동 항목:
- `find_classes.py`, `find_classes_old.py`
- `classes_list.txt`, `classes_list_old.txt`
- `news_scraper.spec`
- 루트 `__pycache__/`, `tests/__pycache__/`
- `build/`

## 안정성 업데이트 상세 (v32.7.0)

- **워커 정리 경쟁 상태 완화**: 키워드 단일 키 정리에서 request_id 기반 정리로 변경해 stale finished/error 콜백이 최신 워커를 정리하지 않도록 개선했습니다.
- **네트워크 dedupe 정밀화**: fetch dedupe 기준에 제외어(`-키워드`)를 포함해 동일 검색어의 다른 탭 쿼리 충돌을 줄였습니다.
- **복원 안전성 강화**: 백업 복원은 pending 파일에 예약 후 재시작 시 적용하도록 고정해 실행 중 DB 덮어쓰기 리스크를 줄였습니다.
- **부팅 시 복원 적용**: `main()` 시작 초기에 pending restore를 적용하도록 추가했습니다.
- **설정 스키마 정합성 강화**: `app_settings` 필드 로드 누락을 보완하고 저장은 원자적 교체를 사용합니다.
- **날짜 토글 UX 보정**: 날짜 필터 버튼 ON/OFF 시 즉시 재조회되도록 동작을 통일했습니다.

## 안정성 업데이트 상세 (v32.5.0)

- **탭/스레드 종료 안정성**: 탭 닫기 시 리소스 정리 루틴을 명시적으로 실행하여 백그라운드 워커 잔존 가능성을 낮췄습니다.
- **UI 프리징 완화**: DB 로딩 워커 종료 대기를 제한 시간 기반으로 바꿔, 특정 상황에서 무기한 대기하던 경로를 제거했습니다.
- **강제 스레드 종료 제거**: `QThread.terminate()` 호출을 제거하고 `stop -> quit -> wait` 흐름으로 정리했습니다.
- **키워드 파싱 일관성**: 탭 문자열 파싱을 단일 헬퍼로 통합해 조회/배지/리네임이 같은 기준으로 동작합니다.
- **백업/복원 신뢰성**: 실행 중 백업 시에도 일관된 스냅샷을 우선 생성하고, DB sidecar 파일(`-wal`, `-shm`)을 함께 처리합니다.
- **설정 파일 손상 위험 완화**: 설정 저장 시 임시 파일 기록 후 원자적 교체로 중간 실패에 대한 내성을 높였습니다.

## 설치 및 실행

### 실행 파일 사용
`dist/NewsScraperPro_Safe.exe` 파일을 실행하면 설치 없이 바로 사용 가능합니다.

### 소스 코드 실행
```bash
# 필수 라이브러리 설치
pip install PyQt6 requests

# 실행
python news_scraper_pro.py
```

## API 키 설정

1. [네이버 개발자센터](https://developers.naver.com/apps/#/register)에서 애플리케이션 등록
2. **검색 (Search)** API 권한 선택 (뉴스 검색용)
3. 프로그램 실행 후 `설정(Ctrl+,)` 메뉴에서 Client ID/Secret 입력

## 단축키 가이드

| 단축키 | 기능 |
|--------|------|
| `Ctrl+R` / `F5` | 모든 탭 새로고침 |
| `Ctrl+T` | 새 탭 추가 |
| `Ctrl+W` | 현재 탭 닫기 |
| `Ctrl+F` | 검색창/필터 포커스 |
| `Ctrl+S` | CSV로 내보내기 |
| `Ctrl+,` | 설정 메뉴 열기 |
| `Alt+1~9` | 탭 바로가기 |
| **`Right Click`** | **탭 컨텍스트 메뉴 (New)** |

## 라이선스

MIT License
