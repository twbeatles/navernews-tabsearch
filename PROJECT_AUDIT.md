# Project Audit

- 감사일: 2026-10-22, 후속 수정 완료일: 2026-10-23 (Asia/Seoul)
- 감사 기준: `main`, commit `455436c`, 버전 `32.11.3`
- 후속 반영: 버전 `32.11.4` (2026-10-23). 안정성 수정·문서·회귀 테스트를 포함한다.
- 사용자 승인 범위: 감사 보고서 작성 후, 보고서에서 제안한 개선 및 수정 전체를 적용하도록 후속 요청받았다.
- 사용자 선호: Spec Kit은 명시적 요청이 있을 때만 사용한다. `.specify`/`specs`는 변경하지 않았다.

## 1. Executive Summary

**감사에서 확인한 주요 이슈 3건과 구현 보완 4건을 수정했고, 추정으로 남긴 tombstone 운영 경계는 문서화했다.** 감사 당시 전체 위험도는 Medium이었다. 현재 작업 트리는 핵심 회귀 테스트와 실제 Windows ARM64 패키징·부팅 검사로 수정 결과를 확인했다. Windows x64/Python 3.14 릴리스 환경과 실제 외부 서비스까지 검증한 것은 아니다.

| 항목 | 현재 상태 | 조치 |
|---|---|---|
| ISSUE-001 종료 중 클라우드 워커 누락 | Fixed | 공통 종료 계약, native thread 종료 확인, 대기 중 close 보류, 늦은 callback/새 작업 차단 |
| ISSUE-002 공유 기사 중복 플래그 불일치 | Fixed | writer 예약 후 모든 소속 범위의 이전/새 제목 그룹을 같은 transaction에서 갱신 |
| ISSUE-003 다른 볼륨의 업데이트 실패 | Fixed | 종료 전 실행 파일 옆에 복사·fsync·해시 검증 후 같은 디렉터리 rename swap |
| GAP-001 선택 의존성 부재 시 테스트 실패 | Fixed | 실행 중 UI import에도 명시적 skip |
| GAP-002 가상환경까지 인코딩 검사 | Fixed | 환경·cache 디렉터리 탐색 제외 및 앱 파일 검사 유지 |
| GAP-003 import만 확인하던 업데이트 smoke | Fixed | core import 전에 임시 runtime 격리, 실제 UI/DB/이벤트 루프 기동 |
| GAP-004 JSON 전체 메모리 적재 | Fixed | batch 순차 출력, 취소 시 기존 파일 보존 및 iterator/핸들 정리 |
| GAP-005 장기 오프라인 PC와 삭제 기록 만료 | Documented | 보존 기간의 절충과 영구 보존 선택을 README에 설명. 정책은 유지 |

기사 원본의 손상·유실은 최초 감사나 후속 검증에서 재현되지 않았다. 중복 표시 복구는 기사·북마크·메모를 보존한다. 자동 업데이트 실패 시 이전 exe 복원과 helper의 재실행 경로를 보완했다. 물리적 전원 차단이나 실제 공유 드라이브 장애에서의 무손실을 보증한다는 의미는 아니다.

## 2. Project Understanding

Windows용 PySide6 뉴스 모니터링 앱이다. NAVER API HUB의 키워드 검색 결과를 SQLite에 저장하며, 탭·필터·읽음·북마크·메모·태그·자동화·아카이브 검색·내보내기·백업·공유 폴더 동기화를 제공한다.

| 영역 | 주요 위치 |
|---|---|
| 진입점/부팅 | `news_scraper_pro.py`, `core/bootstrap.py` |
| 메인 UI | `ui/main_window.py`와 기능별 mixin |
| API | `core/naver_api.py`, `core/workers_support/api_worker.py` |
| DB | `core/database.py`, schema/query/mutation/cloud mixin |
| 목록/기사 액션 | `ui/news_tab_support/` |
| 설정·내보내기 | `core/config_store_support/`, `ui/main_window_io_support/` |
| 백업·동기화 | `core/backup_support/`, `core/cloud_sync_support/`, `core/db_cloud_sync_support/` |
| 업데이트/기동 검사 | `core/update_manifest.py`, `core/update_installer.py`, `core/runtime_smoke.py` |

