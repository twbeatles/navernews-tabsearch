# Claude AI Assistant Guidelines - 뉴스 스크래퍼 Pro

> 이 문서는 Claude AI를 위한 프로젝트 컨텍스트 및 지침입니다.

---

## 🎯 프로젝트 컨텍스트

**뉴스 스크래퍼 Pro**는 네이버 뉴스 검색 API를 활용한 **PyQt6 기반 데스크톱 애플리케이션**입니다.

### 핵심 기능
- 🔖 **탭 기반 키워드 검색**: 여러 키워드를 독립 탭으로 관리
- ⏰ **자동 새로고침**: 10분~6시간 주기 백그라운드 업데이트
- 📌 **북마크 & 메모**: 중요 기사 영구 저장
- 🖥️ **시스템 트레이 통합**: 최소화/종료 시 트레이 상주
- 🌙 **라이트/다크 테마**: 현대적 UI 디자인

---

## 🛠️ 기술 스택

```yaml
언어: Python 3.8+
GUI: PyQt6 (Qt 6.x)
데이터베이스: SQLite3
HTTP: requests
패키징: PyInstaller
```

---

## 📁 프로젝트 구조

```
navernews-tabsearch/
│
├── news_scraper_pro.py      # 엔트리포인트 + 호환 re-export 레이어
├── core/                    # 코어 로직
│   ├── bootstrap.py         # 앱 부팅(main), 전역 예외 처리, 단일 인스턴스 가드
│   ├── constants.py         # 경로/버전/앱 상수
│   ├── database.py          # DatabaseManager
│   ├── workers.py           # ApiWorker/DBWorker/AsyncJobWorker
│   ├── config_store.py      # 설정 스키마 정규화 + 원자 저장
│   ├── backup.py            # 백업/복원(pending restore)
│   ├── startup.py           # Windows 자동 시작 레지스트리
│   └── ...
├── ui/                      # UI 로직
│   ├── main_window.py       # MainApp
│   ├── settings_dialog.py   # SettingsDialog
│   ├── news_tab.py          # NewsTab
│   ├── dialogs.py           # 보조 다이얼로그
│   ├── styles.py            # Colors/UIConstants/ToastType/AppStyle
│   └── ...
├── tests/                   # 회귀/호환성/안정성 테스트
├── news_scraper_config.json # 사용자 설정
├── news_database.db         # SQLite 데이터베이스
├── news_icon.ico            # 앱 아이콘
├── news_scraper.log         # 로그 파일
├── README.md                # 사용자 문서
└── news_scraper_pro.spec    # PyInstaller 설정
```

---

## 🔍 코드 탐색 가이드

### 주요 클래스 위치

| 클래스명 | 설명 | 위치 |
|----------|------|-------------|
| `Colors` | 테마 색상 상수 | `ui/styles.py` |
| `AppStyle` | QSS 스타일시트 | `ui/styles.py` |
| `UIConstants` | UI 상수 | `ui/styles.py` |
| `ToastQueue` | 알림 시스템 | `ui/toast.py` |
| `NewsBrowser` | 커스텀 브라우저 | `ui/widgets.py` |
| `DatabaseManager` | DB 연결 관리 | `core/database.py` |
| `ApiWorker` | API 호출 워커 | `core/workers.py` |
| `MainApp` | 메인 윈도우 | `ui/main_window.py` |
| `SettingsDialog` | 설정/도움말 다이얼로그 | `ui/settings_dialog.py` |

---

## ⚙️ 설정 구조

### news_scraper_config.json

```json
{
    "app_settings": {
        "client_id": "네이버 API Client ID",
        "client_secret": "네이버 API Client Secret",
        "theme_index": 0,              // 0=라이트, 1=다크
        "refresh_interval_index": 2,   // 콤보박스 인덱스
        "notification_enabled": true,
        "minimize_to_tray": true,
        "close_to_tray": true,
        "api_timeout": 15
    },
    "tabs": ["키워드1", "키워드2"],
    "search_history": []
}
```

---

## 🎨 스타일 가이드라인

### 색상 사용

```python
# ✅ 올바른 사용 (styles.py에서 임포트)
from styles import Colors

# 위젯 적용
widget.setStyleSheet(f"color: {Colors.LIGHT_PRIMARY};")
```

### 토스트 메시지

