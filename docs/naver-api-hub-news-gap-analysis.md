# NAVER API HUB 뉴스 검색 — 문서 vs 앱 반영 조사

- **문서**: 뉴스 검색 결과 조회 (`/search/v1/news`)
- **문서 갱신 참고**: 2026-06-25 (사용자 제공 스냅샷) → 2026-10-08 개정판 재확인 (2026-11-24)
- **조사일**: 2026-07-16 (2026-11-24 후속 반영: 항목 2·5·6 일부 해소)
- **대상 코드**: `core/naver_api.py`, `core/workers_support/api_worker.py`, fetch 페이지네이션, 설정 검증

---

## 결론 요약

**핵심 계약(엔드포인트·헤더·쿼리·item 필드·페이지 한도)은 대체로 잘 반영되어 있습니다.**  
다만 문서에 있는 일부 옵션·메타데이터·운영 정보는 **의도적 생략**이거나 **미반영** 상태입니다.

---

## 이미 잘 맞는 부분

| 문서 | 구현 | 위치 |
|------|------|------|
| `GET /search/v1/news` | API HUB URL 사용 | `core/naver_api.py` |
| 헤더 `X-NCP-APIGW-API-KEY-ID` / `X-NCP-APIGW-API-KEY` | 동일 | `naver_auth_headers()` |
| `query` (UTF-8) | 검색어 전달 (`requests` params) | `api_worker.py` |
| `display` 1~100 | 고정 `100` (상한) | `api_worker.py` |
| `start` 1~1000 | 커서 + `+100`, 1000 초과 차단 | `start.py`, `state.py`, `config.py` |
| `sort` | `date` 고정 (날짜 내림차순) | `api_worker.py` |
| item: `title`, `link`, `originallink`, `description`, `pubDate` | 파싱·저장 경로에 사용 | `api_worker.py` |
| `<b>` 하이라이트 | 제거 후 저장 | `RE_BOLD_TAGS` + `html.unescape` |
| `total` | 더 불러오기/배지에 사용 | finished payload → `completion.py` |
| Search 오류 `errorCode`/`errorMessage` (SE02 등) | 파싱 후 사용자 메시지 | `parse_naver_api_error` |
| 설정 검증 | 동일 URL/헤더 사용 | `_settings_dialog_tasks.py` |

### 페이지네이션 계약

- 한 번에 `display=100`
- 다음 `start = last + 100`
- `start > 1000`이면 중단

→ 이론상 API로 가져올 수 있는 구간(최대 1000건)을 채웁니다.

---

## 미반영 / 부분 반영 항목

### 1. `sort=sim` (정확도 정렬) — 반영됨 (2026-11-24)

문서:

- `sim` (기본값, 정확도) | `date` (날짜)

앱:

- 기본값 `"sort": "date"` 유지 (최신 수집에 적합)
- `설정 → 일반 → 검색 정렬`에서 최신순(date)/정확도순(sim) 선택 가능
- 설정·가져오기·내보내기·실행 파이프라인 전체에 `api_sort` 정규화(`normalize_api_sort`) 적용, 키 검증도 동일 정렬로 수행

### 2. `format` 파라미터 — 반영됨 (2026-11-24)

문서: `json` (기본) | `xml`  
앱: `format=json` 명시 전송 (`NAVER_NEWS_SEARCH_FORMAT`, 수집·키 검증 공통)

서버 기본값에 의존하지 않으므로 XML 오반환 여지가 없습니다. XML 지원은 필요 없어 보입니다.

### 3. 응답 메타 `lastBuildDate` — 반영됨 (2026-11-24)

수집 결과에 `lastBuildDate`를 담아 탭별(fetch_key)로 보관하고, 탭 툴팁에
`네이버 생성 2026.11.24 09:00` 형태로 표시합니다. 탭 하단 상태 문구는 기존 형식을 유지합니다.

### 4. `originallink` — 반영됨 (2026-11-24)

문서:

- `link`: 네이버 뉴스 URL (없으면 원문)
- `originallink`: 원문 URL

앱:

- `news.originallink` 컬럼 추가 (신규 DB 반영 + 기존 DB 마이그레이션)
- 수집·upsert·조회·클라우드 병합·CSV/Markdown 내보내기에 원문 링크 포함
- 기사 우클릭 **원문으로 열기**, 아카이브 검색 **원문 열기** 지원 (원문이 없거나 같으면 안내)