`news`는 link별 전역 기사와 사용자 상태를 보관하고, `news_keywords`는 query key별 소속 및 중복 플래그를 보관한다. canonical fetch key가 검색 범위의 기준이다. 설정은 JSON, 기본 데이터 위치는 `%LOCALAPPDATA%\NaverNewsScraperPro`다. 로컬 백업은 디렉터리, 클라우드 교환은 ZIP 스냅샷이다.

핵심 흐름:

1. `검색어 → positive keyword/API 키/유지보수/cooldown 검사 → ApiWorker → API HUB → transaction upsert → 자동화·커서·목록·badge·알림`.
2. `필터 → query scope → DBWorker.fetch/count → request ID 검사 → 캐시 → QTextBrowser`.
3. `기사 액션 → 유지보수 guard → DB 저장 성공 확인 → 로컬·다른 탭 상태 및 badge 갱신`.
4. `동기화 요청 → 경로·작업 충돌 검사 → maintenance → snapshot 검증/DB merge → 완료 → UI 갱신`.
5. `완전 종료 → 생산 타이머 정지/API 취소 → 공통 worker 종료 확인 → 미완료면 close 보류 → 탭 정리/config 저장/DB close/app quit`.
6. `업데이트 → 서명·만료·버전·크기 검증 → download hash → 대상 디렉터리 사전 준비 → helper/부모 종료 대기 → rename swap → 격리된 실제 부팅 smoke → 재실행/rollback`.

외부 의존성은 PySide6, requests, charset-normalizer, cryptography다. 배포는 PyInstaller onefile이며 기준 CI는 Windows x64/Python 3.14다.

## 3. Audit Coverage & Limitations

### 분석 방법

README/CLAUDE/AGENTS, 의존성·pytest·pyright·빌드·CI 파일과 핵심 런타임 코드를 확인했다. 최초 감사에서 `.codegraph/`를 확인하고 CodeGraph MCP를 먼저 사용했다. MCP `Transport closed` 이후에는 `codegraph explore` CLI로 계속 분석했다. 이번 구현에서도 MCP 연결 실패 후 CLI를 우선 사용하고, 잘린 source나 비인덱스 문서만 직접 읽기로 보완했다.

CodeGraph로 확인한 주요 관계:

- `ApiWorker.run → upsert_news_detailed → scope별 중복 재계산`.
- `_run_cloud_sync_once → maintenance → IterativeJobWorker → snapshot/merge_cloud_snapshot_db`.
- `closeEvent/real_quit → _perform_real_close → worker cleanup/DatabaseManager.close`.
- `_on_update_downloaded → launch_update_helper → apply_staged_update`.
- settings data task → 수동 중복 복구 → 부모 maintenance 종료 및 목록 갱신.

그래프는 동적 dispatch를 완전히 증명하지 않는다. source의 실제 caller와 테스트로 보완했으며, 존재하지 않는 파일명 질의는 분석 완료로 계산하지 않았다.

### 실행한 검증

