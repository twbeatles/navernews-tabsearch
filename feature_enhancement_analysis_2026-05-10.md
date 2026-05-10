# 기능 고도화 및 추가 기능 제안 분석 (2026-05-10)

## 작성 기준

- 참고 문서: `README.md`, `claude.md`, `project_structure_analysis.md`, `update_history.md`, `implementation_functional_risk_review_2026-05-10.md`
- 참고 코드 영역: `core/`, `ui/`, `tests/`
- 전제: 현재 앱은 네이버 뉴스 검색 API 기반의 PyQt6 데스크톱 앱이며, 탭별 검색/저장 검색/태그/출처 필터/CSV/백업/복원/분석/알림/트레이/FTS 백필까지 이미 상당히 안정화되어 있다.
- 목표: 새 기능을 단순히 많이 나열하기보다, 현재 구조에 자연스럽게 들어가고 테스트 가능한 기능을 우선 제안한다.

## 요약

현재 프로젝트는 기능 수 자체보다도 "탭별 검색 의미 정합성", "로컬 데이터 안전성", "비동기 UI 안정성", "설정/백업/복원" 쪽 완성도가 높다. 따라서 다음 단계의 기능 고도화는 완전히 새로운 큰 영역을 붙이는 것보다, 이미 있는 `태그`, `저장 검색`, `FTS`, `출처 필터`, `통계`, `알림`, `CSV snapshot export`를 더 강하게 연결하는 방향이 가장 효율적이다.

우선순위가 높은 후보는 다음 6개다.

1. 규칙 기반 자동 분류/자동 액션
2. 전역 보관함 검색 및 빠른 필터 탐색
3. 태그 관리 고도화와 일괄 태깅
4. 우선순위/읽기 큐 중심의 "오늘 볼 기사" 화면
5. 트렌드/기간 분석 대시보드 확장
6. 정기 리포트/다이제스트 내보내기

반대로 외부 기사 원문 크롤링, 클라우드 동기화, LLM 요약 같은 기능은 매력은 있지만 보안/정책/의존성/키 관리/패키징 부담이 크므로 후순위가 맞다.

## 현재 기능 기반에서 보이는 강점

### 1. 데이터 모델이 확장 친화적이다

현재 DB는 `news`, `news_keywords`, `news_tags` 중심이다. `news_keywords`가 query scope를 분리하고, `news_tags`가 기사별 자유 태그를 제공한다. 여기에 규칙, 우선순위, 읽기 큐, 알림 정책을 붙이기 좋다.

관련 진입점:

- `core/_db_schema.py`
- `core/_db_queries.py`
- `core/_db_mutations.py`
- `core/_db_analytics.py`
- `core/database.py`

### 2. UI facade 분리가 이미 되어 있다

`MainApp`과 `NewsTab`은 facade에 가깝고, 실제 기능은 `ui/main_window_support/`, `ui/news_tab_support/` 아래로 분리되어 있다. 기능을 추가할 때 거대한 단일 파일에 다시 몰아넣지 않고 작은 support module에 붙일 수 있다.

관련 진입점:

- `ui/_main_window_fetch.py`
- `ui/_main_window_analysis.py`
- `ui/_main_window_settings_io.py`
- `ui/news_tab_support/ui_controls.py`
- `ui/news_tab_support/actions.py`
- `ui/news_tab_support/rendering.py`

### 3. FTS와 snapshot export가 이미 있다

SQLite FTS5 백필과 snapshot export가 있으므로, 전역 검색, 다이제스트 생성, 기간별 리포트, 저장 검색 기반 리포트는 비교적 자연스럽다.

관련 진입점:

- `DatabaseManager.is_news_fts_backfill_complete()`
- `DatabaseManager.backfill_news_fts_chunk(...)`
- `DatabaseManager.iter_news_snapshot_batches(...)`
- `ui/_main_window_settings_io.py`의 CSV export 경로

### 4. 보수적인 안정성 정책이 강하다

설정 import/export, pending restore, 백업 검증, 비동기 worker 정리, 유지보수 모드가 이미 촘촘하다. 새 기능도 이 규칙을 따르면 회귀 위험을 낮출 수 있다.