### 5. 하루 호출 한도 25,000회 — 반영됨 (2026-11-24)

문서:

> 검색 API 하루 호출 한도 25,000회

앱 (`core/api_quota.py`):

- 실제 HTTP 요청마다 날짜별 호출 건수 기록·영속화(`api_quota.json`), 자정 롤오버
- 한도 도달 시 수집 사전 차단 + 자정 이후 안내, 80% 도달 시 1회 경고
- `설정 → 일반 → API 키` 영역에 `오늘 API 호출: N / 25,000건 (잔여 M건)` 표시
- 키 검증 호출도 한도에 포함해 기록한다

### 6. 오류 코드(SE01~SE06, SE99) — 반영됨 (2026-11-24)

`parse_naver_api_error`가 `errorCode`/`errorMessage`를 읽고,
`NAVER_SEARCH_ERROR_HINTS`/`naver_error_hint()`가 코드별 한글 원인 안내를 붙입니다.
`format_naver_http_error`는 400/404에서 해당 안내를 표시합니다.

현재 고정 파라미터(`display=100`, `start` 클램프, `sort=date`) 때문에 SE02/SE03/SE04는 거의 안 나겠지만,
발생 시에도 일반 HTTP 오류 문구만이 아닌 구체적 조치가 보입니다.

### 7. `display` 사용자 설정 — 없음 (의도적일 가능성 큼)

문서 범위 1~100 중 앱은 항상 100.  
효율 측면에서는 합리적이나, “한 번에 더 적게 받기” 같은 옵션은 없습니다.

---

## 의도적으로 문서 기본값과 다른 점

| 항목 | 문서 기본 | 앱 | 평가 |
|------|-----------|-----|------|
| `sort` | `sim` | `date` | 뉴스 최신 수집에 적합, 의도적 선택으로 보임 |
| `display` | `10` | `100` | 상한 활용, 합리적 |
| `format` | `json` | `json` 명시 (2026-11-24) | 해소됨 |

---

## 문서 오류 코드 참고 (앱 전용 매핑 없음)

| HTTP | 코드 | 메시지 (요약) | 설명 |
|------|------|---------------|------|
| 400 | `SE01` | Incorrect query request | URL/파라미터 오류 |
| 400 | `SE02` | Invalid display value | `display` 범위 |
| 400 | `SE03` | Invalid start value | `start` 범위 |
| 400 | `SE04` | Invalid sort value | `sort` 오타 |
| 404 | `SE05` | Invalid search api | API URL 오타 |
| 400 | `SE06` | Malformed encoding | 검색어 UTF-8 |
| 500 | `SE99` | System Error | 서버 내부 오류 |

Gateway 공통 오류(401/403 등)는 `format_naver_http_error`에서 auth 안내를 붙입니다.

---

## 우선순위 제안

| 우선순위 | 항목 | 이유 |
|----------|------|------|
| 낮음 | `display` 사용자 설정 | 문서 범위 1~100 중 항상 100. 효율상 합리적이라 유지 |
| 매우 낮음 | `lastBuildDate` 영속화 | 현재는 메모리 보관 + 툴팁 표시. 재시작 후에도 보려면 설정/DB 저장이 필요 |

---

## 한 줄 정리

이 프로그램은 **NAVER API HUB 뉴스 검색의 필수 계약(URL, 인증 헤더, query/display/start, item 필드, total 기반 페이지네이션, 오류 파싱)을 이미 충실히 반영**하고 있습니다.
2026-11-24 후속 반영으로 **정렬 선택(`sort`)**, **원문 링크 보존(`originallink`)**,
**일일 호출 한도 관리(사전 카운터·차단·경고)**, **오류 코드별 한글 안내(SE01~SE99)**,
**`lastBuildDate` 툴팁 표시**까지 해소했습니다.
남은 선택 항목은 **`display` 사용자 설정**과 **`lastBuildDate` 영속화** 정도입니다.

---

## 관련 코드 경로

| 역할 | 경로 |
|------|------|
| API HUB 상수/헤더/오류 파싱 | `core/naver_api.py` |
| 실제 뉴스 fetch | `core/workers_support/api_worker.py` |
| 더 불러오기 start/total | `ui/main_window_fetch_support/worker_flow_support/` |
| 설정 API 키 검증 | `ui/_settings_dialog_tasks.py` |
| 테스트 | `tests/test_naver_api_hub.py` |