- 최초 감사 baseline: UI 환경에서 480 passed, 1 failed, 1 skipped. 실패는 `.venv` 외부 패키지를 포함한 인코딩 검사였다.
- 수정 후 전체 테스트: **499 passed, 1 skipped, 14 subtests passed**, 실패 0 (40.36초). 원래 실패하던 인코딩 검사와 새 회귀를 포함한다. 보고서 작성 후 문서/인코딩/spec 회귀도 **5 passed**였다.
- 종료 대기 중 업데이트 알림/새 검사를 차단한 마지막 보완 후 관련 종료·업데이트·실제 cloud E2E 회귀는 **27 passed**였고, 타입 검사도 다시 **0 errors**였다.
- 선택 UI 의존성이 없는 Python 3.11.9 ARM64 환경: **134 passed, 50 skipped, 9 subtests passed**, 실패 0. 이후 추가한 인코딩 범위 fixture는 별도 실행으로 확인했다.
- 타입 검사: 설치된 pyright JS CLI와 `.venv` interpreter를 지정한 실행에서 **0 errors, 0 warnings**.
- `.venv`에는 pytest가 없어 기존 Python 3.11의 pytest를 `PYTHONPATH`로 사용했다. 외부 plugin 자동 로딩은 비활성화했다. dependency는 새로 설치하지 않았다.
- 로컬 실행·빌드 환경: Windows ARM64, Python **3.15.1**, PySide6 **6.12.0**, cryptography **46.0.3**, PyInstaller **6.22.3**.
- source `news_scraper_pro.py --smoke`: 성공. 상속된 runtime 경로의 sentinel 파일이 변경되지 않는 테스트 포함.
- PyInstaller 빌드: `.pytest_tmp/audit-build`, `.pytest_tmp/audit-dist` 사용, 성공. 해당 onefile exe의 `--smoke`는 **exit 0**.
- cloud export/import/full 세 모드: subprocess에서 실제 MainApp/QThread와 임시 snapshot·SQLite를 사용하여 I/O 또는 merge transaction 중 종료 요청. 작업 종료 전 DB close 차단, 종료 후 `integrity_check=ok`, snapshot manifest 검증 통과.
- 10만 건 JSON 출력: **106,677,875 bytes**, tracemalloc peak **1,443,150 bytes**, **3.98초**. 본문 1,024자 수준의 합성 데이터이며 실제 DB 전체를 읽는 성능 측정은 아니다.
- cross-volume은 서로 다른 디렉터리 간 rename에 EXDEV를 주입하여 검증했다. 디스크 부족·권한 오류, smoke 실패 및 rollback 결과 기록/재실행도 fixture로 검증했다.

### 한계

- 실제 NAVER API 키, GitHub 배포 다운로드, OneDrive/Dropbox/NAS 서비스, 물리적 다중 볼륨 및 전원 차단은 미검증이다. live API smoke는 opt-in 미설정으로 skip했다.
- Windows x64/Python 3.14 pinned 환경의 GitHub Actions는 실행하지 않았다. source/frozen smoke와 optional dependency 없는 테스트 job을 CI에 추가했지만 원격 통과를 주장하지 않는다.
- Linux/macOS는 README에서 지원 대상으로 약속하지 않는다. 경로 함수의 존재만으로 전체 플랫폼 지원을 판정하지 않았다.
- 실제 사용자 DB·설정은 읽거나 변경하지 않았다. 최초 감사의 합성 실험 1회에서 기본 runtime 로그에 진단 기록이 추가된 부수 효과가 있었으며, 후속 실험과 구현 검증은 로그까지 임시 경로로 격리했다.

## 4. High-Risk Issues

현재 재현된 미해결 High/Critical 이슈는 없다. 아래는 최초 감사에서 확인한 세 이슈와 현재 수정 근거다. Fixed는 구현 및 명시된 테스트 범위의 검증 완료를 의미한다.

### [ISSUE-001] 일반 종료에서 클라우드 동기화 워커 누락 — Fixed

