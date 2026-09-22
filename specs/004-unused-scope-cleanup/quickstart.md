# Quickstart: Unused Search Scope Cleanup

## 전제

- `python -m pytest tests/test_scope_cleanup.py -q` 가 통과하는 상태.
- 데스크톱 앱 실행 가능 환경 (PyQt6).

## 검증 시나리오

1. **죽은 범위 누적 확인**: 탭 A(키워드 `AI`)를 열어 기사를 수집한다. 탭 B(키워드 `반도체`)를 열었다가 닫는다. 통계 화면의 저장소 지표에서 "검색 범위 수"가 2, "사용하지 않는 범위"가 1인지 확인한다.
2. **미리보기**: "사용하지 않는 범위 정리" 버튼을 누른다. 대상에 `반도체` 범위가 표시되고 예상 삭제 건수와 고아 예상 건수가 표시되는지 확인한다.
3. **정리 실행**: 확정을 누른다. 결과에 삭제·잔여·고아 실측이 표시되는지 확인한다. 탭 A의 기사 목록(구성·읽음·북마크)이 전후 동일하고, 통계의 전체 기사 수는 변하지 않는지 확인한다.
4. **재실행**: 정리를 한 번 더 실행한다. 삭제 0건의 보고가 나오는지 확인한다.
5. **거부 경로**: 수집 실행 중에 정리를 시도해 안내와 함께 거부되는지 확인한다. 키워드 탭을 모두 닫고(보관 탭만 남기고) 정리를 시도해 거부되는지 확인한다.

## 실행 명령

```bash
python -m pytest tests/test_scope_cleanup.py -q
python -m pyright core/db_mutations_support/scope_cleanup.py tests/test_scope_cleanup.py
```
