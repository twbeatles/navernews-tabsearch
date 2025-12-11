# 네이버 뉴스 탭검색 프로그램

네이버 뉴스 API를 활용한 실시간 뉴스 검색 및 관리 데스크톱 애플리케이션입니다.

Claude Sonnet 4.5 및 Gemini 2.5 Pro 및 3.0 Pro를 이용하여 작성하였고, 지속 수정중입니다.


![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![PyQt6](https://img.shields.io/badge/PyQt6-6.0+-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Version](https://img.shields.io/badge/Version-27.0-orange.svg)

---

## 📋 주요 기능

### 🔍 뉴스 검색 및 관리
- **멀티 탭 검색**: 여러 키워드를 동시에 모니터링
- **실시간 자동 새로고침**: 10분~6시간 간격으로 자동 업데이트
- **제외 키워드**: 불필요한 뉴스 자동 필터링 (예: `AI -광고 -홍보`)
- **북마크 기능**: 중요한 기사 저장 및 관리
- **메모 기능**: 📝 기사별 메모 작성

### 📊 데이터 관리
- **로컬 데이터베이스**: SQLite 기반 영구 저장 (WAL 모드)
- **읽음/안읽음 상태**: 기사별 읽음 표시 및 관리
- **중복 감지**: 유사한 제목의 기사 자동 감지
- **결과 내 필터링**: 제목/본문 내용으로 빠른 검색
- **데이터 내보내기**: CSV 형식으로 검색 결과 저장

### 🎨 사용자 인터페이스
- **라이트/다크 테마**: 눈의 피로를 줄이는 테마 선택
- **하이라이트 기능**: 키워드 및 필터 텍스트 자동 강조
- **시스템 트레이**: 백그라운드 실행 지원
- **탭 관리**: 드래그 앤 드롭으로 탭 순서 변경
- **토스트 알림**: 비침습적 알림 메시지

### 🔔 알림 기능
- **새 뉴스 알림**: 백그라운드 실행 시 시스템 알림
- **탭별 새 기사 카운트**: 읽지 않은 뉴스 개수 표시

---

## 🚀 설치 방법

### 1. 사전 요구사항
- Python 3.8 이상
- pip (Python 패키지 관리자)

### 2. 라이브러리 설치

```bash
pip install PyQt6 requests
```

### 3. 네이버 API 키 발급
1. [네이버 개발자 센터](https://developers.naver.com/apps/#/register) 접속
2. 애플리케이션 등록
3. **검색 API** 선택 (뉴스 검색)
4. Client ID 및 Client Secret 발급

---

## 💻 사용 방법

### 프로그램 실행

```bash
python "251203 네이버 뉴스 자동검색 vfinal14 - 디버깅.py"
```

### 초기 설정

1. **API 키 입력**
   - 프로그램 실행 후 `⚙ 설정` 버튼 클릭
   - Client ID와 Client Secret 입력
   - `✓ API 키 검증` 버튼으로 확인

2. **자동 새로고침 설정**
   - 설정 메뉴에서 새로고침 간격 선택
   - 10분 / 30분 / 1시간 / 3시간 / 6시간 / 안함

3. **테마 선택**
   - ☀ 라이트 모드 또는 🌙 다크 모드 선택

---

## ⌨️ 키보드 단축키

| 단축키 | 기능 |
|--------|------|
| `Ctrl+R` / `F5` | 모든 탭 새로고침 |
| `Ctrl+T` | 새 탭 추가 |
| `Ctrl+W` | 현재 탭 닫기 |
| `Ctrl+S` | CSV로 내보내기 |
| `Ctrl+F` | 필터 검색창 포커스 |
| `Ctrl+,` | 설정 열기 |
| `F1` | 도움말 열기 |
| `Alt+1~9` | 탭 빠른 전환 |

---

## 🔍 검색 문법

### 기본 검색
```
키워드: 인공지능
결과: "인공지능" 포함된 모든 뉴스
```

### 제외 키워드 사용
```
키워드: 인공지능 -광고 -채용
결과: "인공지능" 포함, "광고"와 "채용" 제외
```

---

## 📁 파일 구조

```
navernews-scrapper/
├── 251203 네이버 뉴스 자동검색 vfinal14 - 디버깅.py  # 메인 프로그램
├── news_scraper_config.json     # 설정 파일 (자동 생성)
├── news_database.db             # 데이터베이스 (자동 생성)
├── news_scraper.log             # 로그 파일 (v27.0+)
├── crash_log.txt                # 크래시 로그 (오류 발생 시)
└── README.md                    # 사용 설명서
```

---

## ⚠️ 문제 해결

### API 오류

| 오류 코드 | 원인 | 해결 방법 |
|-----------|------|-----------|
| 401 | 인증 실패 | API 키 재확인 |
| 429 | 호출 한도 초과 | 잠시 후 재시도 |

### 프로그램이 종료되는 경우

v27.0에서 안정성이 크게 개선되었습니다. 문제 발생 시:
1. `news_scraper.log` 파일 확인
2. `crash_log.txt` 파일 확인

### 데이터베이스 오류

```bash
# 데이터베이스 초기화
rm news_database.db news_database.db-wal news_database.db-shm
```

---

## 📝 버전 히스토리

### v27.0 (현재 버전) - 안정성 대폭 개선
- ✅ **자동 새로고침 안정성**: `QMutex`를 사용한 동시 실행 방지
- ✅ **시그널 안전 처리**: 삭제된 객체로 인한 크래시 방지
- ✅ **로깅 시스템**: `news_scraper.log` 파일에 모든 활동 기록
- ✅ **워커 정리 개선**: 시그널 disconnect 후 안전한 종료

### v26.0
- 스레드 안전성 문제 수정
- 단축키 기능 추가
- 프로그램 내 도움말 기능 추가
- 통계 및 분석 기능 추가

### v18.2 
- 스레드 안전 데이터베이스 연결 개선
- WAL 모드 활성화로 성능 향상
- 메모리 누수 방지 강화

---

## 🔒 보안 및 개인정보

- API 키는 로컬에만 저장
- 모든 데이터는 사용자 컴퓨터에 저장
- 외부 서버로 데이터 전송 없음

**Git 사용 시 `.gitignore`에 추가:**
```gitignore
news_scraper_config.json
news_database.db*
news_scraper.log
crash_log.txt
```

---

## 👨‍💻 개발 정보

- **언어**: Python 3.8+
- **GUI 프레임워크**: PyQt6
- **데이터베이스**: SQLite3 (WAL 모드)
- **API**: 네이버 검색 API
- **AI 도구**: Claude Sonnet, Gemini 2.5/3.0 Pro

## 🔗 유용한 링크

- [네이버 개발자 센터](https://developers.naver.com/)
- [네이버 검색 API 가이드](https://developers.naver.com/docs/serviceapi/search/news/news.md)
- [PyQt6 공식 문서](https://www.riverbankcomputing.com/static/Docs/PyQt6/)

---

## 📄 라이선스

MIT License - 자유롭게 사용, 수정, 배포 가능