## 우선순위별 기능 제안

## P0. 바로 체감되는 저위험 고도화

### 1. 규칙 기반 자동 분류/자동 액션

#### 제안

사용자가 조건과 액션을 조합해 새 기사 수집 시 자동 처리하도록 한다.

예시:

- 제목/본문에 `삼성`, `반도체`가 모두 있으면 `반도체` 태그 자동 추가
- 특정 출처는 자동 북마크
- 특정 키워드는 자동 읽음 처리 또는 알림 제외
- `regex:<패턴>` 매칭 시 중요 태그 추가
- 저장 검색 조건과 일치하면 지정 태그 부여

#### 왜 지금 구조에 잘 맞는가

이미 다음 기반이 있다.

- 태그 CRUD: `DatabaseManager.set_tags(...)`, `news_tags`
- 알림 키워드 regex 정책
- 출처 차단/선호 normalization
- `ApiWorker`의 `new_items` 분리
- 저장 검색 payload 구조

#### 구현 방향

- 설정 스키마에 `automation_rules` 추가
- rule payload 예시:

```json
{
  "name": "반도체 중요 기사",
  "enabled": true,
  "conditions": {
    "tokens_all": ["삼성", "반도체"],
    "publisher_any": ["naver:oid:001", "example.com"],
    "regex": ""
  },
  "actions": {
    "add_tags": ["반도체", "중요"],
    "bookmark": true,
    "mark_read": false,
    "suppress_notification": false
  }
}
```

- rule matching helper는 `core/automation_rules.py` 같은 새 모듈로 분리
- 실제 적용은 DB upsert 이후, 신규 링크에 대해 후처리하는 방식이 안전하다.
- UI는 초기에는 설정창에 간단한 목록/추가/수정/삭제로 시작한다.

#### 테스트 포인트

- import/load에서 invalid rule 보정
- rule 조건 AND/OR/regex 매칭
- rule action이 기존 태그를 덮어쓰지 않고 병합하는지
- 자동 북마크/읽음 처리 실패 시 fetch 성공 메시지와 분리되는지

#### 위험도

중간. 설정 스키마와 DB mutation을 건드리므로 테스트가 필요하지만, 기존 태그/상태 변경 API를 재사용하면 폭발 범위는 제한적이다.

### 2. 전역 보관함 검색 및 빠른 필터 탐색

#### 제안

현재 탭 중심 검색 외에, 저장된 전체 기사 DB를 대상으로 검색하는 "보관함 검색" 화면을 추가한다.

기능:

- 전체 기사에서 제목/본문/메모/태그/출처 검색
- 날짜, 읽음, 북마크, 태그, 출처 필터
- 결과에서 바로 열기/북마크/태그/메모
- 현재 결과를 CSV로 export

#### 왜 필요할까

앱이 오래 사용될수록 "지금 새로 가져오기"보다 "예전에 저장된 기사 찾기"의 가치가 커진다. 이미 FTS5와 태그, 메모, CSV snapshot export가 있어 사용자 체감 대비 구현 효율이 좋다.

#### 구현 방향

- `core/_db_queries.py`에 `search_archive(...)` 또는 기존 `fetch_news(...)`를 확장하지 않고 별도 전역 조회 API 추가
- 전역 검색은 query_key 없이 `news` 기준으로 조회하되, 태그/출처/날짜/읽음/북마크 조건을 공유 helper로 조립
- UI는 `ArchiveSearchDialog` 또는 메인 탭 옆 고정 "보관함" 탭 방식
- FTS 백필 완료 전에는 기존 LIKE fallback 유지

#### 테스트 포인트

- FTS 완료/미완료에서 결과 의미가 같은지
- 태그/메모/출처/날짜 조건 조합
- pagination limit/offset 결정적 정렬
- 결과 액션 후 기존 열린 탭과 상태 동기화

#### 위험도

낮음~중간. 조회 중심이라 비교적 안전하다. 단, `fetch_news(...)`에 무리하게 끼워 넣지 않고 전역 검색 API를 분리하는 것이 좋다.

