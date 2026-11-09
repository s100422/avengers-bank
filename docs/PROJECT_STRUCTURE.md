# 프로젝트 구조

FastAPI + SQLAlchemy(async) + Alembic 백엔드와 Next.js 프론트엔드(`frontend/`). 백엔드는 업무별로 **도메인 폴더**를 나누고, 각 도메인 안은 기본적으로 같은 5개 파일로 구성합니다.

> 처음에는 users·products·accounts·transfers·cards 5개 도메인이었고, 이후 인증·약관·AI 비서가 늘었습니다. 이 문서는 2026-11-09(C-104 시점) 현재 코드에 맞췄습니다.

## 전체 트리

```
avengers-bank/
├── .env.example            # 환경변수 예시 → .env로 복사해서 사용 (.env는 커밋 금지)
├── .env.prod.example       # 운영(배포)용 환경변수 예시
├── docker-compose.yml      # 로컬 개발용 PostgreSQL (127.0.0.1:5435)
├── docker-compose.prod.yml # 배포용 (API + Caddy, DB는 외부)
├── Dockerfile              # API 이미지 (uv sync --frozen)
├── deploy/Caddyfile        # 리버스 프록시·자동 HTTPS
├── pyproject.toml          # 의존성 (uv). AI 비서는 google-genai, langgraph
├── uv.lock
├── alembic.ini
├── alembic/                # DB 마이그레이션
│   ├── env.py              # 모든 models.py를 import해서 테이블 정보를 모음
│   └── versions/           # 마이그레이션 파일이 쌓이는 곳 (head는 `uv run alembic heads`)
├── docs/                   # 문서 (README.md의 문서 표 참고)
├── scripts/                # 검증·생성 스크립트: PostgreSQL 동시성 검증, 약관 평가, ERD drawio 생성 (scripts/README.md)
├── tests/                  # pytest (SQLite로 실행, DB 서버 불필요). 기능별 test_*.py + 공용 helpers
├── frontend/               # Next.js 화면 (npm run dev → http://localhost:5173)
│   ├── app/                # 라우트: 홈, accounts/[type]/[id], transfer, products, open/[kind], cards,
│   │                       #        me, login, signup, find-id, reset-password, terms/[versionId]
│   ├── components/         # ui.tsx, verify.tsx, account-password.tsx, history-filter.tsx,
│   │   │                   # home/(홈 카드), terms/(약관 표시·동의 기록)
│   │   └── assistant/      # AI 비서 패널: Assistant, TransferCard, OpenAccountCard, RichText …
│   └── lib/                # api.ts(API 호출·타입), home-prefs.ts, open-draft.ts(가입 화면 임시 저장 항목)
└── src/avengers_bank/
    ├── main.py             # 앱 생성, CORS, 예외 핸들러, 라우터 등록
    ├── seed.py             # 개발용 상품 데이터 (uv run python -m avengers_bank.seed)
    ├── seed_demo.py        # 데모 사용자·계좌 (uv run python -m avengers_bank.seed_demo)
    ├── admin.py            # 관리자 명령 (로그인 잠금 해제, 비밀번호 초기화)
    ├── core/               # 모든 도메인이 같이 쓰는 공용 코드
    │   ├── config.py       # .env 읽기
    │   ├── database.py     # DB 연결, Base, get_db
    │   ├── security.py     # 비밀번호 해시, JWT
    │   ├── cookies.py      # 갱신 토큰·기기 토큰 쿠키, Origin(CSRF) 확인
    │   ├── login_limiter.py# 로그인·인증번호 요청 한도 (프로세스 메모리)
    │   ├── timezone.py     # KST 시간대, 오늘 날짜(KST)
    │   ├── dependencies.py # get_current_user (로그인 사용자 확인)
    │   ├── exceptions.py   # BadRequest/Unauthorized/Forbidden/NotFound/Conflict
    │   ├── exception_handlers.py
    │   └── responses.py    # SuccessResponse, ErrorResponse 형식
    └── domains/
        ├── users/          # 회원가입, 로그인·토큰·기기, 내 정보, 회원 탈퇴 (withdrawal.py)   ✅
        ├── verification/   # 휴대폰 인증번호 (개발용 문자함 dev.py, 발송기 sms.py)          ✅
        ├── recovery/       # 아이디·비밀번호 찾기, 계좌 비밀번호 재설정 시작                  ✅
        ├── products/       # 계좌·카드 상품 조회                                          ✅
        ├── accounts/       # 입출금·예금·적금, 거래내역, 계좌 비밀번호, 해지, 이자(interest.py) ✅
        ├── transfers/      # 이체, 적금 납입 (테이블 없음)                                  ✅
        ├── cards/          # 신용·체크카드, 사용내역, 결제, 청구서                           ✅
        ├── terms/          # 상품 약관 발행·동의 기록, 약관 검색(RAG: 청크·임베딩·검색)       ✅
        └── agent/          # AI 금융 비서
            ├── graph.py        # LangGraph: 모델↔도구 반복 (DB를 모름)
            ├── service.py      # 대화 불러오기·저장, 인용 정리, 이체 초안 확인·취소
            ├── model_client.py # Gemini 연결 (공급자 경계)
            ├── prompts.py      # 시스템 지침
            └── tools/          # 조회·이체 초안·가입 준비·약관 검색 Tool (MCP에서도 재사용)
```