- **위치:** `ui/_main_window_tray.py::_perform_real_close`, `core/workers_support/lifecycle.py::request_background_shutdown`, UI cloud callback.
- **최초 우선순위/신뢰도:** High / Likely. 정리 누락은 확인했으나 실제 DB 손상은 재현하지 않았다.
- **문제·조건·영향:** 동기화 중 완전 종료가 worker를 기다리지 않아 DB close/부모 파괴와 충돌할 수 있었다.
- **반증 확인:** maintenance는 종료를 막지 않았고, result/settled 신호 및 deleteLater는 native thread 종료를 보장하지 않았다. SQLite transaction은 물리 손상 위험 일부를 낮추므로 원본 유실로 과장하지 않았다.
- **호출/영향 범위:** 일반/트레이/시스템 종료 → cloud·export/import·FTS·API·자식 대화상자 작업 및 분리 보관된 worker.
- **수정:** 공통 helper로 interruption 요청 및 한정 시간 wait. 작업이 남으면 event.ignore 후 이벤트 루프를 유지하며 재시도한다. 타이머와 새 fetch/cloud cycle을 막고 늦은 cloud 완료 callback도 차단한다. native thread가 끝나야 DB를 닫는다.
- **회귀:** fake worker의 timeout/재시도, 실제 QThread barrier, 실제 cloud export/import/full 중 종료 subprocess 및 재실행 DB 무결성 검사 통과.

### [ISSUE-002] 공유 기사 제목 변경 시 다른 범위 중복 플래그 미갱신 — Fixed

- **위치:** `core/db_mutations_support/news_upsert.py::upsert_news_detailed`.
- **최초 우선순위/신뢰도:** Medium / Confirmed.
- **문제·조건·영향:** A의 L1/L2가 같은 제목인 상태에서 B가 공유 L1의 제목을 바꾸면 A의 duplicate=[1,1]이 남았다. 숨김 조회가 0건이었고 수동 복구 후 2건이 되어 오류를 재현했다. count/export에도 같은 파생 상태가 영향을 줬다.
- **반증 확인:** 기존 transaction은 계산 범위 누락을 해결하지 않았고 UI reload는 낡은 플래그를 읽었다. 전체 DB 재계산은 매 fetch/startup에 실행되지 않는다.
- **호출/영향 범위:** API upsert → 전역 news.title_hash → 모든 news_keywords 소속 → fetch/count/내보내기.
- **수정:** 변경 전 writer 예약과 모든 소속 범위 수집, 이전/새 hash 그룹을 같은 transaction에서 범위 한정 재계산한다. 동일 payload 재저장에는 불필요한 재계산을 하지 않는다. 기존 파생 값은 설정의 수동 복구 도구로 복원할 수 있다.
- **회귀:** 제목이 달라지거나 같아지는 경우, B 첫 소속과 동시에 제목 변경, 영향 없는 C 유지, 재계산 실패 시 title/membership rollback, 수동 복구의 기사·북마크·메모 보존 통과.

### [ISSUE-003] 다른 볼륨에 설치된 실행 파일 업데이트 실패 — Fixed

- **위치:** `core/update_installer.py::prepare_target_update`, `launch_update_helper`, `apply_staged_update`.
- **최초 우선순위/신뢰도:** Medium / Likely. 오류 주입으로 실패를 확인했으며 실제 두 물리 볼륨은 미검증이다.
- **문제·조건·영향:** DATA_DIR staging과 실행 파일의 드라이브가 다르면 os.replace가 실패했다. 기존 exe는 rollback되지만 재실행되지 않았다.
- **반증 확인:** 경로·해시 검사는 있었으나 볼륨을 맞추는 복사가 없었다. 같은 디렉터리의 backup/rollback은 기존 exe를 보존했으므로 데이터 파괴로 분류하지 않았다.
- **호출/영향 범위:** 업데이트 설치 UI → 사전 준비 → helper → rename swap/smoke/재실행.
- **수정:** 앱 종료 전에 실행 파일 옆의 독점 생성 파일로 복사·fsync·재검증한다. 대상 옆 파일끼리 rename하며, 실패 시 원본을 보존한다. smoke 실패의 성공한 rollback은 별도 예외 타입으로 구분하고 결과를 기록한 뒤 이전 앱을 다시 실행한다. 잔여 다운로드 정리 실패는 이미 시작한 설치를 실패로 바꾸지 않는다.
- **회귀:** cross-directory EXDEV 차단 fixture에서 성공, permission/ENOSPC 실패 전 원본 및 다운로드 보존, hash/rename/smoke/rollback, 실패 결과 기록 후 재실행 통과. 실제 onefile startup smoke도 성공.