### 3. 태그 관리 고도화와 일괄 태깅

#### 제안

현재 기사별 태그 편집과 태그 필터는 있지만, 태그 자체를 관리하는 화면이 있으면 운영성이 크게 좋아진다.

기능:

- 태그 목록/사용 개수 보기
- 태그 이름 변경
- 태그 병합
- 미사용 태그 정리
- 현재 표시 결과 전체에 태그 추가/제거
- 선택 기사 다중 태그 적용

#### 왜 지금 구조에 잘 맞는가

`news_tags`가 이미 독립 테이블이고, `get_top_tags(...)`, `get_known_tags()`도 있다. 기능 추가에 필요한 DB 구조가 대부분 준비되어 있다.

#### 구현 방향

- `DatabaseManager.rename_tag(old, new)`, `merge_tags(source, target)`, `delete_tag(tag)`, `add_tag_to_scope(scope, tag)` 추가
- UI는 설정창 또는 별도 `TagManagerDialog`
- `NewsTab` 카드 선택 기능이 없으면 1차는 "현재 표시 결과 전체" 대상으로 시작

#### 테스트 포인트

- rename/merge 시 case-insensitive 중복 제거
- scope 기반 일괄 태그가 현재 필터/기간/출처 조건을 정확히 따르는지
- CSV export 태그 컬럼과 tag filter 옵션 갱신

#### 위험도

중간. 일괄 변경은 유지보수 모드와 chunked worker를 사용해야 한다.

### 4. "오늘 볼 기사" 우선순위 큐

#### 제안

탭별 목록과 별개로, 사용자가 실제로 읽을 기사를 모아주는 작업 화면을 추가한다.

초기 버전은 단순한 로컬 점수 기반으로 충분하다.

점수 예시:

- 새 기사 +3
- 북마크 +5
- 알림 키워드 매칭 +4
- 선호 출처 +2
- 차단 출처 제외
- 읽음이면 제외 또는 낮은 점수
- 태그가 `중요`면 +3

기능:

- "오늘 볼 기사" 탭
- 우선순위 점수순 정렬
- 읽음/북마크/태그 액션
- "나중에 보기" 또는 "오늘 숨기기"

#### 왜 유용한가

탭이 많아지면 사용자는 어떤 탭을 먼저 봐야 할지 모른다. 이 기능은 앱을 단순 수집기에서 실제 뉴스 작업 도구로 올려준다.

#### 구현 방향

- 1차는 DB schema 변경 없이 조회 시 계산 가능
- 장기적으로는 `news_priority` 또는 `news_user_state` 테이블 고려
- 점수 계산 helper는 `core/news_scoring.py` 등으로 분리
- UI는 `MainApp`에 고정 탭 또는 메뉴 액션으로 추가

#### 테스트 포인트

- 점수 계산 deterministic
- 차단 출처/읽음 상태 반영
- 기사 액션 후 기존 탭/북마크 탭 동기화

#### 위험도

낮음~중간. 1차를 계산형으로 만들면 DB 변경 없이 시작할 수 있다.

## P1. 분석/리포트 중심 고도화

### 5. 트렌드/기간 분석 대시보드 확장

#### 제안

현재 통계/출처/태그 분석을 기간 축으로 확장한다.

기능:

- 일자별 수집 기사 수
- 일자별 새 링크 수
- 출처별 시간 추이
- 태그별 시간 추이
- 키워드/탭별 unread 증가량
- 차단/선호 출처 시뮬레이션 결과를 현재보다 더 시각적으로 표시

#### 구현 방향

- `core/_db_analytics.py`에 `get_daily_counts(...)`, `get_tag_trend(...)`, `get_publisher_trend(...)` 추가
- 시각화는 새 의존성 없이 `QTableWidget` + 간단한 HTML bar로 시작
- 큰 차트 라이브러리는 PyInstaller 부담이 커서 후순위

#### 테스트 포인트

- date bucket 계산
- blocked/preferred/tag/date scope 반영
- DB 조회 실패 시 기존 async analysis error 처리 재사용

#### 위험도