## 도메인 안의 5개 파일

(도메인에 따라 파일이 더 있습니다: 예) `users/withdrawal.py`, `accounts/password.py`·`interest.py`, `agent/graph.py`)

```
요청 → router → service → repository → DB
              (schemas, models는 옆에서 사용)
```

| 파일 | 역할 | 비유 |
|---|---|---|
| `router.py` | URL을 받아서 service를 호출하고 응답을 감쌈 | 창구 직원: 접수만 |
| `service.py` | 규칙 검사, 처리 순서, 트랜잭션 | 팀장: "잔액 충분해? 한도 넘었어?" |
| `repository.py` | DB 조회·저장만 | 금고 담당 |
| `models.py` | DB 테이블 정의 (SQLAlchemy) | 장부 양식 |
| `schemas.py` | 요청·응답 데이터 모양 (Pydantic) | 신청서 양식 |

`users` 도메인이 완성된 예시입니다. 새 기능은 이 도메인을 보고 같은 방식으로 작성합니다.

## 도메인끼리 의존하는 방향

```
users ◀── accounts ◀── transfers
  ▲          ▲   ▲
  │          │   └──── agent/tools   (조회·이체 초안·가입 준비: 기존 service를 재사용)
  └──────── cards        (체크카드 결제 → 연결 계좌 출금)
products ◀── accounts, cards   (개설·발급 시 상품 종류 검증)
verification ◀── users, recovery, accounts   (휴대폰 인증 증표: 가입·찾기·비밀번호 재설정)
terms ◀── accounts, cards, agent/tools       (가입 때 약관 동의 확인·기록, 약관 검색)
```

- 다른 도메인의 데이터가 필요하면 **service에서 상대 도메인의 repository**를 호출합니다. 다른 도메인의 router는 호출하지 않습니다.
- 돈이 움직이는 처리(이체, 납입, 카드 결제)는 `async with db.begin():` 블록 **하나** 안에서 잔액 변경과 History 저장을 모두 끝냅니다.

## ERD 테이블 → 코드 위치

| ERD 테이블 | 모델 클래스 | 파일 |
|---|---|---|
| User | `User` | `domains/users/models.py` |
| Account_Products, Card_Products | `AccountProduct`, `CardProduct` | `domains/products/models.py` |
| CheckingAccount, DepositAccount, SavingsAccount | `CheckingAccount`, `DepositAccount`, `SavingsAccount` | `domains/accounts/models.py` |
| Chenking/Deposit/Savings_Account_History | `CheckingAccountHistory` 외 2개 | `domains/accounts/models.py` |
| CreditCard, DebitCard | `CreditCard`, `DebitCard` | `domains/cards/models.py` |
| Credit/Debit_Card_History | `CreditCardHistory`, `DebitCardHistory` | `domains/cards/models.py` |

ERD 이후에 생긴 테이블(설계 외):

| 테이블 | 모델 클래스 | 파일 |
|---|---|---|
| refresh_tokens, user_devices | `RefreshToken`, `UserDevice` | `domains/users/models.py` |
| verification_codes | `VerificationCode` | `domains/verification/models.py` |
| terms_versions, product_terms_revisions·items, terms_consents, terms_index_generations·entries, terms_chunks | `TermsVersion` 외 6개 | `domains/terms/models.py` |
| agent_conversations, agent_messages, agent_transfer_drafts | `AgentConversation`, `AgentMessage`, `TransferDraft` | `domains/agent/models.py` |
| credit_card_bills | `CreditCardBill` | `domains/cards/models.py` |

> ERD의 `Chenking` 오타는 코드에서 `checking`으로 씁니다. 테이블 이름은 snake_case 복수형입니다(예: `checking_accounts`).

## 역할 분담 예시 (초기 5개 도메인 기준)

도메인 폴더 단위로 나누면 서로 같은 파일을 고칠 일이 적습니다.

| 담당 | 폴더 |
|---|---|
| A | `products`, `users`(PATCH 추가) |
| B | `accounts` |
| C | `transfers` (`accounts` repository 사용) |
| D | `cards` (`accounts` repository 사용) |

`core/`와 `main.py`는 공용이므로 수정하기 전에 팀에 공유합니다.
