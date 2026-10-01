# 유역 상수도·풍수해 언론 모니터링 (waterNews)

금강유역 등 유역별 지자체의 **단수 · 상수도 사고 · 풍수해** 상황을 두 채널로 감지하는 웹 앱입니다.

| 채널 | 연계 | 방식 |
|---|---|---|
| 뉴스 | 구글 뉴스(RSS), 네이버 뉴스 검색 API | 키워드 · 기간 · 지역 타겟팅 조회, 예약 키워드 자동 조회 |
| 재난문자 | 행정안전부_긴급재난문자 (재난안전데이터 공유플랫폼 `DSSP-IF-00247`) | 실시간 폴링 + 브라우저 즉시 알림, 기간 조회 |

- **화면(프론트엔드)**: React 19 + Vite (`web/`)
- **서버(백엔드)**: Python 3.9 이상 표준 라이브러리 (`app.py`, `waternews/`) — API 연계·실시간 폴링 담당, pip 설치 불필요

## 실행

### 준비물
- [Python 3.9 이상](https://www.python.org/downloads/) (Windows 설치 시 "Add Python to PATH" 체크)
- [Node.js 20.19 이상 (LTS)](https://nodejs.org/) — React 화면 빌드용

### 1) 처음 한 번: React 화면 빌드
```bash
cd web
npm install
npm run build        # web/dist 생성
cd ..
```

### 2) 서버 실행
```bash
python app.py        # → 브라우저에서 http://127.0.0.1:8080 접속
```
Python 서버가 API와 빌드된 React 화면(`web/dist`)을 함께 제공합니다. 화면 코드를 수정했다면 `npm run build`를 다시 실행하세요.

옵션:
```bash
python app.py --port 9000        # 포트 변경
python app.py --host 0.0.0.0     # 내부망 다른 PC에서 접속 허용 (인증키 노출에 유의)
WATERNEWS_DEMO=1 python app.py   # 데모 모드: 외부 API 없이 가상 데이터로 화면 확인
```
Windows PowerShell 데모 모드: `$env:WATERNEWS_DEMO="1"; python app.py`

### (개발용) 화면 수정하며 실시간 반영
터미널 2개를 사용합니다.
```bash
# 터미널 1 — API 서버
python app.py
# 터미널 2 — React 개발 서버 (저장 시 자동 새로고침)
cd web && npm run dev            # → http://localhost:5173 접속 (/api 는 8080으로 자동 전달)
```

## 화면 구성

- **대시보드** – 오늘 대상 지역 재난문자 수, 상수도·풍수해 관련 문자 수, 단수 감지 건수, 유역별(단수/상수도 사고/풍수해) 집계, 최근 감지 피드, 연계 상태
- **재난문자** – 실시간 목록(신규 수신 시 강조 · 소리 · 브라우저 알림), 기간 조회(최대 31일, 지역명 `rgnNm` 지정 가능), 유역/관련 문자/검색 필터
- **뉴스 조회** – 키워드 선택·추가, 시작일/종료일, 구글·네이버 선택, 유역 타겟팅, CSV 저장
- **환경설정** – 포털 인증키, 네이버 API 키, 조회 예약 키워드, 지역 타겟팅(유역·지자체 추가/삭제), 예약 조회 주기

## 환경설정

### 1. 행정안전부 긴급재난문자 API 인증키
1. [재난안전데이터 공유플랫폼](https://www.safetydata.go.kr/disaster-data/view?dataSn=228) 회원가입 → `행정안전부_긴급재난문자` 이용신청
2. 발급받은 서비스키를 **환경설정 → 포털 인증키(serviceKey)** 에 입력 → **연결 테스트** → **설정 저장**

API 명세(앱에서 사용하는 값):

| 요청변수 | 설명 | 앱 사용 |
|---|---|---|
| `serviceKey` | 서비스키 (필수) | 환경설정 입력값 (URL 인코딩된 키도 자동 처리) |
| `numOfRows` / `pageNo` | 페이지당 개수 / 페이지 번호 | 기본 1000건, `totalCount` 기준 자동 페이지 수집 |
| `returnType` | json, xml | `json` |
| `crtDt` | 조회시작일자 `YYYYMMDD` | 실시간: 오늘(자정 직후는 전날부터), 기간 조회: 시작일 |
| `rgnNm` | 지역명(시도명, 시군구명) | 선택 입력 (비우면 전국 조회 후 앱에서 유역 필터) |

| 출력결과 | 설명 | 앱 사용 |
|---|---|---|
| `SN` | 일련번호 | 신규 문자 판별(중복 제거) |
| `CRT_DT` | 생성일시 | 표시 · 기간 필터 |
| `MSG_CN` | 메시지 내용 | 키워드 강조 · 분류 |
| `RCPTN_RGN_NM` | 수신지역명 | 유역/지자체 매칭 |
| `EMRG_STEP_NM` | 긴급단계명 (위급재난, 긴급재난, 안전안내) | 단계 배지 |
| `DST_SE_NM` | 재해구분명 (수도, 홍수, 호우, 태풍 …) | 분류 보강 (수도→상수도 사고, 홍수·호우·태풍·산사태→풍수해) |
| `REG_YMD` / `MDFCN_YMD` | 등록/수정일자 | 보관 |

> 조회 주기 기본값은 120초(하루 약 720회)입니다. 포털 일일 호출 한도에 맞게 조정하세요.
> 기관망에서 `CERTIFICATE_VERIFY_FAILED` 오류가 나면 **고급 설정 → SSL 인증서 검증**을 해제하세요(포털 샘플 코드와 동일한 방식).

### 2. 네이버 검색 API (선택)
[네이버 개발자센터](https://developers.naver.com/apps/)에서 애플리케이션 등록(검색 API) 후 Client ID / Secret 입력. 구글 뉴스는 키 없이 동작합니다.

### 3. 조회 예약 키워드
기본값: `단수, 상수도, 홍수, 누수, 수도관 파열, 침수`. 자유롭게 추가/삭제할 수 있으며
뉴스 조회 기본 키워드, 재난문자 키워드 강조, **예약 조회(주기적 자동 뉴스 감시)** 에 사용됩니다.

### 4. 지역 타겟팅
기본 유역: **금강유역**(기본 활성), 한강유역, 낙동강유역, 영섬유역. 유역 추가와 유역별 지자체 추가/삭제가 가능합니다.
체크된 유역이 실시간 알림 · 대시보드 집계 대상입니다.

지명 매칭 규칙:
- 시·광역시: 핵심 지명으로 매칭 (`정읍시` → 기사 속 "정읍", `대전광역시` → "대전")
- 군·구: 전체 명칭으로 매칭 (`완주군`, `예산군` — "예산 편성" 같은 오탐 방지)
- 재난문자 수신지역명은 `서울시`로 입력해도 `서울특별시`와 매칭
- 접미사 없이 입력하면 그대로 매칭 (예: `옥천`을 추가하면 "옥천" 포함 기사도 감지)

## 분류 기준 (`waternews/classify.py`)

| 분류 | 주요 단어 |
|---|---|
| 단수 | 단수, 급수 중단, 제한급수, 운반급수, 비상급수 … |
| 상수도 사고 | 상수도, 상수관, 수도관, 송수관, 누수, 파열, 적수, 탁수, 정수장, 배수지 … |
| 풍수해 | 홍수, 호우, 폭우, 침수, 범람, 태풍, 산사태, 홍수경보 … |

## 데이터 저장
- 설정 및 인증키: `data/settings.json` (git 제외, 파일 권한 600). 화면/API 응답에는 키가 마스킹되어 표시됩니다.
- 환경변수로도 키 지정 가능: `SAFETYDATA_SERVICE_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`
- 실시간 재난문자는 메모리에 최근 3일분을 보관합니다.

## 테스트

```bash
python -m unittest discover -s tests -t .
```

## 구조

```
app.py                  HTTP 서버 · API 라우팅 · 실시간 이벤트(SSE)
waternews/disaster.py   긴급재난문자 API 호출 · 응답 파싱 · 기간 조회
waternews/news.py       구글 뉴스 RSS · 네이버 뉴스 API · 통합/중복 제거
waternews/classify.py   단수/상수도 사고/풍수해 분류, 유역·지자체 매칭
waternews/monitor.py    재난문자 실시간 폴링, 예약 키워드 뉴스 조회
waternews/settings.py   환경설정 저장 · 인증키 마스킹
waternews/defaults.py   기본 키워드 · 유역별 지자체 목록
waternews/demo.py       데모 모드 가상 데이터
web/                    React 화면 (Vite)
  src/App.jsx           탭 · 실시간 이벤트(SSE) · 알림
  src/components/       Dashboard, DisasterTab, NewsTab, SettingsTab, Tags
  dist/                 빌드 결과 (npm run build, git 제외)
```