낮음~중간. 조회 중심이라 안전하지만 UI가 커질 수 있으므로 다이얼로그 내부 탭으로 분리하는 것이 좋다.

### 6. 정기 리포트/다이제스트 내보내기

#### 제안

현재 CSV export를 넘어, 사용자가 읽기 쉬운 Markdown/HTML 리포트를 만들 수 있게 한다.

예시:

- 오늘 새 기사 요약 목록
- 저장 검색별 Top N 기사
- 태그별 묶음
- 출처별 묶음
- 미읽음/북마크 중심 리포트

출력 포맷:

- 1차: Markdown `.md`
- 2차: HTML `.html`
- 후순위: PDF

#### 왜 Markdown이 먼저인가

외부 의존성 없이 구현 가능하고, 테스트도 쉽다. HTML은 기존 렌더링 escaping 정책을 재사용할 수 있다. PDF는 렌더링/폰트/패키징 부담이 크다.

#### 구현 방향

- `export_scope_to_csv(...)`와 유사하게 snapshot iterator 기반
- `ui/_main_window_settings_io.py`에 `export_digest_to_markdown(...)` 추가 또는 별도 `ui/exporters.py` 분리
- 저장 검색별 리포트는 `saved_searches` payload를 `DBQueryScope`로 변환하는 helper를 먼저 만든다.

#### 테스트 포인트

- export 중 취소 시 temp file 정리
- Markdown escaping/link formatting
- 저장 검색 scope와 실제 탭 조회 scope 일치

#### 위험도

낮음. CSV export 기반이 이미 좋아서 확장하기 쉽다.

### 7. 출처 지능화: publisher alias / Naver OID 이름 매핑

#### 제안

현재 출처는 URL host 또는 `naver:oid:<id>` 형태로 저장될 수 있다. 여기에 사용자 친화적인 출처 표시명과 alias를 붙인다.

기능:

- `naver:oid:001` 같은 값을 사용자가 `연합뉴스`로 별칭 지정
- `www.example.com`, `m.example.com`, `news.example.com`을 같은 출처 그룹으로 묶기
- 출처별 메모/신뢰도/색상 지정
- 차단/선호 필터 UI에서 alias 표시

#### 구현 방향

- 설정 스키마에 `publisher_aliases` 추가
- 내부 비교값은 기존 normalized publisher를 유지
- 표시 시 alias만 적용
- import/export 포함

#### 테스트 포인트

- alias가 필터 매칭 의미를 바꾸지 않는지
- import 충돌 시 기존/가져온 alias 병합 정책
- CSV export에서 원본 publisher와 표시명 중 무엇을 쓸지 정책 고정

#### 위험도

낮음. 표시 계층 기능으로 시작하면 안전하다.

## P2. 파워 유저 기능

### 8. Command Palette / 빠른 실행

#### 제안

`Ctrl+K` 또는 `Ctrl+Shift+P`로 명령 팔레트를 열어 주요 작업을 빠르게 실행한다.

예시 명령:

- 새 탭 추가
- 저장 검색 적용
- 태그로 필터
- 보관함 검색 열기
- 백업 만들기
- 현재 결과 export
- 설정 열기
- 로그 열기

#### 구현 방향

- `CommandPaletteDialog` 추가
- command registry는 UI action callback과 label/shortcut만 들고 있게 한다.
- 기존 단축키와 충돌하지 않게 README 단축키 표 갱신

#### 위험도

낮음. 기능 자체는 UI wrapper에 가깝다.

### 9. 사용자 프로필/워크스페이스

#### 제안

업무용/개인용/프로젝트별로 탭, 설정, DB를 분리해 사용할 수 있는 프로필 기능.

#### 장점

- 여러 관심사를 한 DB에 섞지 않아도 된다.
- 백업/복원 단위가 명확해진다.
- portable 모드와 잘 맞는다.

#### 구현 방향

- `RuntimePaths`에 profile name을 반영하는 방식 검토
- 실행 중 profile switch는 위험하므로 1차는 시작 시 선택 또는 재시작 필요 방식
- 프로필별 `news_scraper_config.json`, `news_database.db`, `backups/` 분리

