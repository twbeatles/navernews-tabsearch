# 뉴스 스크래퍼 Pro v32.1

네이버 뉴스 API를 활용한 실시간 뉴스 수집 및 관리 프로그램

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![PyQt6](https://img.shields.io/badge/PyQt6-6.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## 주요 기능

### 📰 뉴스 수집
- 네이버 뉴스 API를 통한 실시간 뉴스 검색
- 다중 키워드 탭 지원
- 자동 새로고침 (10분/30분/1시간/3시간/6시간)
- 중복 기사 자동 감지

### 🔍 필터링 및 검색
- 제목/본문 실시간 필터링
- 언론사별 분류
- 읽음/안읽음 상태 관리
- 제외 키워드 설정

### ⭐ 북마크 및 메모
- 중요 기사 북마크
- 기사별 메모 기능
- 북마크 전용 탭

### 🔔 알림 시스템
- 데스크톱 알림
- 키워드 기반 알림
- 알림 소리 설정

### 💾 데이터 관리
- SQLite 로컬 데이터베이스
- 자동 백업 (설정/DB)
- CSV 내보내기
- 설정 가져오기/내보내기

### 🎨 UI/UX
- 라이트/다크 테마
- Apple 스타일 모던 디자인
- 키보드 단축키 지원
- 반응형 레이아웃

---

## 설치 방법

### 요구 사항
- Python 3.8 이상
- 네이버 개발자 API 키

### 의존성 설치

```bash
pip install PyQt6 requests
```

### 실행

```bash
python news_scraper_pro.py
```

---

## 네이버 API 키 발급

1. [네이버 개발자센터](https://developers.naver.com/) 접속
2. 애플리케이션 등록
3. **검색 API (뉴스)** 권한 추가
4. Client ID와 Client Secret 발급
5. 프로그램 설정에서 입력

---

## 키보드 단축키

| 단축키 | 기능 |
|--------|------|
| `Ctrl+R` / `F5` | 새로고침 |
| `Ctrl+T` | 새 탭 추가 |
| `Ctrl+W` | 현재 탭 닫기 |
| `Ctrl+S` | CSV 내보내기 |
| `Ctrl+,` | 설정 |
| `Ctrl+F` | 필터 포커스 |
| `F1` | 도움말 |
| `Ctrl+1~9` | 탭 전환 |

---

## 빌드 방법 (PyInstaller)

### 기본 빌드

```bash
pyinstaller news_scraper.spec
```

### 수동 빌드

```bash
pyinstaller --onefile --windowed --name "뉴스스크래퍼Pro" news_scraper_pro.py
```

---

## 파일 구조

```
navernews-tabsearch/
├── news_scraper_pro.py    # 메인 프로그램
├── news_scraper.spec      # PyInstaller 빌드 설정
├── README.md              # 문서
├── news_scraper_config.json  # 설정 파일 (자동 생성)
├── news_database.db       # 뉴스 데이터베이스 (자동 생성)
├── keyword_groups.json    # 키워드 그룹 (자동 생성)
└── backups/               # 백업 폴더 (자동 생성)
```

---

## 버전 히스토리

### v32.1 (2024-12-29)
- 🐛 closeEvent 속성 오류 수정
- 🔧 네트워크 오류 처리 강화
- 🎨 UI/UX 개선 (버튼 호버 효과, 입력 포커스 등)
- 📌 필터 체크박스 아이콘 추가
- 🔑 API 오류 코드별 상세 메시지

### v32.0
- 자동 백업 기능
- 로그 뷰어
- 키워드 그룹 관리
- 알림 소리

---

## 라이선스

MIT License

---

## 문의

문제가 발생하면 이슈를 등록해주세요.
