# 뉴스 스크래퍼 Pro

![Version](https://img.shields.io/badge/version-32.1-blue)
![Python](https://img.shields.io/badge/python-3.8+-green)
![License](https://img.shields.io/badge/license-MIT-orange)

네이버 뉴스 API를 활용한 실시간 뉴스 수집 및 관리 프로그램입니다.

## ✨ 주요 기능

### 📰 뉴스 수집
- 네이버 검색 API를 통한 실시간 뉴스 수집
- 키워드별 탭 관리 및 그룹화
- 제외 키워드 지원 (예: `주식 -코인`)
- 자동 새로고침 (10분 ~ 6시간 간격)

### 🔖 기사 관리
- ⭐ 북마크 기능
- 📝 기사별 메모 작성
- ✓ 읽음/안읽음 상태 관리
- 🔍 실시간 필터링 (디바운싱 지원)
- 중복 기사 자동 감지

### 🎨 UI/UX
- ☀️ 라이트 / 🌙 다크 테마
- HiDPI 디스플레이 지원
- Toast 알림 + 소리
- 키보드 단축키 지원

### 🛠 도구
- 📋 로그 뷰어 (레벨 필터, 검색)
- 🗂 키워드 그룹 관리
- 💾 자동 백업 (최대 5개 보관)
- 📊 통계 및 분석

## 🚀 시작하기

### 요구사항

```bash
pip install PyQt6 requests
```

### API 키 발급

1. [네이버 개발자 센터](https://developers.naver.com) 접속
2. 애플리케이션 등록 → 검색 API 선택
3. Client ID와 Client Secret 획득
4. 프로그램 실행 → 설정에서 API 키 입력

### 실행

```bash
python news_scraper_pro.py
```

## ⌨️ 키보드 단축키

| 단축키 | 기능 |
|--------|------|
| `Ctrl+R` / `F5` | 모든 탭 새로고침 |
| `Ctrl+T` | 새 탭 추가 |
| `Ctrl+W` | 현재 탭 닫기 |
| `Ctrl+S` | CSV 내보내기 |
| `Ctrl+F` | 필터 검색창 포커스 |
| `Ctrl+,` | 설정 열기 |
| `F1` | 도움말 |
| `Alt+1~9` | 탭 빠른 전환 |

## 📁 파일 구조

```
navernews-tabsearch/
├── news_scraper_pro.py    # 메인 프로그램
├── news_scraper_config.json  # 설정 파일 (자동 생성)
├── news_database.db       # SQLite 데이터베이스 (자동 생성)
├── news_scraper.log       # 로그 파일
├── backups/               # 자동 백업 폴더
├── news_icon.ico          # 아이콘 (선택)
└── README.md
```

## 🔧 빌드 (PyInstaller)

```bash
pyinstaller news_scraper.spec
```

빌드된 실행 파일은 `dist/` 폴더에 생성됩니다.

## 📝 변경 로그

### v32.1 (2024-12-28)
- ✨ 자동 백업 기능 추가 (시작 시 자동 백업, 최대 5개 보관)
- ✨ 로그 뷰어 다이얼로그 (레벨 필터, 검색, 색상 코딩)
- ✨ 키워드 그룹 관리 (폴더 형태 정리)
- ✨ 알림 소리 옵션 (Windows 시스템 사운드)
- ⚡ HiDPI 디스플레이 지원
- ⚡ 필터 디바운싱 (300ms)
- 🔧 테마 색상 시스템 리팩토링

### v31.1
- 탭 배지 (미읽음 수 표시) 추가
- 렌더링 성능 최적화
- DB 인덱스 개선

## 📄 라이선스

MIT License

---

Made with ❤️ using Python & PyQt6
