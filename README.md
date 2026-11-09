# AvengersBank

은행 서비스 백엔드: FastAPI + SQLAlchemy(async) + PostgreSQL + Alembic

## 문서

| 문서 | 내용 |
|---|---|
| [docs/ERD.md](docs/ERD.md) | ER 다이어그램 (Mermaid), 코드에서 지킬 규칙 · 원본: [AvengersBankDiagram.drawio](docs/AvengersBankDiagram.drawio) · 최신(현재 코드): [AvengersBankDiagram_v2.drawio](docs/AvengersBankDiagram_v2.drawio) |
| [docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md) | API 엔드포인트 목록, 요청·응답 형식, 구현 상태 |
| [docs/AUTH.md](docs/AUTH.md) | 로그인·세션 구조(액세스/갱신 토큰, 로그인 한도, 화면 타이머) — 학습용 설명 |
| [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | 폴더 구조, 계층(router → service → repository) 설명, 역할 분담 |
| [docs/DEPLOY.md](docs/DEPLOY.md) | AWS 배포 흐름(EC2 + RDS + Caddy), 다시 접속·코드 업데이트 방법, 겪은 문제 |
| [docs/AGENT.md](docs/AGENT.md) | AI 금융 비서: 실행 방법, 환경변수, Tool 목록, 이체 확인 흐름, 보안 |
| [docs/ACCOUNT_RECOVERY_RESEARCH.md](docs/ACCOUNT_RECOVERY_RESEARCH.md) | 계정 복구 조사: 국내 은행·규정·NIST·OWASP |
| [docs/RETROSPECTIVE.md](docs/RETROSPECTIVE.md) | 회고록(작성 중): 기술 선택과 이유(예: nginx 대신 Caddy), 배운 점 |
| [docs/인수인계.md](docs/인수인계.md) | 프로젝트를 이어받거나 리뷰하는 사람용 요약: 현재 상태, 초기 설계에서 바뀐 것, 코드 규칙, 정해야 할 것 |
| [docs/DESIGN_CHANGES.md](docs/DESIGN_CHANGES.md) | 설계 변경 기록(C-001~): 변경 전·후, 이유, 영향, 검증 |
| [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md) | 다음 할 일·정할 것(단계별 선택지·추천·상태) |
| [docs/HANDOFF.md](docs/HANDOFF.md) | 다음 세션이 이어서 작업하기 위한 메모: 현재 상태, 개발 환경, 일하는 방식 |
| [docs/TERMS_RAG.md](docs/TERMS_RAG.md) · [docs/TERMS_EVAL.md](docs/TERMS_EVAL.md) | 약관 발행·색인·검색 운영, 검색 평가 |

## 시작하기

[uv](https://docs.astral.sh/uv/)와 Docker(또는 직접 설치한 PostgreSQL)가 필요합니다.

```bash
uv sync
cp .env.example .env
docker compose up -d --wait   # PostgreSQL 17을 127.0.0.1:5435에 띄움 (docker-compose.yml)
```

`.env`에 `JWT_SECRET_KEY`(32자 이상)를 채웁니다. `POSTGRES_PASSWORD`(DB 비밀번호)는 `docker-compose.yml`이 읽고 `DATABASE_URL`의 비밀번호와 같아야 합니다(`.env.example`에 맞춰져 있음). **예전 `.env`를 쓰고 있다면 `POSTGRES_PASSWORD=1234`를 추가하세요**(없으면 `docker compose`가 오류를 냅니다). `ACCESS_TOKEN_EXPIRE_MINUTES`(기본 5)·`SESSION_EXPIRE_MINUTES`(기본 30)는 토큰 수명이며 없으면 기본값을 씁니다([docs/AUTH.md](docs/AUTH.md)).

> **Windows 주의**
> - `DATABASE_URL`의 호스트는 `localhost`가 아니라 `127.0.0.1`로 둡니다. `localhost`는 IPv6(`::1`)로 먼저 연결을 시도하는데, Windows에서 psycopg 비동기 연결이 거절된 `::1`에서 다음 주소로 넘어가지 못하고 멈춥니다.
> - 서버는 `fastapi dev`로 실행합니다. `fastapi run`은 Windows 기본 이벤트 루프(Proactor)를 써서 psycopg 비동기 모드가 동작하지 않습니다(DB 요청마다 500).

```bash
uv run alembic upgrade head
uv run python -m avengers_bank.seed   # 개발용 상품 데이터 (같은 이름은 건너뛰고 새 상품만 추가)
uv run fastapi dev
```

최초 마이그레이션(`alembic/versions/6e15576e9ff5_create_initial_tables.py`)은 저장소에 들어 있으므로 `upgrade head`만 실행합니다. 새 마이그레이션을 받았을 때(예: 갱신 토큰용 `refresh_tokens` 테이블)도 `uv run alembic upgrade head`만 다시 실행하면 됩니다.

### 프론트엔드 (Next.js)

API 서버를 띄운 상태에서 다른 터미널로 실행하고 http://localhost:5173 을 엽니다. 포트를 5173으로 고정해서 API의 CORS 기본값과 맞췄습니다.

```bash
cd frontend
npm install
npm run dev
```

다른 API(예: 배포 서버)를 부르려면 `frontend/.env.example`을 `.env.local`로 복사해 `NEXT_PUBLIC_API_BASE_URL`을 바꿉니다.

### 개발용 잔액 충전

외부 입금 기능이 없어서, 이체·결제를 시험하려면 잔액을 채워야 합니다. `.env`의 `ENABLE_DEV_ENDPOINTS=true`일 때만 열리는 개발용 API를 씁니다(`.env.example`에 켜져 있음, 운영 환경에서는 끄기).

```
POST /dev/accounts/checking/{account_id}/charge   { "amount": 100000 }
```

### 인증번호 확인(개발용 문자함)과 관리자 명령

회원가입·휴대폰 번호 변경·비밀번호 찾기·계좌 비밀번호 재설정의 **인증번호는 개발 모드에서 서버 로그(`[개발용 문자]`)와 화면의 '개발용 문자함'(`GET /dev/sms`)으로 확인**합니다. 실제 문자 발송은 아직 없고, `ENABLE_DEV_ENDPOINTS=true`가 필요합니다.

데모 사용자·계좌는 서버를 띄운 뒤 `uv run python -m avengers_bank.seed_demo [login_id] [password]`로 만듭니다(기본 `admin123` / `Passw0rd!23`, 계좌 비밀번호 `1357`). 가입 인증번호도 개발용 문자함에서 읽어 처리하므로 역시 `ENABLE_DEV_ENDPOINTS=true`가 필요합니다.

로그인을 5회 연속 틀리면 아이디가 잠깁니다(비밀번호 찾기로 해제). 스스로 복구할 수 없을 때는 관리자 명령을 씁니다.

```bash
uv run python -m avengers_bank.admin unlock <login_id>           # 로그인 잠금 해제
uv run python -m avengers_bank.admin reset-password <login_id>   # 새 비밀번호 입력 → 잠금 해제, 모든 세션 폐기
```

### 모델을 바꿨을 때

`models.py`를 수정한 사람만 마이그레이션을 만들고, 만든 파일을 함께 커밋합니다.

```bash
uv run alembic revision --autogenerate -m "무엇을 바꿨는지"
# 생성된 파일을 열어 내용 확인 후
uv run alembic upgrade head
uv run alembic check   # 모델과 마이그레이션이 일치하면 "No new upgrade operations detected."
```

- 각자 `revision --autogenerate`를 따로 돌리면 리비전 ID가 달라져서 충돌합니다. 다른 사람이 만든 마이그레이션은 받아서 `upgrade head`만 합니다.
- 새 `models.py`(새 테이블)를 추가했다면 `alembic/env.py`의 import 목록에도 추가해야 autogenerate가 테이블을 인식합니다.

API 문서: http://127.0.0.1:8000/docs

## 테스트

```bash
uv run pytest
```

테스트는 SQLite로 돌아가서 PostgreSQL 없이도 실행됩니다.

### 동시성 검증 (PostgreSQL)

SQLite는 `SELECT ... FOR UPDATE` 잠금을 무시하므로, **pytest가 통과해도 동시 요청에서 돈이 맞는지는 확인되지 않습니다.**
이체·결제·청구서 처럼 돈이 움직이는 코드를 바꿨다면 [scripts/README.md](scripts/README.md)의 스크립트로 실제 PostgreSQL에서 확인하세요(수동 실행).

```bash
uv run python scripts/pg_transfer_concurrency.py
```

## 현재 상태

| 도메인 | 상태 |
|---|---|
| users | ✅ 회원가입(휴대폰 인증), 로그인(5회 연속 실패 잠금)·토큰 갱신·로그아웃, 내 정보 조회·수정, 비밀번호 변경 |
| verification · recovery | ✅ 휴대폰 인증번호(개발용 문자함), 아이디·비밀번호 찾기(계좌번호 + 계좌 비밀번호 + 휴대폰 인증) |
| products | ✅ 계좌·카드 상품 목록/상세 조회, 상품 종류 검증 메서드 |
| accounts | ✅ 입출금·예금·적금 개설, 내 계좌 조회, 상세, 거래내역 조회, 별칭·이체 한도 수정, 계좌 비밀번호(숫자 4자리, 5회 잠금), 예·적금 해지, 예·적금 이자 미리 보기(오늘 해지하면 / 만기까지 두면) |
| transfers | ✅ 입출금 이체(잔액·1회·1일 한도 검사), 적금 납입 (예금은 가입 시 입출금 계좌에서 가입 금액 이체) |
| cards | ✅ 신용·체크카드 발급, 조회, 결제(사용), 신용카드 청구서 생성·납부 |
| terms | ✅ 상품 약관 동의(가입 때 필수)와 약관 검색(RAG, 출처 링크) ([docs/TERMS_RAG.md](docs/TERMS_RAG.md)) |
| agent | ✅ AI 금융 비서(Gemini, LangGraph로 모델↔도구 반복): 자산 요약·거래내역·카드값·약관 조회, 이체 초안 → 화면 확인 후 실행, 예·적금 가입 준비 카드 → 가입 화면에서 이어서 ([docs/AGENT.md](docs/AGENT.md)) |
| frontend | ✅ Next.js(`frontend/`): 홈·계좌 상세·이체·상품·가입·카드·내 정보·찾기 화면과 AI 비서 패널 |