```python
# 성공 알림
self.toast_queue.add("저장되었습니다", ToastType.SUCCESS)

# 오류 알림
self.toast_queue.add(f"오류: {error}", ToastType.ERROR)

# 정보 알림
self.toast_queue.add("새 기사 10건", ToastType.INFO)

# 경고 알림
self.toast_queue.add("API 키를 확인하세요", ToastType.WARNING)
```

---

## 🔒 스레드 안전성

### DatabaseManager 사용

```python
# ✅ 안전한 DB 접근
with self.db_manager.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM articles WHERE keyword=?", (keyword,))
    results = cursor.fetchall()

# ❌ 직접 연결 금지
conn = sqlite3.connect("news_database.db")  # 스레드 문제 발생
```

### QThread 패턴

```python
class SearchWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def run(self):
        try:
            results = self.search_news()
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))
```

### 탭 키워드 파싱 정책 (v32.5.0)

탭 문자열 파싱은 반드시 `parse_tab_query(raw)`를 사용합니다.

```python
db_keyword, exclude_words = parse_tab_query("IT 기술 -광고")
# db_keyword: "IT"  (레거시 정책 유지)
# exclude_words: ["광고"]
```

- 조회/배지/리네임/수집 경로에서 동일한 파싱 함수를 사용해 동작 일관성을 유지합니다.
- 신규 코드에서 `split()[0]` 직접 파싱은 사용하지 않습니다.

---

## 🐛 자주 발생하는 이슈

### 1. HiDPI 스케일링 문제
```python
# PyQt6 import 전에 반드시 설정
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
```

### 2. PyInstaller 경로 문제
```python
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))
```

### 3. 링크 클릭 시 화면 깜빡임
```python
# NewsBrowser에서 setOpenLinks(False) 설정
self.setOpenExternalLinks(False)
self.setOpenLinks(False)
```

---

## 📝 수정 체크리스트

코드 수정 시 다음을 확인하세요:

- [ ] `VERSION` 상수 업데이트
- [ ] `update_history.md`에 변경 내역 추가
- [ ] 라이트/다크 테마 모두 테스트
- [ ] PyInstaller 빌드 테스트
- [ ] 로깅 추가 (`logger.info`, `logger.error`)
- [ ] 타입 힌트 작성
- [ ] 한국어 UI 텍스트 일관성

---

## 🧭 작업 유형별 가이드

### UI 수정 시
1. `Colors` 클래스에서 색상 확인
2. `AppStyle.LIGHT` 및 `AppStyle.DARK` 동시 수정
3. `UIConstants`에서 패딩, 마진 등 참조

### DB 스키마 수정 시
1. `DatabaseManager._init_schema()` 수정
2. 마이그레이션 로직 추가
3. 기존 사용자 데이터 보존 확인

### 새 기능 추가 시
1. 관련 클래스 위치 파악 (위 테이블 참조)
2. 시그널/슬롯 패턴 준수
3. 설정 항목이 필요하면 `news_scraper_config.json` 스키마 확장

### 버그 수정 시
1. `news_scraper.log` 확인
2. 관련 예외 처리 강화
3. 토스트 메시지로 사용자 알림

---

## 🔧 워커 클래스 패턴

### ApiWorker (API 호출)

```python
class ApiWorker(QObject):
    """비동기 API 호출 워커"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, client_id, client_secret, keyword, 
                 exclude_words, db_manager, start_idx=1, 
                 max_retries=3, timeout=15, session=None):
        ...
    
    def run(self):
        """재시도 로직 포함 API 호출"""
        for attempt in range(self.max_retries):
            try:
                resp = session.get(url, headers=headers, params=params)
                # 429 Rate Limit 처리
                # 결과 DB 저장
                self.finished.emit(result)
            except requests.Timeout:
                # 재시도
            ...
    
    def stop(self):
        self._destroyed = True
        self.is_running = False
```

### DBWorker (DB 조회)

```python
class DBWorker(QThread):
    """비동기 DB 조회 워커"""
    finished = pyqtSignal(list, int)  # data, total_count
    error = pyqtSignal(str)
    
    def run(self):
        # 제외어 파싱: parse_tab_query(raw) 사용
        search_keyword, exclude_words = parse_tab_query(self.keyword)
        
        data = self.db.fetch_news(...)
        
        self.finished.emit(data, len(data))
```

### AsyncJobWorker (범용 비동기)