#### 위험도

높음. 런타임 경로, 단일 인스턴스, 백업, pending restore가 모두 얽힌다. 충분한 설계 문서가 먼저 필요하다.

### 10. 고급 검색 문법 확장

#### 제안

현재 `키워드 -제외어` 중심 문법을 조금 확장한다.

예시:

- `publisher:연합뉴스`
- `tag:반도체`
- `is:unread`
- `is:bookmarked`
- `after:2026-05-01`
- `before:2026-05-10`

#### 구현 방향

- 기존 `parse_search_query()`에 바로 섞기보다 별도 advanced parser를 둔다.
- 탭 생성용 검색어와 보관함 검색용 문법을 분리하는 것이 안전하다.
- 저장 검색 payload와 연결하면 효과가 크다.

#### 위험도

중간. 검색어 문법은 기존 탭 canonical query 정책과 충돌할 수 있다. 먼저 보관함 검색 화면 한정으로 도입하는 것이 좋다.

## P3. 신중히 검토할 기능

### 11. 외부 기사 원문 스냅샷

#### 매력

기사 원문 일부를 저장하면 나중에 링크가 사라져도 확인할 수 있고, 더 정확한 검색/요약이 가능하다.

#### 리스크

- 외부 사이트 약관/robots/저작권 이슈
- 로그인/쿠키/리다이렉트/차단 대응 부담
- private/local URL 차단 정책 확장 필요
- 저장 용량 급증
- PyInstaller 의존성 증가 가능

#### 권장

기본 기능으로 넣지 말고, 사용자가 명시적으로 켠 경우에만 "본문 가져오기 시도"를 제공하는 정도가 적절하다. 초기에는 기사 본문 전체 저장보다 사용자가 직접 작성하는 메모와 태그를 강화하는 편이 안전하다.

### 12. LLM 요약/분류

#### 매력

기사 요약, 중요도 분류, 중복 클러스터링, 일일 브리핑을 고도화할 수 있다.

#### 리스크

- API 키/비용/개인정보/네트워크 실패 처리
- 결과 품질과 재현성
- 설정 export/import에서 secret 제외 정책 추가 필요
- 테스트에서 외부 API mock 체계 필요

#### 권장

먼저 로컬 deterministic 기능인 규칙 기반 자동 분류, 다이제스트 export, 우선순위 큐를 만든 뒤 선택형 plugin-like 구조로 검토한다.

### 13. 클라우드 동기화

#### 매력

여러 PC에서 탭/읽음/태그/북마크를 공유할 수 있다.

#### 리스크

- 충돌 해결
- 인증
- DB 병합
- 백업/복원과 동시성
- 개인정보/보안

#### 권장

현재는 설정 export/import와 백업 복원을 더 다듬는 편이 낫다. 클라우드 동기화는 별도 제품 수준의 설계가 필요하다.

## 권장 로드맵

### 1단계: 운영 편의 강화

1. 태그 관리 다이얼로그
2. Markdown 다이제스트 export
3. 전역 보관함 검색
4. 출처 alias 표시

이 단계는 대부분 조회/표시/기존 태그 API 확장 중심이라 위험이 낮다.

### 2단계: 자동화와 우선순위

1. 규칙 기반 자동 분류/자동 액션
2. 오늘 볼 기사 우선순위 큐
3. 알림 정책 고도화
4. 저장 검색 기반 리포트

이 단계부터 설정 스키마와 DB mutation을 건드리므로 테스트와 문서 업데이트가 중요하다.

### 3단계: 분석/워크스페이스

1. 기간별 트렌드 분석
2. publisher alias/group 고도화
3. 프로필/워크스페이스
4. 고급 검색 문법

프로필/워크스페이스는 런타임 경로와 백업/복원에 영향이 크므로 가장 늦게 두는 편이 안전하다.

## 기능별 구현 진입점 요약

