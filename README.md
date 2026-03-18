# 🔍 Naver Search Analyst Dashboard

네이버 Open API 기반 실시간 검색 분석 대시보드

| 기능 | 설명 |
|------|------|
| 최신 5개 게시글 | 뉴스/블로그/웹문서 최신 결과 |
| 키워드 빈도 분석 | KoNLPy Okt 명사 추출 → 상위 20 키워드 |
| 감정 분석 | KNU SentiLex 기반 긍정/부정/중립 분류 |
| 연관어 네트워크 | 공동출현 그래프 (D3 force-directed) |
| 자동 페이지네이션 | 기간 내 최대 1,000건 수집 |

---

## 🔑 네이버 API 키 발급

1. https://developers.naver.com → 로그인
2. **애플리케이션 등록** → 이름 입력
3. **사용 API**: `검색` 체크
4. **환경 추가**: `WEB 설정` → localhost 등록
5. **Client ID** / **Client Secret** 복사 → 대시보드에 입력

---

## 🚀 실행 방법

### 방법 1 — Docker (권장)

```bash
cd naver-dashboard
docker-compose up -d --build

# http://localhost:8000 접속
```

> 첫 빌드 시 Java + Python 패키지 설치로 2~5분 소요.  
> KoNLPy JVM 초기화(최대 30초)는 서버 시작 후 백그라운드에서 자동 진행됩니다.  
> 우측 상단 **KoNLPy ✓ / SentiLex ✓** 배지가 초록색이 되면 분석 준비 완료.

```bash
docker-compose down   # 종료
```

---

### 방법 2 — Python 직접 실행 (Java 필요)

```bash
# 1. Java 17+ 설치 확인
java -version

# 2. 의존성 설치
cd naver-dashboard/backend
pip install -r requirements.txt

# 3. 서버 실행
python main.py

# 4. http://localhost:8000 접속
```

---

## 📁 프로젝트 구조

```
naver-dashboard/
├── backend/
│   ├── main.py          # FastAPI 앱
│   ├── naver.py         # 네이버 API 클라이언트 (페이지네이션)
│   ├── nlp.py           # KoNLPy + KNU SentiLex + 분석 로직
│   ├── requirements.txt
│   └── data/            # KnuSentiLex.json (자동 다운로드)
├── frontend/
│   └── index.html       # 대시보드 UI (Chart.js + D3.js)
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## 🌐 외부 배포

**Railway (GitHub 연동, 무료)**
```bash
# GitHub Push 후 railway.app에서 연결
# Root directory: backend
# Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

**Fly.io**
```bash
fly launch
fly deploy
```

---

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/status` | KoNLPy / SentiLex 준비 상태 |
| POST | `/api/latest` | 최신 5건 가져오기 |
| POST | `/api/analyze` | 전체 수집 + NLP 분석 |

---

## ⚠️ 주의사항

- 네이버 검색 API: 일 25,000건 호출 한도
- 한 번에 최대 1,000건 수집 가능 (start 파라미터 한도)
- KoNLPy Okt 초기화는 서버 시작 시 백그라운드 실행 (최대 30초)
- KNU SentiLex는 최초 실행 시 GitHub에서 자동 다운로드 후 `backend/data/`에 캐싱