```python
class AsyncJobWorker(QThread):
    """단발성 비동기 작업 수행"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    
    def __init__(self, job_func, *args, **kwargs):
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs
    
    def run(self):
        result = self.job_func(*self.args, **self.kwargs)
        self.finished.emit(result)
```

---

## 📝 HTML 템플릿 시스템

### AppStyle.HTML_TEMPLATE

뉴스 렌더링에 사용되는 CSS 템플릿 (Colors 헬퍼와 함께 사용):

```python
colors = Colors.get_html_colors(is_dark=True)
css = AppStyle.HTML_TEMPLATE.format(**colors)
```

### 뉴스 아이템 HTML 구조

```html
<div class="news-item read duplicate">
    <a href="app://open/{hash}" class="title-link">⭐ 제목</a>
    <div class="meta-info">
        <span class="meta-left">
            📰 언론사 · 날짜 
            <span class="keyword-tag">키워드</span>
            <span class="duplicate-badge">유사</span>
        </span>
        <span class="actions">
            <a href='app://share/{hash}'>공유</a>
            <a href='app://ext/{hash}'>외부</a>
            <a href='app://note/{hash}'>메모 📝</a>
            <a href='app://bm/{hash}'>북마크</a>
        </span>
    </div>
    <div class="description">기사 요약...</div>
</div>
```

---

## ⚙️ 설정 옵션 상세

### app_settings 전체 필드

```json
{
    "app_settings": {
        "client_id": "네이버 클라이언트 ID",
        "client_secret": "네이버 클라이언트 시크릿",
        "theme_index": 0,              // 0=라이트, 1=다크
        "refresh_interval_index": 2,   // 0=10분, 1=30분, 2=1시간...
        "notification_enabled": true,  // 데스크톱 알림
        "alert_keywords": [],          // 특정 키워드 알림
        "sound_enabled": true,         // 알림 소리
        "minimize_to_tray": true,      // 최소화→트레이
        "close_to_tray": true,         // 닫기→트레이
        "start_minimized": false,      // 최소화 상태로 시작
        "auto_start_enabled": false,   // Windows 시작 시 자동 실행
        "notify_on_refresh": false,    // 새로고침 완료 알림
        "api_timeout": 15,             // API 타임아웃 (초)
        "window_geometry": {           // 창 위치/크기
            "x": 100, "y": 100,
            "width": 1100, "height": 850
        }
    },
    "tabs": ["키워드1", "키워드2"],
    "search_history": [],
    "keyword_groups": {                // KeywordGroupManager 관리
        "그룹명": ["키워드1", "키워드2"]
    }
}
```

### 새로고침 간격 인덱스

| 인덱스 | 간격 |
|--------|------|
| 0 | 10분 |
| 1 | 30분 |
| 2 | 1시간 |
| 3 | 2시간 |
| 4 | 6시간 |
| 5 | 비활성화 |

---

## 🐞 문제 해결 가이드

### 1. API 오류

```python
# HTTP 401: 인증 실패
→ API 키 확인 (설정 다이얼로그)

# HTTP 429: 요청 제한 초과
→ 자동 재시도 (2초, 4초, 6초 대기)
→ 실패 시 "잠시 후 다시 시도" 메시지

# HTTP 5xx: 서버 오류
→ 네이버 API 서버 상태 확인
```

### 2. DB 오류

```python
# "database is locked"
→ 다른 프로세스가 DB 사용 중
→ 앱 재시작 또는 프로세스 확인

# 테이블 없음
→ DatabaseManager._init_schema() 자동 실행됨
→ 수동 복구: DB 파일 삭제 후 재시작
```

### 2-1. 백업/복원 무결성 (v32.6.0)

```python
# 백업
# 1) sqlite backup API로 일관된 스냅샷 생성 시도
# 2) 실패 시 파일 복사 fallback
# 3) -wal/-shm sidecar 동시 처리

# 복원
# 1) UI에서 즉시 복원하지 않고 pending restore 예약
# 2) 앱 재시작 시 DB 본체/sidecar(-wal, -shm) 적용
```

- 실행 중 DB 덮어쓰기를 피하기 위해 복원은 재시작 적용 정책으로 고정되었습니다.

### 3. UI 깜빡임