| 기능 | 핵심 파일 | 테스트 후보 |
|---|---|---|
| 자동 분류/액션 | `core/config_store_impl.py`, `core/_db_mutations.py`, 새 `core/automation_rules.py`, 설정 UI | `tests/test_automation_rules.py`, import/export roundtrip |
| 보관함 검색 | `core/_db_queries.py`, 새 archive dialog, `ui/_main_window_analysis.py` 또는 새 UI module | FTS/LIKE 동등성, pagination, 액션 동기화 |
| 태그 관리 | `core/_db_mutations.py`, `core/_db_analytics.py`, `ui/dialogs.py` 또는 새 dialog | rename/merge/delete, scope 일괄 태그 |
| 오늘 볼 기사 | 새 `core/news_scoring.py`, `core/_db_queries.py`, MainApp 고정 탭 | 점수 계산, visibility 반영, 상태 동기화 |
| 트렌드 분석 | `core/_db_analytics.py`, `ui/_main_window_analysis.py` | date bucket, tag/publisher trend |
| Markdown digest | `ui/_main_window_settings_io.py` 또는 새 `ui/exporters.py` | snapshot export, escaping, cancel cleanup |
| 출처 alias | `core/config_store_impl.py`, `core/content_filters.py`, card render/설정 UI | alias display, import merge, filter 의미 보존 |
| Command Palette | 새 `ui/command_palette.py`, `ui/main_window_support/ui_shell.py` | command registry, shortcut smoke |
| 프로필 | `core/runtime_support/paths.py`, `core/bootstrap.py`, `core/constants.py` | runtime path, single instance, backup path |

## 설계 시 반드시 지켜야 할 원칙

### 1. 조회 scope helper 재사용

새 조회 기능은 기존 `DBQueryScope`, visibility filter, tag filter, text filter 의미와 어긋나면 안 된다. 특히 탭 목록, count, export, 일괄 처리의 범위가 달라지는 문제가 반복적으로 발생하기 쉽다.

### 2. 쓰기 작업은 chunked worker와 유지보수 모드 사용

일괄 태그, 자동 분류 재적용, 대량 상태 변경은 UI thread에서 직접 실행하지 않는다. `IterativeJobWorker`와 유지보수 모드 차단 정책을 따른다.

### 3. 설정 스키마 추가 시 import/export/문서/테스트를 함께 갱신

새 설정 필드는 최소한 다음을 같이 본다.

- `AppSettings` / `DEFAULT_CONFIG`
- `normalize_loaded_config(...)`
- `normalize_import_settings(...)`
- settings export/import payload
- 설정 UI
- README의 데이터/설정 파일 설명
- roundtrip/import normalization 테스트

### 4. 새 의존성은 최대한 피한다

현재 앱은 PyInstaller onefile 배포를 중요하게 본다. 차트, PDF, 원문 파싱, LLM SDK 같은 의존성은 패키징과 보안 표면을 늘린다. 먼저 표준 라이브러리와 PyQt6/SQLite로 가능한 형태를 검토한다.

### 5. 사용자 표시 문자열은 한국어 기준 유지

README와 최근 안정화 포인트에 맞춰 UI/토스트/다이얼로그 문자열은 한국어를 기본으로 한다. 내부 log/PERF key는 영문 유지 가능하다.

## 최종 추천

가장 먼저 구현할 기능은 `태그 관리 고도화`와 `Markdown 다이제스트 export`다. 둘 다 기존 데이터 모델과 export 구조를 활용하므로 리스크가 낮고, 사용자가 즉시 체감할 수 있다.

그 다음은 `전역 보관함 검색`과 `규칙 기반 자동 분류`가 좋다. 전자는 FTS/태그/출처 필터의 가치를 끌어올리고, 후자는 앱을 단순 수집기에서 개인화된 뉴스 워크플로 도구로 확장한다.

장기적으로는 `오늘 볼 기사` 큐와 `트렌드 분석`을 붙이면, 많은 탭과 긴 사용 기간에서 앱의 존재 이유가 더 강해진다. 다만 프로필, 원문 스냅샷, LLM 요약, 클라우드 동기화는 안정성/정책/보안 비용이 크므로 현재 단계에서는 별도 설계 문서를 먼저 만드는 것이 맞다.
