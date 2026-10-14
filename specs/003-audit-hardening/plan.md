# Implementation Plan: 감사 후속 안정성 강화

**Branch**: `main` | **Date**: 2026-08-23 | **Spec**: [spec.md](spec.md)

## Summary

`PROJECT_AUDIT.md`에서 반증되지 않은 런타임 위험과 기능 갭을 해소한다. 스냅샷 검증 실패와 일시적 병합 실패를 타입으로 분리하고 복구 가능한 격리 관리 API/UI를 제공한다. DB 유지보수는 worker가 실제 종료된 경우에만 시작한다. CSV export는 spreadsheet formula를 중화하고, import는 한 기사 단위 transaction과 구조화된 부분 결과를 사용한다. 의존성 계약, 문서 경로, 자동 검증을 현재 구현과 일치시킨다.

## Technical Context

**Language/Version**: Python 3.14 (release CI 기준, Windows x64)

**Primary Dependencies**: PySide6, requests, cryptography, charset-normalizer, PyInstaller

**Storage**: 로컬 SQLite `news_database.db`, JSON 설정 `news_scraper_config.json`, cloud ZIP snapshots

**Testing**: pytest, pyright, PyInstaller smoke/import checks

**Target Platform**: Windows 10/11 desktop

**Project Type**: 단일 PySide6 desktop application

**Performance Goals**: CSV chunking, cloud sync 최대 20개 import/cycle, UI thread 비차단 유지

**Constraints**: public facade/import 및 worker payload 호환성, 사용자 DB에 파괴적 migration 없음, note 10,000자 제한과 snapshot path/size 검증 유지

**Scale/Scope**: cloud sync, fetch lifecycle, CSV IO, dependency/release configuration, documentation과 관련 테스트

## Constitution Check

`.specify/memory/constitution.md`는 미작성 템플릿이므로 강제 gate가 없다. 저장소 가이드의 gate는 모두 통과한다: facade import, API HUB/canonical query/FTS 정책, DB 오류 타입, note 제한, backup containment를 유지하며 테스트·문서·버전을 함께 갱신한다. Phase 1 설계 후 재검토 결과도 동일하다.

## Project Structure

### Documentation (this feature)

```text
specs/003-audit-hardening/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/runtime-hardening.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
core/
├── cloud_sync_support/{models,snapshot_io,import_flow}.py
├── db_mutations_support/article_state.py
├── workers_support/jobs.py
└── constants.py
ui/
├── main_window_fetch_support/worker_flow_support/completion.py
├── main_window_support/base_support/maintenance.py
├── main_window_io_support/{cloud,exports,data_io}.py
└── settings cloud-sync content modules
tests/
├── test_cloud_sync.py
├── test_maintenance_mode.py
├── test_csv_import_export_hardening.py
└── test_dependency_contract.py
```

**Structure Decision**: 기존 facade/mixin 구조 안에서 책임을 확장한다. 새 최상위 package는 만들지 않고 구조화된 결과/오류 타입만 core에 둔다.

## Design Decisions

1. `CloudSnapshotValidationError`만 자동 격리한다. DB lock, permission, disk, cancellation 및 알 수 없는 병합 오류는 원본을 보존하고 retryable error로 반환한다.
2. 격리 항목은 sidecar JSON metadata에 원래 이름·이유·시각을 기록한다. 목록, 재검증, 복구, 삭제는 cloud root containment를 다시 검사한다.
3. 기존 `cleanup_worker() -> bool`은 호환성을 위해 유지하되 유지보수 경로는 구조화된 outcome을 사용한다. `detached_running`은 maintenance 성공 조건이 아니다.
4. CSV 셀은 선행 공백/제어문자 뒤의 `=`, `+`, `-`, `@`를 검사하고 apostrophe를 붙인다. JSON/Markdown export는 변경하지 않는다.
5. CSV import는 기사 한 건의 bookmark/note 변경을 하나의 DB transaction으로 묶고 구조화된 합계를 progress와 최종 결과로 전달한다.
6. release workflow는 repository dependency contract를 설치하며 QtNetwork/entrypoint import smoke를 실행한다.

## Complexity Tracking

강제 constitution 위반 없음.