## 5. Potential Functional Gaps

| 항목 | 최초 판단 | 현재 상태 및 검증 |
|---|---|---|
| GAP-001 테스트 본문 import의 optional dependency 실패 | Confirmed Gap | UI/crypto importorskip 추가. UI 없는 환경에서 실패 0 확인 |
| GAP-002 환경 파일 인코딩 오탐 | Confirmed Gap | os.walk 단계에서 환경·cache 탐색 제외. 외부 invalid UTF-8은 제외하고 앱 invalid UTF-8 fixture는 검사 대상으로 유지 |
| GAP-003 UI/DB 부팅을 검사하지 않는 smoke | Confirmed Gap | import 전 runtime 격리 후 실제 기동. MainApp 초기화 실패가 비정상 종료로 탐지됨 |
| GAP-004 대규모 JSON 메모리 사용 | Likely Gap | 순차 출력으로 보완. 2천 건 메모리 회귀 및 10만 건 계측, 취소 시 기존 파일/iterator 보존 확인 |
| GAP-005 보존 기간보다 긴 오프라인 PC | 추정 | 데이터 정책을 바꾸지 않고 README에 재등장 가능성과 영구 보존 선택을 설명. 실제 업체 동기화 재현은 하지 않음 |

API HUB timeout/retry/redirect 차단, DB 오류 전파, 원자적 설정/CSV/Markdown 저장, tombstone 보존 0의 의미, backup containment와 rollback 등 기존 보호 장치는 유지했다. 이번 수정을 위해 의도된 FTS 정책을 바꾸거나 전체 DB 재계산을 일반 fetch에 추가하지 않았다.

## 6. Documentation Mismatches

확인한 문서 불일치는 다음과 같이 조치했다.

- README 로컬 자동 백업의 ZIP 설명을 실제 디렉터리 형식으로 수정하고 cloud ZIP과 구별했다.
- Date Filter로 API 수집 한계를 늘릴 수 있다는 안내를 제거했다. 저장된 기사 조회 필터임을 명시했다.
- 업데이트 rollback·실제 기동 검사·다른 드라이브 설치를 현재 구현에 맞췄다. 전원 중단으로 원래 exe가 없을 때 바로가기만으로 복구되지 않는 조건과 백업 수동 복구도 설명했다.
- CLAUDE/AGENTS의 optional dependency skip 계약은 테스트 본문에도 적용되도록 구현을 보완했다.
- `docs/runtime_contracts.md`에 worker 종료와 전역 기사/검색 범위 파생 상태, 업데이트·출력 및 플랫폼별 검증 계약을 정리했다.
- 사용자 요청에 따라 AGENTS/CLAUDE에 Spec Kit 명시적 opt-in 선호를 기록했다. Spec Kit 기능 문서는 갱신하지 않았다.

이번 감사 범위에서 추가로 확인한 미조치 문서 불일치는 없다. 실서비스·x64 검증 한계는 위에 별도로 명시했다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

- [x] 일반 종료의 cloud 및 DB 관련 worker 수명 보호.
- [x] 공유 기사 제목 변경의 모든 영향 범위 중복 플래그 갱신.
- [x] 오류 재현·rollback·종료 경합 회귀 추가.
- [x] 기존 파생 상태의 비파괴 수동 복구 도구 제공.

### Phase 2 — Stability

- [x] 대상 디렉터리 업데이트 준비 및 권한/공간 오류 처리, rollback 재실행.
- [x] optional dependency skip와 인코딩 검사 범위 수정.
- [x] 사용자 runtime을 분리한 실제 source/frozen startup smoke.
- [x] cloud 종료·메모리·취소·업데이트 fault injection 회귀와 CI 연결.
- [x] 사용자 안내 정정.