```python
# 원인: setOpenLinks(True)가 페이지 내비게이션 유발
# 해결:
self.browser.setOpenExternalLinks(False)
self.browser.setOpenLinks(False)

# 스크롤 위치 유지
scroll_pos = self.browser.verticalScrollBar().value()
self.browser.setHtml(html)
QTimer.singleShot(0, lambda: self.browser.verticalScrollBar().setValue(scroll_pos))
```

### 4. 메모리 누수

```python
# 토스트 애니메이션 정리
if hasattr(self, 'anim_out'):
    self.anim_out.stop()
    self.anim_out.deleteLater()

# 워커 스레드 정리
if self.worker and self.worker.isRunning():
    self.worker.stop()
    self.worker.wait(1000)
```

---

## 🔍 디버깅 팁

### 로그 확인

```python
# 로그 파일 위치
LOG_FILE = os.path.join(APP_DIR, "news_scraper.log")

# 로그 레벨별 색상 (LogViewerDialog)
[ERROR], [CRITICAL] → 빨간색
[WARNING] → 노란색
[INFO] → 초록색
```

### 런타임 디버깅

```python
# 워커 상태 확인
logger.info(f"ApiWorker 시작: {self.keyword}")
logger.info(f"ApiWorker 완료: {self.keyword} ({len(items)}개)")

# DB 연결 상태
logger.info(f"DB 연결 {closed_count}개 정상 종료")
logger.warning(f"비상 연결 {emergency_count}개가 정리되지 않음")
```

### 크래시 로그

```python
# 예외 발생 시 자동 기록
try:
    ...
except Exception as e:
    logger.error(f"오류: {e}")
    traceback.print_exc()
```

---

## 🎨 테마 커스터마이징

### 새 색상 추가

```python
# Colors 클래스에 추가
class Colors:
    # 새 색상 정의
    LIGHT_MY_COLOR = "#123456"
    DARK_MY_COLOR = "#654321"
    
    @classmethod
    def get_html_colors(cls, is_dark: bool) -> Dict[str, str]:
        if is_dark:
            return {
                ...
                'my_color': cls.DARK_MY_COLOR,
            }
        else:
            return {
                ...
                'my_color': cls.LIGHT_MY_COLOR,
            }
```

### QSS 스타일 수정

```python
# AppStyle 클래스 수정
class AppStyle:
    LIGHT = f"""
        QPushButton#MyButton {{
            background-color: {Colors.LIGHT_MY_COLOR};
        }}
    """
```

---

## 📚 참고 자료

- [네이버 검색 API 문서](https://developers.naver.com/docs/search/news/)
- [PyQt6 공식 문서](https://www.riverbankcomputing.com/static/Docs/PyQt6/)
- [SQLite 문서](https://www.sqlite.org/docs.html)
- [gemini.md](gemini.md) - Gemini AI 지침서

---

## 💡 팁

1. **중간 모듈 분리 구조**: 엔트리포인트는 `news_scraper_pro.py`이며 핵심 로직은 `query_parser.py`, `config_store.py`, `backup_manager.py`, `workers.py`, `worker_registry.py`로 분리됨
2. **한국어 환경**: UI 텍스트, 로그, 주석 모두 한국어
3. **Windows 특화**: 시스템 트레이, 자동 시작 등 Windows 전용 기능 포함
4. **성능 최적화**: LRU 캐시, 연결 풀, 비동기 처리, 디바운싱 적용됨
5. **버전 관리**: 변경 시 `VERSION` 상수와 `update_history.md` 동시 업데이트



## v32.7.0 Refactor Update

### Architecture Baseline
- Entrypoint: `news_scraper_pro.py` (thin compatibility layer)
- Core modules: `core/*`
- UI modules: `ui/*`
- Compatibility wrappers: root-level `query_parser.py`, `config_store.py`, `backup_manager.py`, `worker_registry.py`, `workers.py`, `database_manager.py`, `styles.py`

### Compatibility Contract
- Keep `python news_scraper_pro.py` launch behavior.
- Keep `import news_scraper_pro as app` compatibility.
- Keep these exports: `parse_tab_query`, `build_fetch_key`, `DatabaseManager`, `AutoBackup`, `apply_pending_restore_if_any`, `PENDING_RESTORE_FILENAME`.

### Test Policy
- Prefer behavior/contract tests over monolithic source-string checks.
- Validate entrypoint and wrapper compatibility explicitly.