### Phase 3 — Structural

- [x] API 외 작업 및 분리 worker도 포함한 공통 종료 계약 적용.
- [x] 전역 기사와 검색 범위의 파생 상태 계약 문서화 및 테스트.
- [x] JSON 순차 출력과 대용량 계측.
- [x] Windows ARM64 로컬 검증과 Windows x64 릴리스 CI를 분리하여 기록.

다음 릴리스에서는 GitHub Actions의 x64 결과를 확인하고 필요 시 실제 두 볼륨 및 운영 클라우드 폴더 smoke를 수행하는 것이 좋다. 이는 로컬에서 이미 실행한 검사로 기재하지 않았다.

## 8. Test Recommendations

| 영역 | 입력/기대 결과 | 현재 검증 |
|---|---|---|
| Unit/DB | 공유 제목 변경·첫 membership·다른 범위·실패 rollback | 새 `test_shared_title_updates.py` 및 기존 DB tests 통과 |
| 상태/복구 | 수동 플래그 복구 후 기사/북마크/메모 보존 | 새 audit stability regression 통과 |
| API 오류 | 200/빈 결과/JSON/401/403/429/5xx/timeout/redirect/DB failure | 기존 API worker·HTTP policy·취소 tests 유지 및 전체 실행 포함. live API는 skip |
| Concurrency/E2E | 실제 cloud I/O/merge 중 종료 → 작업 종료 전 DB close 금지, 재개 DB 무결성 | export/import/full subprocess 3개 통과 |
| 업데이트 | 볼륨 오류·공간/권한 부족·smoke 실패·rollback 결과/재실행 | fixture fault injection과 기존 updater regressions 통과 |
| smoke | 상속된 사용자 경로 무시, UI 초기화 실패 탐지, 실제 onefile 기동 | source subprocess 및 로컬 ARM64 exe 통과 |
| 출력 | batch별 메모리 제한, 중간 취소, 기존 파일 유지, iterator 종료 | JSON 회귀 및 10만 건 계측 완료 |
| 인코딩/선택 의존성 | 외부 환경 제외, 앱 손상은 탐지, UI 미설치 skip | fixture 및 Python 3.11 축소 환경 실행 완료 |
| cloud/backup | invalid snapshot 격리, idempotency, merge/restore rollback, 안전 경로 | 기존 tests 전체 실행 포함 |
| 릴리스 플랫폼 | x64/Python 3.14 pinned source/frozen startup, 선택 의존성 없는 core job | CI 구성 추가. 원격 실행 결과는 미확인 |
| 실환경 | 실제 API 키·동기화 업체·두 물리 볼륨·전원 중단 | 미실행. 배포 전 운영 검증 대상으로 유지 |

## 9. Final Assessment

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Good | 재현된 파생 플래그 오류 수정 및 경계/rollback 회귀 통과 |
| Runtime Stability | Acceptable | 실제 cloud 작업 중 종료 및 source/frozen 부팅 성공. 운영 장애 환경은 미검증 |
| Data Integrity | Good | transaction 유지, 비파괴 수동 복구, 작업 종료 전 DB close 금지 및 무결성 검사 |
| Error Resilience | Good | 업데이트·취소·공간/권한 오류와 rollback 경계 검증 |
| Cross-platform Robustness | Acceptable | Windows ARM64 로컬 성공, Windows x64 CI 추가. Linux/macOS 지원 확장 없음 |
| Test Confidence | Acceptable | 전체 회귀·타입·onefile smoke 및 대용량 계측. 실서비스와 x64 원격 결과는 미확인 |

최초 우선 수정 대상인 **클라우드 종료 처리, 공유 기사 중복 플래그, 다른 볼륨 업데이트**는 모두 현재 작업 트리에 반영했다. 기존 DB의 잘못된 중복 표시는 필요 시 설정의 복구 도구로 처리하며, 실제 사용자 DB에 복구 작업을 임의 실행하지 않았다.
