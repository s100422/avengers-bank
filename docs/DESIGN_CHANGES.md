# 설계 변경 기록

팀 초기 설계(docs/ERD.md, API_ENDPOINTS.md, PROJECT_STRUCTURE.md 및 원본 코드)를 바탕으로 **개인으로 작업하면서** 바꾼 것, 구현한 것, 앞으로 할 것을 모아 둔 문서다.
팀 회의 때 이 문서 하나로 "무엇을, 왜, 어떻게" 바꿨는지 공유하는 게 목적이다. (최종 갱신: 2026-11-09, 변경 항목 C-001 ~ C-105)

| 알고 싶은 것 | 볼 곳 |
|---|---|
| 초기 설계에서 무엇이 달라졌나 | **1부** |
| 지금 어디까지 구현됐고 어떻게 확인했나 | **2부** |
| 앞으로 무엇을 만들고 무엇을 정해야 하나 | **3부**(요약)와 [NEXT_STEPS.md](NEXT_STEPS.md)(현재 목록) |
| 하나하나의 이유·변경 전후·검증 | **4부** (C-001 ~ C-106) |
| 처음 코드 리뷰 9개 항목은 어떻게 됐나 | 부록 A |
| 시간순 전체 목록, 작성 규칙, 템플릿 | 부록 B, 작성 규칙 |

---

## 1부. 초기 설계에서 바꾼 것

팀의 ERD·API 문서·원본 코드와 **달라진 것**이다. 원본 `AvengersBankDiagram.drawio`는 **고치지 않고 그대로** 뒀다. 현재 구조는 `AvengersBankDiagram_v2.drawio`(C-027)에 있다. 원본은 내가 바꾸기 전부터 ERD.md·코드와 달랐다(`User` 표에 `hashed_password`·`nick_name`이 없음).

### 1-1. DB 스키마(ERD)

| 대상 | 초기 설계 | 변경 | 이유 | ID |
|---|---|---|---|---|
| `credit_card_bills` (신규 테이블) | 없음 | 청구서: 이용 기간·합계·납부 예정일·상태(UNPAID/PAID)·납부 시각 | 청구·납부를 기록할 곳이 없었다 | C-010 |
| `credit_card_histories.bill_id` | 없음 | 어느 청구서에 포함됐는지 (NULL = 청구 전) | 같은 사용내역이 두 번 청구되지 않게 | C-010 |
| `credit_cards.credit_limit` | 없음 | 카드별 신용 한도 (발급 때 상품 한도를 복사) | 한도 개념이 없었다 | C-011, C-013 |
| `card_products.credit_limit` | 없음 | 신용 상품은 한도 필수, 체크 상품은 NULL | 한도를 상품별 고정값으로 정함 | C-013 |
| `credit_cards.accumulated_amount` | 누적 사용액 | 신용카드는 **미결제액**(결제하면 증가, 청구서 납부하면 감소). 이름도 `outstanding_amount`로 바뀜 | 누적액으로는 한도 검사를 할 수 없다 | C-012, C-035 |
| 거래내역 `from_account`, `sending_account` | 컬럼 2개 | `counterpart_account` 1개로 통합 | 한 줄에는 항상 하나만 값이 있다 | C-007 |
| 거래내역 `change_amount` / `deposit_amount` | 이름·부호 규칙이 제각각 | `amount`로 통일, **항상 양수**(방향은 `type`) | 금액 합계에서 부호 혼용 방지 | C-008 |
| 거래내역 `balance_after` | 없음 | 거래 후 잔액 추가 | 시점별 잔액 표시, 장부 검증 | C-008 |
| 인덱스 | FK 컬럼에 없음 | `user_id`, 카드 `checking_account_id`, 거래내역 `(계좌, 시각)` | 조회와 1일 한도 합계 성능 | C-003 |
| CHECK 제약 | 없음 | 잔액 ≥ 0, 날짜 1~31, 상품 type, 금액 > 0, 청구서 상태, 한도 범위 등 (최초 마이그레이션 기준 20개) | 서비스 코드에 버그가 있어도 잘못된 값이 저장되지 않게 | C-004, C-008, C-010, C-011, C-013 |

### 1-2. 규칙·API 설계

| 항목 | 초기 설계 | 변경 | ID |
|---|---|---|---|
| 계좌번호 발급 | 3개 테이블을 모두 조회해 중복 방지 | 종류별 앞자리(입출금 `110-`, 예금 `120-`, 적금 `220-`)로 테이블 간 충돌을 없애고, 같은 테이블 안의 중복은 unique 제약으로 잡아 새 번호로 재시도 | C-006 |
| 카드번호 | 형식 미정 | 신용 `4000-`, 체크 `5000-` 앞자리, 같은 방식으로 재시도 | C-023 |
| "오늘"의 기준 (1일 이체 한도) | 미정 | 한국 시간(KST) 00:00부터, UTC로 바꿔 `date >= 시각`으로 비교 | C-009, 구현 C-022 |
| 동시 요청 | "한 트랜잭션으로"만 | **먼저 잠그고 잠근 뒤에 검사**, 잠금 순서 고정(입출금 계좌 → 예금·적금 → 카드 → 청구서). ERD 규칙 9 | C-017 |
| 자기 계좌로 이체 | 언급 없음 | 거부 (`SAME_ACCOUNT_TRANSFER`) | C-005 |
| 신용카드 청구 | 없음 | 스케줄러 없이 **본인이 API로** 생성·납부. 이용 기간 = 지난달, 납부 예정일 = 다음 달 결제일 | C-010, 구현 C-023 |
| 신용 한도를 정하는 방법 | 없음 | 상품별 고정(요청으로 받지 않음) | C-013 |
| 거래내역 `type` 값 | 예시만 있음 | 7개 값을 실제로 사용 (`NEXT_STEPS.md` 1-8에서 확정) | C-022, C-023 |
| API 요청·응답 모양 | 경로와 설명만 | 개설·이체·결제·청구서·내 정보 수정의 요청·응답을 구현하면서 정함 | C-020, C-022, C-023, C-024 |

### 1-3. 환경·원본 코드 수정

| 항목 | 변경 | ID |
|---|---|---|
| `.env.examples` | `.env.example`로 파일 이름 변경 (문서와 일치) | C-001 |
| 회원가입 | 같은 아이디로 동시에 가입하면 500이던 것을 409로 (원본 코드 버그 수정) | C-002 |
| 마이그레이션 | 최초 마이그레이션을 저장소에 포함, README 절차 변경 (각자 만들면 충돌) | C-014 |
| `docker-compose.yml` | 로컬 PostgreSQL을 명령 한 줄로 띄움 (신규) | C-015 |
| DB 호스트 | `localhost` → `127.0.0.1`, Windows `fastapi run` 주의사항 (README) | C-016 |
| 로그인 | 없는 아이디는 비밀번호 검증을 건너뛰어 응답 시간으로 아이디 존재를 알 수 있던 것을 수정 (원본 코드 보안 수정, 응답 시간 차이 45배 → 1.01배) | C-026 |
| `get_current_user` | **코드 변경 없음.** 초기 리뷰 지적("커넥션 2개")이 과장이었음을 정정하고 이유를 주석으로 남김 | C-018 |

### 1-4. 팀 설계에 없던 것을 추가한 것

| 항목 | 내용 | ID |
|---|---|---|
| 개발용 충전 API | `POST /dev/accounts/checking/{id}/charge`. 설정(`ENABLE_DEV_ENDPOINTS`)이 켜졌을 때만 열림, 기본은 꺼짐 | C-021 |
| 시드 스크립트 | `uv run python -m avengers_bank.seed` (상품 데이터) | C-019 |
| 조회 페이징 | 계좌 거래내역·카드 사용내역에 `limit`/`offset` | C-020, C-023 |
| 입력 상한·한도 기본값 | 금액 상한 1조 원, 이체 한도 기본값 | C-020 |
| 종류 차이 표 | `accounts/kinds.py`, `cards/kinds.py`로 입출금·예금·적금 / 신용·체크의 차이를 한 곳에 모음 | C-020, C-023 |
| PostgreSQL 검증 스크립트 | `scripts/`: 동시 충전·이체·카드 결제의 잠금 검증, 번호 중복 오류 메시지 확인. 개발용 DB에서만, 수동 실행 | C-025 |
| ERD 다이어그램 v2 | `docs/AvengersBankDiagram_v2.drawio`: 현재 모델에서 자동 생성(`scripts/generate_erd_drawio.py`), 노란 칸 = 초기 설계에서 바뀐 곳. 원본 drawio는 수정하지 않음 | C-027 |

**공용 파일을 건드린 것** (PROJECT_STRUCTURE.md는 `core/`·`main.py`를 수정하기 전에 팀에 공유하라고 되어 있다): `main.py`(개발용 라우터 등록 3줄, C-021), `core/config.py`(`enable_dev_endpoints`, C-021), `core/timezone.py`(새 파일, C-020·C-022·C-023), `core/security.py`(`DUMMY_HASH`, C-026).

---

## 2부. 구현 현황

| 도메인 | 엔드포인트 | 상태 | 근거 |
|---|---|---|---|
| users | 4 / 4 | ✅ 회원가입·로그인·내 정보 조회는 팀 원본, **내 정보 수정(`PATCH /users/me`)은 C-024에서 구현**. 소스에 남은 TODO 없음. 토큰 갱신·로그아웃(`POST /users/token/refresh`, `POST /users/logout`)은 C-083, 입력 규칙 C-084. **토큰 쿠키 전환 + 기기 등록(`/users/login/device*`, `/users/me/devices`)은 C-096** | C-024, C-083, C-084, C-096 |
| products | 4 / 4 | ✅ 구현 | C-019 |
| accounts | 7 / 7 | ✅ 구현 (예금은 개설 때 가입 금액을 필수로 입금 C-076·C-079, 상품별 최소 가입 금액 C-080). 설계 외 추가: 해지 C-043, 계좌 비밀번호 C-092, **이자 미리 보기 `GET /accounts/{type}/{id}/interest-preview` C-104** | C-020, C-076, C-079, C-080, C-104 |
| transfers | 2 / 2 | ✅ 구현 (`POST /transfers/deposit`는 C-079에서 삭제: 예금은 가입 후 추가 입금 불가) | C-022, C-079 |
| cards | 10 / 10 | ✅ 구현 | C-023 |
| dev (설계 외) | 1 | ✅ 구현 | C-021 |
| terms (설계 외) | 3 + 가입 5종 동의 + Agent Tool 2개 | ✅ 구현. 예금 약관 4개는 1.1.0으로 개정·발행 (나머지 17개는 1.0.0) | C-075, C-081 |
| agent (설계 외) | 4 (`/agent/chat`, 대화 조회, 이체 확인·취소) | ✅ 구현. Tool 8개(조회·이체 초안·**예·적금 가입 준비 카드**·약관 검색), 모델↔도구 반복은 **LangGraph**, 계좌는 이름으로 찾기, 한도 오류에 금액 | C-070, C-071, C-099 ~ C-103 |
| 인프라 | 최초 마이그레이션, docker compose, 시드(상품 `seed.py`, 데모 사용자·계좌 `seed_demo.py`) | ✅ | C-014, C-015, C-019, C-078 |

### 검증 현황

| 방법 | 범위 | 결과 |
|---|---|---|
| pytest (SQLite) | 전체 | 465개 통과, 3개 skip (2026-11-09, C-104 커밋 기준. skip은 PostgreSQL이 필요한 테스트로, 같은 경로는 `scripts/`의 PG 스크립트로 확인). PG 동시성 스크립트는 C-097 이후 다시 돌리지 않았다(그 뒤 변경은 잠금 로직을 건드리지 않음) |
| 실제 PostgreSQL: 마이그레이션 | upgrade → downgrade → upgrade, `alembic check` | 통과 (C-014) |
| 실제 PostgreSQL: 동시성 | 충전(C-021), 이체·적금·예금(C-022), 카드 결제·청구서(C-023), 해지(C-043, C-079에서 적금 납입 경합으로 수정), 예금 가입 금액 입금(C-079), 토큰 동시 갱신(C-083), 동시 로그인·단일 세션(C-088) | 통과. 잠금을 뺀 대조군에서는 문제가 재현됨. **`scripts/`로 다시 실행 가능**(C-025), 로그인 잠금·인증번호 발송(C-090·C-091), 계좌 비밀번호(C-092). 회원 탈퇴 ↔ 입금(C-095). **스크립트 12개 모두 통과(2026-11-09)** |
| 서버를 띄운 HTTP 확인 | 계좌, 충전, 이체, 카드, 청구서 | 통과 |

- SQLite는 `FOR UPDATE` 잠금을 무시한다. **pytest가 통과해도 동시성은 검증된 것이 아니다**(C-017 결정: pytest는 SQLite 유지).
- PostgreSQL 동시성 검증은 `scripts/`의 스크립트로 한다(수동 실행, `scripts/README.md`). 서비스 함수를 직접 호출하므로 라우터 계층은 확인하지 않고, 코드를 바꾼 뒤에는 다시 실행해야 한다.

---

## 3부. 앞으로 할 일과 정할 것

### 3-1. 앞으로 할 일·정할 것 → [NEXT_STEPS.md](NEXT_STEPS.md)

목록이 길고 계속 바뀌어서 `docs/NEXT_STEPS.md`로 옮겼다(단계별 · 선택지 · 추천 · 규모 · 진행 상태). **그 파일이 현재 목록이다.**
결정하고 구현하면 이 문서 4부에 C-항목을 쓰고, 아래 3-2에 "이미 정한 것"을 추가하고, NEXT_STEPS.md의 상태를 바꾼다.

### 3-2. 이미 정한 것 (되돌리지 않기)

| 결정 | 날짜 | ID |
|---|---|---|
| 신용 한도는 상품별 고정 | 2026-11-05 | C-013 |
| 신용카드 발급 장수 제한 없음 (허점을 알고 감수) | 2026-11-05 | C-013 |
| 청구서는 본인이 API로 호출, 부분 납부·연체 이자·리볼빙은 범위 밖 | 2026-11-05 | C-010 |
| pytest는 SQLite 유지, 잠금은 PostgreSQL에서 따로 확인 | 2026-11-05 | C-017 |
| 잔액은 개발용 충전 API로 채움 | 2026-11-05 | C-021 |
| 없는 아이디도 가짜 해시로 비밀번호 검증을 거치게 해서 로그인 응답 시간으로 아이디를 알 수 없게 함 | 2026-11-05 | C-026 |
| 내 정보 수정은 이름·닉네임·전화번호만, 바꿀 수 없는 필드는 422 | 2026-11-05 | C-024 |
| 검증 스크립트는 `scripts/`에 보관하고 수동으로 실행 | 2026-11-05 | C-025 |
| 원본 drawio는 고치지 않고, 현재 구조는 v2 파일로 따로 만든다 | 2026-11-05 | C-027 |
| git으로 버전 관리 시작 (원격 저장소는 아직 없음) | 2026-11-05 | C-028 |
| 임시 값 1-1~1-7(한도·상한·번호 앞자리·시드·201·재시도 5번) 그대로 확정, ruff 도입 안 함 | 2026-11-05 | C-029 |
| 거래내역 type 7개 확정, 예금·적금 거래내역은 `TRANSFER_IN`만 허용(DB CHECK) | 2026-11-05 | C-030 |
| 남의 계좌·카드는 존재 여부를 숨기려고 404로 통일 | 2026-11-05 | C-031 |
| `per_transfer_limit <= daily_transfer_limit`를 DB CHECK로도 강제 | 2026-11-05 | C-032 |
| 만기일 당일부터 예금·적금 입금 거절 (`ACCOUNT_MATURED`) | 2026-11-05 | C-033 |
| 적금·예금은 자유 금액·여러 번 입금 유지 (3-1과 함께 다시 봄) | 2026-11-05 | C-034 |
| 신용카드 미결제액 컬럼은 `outstanding_amount`, 체크카드는 `accumulated_amount` 유지 / 체크카드 결제의 가맹점명은 `counterpart_name`에 저장 | 2026-11-05 | C-035 |
| 카드 사용내역은 `used_amount` 이름 유지 | 2026-11-05 | C-036 |
| 청구서는 이용 기간 직후부터 만들 수 있고 경로는 `bills` 유지 | 2026-11-05 | C-037 |
| 이체의 받는 계좌번호 존재 여부가 드러나는 점은 알고 감수 (이름 확인 단계 없음) | 2026-11-05 | C-038 |
| 회원가입은 중복 아이디를 409로 알려 줌 (감수) | 2026-11-05 | C-039 |
| 로그인 실패 제한은 프로세스 메모리 카운터((아이디,IP) 5회 / IP 20회, 15분), 서비스로 쓸 때 다시 검토 | 2026-11-05 | C-040 |
| 이름·전화번호는 길이만 검증 (형식 검증 없음) | 2026-11-05 | C-041 |
| API 시각은 UTC로 내려 주고 KST 변환은 화면에서 | 2026-11-05 | C-042 |
| 해지는 원금+이자를 내 입출금 계좌로, 계좌는 `status`로 남김, 이자는 입금별 단리 일할(만기 후 이자 없음, 중도 해지는 금리 50%) | 2026-11-05 | C-043 |
| 카드는 정지·해제·해지만 지원(재발급·한도 변경 없음), 신용카드 해지는 미결제액 0일 때만 | 2026-11-05 | C-044 |
| 비밀번호 변경은 현재 비밀번호 확인 + 로그인과 같은 실패 한도, 기존 토큰은 폐기하지 않음, 회원 탈퇴는 안 함 | 2026-11-05 | C-045 |
| `GET /health`는 DB까지 확인하고 실패 원인은 로그에만 남김 / 수수료·예약 이체는 하지 않음 | 2026-11-05 | C-046 |
| CORS 허용 주소는 `CORS_ORIGINS`(쉼표 구분) 환경변수, 기본값은 localhost:5173 | 2026-11-05 | C-047 |
| compose의 DB 비밀번호는 `.env`의 `POSTGRES_PASSWORD`, 이미지는 `postgres:17-trixie`(기존 볼륨과 같은 Debian) | 2026-11-05 | C-048 |
| 마이그레이션 파일은 `날짜_시각-리비전ID_설명.py` 이름, DB `server_default`는 필요할 때 | 2026-11-05 | C-049 |
| 개발용 API가 켜져 있으면 시작 때 경고(막지는 않음) / Windows `fastapi run`은 README 안내로 충분 | 2026-11-05 | C-050 |
| 동시성 검증 스크립트는 수동 실행 유지, 원본 drawio(v1)는 그대로 | 2026-11-05 | C-051 |
| 배포는 Docker 이미지 + Caddy(자동 HTTPS) + 외부 DB, API 포트는 내부 네트워크에만 열고 워커는 1개 | 2026-11-05 | C-052 |
| 첫 배포는 도메인 없이 HTTP(`DOMAIN=:80`), DB는 RDS PostgreSQL | 2026-11-06 | C-053 |
| AWS 첫 배포: EC2 + RDS PostgreSQL 17, sslip.io로 도메인 없이 HTTPS, 저장소 공개 | 2026-11-06 | C-054 |
| 프론트엔드는 같은 저장소 `frontend/`에 Next.js(클라이언트 컴포넌트만), CORS는 개발 포트 5173으로 맞춤 | 2026-11-06 | C-055 |
| 배포 절차는 README가 아니라 `docs/DEPLOY.md`에 흐름 위주로, 개인 인프라 값은 자리 표시로 | 2026-11-06 | C-056 |
| 프론트는 하단 탭(홈·이체·상품·내 정보)으로 오가고, 있는 API만 화면으로 꺼냄 | 2026-11-06 | C-057 |
| 프론트 디자인은 시안 A(피치 카드형), 서체 Pretendard, 휴대폰은 하단 탭·PC는 왼쪽 메뉴, 라이트 모드만 | 2026-11-06 | C-058 |
| 새 기기 로그인의 개발용 문자함은 가려진 번호가 아니라 사용자가 입력한 번호로 연다 | 2026-11-09 | C-097 |
| 가입 화면의 입력값은 바뀔 때마다 보관해 약관 전문·다른 화면에 다녀와도 유지하고, 계좌 비밀번호는 메모리에만 둔다 | 2026-11-09 | C-098 |
| AI 비서는 계좌를 id가 아니라 사용자가 말한 이름으로 가리키고 서버가 찾는다(없음·여럿이면 후보를 돌려 되묻기) | 2026-11-09 | C-099, C-100 |
| AI 비서의 모델↔도구 반복은 LangGraph(`langgraph`만 사용, `langchain-google-genai`·checkpointer는 쓰지 않음). 대화는 `agent_messages` DB 저장 유지 | 2026-11-09 | C-101 |
| 이체 한도 오류에 한도 금액을 담는다(모델이 한도를 지어내지 않게) | 2026-11-09 | C-102 |
| AI 비서는 예·적금 가입을 하지 않고 가입 화면을 미리 채우는 카드까지만 만든다(약관 동의·계좌 비밀번호는 화면에서). 만기 날짜는 서버가 계산 | 2026-11-09 | C-103 |
| 계좌 상세: 해지하기는 맨 아래 작은 링크, 비밀번호 재설정은 입력칸을 누를 때·미설정·잠김일 때만 표시. 예·적금 이자 미리 보기(적금 만기는 매월 납입 계속 가정) | 2026-11-09 | C-104 |

> C-059 ~ C-096에서 정한 것은 이 표에 옮기지 못했다. 각 C-항목의 "결정"·"논의 포인트"와 [인수인계.md](인수인계.md) 5장을 본다.

---

## 4부. 변경 상세

### C-001. 환경변수 예시 파일명을 문서와 일치

- **날짜:** 2026-11-04
- **분류:** 문서
- **상태:** 적용
- **바뀐 파일:**
  - `.env.examples` → `.env.example` (파일 이름만 변경, 내용 동일)

#### 변경 전
README.md와 PROJECT_STRUCTURE.md는 `.env.example`을 안내하는데, 실제 파일은 `.env.examples`였다.
```bash
cp .env.example .env   # README.md 19번 줄
```

#### 변경 후
실제 파일을 `.env.example`로 바꿔서 문서와 맞췄다. 문서는 수정하지 않았다.

#### 이유
- 재현: 새 팀원이 README 순서대로 `cp .env.example .env`를 치면 "No such file"로 실패한다. 첫 실행 단계에서 막힌다.
- 문서 2곳을 고치는 것보다 파일 1개 이름을 바꾸는 게 변경 범위가 작고, `.env.example`이 일반적인 관례다.

#### 영향 범위
- 코드 영향 없음. 이 파일을 참조하는 코드는 없다.

#### 검증
- `ls`로 `.env.example`이 있는지, `grep`으로 문서 경로가 일치하는지 확인했다.

#### 팀 논의 포인트
- 팀 저장소에서도 파일 이름을 바꿔야 한다.

---

### C-002. 동시 회원가입 중복 시 500 → 409

- **날짜:** 2026-11-05
- **분류:** 동시성
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/users/service.py` (`UserService.signup`)
  - `tests/test_users.py` (`test_signup_race_unique_violation_returns_409` 추가)

#### 변경 전
```python
async with db.begin():
    if await user_repository.find_by_login_id(db, data.login_id) is not None:
        raise ConflictException(
            code="LOGIN_ID_ALREADY_EXISTS",
            message="이미 사용 중인 아이디입니다.",
        )
    user = User(...)
    await user_repository.save(db, user)
    await db.refresh(user)
```

#### 변경 후
```python
duplicate = ConflictException(
    code="LOGIN_ID_ALREADY_EXISTS", message="이미 사용 중인 아이디입니다."
)

try:
    async with db.begin():
        if await user_repository.find_by_login_id(db, data.login_id) is not None:
            raise duplicate
        user = User(...)
        await user_repository.save(db, user)
        await db.refresh(user)
except IntegrityError:
    # 동시 가입 요청이 위 조회를 함께 통과하면 DB unique 제약이 최종 판정한다.
    raise duplicate from None
```

#### 이유
- 원래 코드는 "조회 → 없으면 insert" 순서였다. 두 단계 사이에 다른 요청이 끼어드는 것을 막을 수 없다.
- 재현: A와 B가 동시에 `login_id="ironman"`으로 가입한다.
  1. 두 요청 모두 조회 단계에서 "없음"을 받는다.
  2. A의 insert는 성공한다.
  3. B의 insert는 `users.login_id`의 unique 제약에 걸려 `IntegrityError`가 난다.
  4. 이 예외는 처리되지 않으므로 `unexpected_error_handler`로 가서 **500 INTERNAL_SERVER_ERROR**가 응답된다.
- 실제로는 아이디 중복이므로 409 `LOGIN_ID_ALREADY_EXISTS`가 맞다.
- 조회 단계는 그대로 남겼다. 평소 중복은 조회에서 걸러지고, unique 제약은 동시 요청일 때만 마지막 방어선 역할을 한다.

#### 영향 범위
- API 응답 형식 변경 없음. 동시 요청 상황에서 500이 409로 바뀐다.
- `users` 테이블에 unique 제약은 `login_id` 하나뿐이다. 그래서 `IntegrityError`가 나면 아이디 중복으로 보는 게 맞다. **나중에 `phone` 같은 다른 unique 컬럼이 생기면** 제약 이름으로 구분하도록 고쳐야 한다.

#### 검증
- 새 테스트를 추가했다. 첫 가입 후 `find_by_login_id`가 항상 None을 돌려주도록 바꿔서 조회 단계를 통과시키고, insert에서 unique 제약에 걸리게 했다. 그 결과 409와 `LOGIN_ID_ALREADY_EXISTS`가 나오는 것을 확인했다.

#### 팀 논의 포인트
- 계좌번호(`account_num`)와 카드번호(`card_num`) 발급에도 같은 문제가 있다. 이때는 409를 돌려주기보다 **번호를 새로 만들어 재시도**하는 방식이 맞을 것 같다.

---

### C-003. FK·거래내역 조회 컬럼에 인덱스 추가

- **날짜:** 2026-11-05
- **분류:** DB 스키마
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/accounts/models.py`
  - `src/avengers_bank/domains/cards/models.py`

#### 변경 전
```python
user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), nullable=False)
# credit_cards / debit_cards
checking_account_id: Mapped[int] = mapped_column(
    ForeignKey("checking_accounts.checking_account_id"), nullable=False
)
# history 테이블: 인덱스 없음
```

#### 변경 후
```python
# checking/deposit/savings_accounts, credit/debit_cards
user_id: Mapped[int] = mapped_column(
    ForeignKey("users.user_id"), nullable=False, index=True
)
# credit_cards / debit_cards
checking_account_id: Mapped[int] = mapped_column(
    ForeignKey("checking_accounts.checking_account_id"), nullable=False, index=True
)
# history 테이블: (계좌 또는 카드 ID, 시각) 복합 인덱스
__table_args__ = (
    Index("ix_checking_account_histories_account_date", "checking_account_id", "date"),
)
```

| 테이블 | 추가한 인덱스 | 쓰이는 조회 |
|---|---|---|
| `checking/deposit/savings_accounts` | `user_id` | `GET /accounts` (내 계좌 전체) |
| `credit_cards`, `debit_cards` | `user_id`, `checking_account_id` | `GET /cards`, 계좌에 연결된 카드 조회 |
| `checking_account_histories` | `(checking_account_id, date)` | 거래내역 조회, **1일 이체 한도 합계** |
| `deposit_account_histories` | `(deposit_account_id, date)` | 거래내역 조회 |
| `savings_account_histories` | `(savings_account_id, date)` | 거래내역 조회 |
| `credit_card_histories` | `(credit_card_id, time)` | 사용내역 조회 |
| `debit_card_histories` | `(debit_card_id, time)` | 사용내역 조회 |

#### 이유
- PostgreSQL은 PK와 unique 컬럼에만 인덱스를 자동으로 만든다. **FK 컬럼에는 만들지 않는다.**
- 재현: 거래내역이 100만 건 쌓인 상태에서 계좌 하나의 거래내역을 조회하거나 이체 한도를 검사하면, 매번 테이블 전체를 훑는다(Seq Scan). 이체 한도 검사는 이체할 때마다 실행되므로, 이체 API 전체가 느려진다.
- history 테이블에 복합 인덱스를 쓴 이유는 다음과 같다.
  - 조회 조건이 항상 "특정 계좌 + 날짜 범위/정렬"이다.
  - 복합 인덱스 하나로 계좌 ID 단독 조회까지 커버되므로, 단일 인덱스를 따로 두지 않았다.
- `product_id`에는 인덱스를 넣지 않았다. 상품 기준으로 계좌를 찾는 API가 없기 때문이다.

#### 영향 범위
- 테이블 구조와 API는 그대로다. insert할 때 인덱스 갱신 비용이 조금 늘어난다.
- 아직 마이그레이션 파일이 없어서, 최초 마이그레이션에 함께 포함된다.

#### 검증
- 기존 테스트가 모두 통과했다. SQLite `create_all`에서도 인덱스가 생성된다.
- 성능 측정은 하지 않았다.

#### 팀 논의 포인트
- 앞으로 다른 조회 패턴이 생기면 인덱스를 추가하면 된다. 예: 카드 사용처(`place_of_use`)로 검색하는 기능.

---

### C-004. 잔액·날짜·상품 종류 CHECK 제약 추가

- **날짜:** 2026-11-05
- **분류:** DB 스키마
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/accounts/models.py`
  - `src/avengers_bank/domains/cards/models.py`
  - `src/avengers_bank/domains/products/models.py`
  - `tests/test_constraints.py` (새 파일)

#### 변경 전
값의 범위를 DB에서 막는 제약이 없었다. 주석으로만 범위를 적어 두었다.
```python
type: Mapped[str] = mapped_column(String(20), nullable=False)  # CHECKING / DEPOSIT / SAVINGS
monthly_deposit_date: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 매월 납입일(1~31)
payment_date: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 매월 결제일(1~31)
```

#### 변경 후
| 테이블 | 제약 이름 | 조건 |
|---|---|---|
| `checking_accounts` | `ck_checking_accounts_balance_non_negative` | `balance >= 0` |
| `deposit_accounts` | `ck_deposit_accounts_balance_non_negative` | `balance >= 0` |
| `savings_accounts` | `ck_savings_accounts_balance_non_negative` | `balance >= 0` |
| `savings_accounts` | `ck_savings_accounts_monthly_deposit_date_range` | `monthly_deposit_date BETWEEN 1 AND 31` |
| `credit_cards` | `ck_credit_cards_payment_date_range` | `payment_date BETWEEN 1 AND 31` |
| `account_products` | `ck_account_products_type` | `type IN ('CHECKING', 'DEPOSIT', 'SAVINGS')` |
| `card_products` | `ck_card_products_type` | `type IN ('CREDIT', 'DEBIT')` |

```python
__table_args__ = (
    CheckConstraint("balance >= 0", name="ck_checking_accounts_balance_non_negative"),
)
```

#### 이유
- ERD.md에는 "DB 구조만으로는 막을 수 없는 부분이라 애플리케이션 코드에서 보장"한다고 되어 있다. 하지만 위 규칙들은 **DB CHECK 제약으로 막을 수 있다.**
- 서비스 코드에서 잔액 검사를 하더라도, DB가 마지막 방어선이 된다.
  - 재현 1: 이체 코드에 행 잠금이 빠진 버그(검토 항목 2번)가 있으면, 동시 출금 두 건이 모두 잔액 검사를 통과한다. 그러면 잔액이 -10,000원으로 저장된다. CHECK 제약이 있으면 두 번째 출금이 `IntegrityError`로 실패하고 롤백된다. **잘못된 돈이 장부에 남지 않는다.**
  - 재현 2: 관리자 SQL이나 시드 스크립트로 상품 `type='Checking'`(대소문자 오타)이 들어가면, 계좌 개설 시 상품 종류 검증이 계속 실패한다. 원인을 찾기도 어렵다.
- 제약 이름을 직접 붙인 이유: Alembic 마이그레이션과 에러 로그에서 어떤 제약에 걸렸는지 알아보기 쉽다.

#### 영향 범위
- 정상적인 요청에는 영향이 없다.
- 서비스 코드에서 검사를 빠뜨리면 400이 아니라 500(`IntegrityError`)이 난다. 그러니 **서비스 검사는 그대로 해야 한다.** CHECK는 대체 수단이 아니라 보험이다.
- 상품 `type` 값 목록을 바꾸려면 마이그레이션이 필요하다.

#### 검증
- `tests/test_constraints.py`를 새로 만들었다. 다음 다섯 가지 경우에 각각 `IntegrityError`가 나는 것을 확인했다.
  - 잘못된 상품 type 2종(계좌·카드)
  - 음수 잔액
  - 납입일 32
  - 결제일 0
- 테스트 DB는 SQLite이고, SQLite도 CHECK 제약을 지킨다.

#### 팀 논의 포인트
- 아래 제약은 이번에 넣지 않았다. 추가할지 정해야 한다.
  - `per_transfer_limit > 0`
  - `daily_transfer_limit >= per_transfer_limit`
  - `monthly_payment > 0`
  - 거래내역의 금액 `> 0`: 부호를 쓰는 방식(출금을 음수로 저장)을 쓸지 먼저 정해야 한다.
  - `accumulated_amount >= 0`
- 거래내역 `type` 값 목록이 정해지면 CHECK 제약도 같이 넣는 게 좋다.

---

### C-005. 이체 TODO에 자기 계좌 이체 거부 추가

- **날짜:** 2026-11-05
- **분류:** 문서
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/transfers/service.py` (TODO 주석)

#### 변경 전
```python
#       2. 받는 계좌 찾기 (NotFoundException)
#       3. 잔액, 1회 한도, 1일 한도 검사 (BadRequestException)
```

#### 변경 후
```python
#       2. 받는 계좌 찾기 (NotFoundException)
#          받는 계좌 == 보내는 계좌면 거부 (BadRequestException, code="SAME_ACCOUNT_TRANSFER")
#       3. 잔액, 1회 한도, 1일 한도 검사 (BadRequestException)
```

#### 이유
- 재현: `from_checking_account_id=1`이고 `to_account_num`이 1번 계좌의 번호이면 어떻게 되는지 보자.
  - 같은 계좌에서 빼고 더하므로 잔액은 그대로다.
  - 그런데 거래내역에는 출금·입금 2줄이 남고, **1일 이체 한도는 소진**된다.
  - 행 잠금을 두 번 거는 코드라면, 같은 행을 두 번 잠그는 경우도 고려해야 한다.
- 의미 없는 요청이므로 처음부터 거부한다.

#### 영향 범위
- 코드 동작 변경 없음(TODO 주석). API_ENDPOINTS.md의 이체 실패 예시에 `400 SAME_ACCOUNT_TRANSFER`를 추가했다(2026-11-05, C-010 작업 때 함께 반영).

#### 검증
- 해당 없음(주석). 이체를 구현할 때 테스트를 추가한다.

#### 팀 논의 포인트
- 에러 코드 이름 `SAME_ACCOUNT_TRANSFER`를 이대로 쓸지 정해야 한다.

---

### C-006. 계좌번호를 종류별 앞자리로 발급 (테이블 간 중복 검사 제거)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용 (설계는 이 항목, 발급 코드는 C-020에서 구현)
- **바뀐 파일:**
  - `docs/ERD.md` (코드 규칙 1번, "팀에서 정해야 할 것")
  - `src/avengers_bank/domains/accounts/service.py` (TODO 주석)
  - `src/avengers_bank/domains/accounts/repository.py` (TODO 주석, `exists_by_account_num` 삭제)

#### 변경 전
ERD.md 규칙 1번:
> **계좌번호 중복 방지:** 계좌 테이블이 3개라서 `account_num`이 테이블 사이에서 겹칠 수 있습니다. 계좌번호는 `accounts.service`에서만 발급하고, 세 테이블을 모두 검사합니다.

```python
# repository.py
# TODO: exists_by_account_num(db, account_num) — 3개 테이블 모두 검사 (계좌번호 중복 방지)
# service.py
#       - 계좌번호 발급은 여기 한 곳에서만 (account_repository.exists_by_account_num으로 중복 검사)
```

#### 변경 후
ERD.md 규칙 1번:
> **계좌번호는 종류별 앞자리로 발급:** 입출금 `110-`, 예금 `120-`, 적금 `220-`로 시작합니다(`110-XXX-XXXXXX`). 앞자리가 달라서 테이블 사이에서 겹치지 않습니다. 계좌번호는 `accounts.service`에서만 발급하고, 같은 테이블 안에서 겹치면(unique 제약 `IntegrityError`) 새 번호로 재시도합니다.

```python
# repository.py
#       계좌번호 중복 검사 메서드는 두지 않는다. 앞자리로 종류가 나뉘므로 테이블 간 중복이 없고,
#       같은 테이블 안의 중복은 unique 제약(IntegrityError)으로 잡아 service에서 재발급한다.
# service.py
#       - 계좌번호 발급은 여기 한 곳에서만. 형식: 종류별 앞자리 + 랜덤
#         입출금 110-XXX-XXXXXX / 예금 120-XXX-XXXXXX / 적금 220-XXX-XXXXXX
#         insert에서 IntegrityError(같은 번호)가 나면 번호를 새로 만들어 재시도 (최대 N회)
```

#### 이유
- 원래 방식은 "세 테이블을 조회하고, 없으면 insert"였다. C-002의 회원가입과 같은 구조라서 **동시 요청에 뚫린다.**
  - 재현: 입출금 계좌 개설과 적금 계좌 개설이 동시에 같은 랜덤 번호 `110-123-456789`를 뽑았다고 하자.
  - 두 요청 모두 세 테이블 조회에서 "없음"을 받는다.
  - 서로 다른 테이블에 insert하므로, 테이블별 unique 제약으로는 막히지 않는다.
  - 결과적으로 **같은 계좌번호가 두 개** 생긴다.
  - 이체는 `to_account_num`으로 받는 계좌를 찾는다. 같은 번호가 둘이면 받는 계좌가 모호해진다.
- 앞자리로 종류를 나누면 테이블 간 충돌은 **구조적으로 불가능**하다. 남는 건 같은 테이블 안의 충돌뿐이고, 이건 DB unique 제약이 동시 요청까지 정확히 막는다.
- 덤으로 생기는 이점: 계좌번호만 보고 종류를 알 수 있다. 이체 시 받는 계좌가 입출금인지 바로 판단된다.

#### 영향 범위
- 아직 발급 코드가 없어서 동작 변경은 없다.
- `account_repository.exists_by_account_num` TODO가 사라졌다. 이 메서드를 쓰려던 팀원 코드가 있다면 바꿔야 한다.
- API_ENDPOINTS.md 응답 예시의 `"220-987-654321"`(적금)은 새 규칙과 맞는다. `"110-555-000111"`(이체 대상 입출금)도 맞는다.

#### 검증
- 해당 없음(설계·주석). 발급 코드를 구현할 때 다음을 테스트한다.
  - 앞자리 형식이 맞는지
  - `IntegrityError`가 나면 재시도하는지

#### 팀 논의 포인트
- **앞자리 값 `110`·`120`·`220`은 내가 임의로 정했다.** 팀이 정하면 바꾼다.
- 재시도 최대 횟수(N)와, N번 모두 실패했을 때의 응답(500? 503?)을 정해야 한다.
- **[해결: C-023에서 신용 `4000-`, 체크 `5000-`로 구현]** 카드번호도 같은 방식을 쓸지 정해야 한다. 예: 신용 `4xxx`, 체크 `5xxx`.

---

### C-007. 거래내역 `from_account`·`sending_account` → `counterpart_account` 통합

- **날짜:** 2026-11-05
- **분류:** DB 스키마
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/accounts/models.py` (`CheckingAccountHistory`, `DepositAccountHistory`, `SavingsAccountHistory`)
  - `docs/ERD.md` (Mermaid 다이어그램, 코드 규칙 6번)
  - ⚠️ `docs/AvengersBankDiagram.drawio`는 **수정하지 않았다**(원본 다이어그램은 팀 소유)

#### 변경 전
```python
# CheckingAccountHistory
from_account: Mapped[str | None] = mapped_column(String(20))
sending_account: Mapped[str | None] = mapped_column(String(20))
# DepositAccountHistory, SavingsAccountHistory
from_account: Mapped[str | None] = mapped_column(String(20))
```
의미(작성자에게 확인함): `from_account`는 입금한 계좌번호, `sending_account`는 내가 보내는 계좌번호다.

#### 변경 후
```python
# 세 history 테이블 공통
# 상대 계좌번호: 입금이면 보낸 계좌, 출금이면 받는 계좌
counterpart_account: Mapped[str | None] = mapped_column(String(20))
```

#### 이유
- 거래 한 줄은 입금이거나 출금이다. 그래서 두 컬럼 중 **항상 하나만 값이 있고 나머지는 NULL**이다.
- 두 컬럼일 때 생기는 문제:
  - "상대 계좌로 검색"하려면 `WHERE from_account = ? OR sending_account = ?`처럼 두 컬럼을 다 봐야 한다.
  - 두 컬럼에 모두 값이 들어가는 잘못된 행을 막으려면 CHECK 제약이 하나 더 필요하다.
  - 이름만 보고 의미를 헷갈리기 쉽다. 실제로 리뷰 때 의미를 작성자에게 물어봐야 했다.
- 방향은 이미 `type`(입금/출금)에 있다. 그래서 "상대 계좌"는 컬럼 하나로 충분하다.
- 예금·적금 history도 같은 이름으로 맞췄다. 세 테이블의 컬럼 구성이 같아지면 거래내역 조회 응답 스키마도 하나로 쓸 수 있다.

#### 영향 범위
- 컬럼 이름과 개수가 바뀐다. 아직 history를 읽고 쓰는 코드가 없어서 깨지는 코드는 없다.
- 마이그레이션 파일이 없으므로 최초 마이그레이션에 그대로 반영된다.
- **drawio 원본과 ERD.md가 이제 다르다.** 팀에 공유할 때 drawio도 고쳐야 한다.

#### 검증
- 기존 테스트 전체 통과(테이블 생성 포함).

#### 팀 논의 포인트
- 원본 ERD 작성자의 의도와 맞는지 확인한다.
- 카드 결제·현금 입금처럼 상대 계좌가 없는 거래는 NULL이다. 카드 결제라면 "가맹점명"을 남기고 싶을 수 있다. 그러면 `counterpart_name` 같은 컬럼을 추가할지 정해야 한다.

---

### C-008. 거래내역 금액 컬럼 `amount`로 통일(항상 양수) + `balance_after` 추가

- **날짜:** 2026-11-05
- **분류:** DB 스키마
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/accounts/models.py` (history 3개 테이블)
  - `docs/ERD.md` (Mermaid 다이어그램, 코드 규칙 6번)
  - `tests/test_constraints.py` (`test_account_history_amount_and_balance_after` 추가)

#### 변경 전
```python
# CheckingAccountHistory
change_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
# DepositAccountHistory, SavingsAccountHistory
deposit_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
# 거래 후 잔액 컬럼 없음, 금액 부호 규칙 없음
```

#### 변경 후
```python
__table_args__ = (
    Index(...),
    CheckConstraint("amount > 0", name="ck_checking_account_histories_amount_positive"),
    CheckConstraint(
        "balance_after >= 0", name="ck_checking_account_histories_balance_after_non_negative"
    ),
)
# 금액은 항상 양수, 입금/출금 방향은 type으로 구분한다.
amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 거래 후 잔액
```
예금·적금 history도 같다. 제약 이름은 테이블별로 다르다(`ck_deposit_...`, `ck_savings_...`).

#### 이유
- **`balance_after` 추가:** 실제 은행 거래내역에는 "거래 후 잔액"이 항상 표시된다.
  - 이 컬럼이 없으면, 특정 시점의 잔액을 보여주려고 첫 거래부터 금액을 모두 더해야 한다. 거래내역이 페이지로 나뉘면 계산할 수도 없다.
  - 장부 검증에도 쓰인다. 계좌의 마지막 `balance_after`는 `checking_accounts.balance`와 같아야 한다. 다르면 어딘가에서 잔액만 바뀌고 History를 안 남긴 버그가 있다는 뜻이다.
- **금액은 항상 양수:** `change_amount`라는 이름은 부호(출금은 음수)를 쓰는 건지 애매했다.
  - 재현: 한 사람은 출금을 `-10000`으로, 다른 사람은 `10000` + `type=WITHDRAW`로 저장한다. 그러면 1일 이체 한도 합계(`SUM`) 결과가 엉망이 된다.
  - 양수로 고정하고 CHECK 제약(`amount > 0`)으로 강제하면, 이런 혼용을 DB가 막는다.
- **이름 `amount`로 통일:** 예금·적금 테이블의 `deposit_amount`는 출금(만기 해지 등)에도 쓰여야 한다. 그런데 이름이 "입금액"이라서 맞지 않는다. 세 테이블이 같은 이름을 쓰면 C-007과 함께 응답 스키마를 공유할 수 있다.

#### 영향 범위
- 컬럼 이름 변경과 컬럼 추가. 아직 history 코드가 없어서 깨지는 코드는 없다.
- 돈이 움직이는 모든 처리는 이제 History를 저장할 때 `balance_after`를 함께 넣어야 한다(NOT NULL). 잔액을 바꾼 **직후의 값**을 같은 트랜잭션 안에서 넣는다.
- 1일 이체 한도 합계는 `SUM(amount) WHERE type = '이체 출금'` 형태가 된다. 그래서 **거래내역 type 값 목록을 먼저 정해야 한다.**

#### 검증
- `test_account_history_amount_and_balance_after`를 추가했다. `amount=0`, `amount=-1000`, `balance_after=-1` 세 경우 모두 `IntegrityError`가 나는 것을 확인했다.
- 전체 테스트 12개 통과.

#### 팀 논의 포인트
- 거래내역 `type` 값 목록을 정해야 한다. 방향을 type으로 구분하므로 이제 필수다. 예: `DEPOSIT`, `WITHDRAW`, `TRANSFER_IN`, `TRANSFER_OUT`, `CARD_PAYMENT`, `SAVINGS_PAYMENT`.
- 목록이 정해지면 `type IN (...)` CHECK 제약도 추가한다.
- 카드 history의 `used_amount`도 `amount`로 맞출지 정해야 한다. 이번에는 바꾸지 않았다.

---

### C-009. 1일 이체 한도의 "오늘" 기준을 KST로 명시

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용 (설계는 이 항목, 구현은 C-022에서 완료)
- **바뀐 파일:**
  - `docs/ERD.md` (코드 규칙 7번 추가)
  - `src/avengers_bank/domains/accounts/repository.py` (`sum_today_transfer_amount` TODO)

#### 변경 전
```python
# TODO: sum_today_transfer_amount(db, checking_account_id) — 1일 이체 한도 검사용
```
"오늘"이 어느 시간대 기준인지 정해져 있지 않았다.

#### 변경 후
```python
# TODO: sum_today_transfer_amount(db, checking_account_id, since) — 1일 이체 한도 검사용
#       since = 오늘 00:00 KST(Asia/Seoul)를 UTC로 바꾼 시각. WHERE date >= since 로 조회
#       (date 컬럼에 함수를 씌우지 않아야 ix_checking_account_histories_account_date 인덱스를 탄다)
```
ERD.md 규칙 7번:
> **하루 기준은 KST:** 1일 이체 한도의 "오늘"은 한국 시간(Asia/Seoul) 00:00부터입니다. 코드에서 오늘 00:00 KST를 UTC 시각으로 바꿔 `date >= 그 시각`으로 조회합니다.

#### 이유
- `date` 컬럼은 `DateTime(timezone=True)`이다. 저장되는 값은 하나의 시점이지만, "오늘"의 시작은 시간대에 따라 다르다.
  - 재현: 서버나 DB 세션이 UTC로 설정된 상태에서 `date::date = CURRENT_DATE`로 오늘을 판단한다고 하자.
  - 한국 시간 **오전 0시~9시** 사이의 이체는 UTC로 "어제"다. 그래서 전날 한도에 합산된다.
  - 사용자는 자정이 지났는데 한도가 초기화되지 않았다고 느낀다. 반대로 오전 9시에 한도가 갑자기 다시 생긴다.
- 기준 시각을 **애플리케이션에서 계산해 파라미터로 넘기면**, 서버와 DB의 시간대 설정과 상관없이 결과가 같다.
- `date >= since` 형태로 조회해야 C-003에서 만든 `(checking_account_id, date)` 인덱스를 쓸 수 있다. `DATE(date)`처럼 컬럼에 함수를 씌우면 인덱스를 못 쓴다.

#### 영향 범위
- 아직 이체 코드가 없어서 동작 변경은 없다.
- Python 3.13 표준 라이브러리 `zoneinfo.ZoneInfo("Asia/Seoul")`를 쓰면 된다.
  - Windows에는 시간대 DB가 없을 수 있어서 `tzdata` 패키지가 필요할 수 있다.
  - 구현할 때 확인하고, 필요하면 의존성에 추가한다.

#### 검증
- 해당 없음(설계·주석). 구현할 때 다음 경계 시각을 테스트한다.
  - KST 23:59 이체 + 다음날 00:01 이체 → 서로 다른 날로 계산되는지
  - UTC 15:00 = KST 00:00

#### 팀 논의 포인트
- 거래내역을 화면에 표시하는 시간대도 KST로 할지 정해야 한다. API는 ISO8601 + 시간대 정보로 내려주고, 화면에서 변환하는 방법도 있다.

---

### C-010. 신용카드 청구서 테이블 `credit_card_bills` + 청구·납부 API 설계

- **날짜:** 2026-11-05
- **분류:** DB 스키마 (+ API 설계)
- **상태:** 적용 (테이블 적용, 청구·납부 API는 C-023에서 구현)
- **바뀐 파일:**
  - `src/avengers_bank/domains/cards/models.py` (`CreditCardBill` 새 모델, `CreditCardHistory.bill_id` 추가)
  - `alembic/env.py` (`CreditCardBill` import 추가: 빠뜨리면 autogenerate가 테이블을 못 본다)
  - `src/avengers_bank/domains/cards/service.py`, `router.py`, `repository.py`, `schemas.py` (TODO 주석)
  - `docs/ERD.md` (다이어그램, 테이블 요약, 규칙 2·8번)
  - `docs/API_ENDPOINTS.md` (cards 엔드포인트 4개, 예시, 범위 밖 명시)
  - `tests/test_constraints.py` (청구서 제약 테스트)
  - ⚠️ `docs/AvengersBankDiagram.drawio`는 수정하지 않음

#### 변경 전
- 신용카드 관련 테이블은 `credit_cards`와 `credit_card_histories`만 있었다.
- `credit_cards.payment_date`(매월 결제일)는 있었지만, 그날 무엇을 얼마나 청구·출금하는지에 대한 구조가 없었다.
- 사용내역이 어느 청구에 포함됐는지 기록하는 컬럼도 없었다.

#### 변경 후
```python
class CreditCardHistory(Base):
    ...
    # 이 사용내역이 포함된 청구서. NULL이면 아직 청구 전
    bill_id: Mapped[int | None] = mapped_column(
        ForeignKey("credit_card_bills.bill_id"), index=True
    )


class CreditCardBill(Base):
    """신용카드 청구서: 이용 기간(전월 1일~말일, KST)의 미청구 사용내역 합계"""

    __tablename__ = "credit_card_bills"
    __table_args__ = (
        UniqueConstraint("credit_card_id", "period_start", name="uq_credit_card_bills_card_period"),
        CheckConstraint("total_amount > 0", name="ck_credit_card_bills_total_amount_positive"),
        CheckConstraint("period_end >= period_start", name="ck_credit_card_bills_period_order"),
        CheckConstraint("status IN ('UNPAID', 'PAID')", name="ck_credit_card_bills_status"),
        CheckConstraint(
            "(status = 'PAID') = (paid_at IS NOT NULL)",
            name="ck_credit_card_bills_paid_at_matches_status",
        ),
    )

    bill_id, credit_card_id(FK), period_start, period_end, total_amount,
    due_date, status(기본 UNPAID), paid_at(NULL), created_at
```

새 API (모두 🔒, 본인 카드만):

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/cards/credit/{card_id}/bills` | 청구서 생성. body `{"year_month": "2026-10"}` |
| GET | `/cards/credit/{card_id}/bills` | 청구서 목록 |
| GET | `/cards/credit/{card_id}/bills/{bill_id}` | 청구서 상세 + 포함된 사용내역 |
| POST | `/cards/credit/{card_id}/bills/{bill_id}/payments` | 청구서 납부 (결제 계좌에서 전액 출금) |

정한 규칙 (2026-11-05 논의 결과):
1. **누가 호출:** 카드 주인 본인. 관리자 권한은 이 프로젝트에 없다.
2. **이용 기간:** 전월 1일 ~ 말일(KST).
   - 납부 예정일(`due_date`)은 다음 달 `payment_date`일이다.
   - 그 달에 없는 날이면 말일로 당긴다. 예: 결제일 31일 → 2월에는 28일 또는 29일.
3. **범위 밖:** 부분 납부, 연체 이자, 리볼빙.

#### 이유
- **청구서 테이블이 필요한 이유:** 테이블 없이는 두 가지에 답할 수 없다.
  - "이번에 얼마를 청구해야 하나?" 누적액만으로는 이미 갚은 금액과 아직 안 갚은 금액이 섞인다.
  - "어떤 사용내역이 어느 청구에 들어갔나?"
  - 재현: 10월에 8만 원을 쓰고 11월 14일에 납부했다. 그리고 11월에 3만 원을 더 썼다. 12월 청구 금액이 3만 원이라는 걸 알려면, 10월분이 이미 청구·납부됐다는 기록이 있어야 한다.
- **`bill_id`를 사용내역에 둔 이유:**
  - 청구서를 만들 때 `bill_id IS NULL`인 사용내역만 합산한다. 그러면 **같은 사용내역이 두 번 청구되는 일이 없다.**
  - 청구서 상세에서 포함된 내역을 바로 조회할 수 있다(`bill_id` 인덱스).
- **스케줄러 대신 API:**
  - 이 프로젝트에는 정해진 시각에 작업을 실행하는 스케줄러가 없다. 그래서 본인이 호출해서 청구·납부를 실행한다.
  - 로직은 `card_service.create_bill` / `pay_bill`에 둔다. 나중에 스케줄러를 붙이면 같은 함수를 호출하기만 하면 된다.
  - 테스트할 때 시간이 흐르기를 기다릴 필요가 없다는 장점도 있다.
- **DB 제약을 넣은 이유:**
  - `(credit_card_id, period_start)` unique: 같은 달 청구서 생성을 동시에 두 번 호출해도 하나만 생긴다. 조회 후 insert 방식만으로는 동시 요청을 못 막는다(C-002와 같은 문제).
  - `status`와 `paid_at`이 서로 맞는지 검사: PAID인데 납부 시각이 없거나, UNPAID인데 납부 시각이 있는 모순된 행을 막는다.
  - `total_amount > 0`: 사용내역이 없는 달에 0원 청구서가 생기지 않게 한다. 서비스에서는 `NO_UNBILLED_USAGE`(400)로 먼저 거른다.

#### 영향 범위
- 새 테이블 1개와 `credit_card_histories`의 컬럼 1개(nullable)가 추가된다. 아직 마이그레이션이 없어서 최초 마이그레이션에 포함된다.
- 새 에러 코드:
  - `BILLING_PERIOD_NOT_ENDED` (400)
  - `NO_UNBILLED_USAGE` (400)
  - `BILL_ALREADY_EXISTS` (409)
  - `BILL_ALREADY_PAID` (409)
  - `INSUFFICIENT_BALANCE` (400, 납부)
- 납부는 돈이 움직이는 처리다. 그래서 ERD 규칙 2번(한 트랜잭션)에 추가했다. 납부 시 남기는 입출금 거래내역 `type`은 `CARD_BILL_PAYMENT`이다.
- `alembic/env.py`의 import 목록에 새 모델을 추가했다. 이걸 빠뜨리면 autogenerate가 테이블을 만들지 않는다.

#### 검증
- `tests/test_constraints.py`에 아래 두 테스트를 추가했다. 전체 테스트 19개 통과.
  - `test_credit_card_bill_constraints`: 0원 청구, 기간 역전, 알 수 없는 상태, paid_at 없는 PAID를 각각 거부하는지
  - `test_credit_card_bill_one_per_period`: 같은 카드·같은 기간 청구서 두 번째 insert를 거부하는지
- PostgreSQL 방언으로 `CREATE TABLE` DDL을 생성해서 제약들이 정상적으로 나오는 것을 확인했다. 실제 PostgreSQL 서버에서 실행해 보지는 않았다.
- API는 아직 구현하지 않았다(TODO).

#### 팀 논의 포인트
- 청구서 API의 경로와 이름. `bills`로 할지 `statements`로 할지.
- 청구서 생성을 본인 호출로 한 것은 "스케줄러가 없어서 생긴 타협"이다. 나중에 스케줄러를 도입할지 정해야 한다.
- **연체 처리를 범위에서 뺐다.** 그래서 납부 예정일이 지나도 상태는 UNPAID 그대로다. 나중에 `OVERDUE` 상태를 추가하려면 `ck_credit_card_bills_status` 제약도 바꿔야 한다.
- 이용 기간 중에 카드가 해지되는 경우 등은 고려하지 않았다. 카드 해지 기능 자체가 없다.

---

### C-011. 신용카드 한도 `credit_limit` 추가 + 결제 시 한도 검사

- **날짜:** 2026-11-05
- **분류:** DB 스키마
- **상태:** 적용 (컬럼·제약 적용, 한도 검사는 C-023에서 구현)
- **바뀐 파일:**
  - `src/avengers_bank/domains/cards/models.py` (`CreditCard`)
  - `src/avengers_bank/domains/cards/service.py`, `schemas.py` (TODO 주석)
  - `docs/ERD.md`, `docs/API_ENDPOINTS.md`
  - `tests/test_constraints.py`

#### 변경 전
```python
class CreditCard(Base):
    __table_args__ = (
        CheckConstraint("payment_date BETWEEN 1 AND 31", name="ck_credit_cards_payment_date_range"),
    )
    ...
    card_num: Mapped[str] = mapped_column(String(19), unique=True, nullable=False)
    accumulated_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
```
한도 개념이 없어서 신용카드로 금액 제한 없이 결제할 수 있었다.

#### 변경 후
```python
__table_args__ = (
    CheckConstraint("payment_date BETWEEN 1 AND 31", name="ck_credit_cards_payment_date_range"),
    CheckConstraint("credit_limit > 0", name="ck_credit_cards_credit_limit_positive"),
    # 동시 결제로 서비스의 한도 검사가 뚫려도 한도 초과·음수 미결제액은 DB가 막는다.
    CheckConstraint(
        "accumulated_amount BETWEEN 0 AND credit_limit",
        name="ck_credit_cards_accumulated_amount_within_limit",
    ),
)
...
credit_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 신용 한도
```
결제 TODO(service.py):
```python
#       신용카드: 카드 행 잠금(with_for_update)
#                 accumulated_amount(미결제액) + used_amount > credit_limit 이면
#                 BadRequestException(code="CREDIT_LIMIT_EXCEEDED")
#                 → CreditCardHistory 저장(bill_id=NULL) + accumulated_amount 증가
```

#### 이유
- 한도가 없으면 신용카드로 무한정 결제할 수 있다. 잔액을 검사하는 체크카드와 달리, 신용카드에는 어떤 금액 제한도 없게 된다.
- 재현: 한도 100만 원 카드에 미결제액이 90만 원 있다. 이 상태에서 20만 원 결제 두 건이 동시에 들어오면, 둘 다 "90 + 20 > 100"에 걸려야 한다. 그런데 잠금 없이 조회하면 각 요청이 "아직 90만 원"이라고 읽을 수 있다.
  - **1차 방어:** 서비스에서 카드 행을 잠근다(`with_for_update`). 두 번째 요청은 첫 번째가 끝날 때까지 기다리므로, 갱신된 미결제액을 보고 정확히 판단한다.
  - **2차 방어:** 잠금을 빠뜨리는 버그가 있어도 CHECK 제약(`accumulated_amount <= credit_limit`)이 한도 초과 저장을 막는다.
- 한도 검사를 "미결제액 컬럼 하나 + 결제 금액"으로 할 수 있는 건 C-012 덕분이다.

#### 영향 범위
- `credit_cards`에 NOT NULL 컬럼이 추가된다. 그래서 신용카드 발급 요청에 `credit_limit` 값이 필요하다. 요청에서 받을지, 상품별 기본값을 쓸지는 아래 논의 포인트 참고.
- 새 에러 코드: `CREDIT_LIMIT_EXCEEDED` (400).
- 체크카드(`debit_cards`)는 바뀌지 않았다.

#### 검증
- `test_credit_card_outstanding_within_limit`를 추가했다. 미결제액 -1과, 한도(10만 원)보다 1원 많은 금액을 각각 거부하는지 확인한다.
- 기존 결제일 테스트에도 `credit_limit` 값을 추가했다.

#### 팀 논의 포인트
- ~~**한도를 누가 정하는가**~~ → 상품별 고정 한도로 결정 (C-013)
- 한도 변경 API(`PATCH /cards/credit/{id}`)가 필요한지 정해야 한다.

---

### C-012. 신용카드 `accumulated_amount` 의미를 "미결제액"으로 변경

- **날짜:** 2026-11-05
- **분류:** DB 스키마 (컬럼 의미 변경)
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/cards/models.py` (`CreditCard.accumulated_amount` 주석, CHECK 제약은 C-011)
  - `docs/ERD.md` (다이어그램 설명, 규칙 4번)
  - `src/avengers_bank/domains/cards/service.py` (TODO: 납부 시 감소)

#### 변경 전
ERD.md 규칙 4번:
> **`accumulated_amount` 동기화:** 카드 History를 저장할 때 이 값도 같이 증가시킵니다.

즉 신용카드와 체크카드 모두 **누적 사용액**이었다. 늘어나기만 하고 줄어들지 않는다.

#### 변경 후
```python
# 아직 갚지 않은 금액: 사용하면 증가, 청구서 납부하면 청구 금액만큼 감소
accumulated_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
```
ERD.md 규칙 4번:
> **`accumulated_amount` 동기화:** 카드 History를 저장할 때 이 값도 같이 증가시킵니다. 신용카드에서는 **미결제액**이라서 청구서를 납부하면 청구 금액만큼 줄이고, 결제 때 `미결제액 + 결제 금액 <= credit_limit`을 검사합니다. (체크카드는 누적 사용액 그대로)

#### 이유
- 누적 사용액은 한도 검사에 쓸 수 없다.
  - 재현: 한도 100만 원 카드로 매달 50만 원씩 쓰고 꼬박꼬박 갚았다고 하자. 3개월이 지나면 누적 사용액은 150만 원이다.
  - 누적 사용액으로 한도를 검사하면 **다 갚았는데도 한도 초과**가 된다.
- "아직 갚지 않은 금액"을 다른 방법으로 계산할 수도 있다. 미청구 사용내역 합계와 UNPAID 청구서 합계를 매번 더하는 것이다. 하지만 결제할 때마다 두 테이블을 집계해야 하고, 그 사이에 값이 바뀌지 않게 잠금도 복잡해진다.
- 미결제액을 컬럼 하나에 유지하면 다음과 같이 단순해진다.
  - 한도 검사: 카드 행 하나만 잠그고 읽으면 된다.
  - CHECK 제약 `0 <= 미결제액 <= 한도`를 걸 수 있다.
  - 납부할 때는 청구 금액만큼 빼면 된다.
- 납부는 항상 청구서 단위 전액이다(부분 납부는 범위 밖). 그래서 "빼는 금액 = `total_amount`"로 규칙이 단순하다.

#### 영향 범위
- **같은 컬럼 이름이 카드 종류에 따라 다른 의미를 갖는다.** 신용카드는 미결제액, 체크카드는 누적 사용액이다.
  - `CardSummaryResponse.accumulated_amount`(GET /cards)도 카드 종류마다 의미가 다르다.
  - 화면에 표시할 때 혼동하지 않게 주의해야 한다.
- 정합성 규칙이 생긴다. 미결제액은 항상 다음 합과 같아야 한다.
  - 미청구 사용내역(`bill_id IS NULL`)의 `used_amount` 합
  - UNPAID 청구서의 `total_amount` 합
  - 결제·청구·납부를 모두 한 트랜잭션으로 처리하면 이 규칙이 유지된다.

#### 검증
- C-011의 제약 테스트로 범위(0 ~ 한도)를 확인했다.
- 증가·감소 로직은 아직 구현 전이다. 구현할 때는 "결제 → 청구 → 납부 후 미결제액 0" 흐름 테스트를 추가한다.

#### 팀 논의 포인트
- 신용카드 컬럼 이름을 `outstanding_amount`로 바꿀지. 이름과 의미가 일치하지만, 체크카드와 이름이 달라져 `CardSummaryResponse`를 손봐야 한다. 이번에는 팀 ERD와의 차이를 줄이려고 이름은 그대로 두었다.
- 체크카드의 누적 사용액이 실제로 어디에 쓰이는지 정해야 한다. 쓰는 곳이 없으면 컬럼을 없애는 것도 방법이다.

---

### C-013. 신용 한도를 카드 상품별로 고정 (`card_products.credit_limit`)

- **날짜:** 2026-11-05
- **분류:** DB 스키마
- **상태:** 적용 (컬럼·제약 적용, 발급 시 복사는 C-023에서 구현)
- **바뀐 파일:**
  - `src/avengers_bank/domains/products/models.py` (`CardProduct.credit_limit`, CHECK 제약)
  - `src/avengers_bank/domains/products/schemas.py` (`CardProductResponse.credit_limit`)
  - `src/avengers_bank/domains/cards/models.py` (`CreditCard.credit_limit` 주석)
  - `src/avengers_bank/domains/cards/service.py`, `schemas.py` (TODO 주석)
  - `docs/ERD.md` (다이어그램, 규칙 3번)
  - `tests/test_constraints.py`

#### 변경 전
- C-011에서 `credit_cards.credit_limit`을 추가했지만, 값을 어디서 가져오는지는 정하지 않았다.
- TODO는 이랬다.
```python
# cards/service.py
#       - 신용카드: credit_limit 필수 (기본값·최대값은 팀 결정)
# cards/schemas.py
# TODO: CreditCardCreate에 credit_limit 추가
```
`card_products`에는 한도 컬럼이 없었다.

#### 변경 후
```python
class CardProduct(Base):
    __table_args__ = (
        CheckConstraint("type IN ('CREDIT', 'DEBIT')", name="ck_card_products_type"),
        # 신용카드 상품은 한도 필수, 체크카드 상품은 한도 없음.
        # IS NOT NULL을 빼면 NULL > 0 이 UNKNOWN이 되어 CHECK를 통과해 버린다.
        CheckConstraint(
            "(type = 'CREDIT' AND credit_limit IS NOT NULL AND credit_limit > 0)"
            " OR (type = 'DEBIT' AND credit_limit IS NULL)",
            name="ck_card_products_credit_limit_by_type",
        ),
    )
    ...
    # 이 상품으로 발급하는 신용카드의 한도(원). 발급 때 credit_cards.credit_limit으로 복사한다.
    credit_limit: Mapped[int | None] = mapped_column(BigInteger)
```
```python
# cards/service.py
#       - 신용카드: credit_limit = 상품(card_products)의 credit_limit 그대로 복사 (요청으로 받지 않음)
# cards/schemas.py: "CreditCardCreate에 credit_limit 추가" TODO 삭제
# products/schemas.py: CardProductResponse에 credit_limit: int | None 추가
```

#### 이유
- 실제 카드사는 소득, 신용점수, 기존 부채를 심사해서 고객마다 한도를 정한다. 이 프로젝트에는 심사에 쓸 데이터가 없다.
- 그래서 **심사 결과를 "상품별 고정 한도"로 대신한다.** 예: 기본 카드 300만 원, 프리미엄 카드 1,000만 원.
- 희망 한도(사용자가 더 낮게 요청하는 것)도 검토했지만 넣지 않았다(2026-11-05 결정). 발급 요청이 단순해지고, 검증할 것도 줄어든다.
- **상품 한도를 카드에 복사하는 이유:**
  - 나중에 상품 한도를 바꿔도 이미 발급된 카드의 한도는 그대로 유지돼야 한다. 실제 카드사도 상품 조건을 바꿔도 기존 고객의 한도는 바꾸지 않는다.
  - C-011의 CHECK 제약(`accumulated_amount BETWEEN 0 AND credit_limit`)은 같은 행의 컬럼끼리만 비교할 수 있다. 그래서 카드 행에 한도 값이 있어야 한다.
- **CHECK 제약을 타입별로 건 이유:** 같은 테이블에 신용·체크 상품이 섞여 있다. 신용 상품에 한도가 빠지면 발급할 때 복사할 값이 없어서 `credit_cards`의 NOT NULL 제약에서 실패한다. 이걸 상품을 등록하는 시점에 미리 막는다.

#### 영향 범위
- `card_products`에 nullable 컬럼이 추가된다. 체크카드 상품은 NULL이다.
- 신용카드 상품 시드 데이터에 `credit_limit` 값이 반드시 필요하다.
- `GET /products/cards` 응답에 `credit_limit` 필드가 추가된다. 체크카드 상품이면 `null`이다.
- 신용카드 발급 요청(`POST /cards/credit`)에는 한도 필드가 없다.

#### 검증
- 새 테스트 2개를 추가했다. 전체 테스트 23개 통과.
  - `test_card_product_credit_limit_by_type`: 한도 없는 신용 상품, 한도 0원 신용 상품, 한도 있는 체크 상품을 각각 거부하는지 확인한다.
  - `test_card_product_valid_credit_limit`: 정상적인 신용 상품(한도 있음)과 체크 상품(한도 없음)은 저장되는지 확인한다.
- **이 테스트가 실제 버그를 잡았다.**
  - 처음에 쓴 조건은 `(type = 'CREDIT' AND credit_limit > 0) OR ...`이었다. 이 조건으로는 한도가 NULL인 신용 상품이 통과했다.
  - SQL에서 `NULL > 0`은 거짓이 아니라 **UNKNOWN**이다. CHECK 제약은 UNKNOWN을 "위반 아님"으로 처리한다.
  - `credit_limit IS NOT NULL`을 명시해서 고쳤다.
  - 다른 CHECK 제약들도 같은 문제가 있는지 확인했다. 모두 NOT NULL 컬럼에 걸려 있거나 `IS NOT NULL`로만 비교하므로 문제없다.

#### 팀 논의 포인트
- 상품별 한도 값. 예시는 300만, 1,000만 원이고 시드 데이터를 만들 때 정한다.
- 한도 상향·하향 기능은 없다. 필요해지면 희망 한도나 한도 변경 API를 추가로 검토한다.
- 한 사람이 신용카드를 여러 장 발급받으면 한도가 그만큼 늘어난다(실제 카드사는 고객 총 한도로 막는다).
  - **2026-11-05 결정: 발급 장수 제한을 두지 않는다.** 카드별 한도만 검사한다. 이 허점은 알고서 감수한 것이다.
  - 팀에서 막아야 한다고 보면, 가장 단순한 방법은 "1인당 신용카드 1장"이다. 발급할 때 검사하고, 동시 요청까지 막으려면 `credit_cards.user_id`에 unique 제약을 건다.

---

### C-014. 최초 마이그레이션 파일 생성 + README 마이그레이션 절차 변경

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:**
  - `alembic/versions/6e15576e9ff5_create_initial_tables.py` (새 파일, autogenerate 결과를 수정 없이 사용)
  - `README.md` ("시작하기" 절차, "모델을 바꿨을 때" 절 추가)

#### 변경 전
`alembic/versions/`에는 `.gitkeep`만 있었다. README는 모든 팀원에게 다음 절차를 안내했다.
```bash
uv run alembic revision --autogenerate -m "create initial tables"
uv run alembic upgrade head
uv run fastapi dev
```

#### 변경 후
최초 마이그레이션 파일을 저장소에 넣었다(리비전 `6e15576e9ff5`). README의 시작 절차는 다음과 같다.
```bash
uv run alembic upgrade head
uv run fastapi dev
```
"모델을 바꿨을 때" 절을 추가했다. 내용은 다음과 같다.
- 모델을 수정한 사람만 `revision --autogenerate`를 실행하고, 생성된 파일을 함께 커밋한다.
- 다른 사람은 그 파일을 받아서 `upgrade head`만 실행한다.
- 커밋 전에 `alembic check`로 모델과 마이그레이션이 일치하는지 확인한다.
- 새 모델 파일을 만들었다면 `alembic/env.py`의 import 목록에 추가한다.

#### 이유
- 원래 절차대로 하면 팀원마다 **리비전 ID가 다른 "최초 마이그레이션"**이 생긴다.
  - 재현: A의 파일은 `abc123_create_initial_tables.py`, B의 파일은 `def456_create_initial_tables.py`가 된다.
  - 둘 다 커밋하면 `down_revision=None`인 시작점이 두 개가 된다. 그러면 `upgrade head`가 "Multiple head revisions" 에러로 실패한다.
  - 한 명만 커밋해도 문제다. 다른 팀원의 DB에는 자기가 만든 리비전 ID가 `alembic_version`에 기록돼 있다. 저장소의 리비전을 모르니 다음 마이그레이션을 적용할 수 없다.
- 마이그레이션은 "DB 구조의 변경 이력"이다. 모든 사람이 같은 파일을 같은 순서로 적용해야 DB 구조가 같아진다.
- 지금이 최초 마이그레이션을 만들기 좋은 시점이다. C-003·C-004·C-007·C-008·C-010·C-011·C-013의 스키마 변경이 모두 끝났고, 아직 운영 데이터가 없다. 그래서 이 변경들을 별도 마이그레이션으로 쪼개지 않고 최초 파일 하나에 담았다.

#### 영향 범위
- **이미 각자 autogenerate로 DB를 만든 팀원이 있다면** 그 DB의 `alembic_version`은 이 리비전을 모른다. 로컬 DB를 지우고 `upgrade head`를 다시 실행해야 한다. 개발용 DB라 데이터 손실 걱정은 없다.
- 앞으로 모델을 바꾸는 모든 작업은 "모델 수정 + 마이그레이션 파일"을 함께 커밋해야 한다.
- 두 사람이 동시에 마이그레이션을 만들면 head가 갈라질 수 있다. 그때는 `alembic merge heads`로 합친다.

#### 검증
로컬에 이 프로젝트용 PostgreSQL(5435 포트)이 실행 중이 아니었다. 그래서 **임시 PostgreSQL 17 컨테이너**(이미 내려받아 둔 `pgvector/pgvector:pg17-trixie` 이미지, 55435 포트)를 띄워서 확인했다. 확인이 끝나고 컨테이너는 삭제했다.

| 단계 | 결과 |
|---|---|
| `alembic revision --autogenerate` (빈 DB 기준) | 14개 테이블과 인덱스를 모두 감지 |
| `alembic upgrade head` | 테이블 14개, CHECK 제약 20개 생성 |
| `alembic downgrade base` | 테이블 0개 (전부 삭제) |
| `alembic upgrade head` (재실행) | 다시 정상 생성 |
| `alembic check` | `No new upgrade operations detected.` 모델과 마이그레이션이 일치 |
| 실제 PostgreSQL에서 제약 동작 | 한도 없는 신용 상품 insert 시 `ck_card_products_credit_limit_by_type` 위반으로 거부 |

- CHECK 제약 20개의 내역: `account_products` 1, `card_products` 2, 계좌 3종 4, 거래내역 3종 6, `credit_cards` 3, `credit_card_bills` 4.
- pytest 23개도 계속 통과한다. 단, pytest는 SQLite에서 `create_all`을 쓰므로 마이그레이션 파일을 거치지 않는다.

#### 팀 논의 포인트
- 마이그레이션 파일 이름 규칙. 지금은 기본값인 `<리비전ID>_<설명>.py`이다. `alembic.ini`의 `file_template`을 바꾸면 날짜를 앞에 붙여 순서를 보기 쉽게 할 수 있다.
- **`balance`, `accumulated_amount`, `status`의 기본값은 Python(ORM) 쪽에만 있다**(`default=0`, `default="UNPAID"`). DB에는 기본값이 없다.
  - 그래서 SQL로 직접 insert하는 시드 스크립트에서는 이 값들을 반드시 적어야 한다. 빠뜨리면 NOT NULL 위반이 난다.
  - DB 기본값(`server_default`)도 둘지 정해야 한다. 둔다면 마이그레이션을 하나 더 만들어야 한다.
- ~~이 프로젝트용 로컬 PostgreSQL을 어떻게 띄울지 팀 공통 방법이 없다~~ → C-015에서 `docker-compose.yml` 추가

---

### C-015. 로컬 DB용 `docker-compose.yml` 추가

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:**
  - `docker-compose.yml` (새 파일)
  - `README.md` ("시작하기"에 `docker compose up -d --wait` 추가)

#### 변경 전
- PostgreSQL을 어떻게 띄울지에 대한 안내나 설정이 없었다.
- `.env.example`은 `postgres:1234@localhost:5435/avengers_bank`를 가정했지만, 그 DB를 만드는 방법은 각자 알아서 해야 했다.
- 실제로 내 PC의 5435 포트에는 아무것도 없어서 서버와 마이그레이션 모두 DB에 연결할 수 없었다.

#### 변경 후
```yaml
services:
  db:
    # PostgreSQL 17 (pgvector 확장 포함 이미지, 기능은 일반 postgres:17과 같음)
    image: pgvector/pgvector:pg17-trixie
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: "1234"
      POSTGRES_DB: avengers_bank
    ports:
      - "127.0.0.1:5435:5432"
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d avengers_bank"]
      ...
    restart: unless-stopped

volumes:
  db-data:
```

#### 이유
- 모든 팀원이 **같은 버전, 같은 포트, 같은 접속 정보**의 DB를 명령 한 줄로 띄울 수 있다. 각자 설치한 PostgreSQL은 버전과 설정이 달라서 "내 PC에서는 되는데" 문제가 생긴다.
- 접속 정보를 `.env.example`과 똑같이 맞춰서, `.env`를 복사만 하면 바로 연결된다.
- 설계 선택:
  - **`127.0.0.1`에만 포트를 연다:** 비밀번호가 `1234`인 DB가 같은 네트워크(카페 와이파이 등)의 다른 기기에 노출되지 않게 한다.
  - **이름 있는 볼륨(`db-data`):** 컨테이너를 지웠다 다시 만들어도 데이터가 남는다. 초기화하려면 `docker compose down -v`를 쓴다.
  - **healthcheck:** `docker compose up -d --wait`가 DB가 접속 가능한 상태가 될 때까지 기다린다. 바로 이어서 `alembic upgrade head`를 실행해도 실패하지 않는다.
  - **이미지:** 내 PC에 이미 있던 `pgvector/pgvector:pg17-trixie`를 썼다. 새로 내려받지 않기 위해서다. PostgreSQL 17에 pgvector 확장만 추가된 이미지이고, 확장을 쓰지 않으면 일반 `postgres:17`과 같다.

#### 영향 범위
- 이미 5435 포트를 다른 프로그램이 쓰고 있으면 컨테이너가 뜨지 않는다. 그때는 포트를 바꾸고 `.env`도 같이 바꾼다.
- 직접 설치한 PostgreSQL을 쓰는 팀원은 이 파일을 쓰지 않아도 된다. 대신 `.env`의 접속 정보를 자기 환경에 맞춰야 한다.

#### 검증
- `docker compose up -d --wait`를 실행해 컨테이너 `avengers-bank-main-db-1`이 healthy 상태로 뜨는 것을 확인했다.
- `alembic upgrade head`로 `6e15576e9ff5 (head)`를 적용했다.
- `fastapi dev`로 서버를 띄워 실제 DB에 다음을 요청했다.
  - 회원가입 201
  - 로그인 토큰 발급
  - `/users/me` 200
  - 중복 가입 409
- 확인용 사용자는 삭제했다.

#### 팀 논의 포인트
- 이미지를 공식 `postgres:17`로 바꿀지 정해야 한다. 팀원 대부분은 어느 이미지든 새로 받아야 하므로, 의미가 분명한 공식 이미지가 낫다.
- 비밀번호를 `.env`에서 읽게 할지 정해야 한다. 지금은 `.env.example`과 같은 값을 compose 파일에 그대로 적었다. 로컬 개발용이라 그대로 둬도 큰 문제는 없다.
- API 서버도 compose에 넣을지 정해야 한다. 지금은 DB만 들어 있다.

---

### C-016. DB 호스트 `localhost` → `127.0.0.1` + Windows 실행 주의사항

- **날짜:** 2026-11-05
- **분류:** 문서 (설정)
- **상태:** 적용
- **바뀐 파일:**
  - `.env.example`, `.env` (`DATABASE_URL`의 호스트만 변경)
  - `README.md` ("Windows 주의" 블록)

#### 변경 전
```
DATABASE_URL=postgresql+psycopg://postgres:1234@localhost:5435/avengers_bank
```
README는 `uv run fastapi dev`만 안내했고, 운영체제에 따른 주의사항은 없었다.

#### 변경 후
```
DATABASE_URL=postgresql+psycopg://postgres:1234@127.0.0.1:5435/avengers_bank
```
README에 "Windows 주의" 블록을 추가했다.
- `DATABASE_URL`의 호스트는 `127.0.0.1`로 둔다.
- 서버는 `fastapi dev`로 실행한다. `fastapi run`은 Windows에서 DB 요청이 모두 500이 된다.

#### 이유
두 가지 모두 **Windows + psycopg 비동기 모드**에서만 생기는 문제이고, 직접 재현했다.

**1. `localhost`로 연결하면 무한 대기**
- 재현: DB 컨테이너가 정상인 상태에서 같은 접속 정보로 호스트만 바꿔 연결해 봤다.
  - `127.0.0.1`: 0.4초 만에 연결
  - `localhost`: 10초 동안 응답 없음(타임아웃)
  - `alembic upgrade head`도 `localhost`일 때는 2분이 지나도 끝나지 않았다.
- 원인:
  - Windows에서 `localhost`는 `::1`(IPv6), `127.0.0.1` 순서로 풀린다.
  - 컨테이너는 `127.0.0.1`에만 열려 있어서 `::1` 연결은 즉시 거절된다. PowerShell로 확인했다.
  - 그런데 psycopg가 Windows용 select 기반 이벤트 루프에서는 이 "거절"을 감지하지 못한다. 그래서 다음 주소로 넘어가지 못하고 멈춘다.
- 해결 방법은 두 가지가 있었다.
  - 컨테이너 포트를 IPv6(또는 모든 주소)에도 연다. 하지만 비밀번호 `1234`인 DB를 외부에 노출할 수 있어서 택하지 않았다.
  - **호스트를 `127.0.0.1`로 명시한다.** 변경이 가장 작고 다른 운영체제에도 영향이 없다. 이 방법을 택했다.

**2. `fastapi run`으로 실행하면 DB 요청이 전부 500**
- 재현: `fastapi run`으로 서버를 띄우고 로그인을 요청했다. 서버 로그에 아래 에러가 남았다.
  > `psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode.`
- 원인:
  - uvicorn 0.54(`uvicorn/loops/asyncio.py`)는 Windows에서 서브프로세스 없이 실행하면 Proactor 이벤트 루프를 쓴다.
  - psycopg 비동기 모드는 Proactor를 지원하지 않는다.
  - `fastapi dev`는 reload 모드라서 서브프로세스로 실행된다. 그래서 Selector 루프를 쓰고, 정상 동작한다.
  - `alembic/env.py`가 정상이었던 것도 Windows에서 Selector 루프를 명시해 뒀기 때문이다.
- 코드는 바꾸지 않고 문서로 안내하기로 했다.
  - 개발은 `fastapi dev`로 하고, 배포 서버는 보통 Linux라 이 문제가 없다.
  - 코드로 고치려면 uvicorn을 직접 실행하면서 사용자 정의 loop factory를 넘기거나, DB 드라이버를 asyncpg로 바꿔야 한다. 지금 필요하지 않은 변경이다.

#### 영향 범위
- macOS·Linux 팀원에게는 영향이 없다. `127.0.0.1`은 어디서나 같은 의미다.
- 기존 `.env`를 쓰는 Windows 팀원은 호스트를 직접 바꿔야 한다. `.env`는 저장소에 없으므로 자동으로 바뀌지 않는다.

#### 검증
- `127.0.0.1`과 `localhost`의 연결 시간을 직접 비교했다(0.4초 / 10초 타임아웃).
- 호스트를 바꾼 뒤 `alembic upgrade head`가 정상적으로 끝났다.
- `fastapi run`에서는 Proactor 에러를 확인했고, `fastapi dev`에서는 회원가입·로그인·내 정보·중복 가입이 모두 정상이었다(C-015 검증과 같음).

#### 팀 논의 포인트
- Windows에서 `fastapi run`도 동작해야 하는지 정해야 한다. 필요하면 DB 드라이버를 `asyncpg`로 바꾸는 방법을 검토한다. 그러면 URL scheme과 의존성이 바뀐다.

---

### C-017. 돈이 움직이는 처리의 행 잠금 규칙 (ERD 규칙 9)

- **날짜:** 2026-11-05
- **분류:** 동시성
- **상태:** 적용 (규칙 확정, 구현·검증은 C-021·C-022·C-023에서 완료)
- **바뀐 파일:**
  - `docs/ERD.md` (코드 규칙 9번 추가)
  - `src/avengers_bank/domains/transfers/service.py` (이체·납입 TODO 순서 재작성)
  - `src/avengers_bank/domains/accounts/repository.py` (`lock_checking_accounts` TODO 추가)
  - `src/avengers_bank/domains/cards/service.py` (체크카드 결제·청구서 납부 TODO에 잠금 순서 명시)

#### 변경 전
이체 TODO에는 트랜잭션만 있고 잠금이 없었다. 검사가 잠금보다 먼저였다.
```python
#   async with db.begin():
#       1. 보내는 계좌가 본인 것인지 확인 (ForbiddenException)
#       2. 받는 계좌 찾기 (NotFoundException)
#          받는 계좌 == 보내는 계좌면 거부 (...)
#       3. 잔액, 1회 한도, 1일 한도 검사 (BadRequestException)
#       4. 양쪽 balance 변경
#       5. 양쪽 CheckingAccountHistory 한 줄씩 저장
```
ERD.md 규칙 2번은 "한 트랜잭션으로"만 요구했다. 청구서 납부 TODO는 "PAID인지 확인 → 잠금" 순서였다.

#### 변경 후
ERD.md 규칙 9번:
> **돈이 움직이기 전에 행 잠금:** 잔액·한도·청구서 상태를 바꾸는 처리는 해당 행을 `SELECT ... FOR UPDATE`(`with_for_update()`)로 **먼저 잠그고, 잠근 뒤에** 검사합니다. 잠그기 전에 읽은 값으로 검사하면 동시 요청이 둘 다 통과합니다.
> - 잠금 순서는 항상 같게: 입출금 계좌(ID 오름차순) → 예금·적금 계좌 → 카드 → 청구서. 순서가 다르면 두 요청이 서로를 기다리는 데드락이 생깁니다.
> - 잠금 쿼리에는 `.execution_options(populate_existing=True)`를 붙여 세션에 남아 있는 예전 값을 최신 값으로 덮어씁니다.
> - 테스트 DB(SQLite)는 `FOR UPDATE`를 무시하므로 동시성 테스트는 PostgreSQL에서 해야 합니다.

이체 TODO(transfers/service.py):
```python
#   async with db.begin():
#       1. 받는 계좌 찾기: find_checking_by_account_num (NotFoundException)
#          받는 계좌 id == from_checking_account_id 면 거부 (..., code="SAME_ACCOUNT_TRANSFER")
#       2. 두 계좌를 한 번에 잠금: lock_checking_accounts(db, [from_id, to_id])  ← ID 오름차순
#          보내는 계좌가 없으면 NotFoundException, 본인 것이 아니면 ForbiddenException
#       3. (잠근 뒤에) 잔액, 1회 한도, 1일 한도 검사 (BadRequestException)
#          1일 한도 합계도 보내는 계좌를 잠근 뒤에 계산해야 동시 이체가 한도를 우회하지 못한다
#       4. 양쪽 balance 변경
#       5. 양쪽 CheckingAccountHistory 한 줄씩 저장 (amount 양수, balance_after, counterpart_account)
```
잠금 메서드 TODO(accounts/repository.py):
```python
# TODO: lock_checking_accounts(db, ids)
#       select(CheckingAccount).where(id IN ids).order_by(id).with_for_update()
#           .execution_options(populate_existing=True)
```
청구서 납부 TODO: "결제 계좌 → 카드 → 청구서 순서로 잠금 → (잠근 뒤에) 이미 PAID면 409" 순서로 바꿨다.

#### 이유
- **트랜잭션만으로는 동시 요청을 막지 못한다.** PostgreSQL 기본 격리 수준(READ COMMITTED)에서는 두 트랜잭션이 같은 행을 동시에 읽을 수 있다.
  - 재현(이중 출금): 잔액 10만 원 계좌에서 8만 원 이체 두 건이 동시에 들어온다.
  - 두 요청 모두 잔액을 10만 원으로 읽고 "충분함" 검사를 통과한다.
  - 각자 `balance = 2만 원`으로 저장한다(나중에 쓴 쪽이 이김). 결과적으로 16만 원이 나갔는데 잔액은 2만 원이다. **돈이 생겨난다.**
  - C-004의 `balance >= 0` 제약도 이 경우는 못 막는다. 저장되는 값이 음수가 아니기 때문이다.
- **1일 한도도 같은 문제다.**
  - 재현: 한도 100만 원, 오늘 90만 원을 이미 보냈다. 이 상태에서 10만 원 이체 두 건이 동시에 오면, 둘 다 오늘 합계를 90만 원으로 읽고 통과한다.
  - 보내는 계좌 행을 잠그면 같은 계좌의 이체가 한 줄로 서게 된다. 그래서 합계 계산도 정확해진다. 한도 합계용 별도 잠금이 필요 없다.
- **잠금 순서를 고정하는 이유(데드락):**
  - 재현: A→B 이체와 B→A 이체가 동시에 실행된다.
  - 각자 "보내는 계좌"부터 잠그면, 첫 번째는 A를 잡고 B를 기다리고, 두 번째는 B를 잡고 A를 기다린다. 서로를 영원히 기다린다.
  - PostgreSQL이 이를 감지해 한쪽을 에러로 끝내긴 하지만, 사용자는 500을 받는다.
  - 항상 ID가 작은 계좌부터 잠그면 이런 순환이 생기지 않는다. 테이블이 섞이는 경우(계좌+카드+청구서)도 같은 이유로 테이블 간 순서를 정했다.
- **`populate_existing`이 필요한 이유:**
  - SQLAlchemy 세션은 같은 행을 다시 조회하면 이미 메모리에 있는 객체를 돌려준다.
  - 재현: 1단계에서 보내는 계좌를 잠금 없이 읽은 뒤, 2단계에서 잠금 조회를 한다. 잠금은 걸리지만 `balance`는 1단계에서 읽은 예전 값 그대로다.
  - `populate_existing`을 붙이면 잠근 시점의 DB 값으로 덮어쓴다.
- **청구서 납부에서 "잠근 뒤에 PAID 확인"인 이유:** 납부 버튼을 두 번 빠르게 누르면 두 요청 모두 UNPAID를 보고 각자 출금할 수 있다. 잠근 뒤에 확인하면 두 번째 요청은 PAID를 보고 409로 끝난다.
- **자기 계좌 이체(C-005) 검사를 잠금 전에 하는 이유:** 같은 ID를 두 번 넘기면 `IN (1, 1)`이 되어 한 행만 잠긴다. 잠금 자체는 문제없지만, 의미 없는 요청을 잠금 전에 거르는 편이 단순하다.

#### 영향 범위
- 아직 이체·결제 코드가 없어서 동작 변경은 없다. 구현하는 사람은 규칙 9를 따라야 한다.
- 잠금 때문에 같은 계좌에 대한 동시 요청은 순서대로 처리된다. 같은 계좌로 초당 수백 건이 몰리지 않는 한 성능 문제는 없다.
- `db.begin()` 블록이 끝날 때 잠금이 풀린다. 그래서 블록 안에서 외부 API 호출처럼 오래 걸리는 작업을 하면 안 된다.

#### 검증
- 해당 없음(규칙·주석). 구현할 때 PostgreSQL(C-015의 compose DB)에서 다음 동시성 테스트를 한다.
  - 잔액이 부족해지는 이체 두 건을 동시에 보내 한 건만 성공하는지
  - A→B, B→A 이체를 동시에 보내 둘 다 정상 처리되는지(데드락 없음)
- pytest(SQLite)는 `FOR UPDATE`를 무시하므로 이 테스트를 대신할 수 없다.

#### 팀 논의 포인트
- 동시성 테스트를 PostgreSQL에서 돌리는 방법.
  - **2026-11-05 결정: pytest는 지금처럼 SQLite로 유지한다.** DB 서버 없이 `uv run pytest`만으로 돌아가는 편의성을 우선했다.
  - 그 대신 잠금이 실제로 동작하는지는 이체·결제를 구현할 때 compose PostgreSQL에서 **따로 확인**하고, 결과를 해당 변경 기록의 "검증"에 남긴다.
  - SQLite 테스트가 통과해도 잠금이 검증된 것은 아니라는 점을 팀과 공유해야 한다.
- 잠금 대신 원자적 UPDATE를 쓰는 방법도 있다. 예: `UPDATE ... SET balance = balance - :x WHERE id = :id AND balance >= :x`.
  - 잔액 검사 하나에는 더 간단하다.
  - 하지만 1일 한도·1회 한도·`balance_after` 기록까지 함께 해야 해서 잠금 방식을 택했다.

---

### C-018. `get_current_user` 별도 세션 유지 + 이유 주석 (리뷰 지적 정정)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용 (주석만 추가, 동작 변경 없음)
- **바뀐 파일:**
  - `src/avengers_bank/core/dependencies.py` (`get_current_user` 주석)

#### 변경 전
```python
async with SessionLocal() as db:
    user = await user_service.get_current_user(db, credentials.credentials)
    return UserResponse.model_validate(user)
```
초기 리뷰(검토 항목 7번)에서는 이 코드를 이렇게 지적했다.
> `get_current_user`가 `get_db` 대신 별도 세션 사용 (요청당 커넥션 2개, 단 바꾸면 `db.begin()` 충돌 주의)

#### 변경 후
```python
# get_db를 쓰지 않고 세션을 따로 연다. 같은 세션을 쓰면 여기서 한 조회가 트랜잭션을
# 자동으로 시작해서, 이후 service의 `async with db.begin():`이 "이미 시작됨" 오류를 낸다.
# 이 세션은 블록이 끝날 때 커넥션을 반납하므로 커넥션 두 개를 동시에 쓰지는 않는다.
async with SessionLocal() as db:
    user = await user_service.get_current_user(db, credentials.credentials)
```

#### 이유
- **리뷰 지적을 정정한다. "요청당 커넥션 2개"는 과장이었다.**
  - `get_current_user`의 세션은 `async with` 블록이 끝날 때 닫히고, 그때 커넥션을 풀에 반납한다.
  - `get_db`의 세션은 첫 쿼리를 실행할 때 비로소 커넥션을 가져간다.
  - 그래서 두 커넥션은 **순서대로** 쓰이고, 동시에 두 개를 차지하지 않는다. 실제 비용은 요청당 풀에서 한 번 더 꺼내는 것뿐이라 무시할 만하다.
- **`get_db`로 바꾸면 기존 패턴이 깨진다.** 직접 확인했다.
  - 같은 세션에서 조회를 하나 실행한 뒤 `async with db.begin():`을 열면 `InvalidRequestError: A transaction is already begun on this Session.`이 난다.
  - SQLAlchemy 세션은 첫 쿼리 때 트랜잭션을 자동으로 시작하기 때문이다.
  - 이 프로젝트의 service 계층은 모두 `async with db.begin():` 패턴(ERD 규칙 2, 9)을 쓴다. 인증 조회가 같은 세션을 쓰면 로그인이 필요한 모든 API가 실패한다.
- 그래서 지금 구조가 맞다. 다음 사람이 "커넥션 낭비"라고 보고 `get_db`로 바꾸지 않도록 이유를 주석으로 남겼다.

#### 영향 범위
- 동작 변경 없음.
- `get_current_user`가 돌려주는 것은 ORM 객체가 아니라 `UserResponse`(Pydantic)다. 그래서 세션이 닫혀도 쓸 수 있다. service에서 `User` ORM 객체가 필요하면 `current_user.user_id`로 자기 세션에서 다시 조회한다.

#### 검증
- 같은 세션에서 "조회 → `db.begin()`"을 실행해 위 에러가 나는 것을 확인했다.
- 전체 테스트 23개 통과. C-015에서 실제 PostgreSQL로 `/users/me`도 정상 동작을 확인했다.

#### 팀 논의 포인트
- 없음. 다만 트랜잭션 패턴을 바꾸는 일이 생기면 이 의존성도 함께 검토해야 한다. 예: 요청 단위 트랜잭션 미들웨어를 도입하는 경우.

---

### C-019. products 도메인 구현 + 개발용 시드 스크립트 추가

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/products/repository.py`, `service.py`, `router.py` (TODO → 구현)
  - `src/avengers_bank/seed.py` (새 파일)
  - `tests/test_products.py` (새 파일, 테스트 8개)
  - `docs/API_ENDPOINTS.md` (products 4개 📝 → ✅), `README.md` (시작 절차·현재 상태), `docs/PROJECT_STRUCTURE.md`

#### 변경 전
세 파일(repository·service·router) 모두 TODO 주석만 있었다. 상품 조회 API가 없었고, 개발 DB에 상품을 넣는 방법도 없었다. 상품이 없으면 계좌 개설·카드 발급을 만들어도 시험할 수 없다.

#### 변경 후
API는 문서(API_ENDPOINTS.md)에 정한 4개를 그대로 구현했다. 응답 형식은 기존 `SuccessResponse`를 쓴다.

| 메서드 | 경로 | 동작 |
|---|---|---|
| GET | `/products/accounts?type=` | 계좌 상품 목록. `type` 생략 시 전체, 상품 ID 순 |
| GET | `/products/accounts/{product_id}` | 상세. 없으면 404 `ACCOUNT_PRODUCT_NOT_FOUND` |
| GET | `/products/cards?type=` | 카드 상품 목록 (신용 상품은 `credit_limit` 포함, 체크는 `null`) |
| GET | `/products/cards/{product_id}` | 상세. 없으면 404 `CARD_PRODUCT_NOT_FOUND` |

```python
# router.py: type을 Literal로 받아서 목록에 없는 값은 FastAPI가 422로 거른다
type: Literal["CHECKING", "DEPOSIT", "SAVINGS"] | None = None
```
accounts·cards가 계좌 개설·카드 발급 때 부를 "상품 종류 검증"(ERD 규칙 3)도 `ProductService`에 만들었다.
```python
await product_service.require_account_product(db, product_id, "CHECKING")  # 없으면 404, 종류가 다르면 400 PRODUCT_TYPE_MISMATCH
await product_service.require_card_product(db, product_id, "CREDIT")
```
시드 스크립트: `uv run python -m avengers_bank.seed`
- 계좌 상품 3개(입출금·정기예금·정기적금), 카드 상품 3개(신용 300만 원·1,000만 원, 체크)를 넣는다.
- 상품이 하나라도 있으면 아무것도 하지 않는다(여러 번 실행해도 안전).

#### 이유
- **조회 API에 인증을 걸지 않았다.** 문서에도 인증 열이 비어 있었다. 상품 정보는 가입 전에도 보여줘야 하는 공개 정보다.
- **`type`을 `Literal`로 제한:** 문자열로 받으면 `?type=LOAN` 같은 잘못된 값이 "결과 0건, 200"으로 조용히 넘어간다. 오타를 바로 알 수 있도록 422로 거절한다.
- **종류 검증을 products 서비스에 둔 이유:** 상품 종류를 아는 곳은 products 도메인이다. accounts·cards가 각자 `product.type == ...`을 비교하면 코드가 흩어지고 에러 코드도 달라진다. 에러 코드를 `PRODUCT_TYPE_MISMATCH` 하나로 통일했다.
- **시드 스크립트가 동기 엔진을 쓰는 이유:** Windows에서 psycopg 비동기는 이벤트 루프 문제가 있다(C-016). 한 번 실행하고 끝나는 스크립트라 동기 엔진이 단순하고, 그 문제를 피한다.
- **시드를 마이그레이션에 넣지 않은 이유:** 마이그레이션은 DB 구조의 이력이다. 임시 값(금리·한도 예시)을 거기 넣으면 나중에 값을 바꿀 때 데이터 마이그레이션이 필요해진다. 개발용 데이터는 따로 두었다.

#### 영향 범위
- 새 에러 코드: `ACCOUNT_PRODUCT_NOT_FOUND`(404), `CARD_PRODUCT_NOT_FOUND`(404), `PRODUCT_TYPE_MISMATCH`(400, accounts·cards가 사용 예정).
- 상품을 등록·수정하는 API는 없다. 상품은 시드나 SQL로만 넣는다. 이 프로젝트에 관리자 개념이 없어서 범위에서 뺐다.
- 로컬 개발 DB(compose)에는 시드를 이미 실행해 두었다. 다른 DB에서는 `upgrade head` 뒤에 한 번 실행해야 한다.

#### 검증
- `tests/test_products.py` 8개를 추가했고, 전체 테스트 31개가 통과한다. 확인하는 내용:
  - 목록과 `type` 필터, 잘못된 `type` → 422
  - 상세, 없는 ID → 404와 에러 코드
  - 카드 목록에서 신용만 `credit_limit` 값이 있고 체크는 `null`
  - 종류 검증: 맞으면 통과, 다르면 400, 없으면 404
- 실제 PostgreSQL(compose DB)에서 시드를 두 번 실행해 두 번째는 건너뛰는 것을 확인했다.
- `fastapi dev` 서버로 7개 요청(목록·필터·상세·404·카드 목록·체크 필터·잘못된 type)을 보내 모두 기대한 상태 코드와 내용이 나왔다. 한글은 응답과 DB(UTF8) 모두 정상이다.

#### 팀 논의 포인트
- **시드의 상품 이름·금리·한도는 내가 임의로 정한 예시다.** 금리 0.10 / 3.00 / 3.50 %, 한도 300만 / 1,000만 원이다. 팀 값으로 바꿔야 한다.
- 상품 관리 API(등록·수정)가 필요한지 정해야 한다. 필요하면 관리자 권한부터 설계해야 한다.
- 목록에 페이징을 넣지 않았다. 상품은 수십 개 이하일 것이라고 보았다.

---

### C-020. accounts 도메인 구현 (개설·조회·거래내역·수정)

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용 (잠금·합계 메서드는 C-021·C-022에서 구현)
- **바뀐 파일:**
  - `src/avengers_bank/domains/accounts/` — `router.py`, `service.py`, `repository.py`, `schemas.py` (TODO → 구현), `kinds.py` (새 파일)
  - `src/avengers_bank/core/timezone.py` (새 파일: `KST`, `today_kst()`)
  - `tests/test_accounts.py` (새 파일, 테스트 18개), `tests/conftest.py` (`make_user`, `account_products` fixture 추가)
  - `docs/API_ENDPOINTS.md`, `README.md`, `docs/PROJECT_STRUCTURE.md`

#### 변경 전
router·service·repository는 TODO 주석뿐이었고, schemas에는 `AccountSummaryResponse` 하나만 있었다. API 목록(API_ENDPOINTS.md)은 경로와 설명만 정해 두었고, **요청 본문이 어떤 모양인지는 정해져 있지 않았다.**

#### 변경 후
문서에 정한 7개 API를 모두 구현했다. 모두 로그인 필요(401).

| 메서드 | 경로 | 동작 |
|---|---|---|
| GET | `/accounts` | 내 계좌 전체(3종 합쳐 개설 순) |
| POST | `/accounts/checking` · `/deposit` · `/savings` | 개설 → 201 |
| GET | `/accounts/{type}/{account_id}` | 상세. 종류마다 필드가 다르다(`account_type`으로 구분) |
| GET | `/accounts/{type}/{account_id}/histories` | 거래내역, 최신순, `limit`(1~200, 기본 50)·`offset` |
| PATCH | `/accounts/{type}/{account_id}` | 별칭·이체 한도 수정 |

요청 본문(이번에 내가 정한 것):
```python
CheckingAccountCreate: product_id, nickname?, per_transfer_limit = 1_000_000, daily_transfer_limit = 5_000_000
DepositAccountCreate:  product_id, maturity_date, nickname?
SavingsAccountCreate:  product_id, monthly_payment, monthly_deposit_date(1~31), maturity_date, nickname?
AccountUpdate:         nickname?, per_transfer_limit?, daily_transfer_limit?   # 보낸 필드만 바뀜
```
계좌번호 발급(C-006을 코드로 옮김):
```python
f"{prefix}-{secrets.randbelow(1000):03d}-{secrets.randbelow(1_000_000):06d}"   # 110-048-767128
for _ in range(5):                       # 같은 테이블에서 겹치면 새 번호로 최대 5번
    try:
        async with db.begin(): ...      # 상품 종류 검증 → 저장
    except IntegrityError as e:
        if "account_num" not in str(e.orig): raise   # 번호 충돌이 아닌 오류는 그대로 올림
# 5번 모두 실패하면 500 ACCOUNT_NUMBER_GENERATION_FAILED
```
세 종류의 차이를 `kinds.py`의 `AccountKind` 표 하나(모델, PK 이름, 상품 type, 앞자리)에 모아서, 개설·조회·수정 코드를 세 벌로 복사하지 않았다.

#### 이유
- **한도 기본값 100만 / 500만 원:** ERD.md "팀에서 정해야 할 것"에 "이체 한도 기본값"이 비어 있었다. 개설 요청마다 한도를 반드시 받게 하면 불편하므로 생략 가능하게 하고, 임시 값을 넣었다.
- **한도·금액에 상한(1조 원)을 둠:** 컬럼이 BIGINT라서 그보다 큰 값이 들어오면 DB 오류로 500이 난다. 입력 검증에서 422로 막는다.
- **만기일은 오늘(KST)보다 뒤여야 함:** 이미 지난 날짜로 예금·적금을 열 수 없다. "오늘"을 서버 시간대가 아니라 KST로 계산한다(ERD 규칙 7과 같은 기준, C-009).
- **번호 충돌이 아닌 `IntegrityError`는 재시도하지 않고 올림:** 모두 재시도하면 다른 원인의 오류도 5번 헛돌고 가려진다. 메시지에 `account_num`이 있는지로 구분한다. SQLite와 **실제 PostgreSQL 세 테이블 모두** 메시지에 `account_num`이 들어 있음을 확인했다(재현: `scripts/pg_unique_violation_message.py`, C-025)(PostgreSQL: `duplicate key value violates unique constraint "checking_accounts_account_num_key"`).
- **남의 계좌는 403, 없는 계좌는 404:** API 문서에 정해 둔 대로다. 단점은 계좌 ID가 존재하는지 알려 준다는 것이다(아래 논의 포인트).
- **PATCH의 의미:** `nickname: null`은 "별칭 지우기", 한도에 `null`은 "안 바꿈"이다. 별칭은 지울 수 있어야 하지만 한도는 비울 수 없다(NOT NULL).
- **한도 수정 검사(1회 ≤ 1일)는 바뀐 뒤의 값끼리 비교:** 한쪽만 보냈을 때도 기존 값과 합쳐서 검사한다. 예: 기존 1일 한도 500만 원에 1회 한도만 600만 원으로 올리면 거절(`400 INVALID_TRANSFER_LIMIT`). 예금·적금에 한도를 보내면 `400 TRANSFER_LIMIT_NOT_SUPPORTED`.
- **거래내역에 페이징을 넣음:** 문서에는 없었다. 거래가 쌓이면 한 번에 전부 내려주는 응답이 계속 커진다.
- **`core/timezone.py`를 따로 둠:** 만기일 검증에 쓰고, 이체의 1일 한도(오늘 00:00 KST)에서도 쓸 것이다.
- **`tzdata` 의존성을 추가하지 않음:** Windows에서는 `psycopg`가 `tzdata`를 끌어오고(`uv.lock`에서 확인), Linux·macOS는 OS의 시간대 데이터를 쓴다.

#### 영향 범위
- 새 에러 코드: `ACCOUNT_NOT_FOUND`(404), `ACCOUNT_FORBIDDEN`(403), `INVALID_TRANSFER_LIMIT`(400), `TRANSFER_LIMIT_NOT_SUPPORTED`(400), `ACCOUNT_NUMBER_GENERATION_FAILED`(500). 상품 관련은 C-019의 `PRODUCT_TYPE_MISMATCH`·`ACCOUNT_PRODUCT_NOT_FOUND`를 쓴다.
- `AccountSummaryResponse`는 그대로이고, `schemas.py`에 상세 응답과 거래내역 응답이 추가됐다.
- **개설한 계좌의 잔액은 항상 0이고, 돈을 넣는 방법이 아직 없다.** 현재 만든 API로는 입금할 수단이 없어서, 이체를 구현해도 잔액이 있는 계좌를 만들려면 SQL로 넣어야 한다(아래 논의 포인트).
- 거래내역은 읽기만 구현했다. 거래내역을 쓰는 `save_history`와 잠금·한도 합계 메서드(C-009, C-017)는 이체 구현 때 만든다.

#### 검증
- 새 테스트 18개(parametrize 포함)를 추가했고, 전체 49개가 통과한다(SQLite). 확인하는 내용:
  - 세 종류의 개설과 앞자리, 기본 한도, 상품 종류 불일치(400)·없는 상품(404)
  - 입력 오류 5가지(1회>1일, 한도 0, 만기일 오늘, 납입일 32, 납입액 음수) → 422
  - 번호 충돌 시 재시도해서 성공 / 계속 겹치면 500
  - 내 계좌만 목록에 나옴, 종류별 상세 필드, 403·404·잘못된 type(422)
  - 거래내역 최신순·페이징·남의 계좌 403
  - 수정(별칭 지우기, 안 보낸 값 유지), 잘못된 수정 거절 후 값이 그대로인지
- 실제 PostgreSQL(compose DB)에서 서버를 띄워 개설 3종, 목록, 상세, 403·404, 수정, 1회>1일 거절, 비로그인 401을 확인했다. 서버 로그에 오류는 없었다. 확인용 사용자와 계좌는 삭제했다.

#### 팀 논의 포인트
- **[해결: C-021 개발용 충전 API]** **돈을 넣는 수단:** 현재 설계에는 외부에서 계좌로 입금하는 기능이 없다(이체는 입출금 → 입출금뿐). 실제 은행 앱이라면 ATM·타행 입금에 해당한다. 학습용이라면 "개발용 충전" API나 시드 스크립트가 필요하다. 이체와 카드 결제를 시험하려면 먼저 정해야 한다.
- **한도 기본값(100만 / 500만 원)과 상한(1조 원)**은 내가 정한 임시 값이다.
- **403으로 남의 계좌 존재를 알려 주는 문제:** 계좌 ID가 1, 2, 3처럼 순서대로라서, 403이면 "존재하는 계좌"라는 걸 알 수 있다. 일부러 404로 통일할지 정해야 한다. 지금은 문서대로 구분한다.
- **계좌 개설 개수 제한이 없다.** 한 사람이 계좌를 몇 개든 열 수 있다.
- **DB에는 `per_transfer_limit <= daily_transfer_limit` 제약이 없다.** 입력 검증과 수정 검사로만 지킨다(C-004 논의 포인트에 있던 항목). 넣으려면 마이그레이션이 필요하다.
- 번호 발급 최대 시도 횟수(5번)와 실패 시 응답(500)은 임시로 정했다. 번호 공간(종류당 약 10억 개)에 비해 충돌은 매우 드물다.

---

### C-021. 개발용 충전 API 추가 (`/dev/...`, 설정으로 켜고 끔) + 행 잠금 실제 검증

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/accounts/dev.py` (새 파일: 충전 API 전체)
  - `src/avengers_bank/domains/accounts/repository.py` (`lock_checking_accounts`, `save_history` 구현 — 이체용 TODO를 여기서 먼저 구현)
  - `src/avengers_bank/domains/accounts/service.py` (`_to_response`·`_get_owned`를 `to_response`·`get_owned`로 이름 변경: 다른 파일에서도 쓰므로 공개)
  - `src/avengers_bank/core/config.py` (`enable_dev_endpoints` 설정, 기본 `False`)
  - `src/avengers_bank/main.py` (⚠️ 공용 파일: 설정이 켜졌을 때만 dev 라우터 등록, 3줄)
  - `.env`, `.env.example` (`ENABLE_DEV_ENDPOINTS=true` 추가)
  - `tests/test_dev.py` (새 파일), `tests/conftest.py` (테스트에서 설정 켜기)
  - `docs/API_ENDPOINTS.md`, `README.md`

#### 변경 전
계좌 잔액을 올릴 방법이 없었다. 설계에 있는 입금 경로는 입출금 → 입출금 이체뿐이라, 잔액이 0인 계좌만 만들어졌고 이체·카드 결제를 시험할 수 없었다(C-020 논의 포인트).

#### 변경 후
```
POST /dev/accounts/checking/{account_id}/charge     { "amount": 100000 }   → 200, 갱신된 입출금 계좌
```
- `ENABLE_DEV_ENDPOINTS=true`일 때만 라우터가 등록된다. 꺼져 있으면 경로 자체가 없고(OpenAPI에도 안 나옴) 호출하면 404다. 코드의 기본값은 `False`다.
- 본인 입출금 계좌만 가능(남의 계좌 403, 없는 계좌 404). 금액은 1원 이상 1조 원 이하.
- 충전하면 잔액이 늘고, 거래내역이 `type="DEV_CHARGE"`, `amount`, `balance_after`로 같은 트랜잭션에서 저장된다(ERD 규칙 6).
```python
async with db.begin():
    await account_service.get_owned(db, kind, account_id, user)                 # 본인 계좌인지
    (account,) = await account_repository.lock_checking_accounts(db, [account_id])  # 규칙 9: 먼저 잠금
    account.balance += amount
    await account_repository.save_history(db, CheckingAccountHistory(..., balance_after=account.balance, type="DEV_CHARGE"))
```

#### 이유
- **이체·결제를 시험하려면 잔액이 필요하다.** SQL로 직접 넣는 방법(다른 선택지)은 코드가 늘지 않지만 매번 SQL을 쳐야 하고, 거래내역이나 `balance_after`를 빠뜨리기 쉽다. API는 실제 이체와 같은 규칙(잠금·내역 기록)으로 돈을 넣어서, 규칙이 맞는지 시험하는 데도 쓸 수 있다.
- **설정으로 켜고 끄고, 기본값을 꺼짐으로 둠:** 입금 한도도 심사도 없이 누구나 돈을 만드는 API라서 운영에 실수로 열리면 치명적이다. 설정을 안 하면 열리지 않게 했다. `.env.example`에는 켜 두었으니 개발자는 복사만 하면 되고, 운영 환경 설정에서는 이 줄을 넣지 않으면 된다.
- **파일 하나로 분리:** 나중에 지울 때 `dev.py`, `main.py`의 3줄, `config.py`의 설정 한 줄만 삭제하면 된다.
- **잔액을 올리는 처리라서 규칙 9를 그대로 지켰다.** 읽고 더해서 쓰는 방식은 동시 요청에서 갱신이 사라진다(아래 검증).
- **`lock_checking_accounts`·`save_history`를 여기서 구현:** 이체 TODO에 있던 메서드다. 이체 구현 전에 실제 DB에서 잠금이 동작하는지 먼저 확인할 수 있었다.
- **`_get_owned`·`_to_response`를 공개 이름으로:** `dev.py`가 같은 소유권 확인·응답 변환을 써야 해서, 밑줄(비공개)을 붙인 채 다른 파일에서 부르는 것보다 이름을 바꿨다. 이체도 같은 함수를 쓸 것이다.

#### 영향 범위
- **`main.py`(공용 파일)를 수정했다.** PROJECT_STRUCTURE.md는 공용 파일을 고치기 전에 팀에 공유하라고 되어 있다. 변경은 설정 조건부 라우터 등록뿐이다.
- 거래내역 `type`에 `DEV_CHARGE` 값이 생겼다. "type 값 목록"(ERD.md, 팀 결정 대기)에 추가될 값이다. 운영에서 이 API를 끄면 이 값은 생기지 않는다.
- 로컬 `.env`에 `ENABLE_DEV_ENDPOINTS=true`를 추가했다(내 PC의 `.env`는 저장소에 없다).
- 충전된 잔액은 외부에서 들어온 돈이라, 정합성 검증(`계좌 마지막 balance_after == balance`)은 그대로 성립한다.
- 새 에러 코드는 없다(`ACCOUNT_FORBIDDEN`, `ACCOUNT_NOT_FOUND` 재사용).

#### 검증
- 새 테스트 6개를 추가했고, 전체 55개가 통과한다(SQLite). 설정 기본값이 `False`인지, 충전 후 잔액·거래내역(`DEV_CHARGE`, `balance_after`), 잘못된 금액 3종(0, -1, 1조 초과)과 거절 후 잔액이 그대로인지, 남의 계좌 403·없는 계좌 404·비로그인 401을 확인한다.
- **SQLite는 `FOR UPDATE`를 무시하므로 잠금은 실제 PostgreSQL에서 따로 확인했다**(C-017 논의 포인트에서 약속한 방식). 같은 계좌에 1,000원 충전 30건을 동시에 보냈다(재현: `scripts/pg_charge_concurrency.py`, C-025).

| | 기대 잔액 | 실제 잔액 | 거래내역 | `balance_after` 값 종류 |
|---|---|---|---|---|
| 잠금 사용(현재 코드) | 30,000 | **30,000** | 30건 | 30 |
| 잠금 없음(대조군) | 30,000 | **4,000** | 30건 | 4 |

  - 대조군은 잠금 없이 읽도록 바꿔 같은 요청을 보낸 것이다. **충전 30건이 모두 성공했는데 26,000원이 사라졌다**(갱신 손실). 그래서 이 검증이 잠금의 효과를 실제로 알아볼 수 있다.
  - 단, 대조군은 읽기와 쓰기 사이에 0.01초 양보를 넣어서 경쟁 구간을 넓혔다. 실제 요청에서 같은 비율로 일어난다는 뜻은 아니고, "잠금이 없으면 손실이 생길 수 있고 있으면 생기지 않는다"는 것을 확인한 것이다.
  - 데드락 검증(두 계좌를 서로 반대 순서로 잠그는 경우)은 계좌 두 개를 잠그는 이체를 구현할 때 한다. 이번에는 계좌 하나만 잠갔다.
- 서버를 실제로 띄워서 확인했다.
  - 설정을 `false`로 덮어쓰면 OpenAPI에 `/dev` 경로가 없고 충전 요청이 404다.
  - `.env` 설정(`true`)에서는 충전 200(잔액 250,000), 남의 계좌 403, 거래내역에 `(DEV_CHARGE, 250000, 250000)`이 남았다. 서버 로그에 오류는 없었다.
- 확인용 사용자·계좌·거래내역은 모두 삭제했다. 개발 DB의 상품 시드는 그대로다.

#### 팀 논의 포인트
- 팀 설계에 없던 API다. 학습용 프로젝트에서 이체·결제 시험을 위해 필요하다고 판단했다. 팀이 원하지 않으면 `dev.py`와 연결 코드를 지우면 된다.
- 운영 환경 설정에서 이 스위치가 꺼져 있는지 어떻게 확인할지(예: 배포 체크리스트, 시작 시 경고 로그)는 정하지 않았다.
- 충전 금액의 하루 한도는 없다. 개발용이라 두지 않았다.
- 입출금 계좌에만 충전된다. 예금·적금은 이체·납입으로만 채운다(설계 그대로).

---

### C-022. transfers 도메인 구현 (이체·적금 납입·예금 입금) + 동시성·데드락 검증

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/transfers/` — `router.py`, `service.py`, `schemas.py` (TODO → 구현)
  - `src/avengers_bank/domains/accounts/repository.py` (`find_checking_by_account_num`, `lock_account`, `sum_today_transfer_amount` 구현)
  - `src/avengers_bank/domains/accounts/kinds.py` (거래내역 type 상수 4개)
  - `src/avengers_bank/core/timezone.py` (`today_start_utc()`)
  - `tests/test_transfers.py` (새 파일, 테스트 13개)
  - `docs/API_ENDPOINTS.md`, `docs/ERD.md`, `README.md`, `docs/PROJECT_STRUCTURE.md`

#### 변경 전
router·service는 TODO 주석이었고, 스키마에는 `TransferCreate`만 있었다(적금·예금 요청과 응답 스키마는 TODO). 이체의 검사 순서, 적금·예금에 한도를 적용하는지, 거래내역 `type` 값은 정해져 있지 않았다.

#### 변경 후
문서에 정한 3개 API를 구현했다. 모두 로그인 필요, 성공하면 201.

| 메서드 | 경로 | 요청 | 하는 일 |
|---|---|---|---|
| POST | `/transfers` | `from_checking_account_id`, `to_account_num`, `amount` | 입출금 → 입출금 이체 |
| POST | `/transfers/savings` | `from_checking_account_id`, `savings_account_id`, `amount` | 입출금 → 내 적금 납입 |
| POST | `/transfers/deposit` | `from_checking_account_id`, `deposit_account_id`, `amount` | 입출금 → 내 예금 입금 |

응답(셋 모두 같은 모양): `{ from_account_num, to_account_num, amount, balance_after }` (`balance_after`는 보낸 입출금 계좌의 거래 후 잔액).

이체 처리 순서 (`async with db.begin():` 하나 안에서):
```python
sender = get_owned(...)                      # 1. 본인 계좌 (403/404)   ← 잠그기 전: 소유자는 바뀌지 않는 정보
receiver = find_checking_by_account_num(...) # 2. 받는 계좌 (404)
receiver == sender 이면 SAME_ACCOUNT_TRANSFER(400)       # 3. 같은 계좌 (C-005)
lock_checking_accounts(db, [sender_id, receiver_id])     # 4. 두 계좌를 ID 순서로 한 번에 잠금 (C-017)
잔액 → 1회 한도 → 1일 한도 검사 (잠근 뒤에)              # 5. INSUFFICIENT_BALANCE / PER_TRANSFER_LIMIT_EXCEEDED / DAILY_LIMIT_EXCEEDED
양쪽 balance 변경 + 양쪽 거래내역 저장(balance_after, counterpart_account)
```
적금 납입·예금 입금: 입출금 계좌를 먼저 잠그고 그다음 적금·예금 계좌를 잠근다(C-017 순서). 잔액만 검사한다.

거래내역 `type` 값 (내가 정함, 팀 결정 대기):

| 상황 | 보낸 입출금 계좌 | 받은 계좌 |
|---|---|---|
| 입출금 → 입출금 | `TRANSFER_OUT` | `TRANSFER_IN` |
| 입출금 → 적금 | `TO_SAVINGS` | `TRANSFER_IN` |
| 입출금 → 예금 | `TO_DEPOSIT` | `TRANSFER_IN` |

`counterpart_account`는 보낸 쪽에는 받는 계좌번호, 받은 쪽에는 보낸 계좌번호다(C-007).

#### 이유
- **잠금 전/후 검사를 나눈 기준:** 소유자·받는 계좌 존재·같은 계좌 여부는 바뀌지 않는 정보라서 잠그기 전에 확인한다(소유자 아닌 사람이 남의 계좌를 잠그는 일을 막는다). 잔액과 1일 한도 합계는 동시 요청으로 바뀌므로 반드시 **잠근 뒤에** 읽는다(C-017 규칙 9).
- **본인 확인(403)을 받는 계좌 확인(404)보다 먼저 함:** 내 계좌가 아닌 사람에게 "받는 계좌가 존재한다"는 정보를 주지 않기 위해서다.
- **받는 계좌는 입출금 계좌만:** 문서의 `POST /transfers`가 "입출금 → 입출금"이다. 예금·적금은 아래의 별도 API로만 넣는다.
- **적금·예금은 본인 계좌에만, 한도는 잔액 검사만:** 문서가 "입출금 → 적금 납입", "입출금 → 예금 입금"이라고만 했다. 1회·1일 한도는 "이체 한도"이고 문서에도 `POST /transfers` 설명에만 있어서, 내 돈을 내 적금·예금으로 옮기는 것에는 적용하지 않았다.
- **1일 한도에는 `TRANSFER_OUT`만 셈:** 들어온 돈(`TRANSFER_IN`)이나 적금·예금으로 보낸 돈(`TO_*`)은 "이체한 금액"이 아니다. 오늘 00:00 KST부터(C-009)이고, `date >= since`로 비교해서 C-003의 `(checking_account_id, date)` 인덱스를 탄다.
- **금액·한도에 상한 1조 원:** C-020과 같은 `Amount` 타입을 재사용했다.
- **`today_start_utc()`가 UTC를 돌려주는 이유:** 시각을 KST 그대로 넘기면 SQLite(테스트)는 시간대를 버리고 시계 숫자만 저장해서 UTC로 저장된 값과 어긋난다. UTC로 통일하면 PostgreSQL과 SQLite 모두 같은 결과가 나온다.
- **성공 응답을 201로:** 거래내역이라는 새 기록이 생기므로 201이다. 문서에 상태 코드가 없어서 내가 정했다.

#### 영향 범위
- 새 에러 코드: `INSUFFICIENT_BALANCE`, `PER_TRANSFER_LIMIT_EXCEEDED`, `DAILY_LIMIT_EXCEEDED`(모두 400). `SAME_ACCOUNT_TRANSFER`는 C-005에서 문서화한 이름 그대로 쓴다.
- 이제 거래내역 `type` 값이 5개 쓰인다: `TRANSFER_OUT`, `TRANSFER_IN`, `TO_SAVINGS`, `TO_DEPOSIT`, `DEV_CHARGE`. 팀이 목록을 정하면 이름과 CHECK 제약을 맞춘다.
- DB 구조 변경은 없다(마이그레이션 불필요).
- 카드 결제(cards)도 같은 잠금·`balance_after` 규칙을 따라야 한다. `account_repository`의 잠금·내역 저장 메서드를 그대로 쓰면 된다.

#### 검증
- 새 테스트 13개(parametrize 포함)를 추가했고, 전체 68개가 통과한다(SQLite). 확인하는 내용:
  - 이체 성공: 양쪽 잔액, 양쪽 거래내역(`type`, `balance_after`, `counterpart_account`), 응답 내용
  - 잔액 부족·1회 한도·1일 한도(누적, 딱 한도만큼은 허용, 1원 더는 거절). 거절된 이체는 잔액과 거래내역을 바꾸지 않음
  - **1일 한도의 경계:** 어제(00:00 KST 1분 전) 이체·들어온 돈·적금 납입은 안 세고, **00:00 KST 정각**의 이체는 센다
  - 같은 계좌(400), 없는 번호(404), 예금 번호를 받는 계좌로 쓰면 404, 남의 계좌에서 보내기(403), 없는 보내는 계좌(404), 금액 0·음수·상한 초과(422), 비로그인(401)
  - 적금 납입·예금 입금: 양쪽 잔액과 거래내역(`TO_SAVINGS`/`TO_DEPOSIT`, `TRANSFER_IN`), 잔액 부족, 남의 적금·예금 403, 없는 계좌 404
- **SQLite는 잠금을 무시하므로 동시성은 실제 PostgreSQL(compose DB)에서 따로 확인했다.** 같은 계좌들에 요청을 동시에 보냈다(`asyncio.gather`, 요청마다 별도 세션. 재현: `scripts/pg_transfer_concurrency.py`, C-025).

| 시나리오 | 결과 | 기대 |
|---|---|---|
| ① A 잔액 10만 원에서 3만 원 이체 10건 | **성공 3 / 잔액부족 7**, A=10,000 B=90,000 | 3건만 성공 |
| ② 1일 한도 30만 원(1회 10만 원)에서 10만 원 이체 10건 | **성공 3 / 한도 초과 7**, A=700,000 B=300,000 | 3건만 성공 |
| ③ A→B 10건 + B→A 10건 동시 | **20건 모두 성공, 데드락 0**, A=B=1,000,000 | 데드락 없음, 합계 보존 |

  - **대조군으로 이 검증이 문제를 알아볼 수 있음을 확인했다.**
    - ①을 잠금 없이 다시 하면 **10건 모두 성공 응답**이 나왔다(총 30만 원을 보냈다고 응답했는데 실제로 움직인 돈은 3만 원: A=70,000 B=30,000). 잔액 10만 원으로 30만 원을 보낸 것처럼 보이는 상태다.
    - ③을 "받은 순서대로 하나씩 따로 잠금"(순서 고정 없음)으로 다시 하면 **20건 중 18건이 데드락으로 실패**했다. ID 순서로 한 번에 잠그는 현재 방식이 그 문제를 막는다.
  - 대조군은 읽기와 쓰기 사이에 짧은 양보(0.01초, 순서 비교 쪽은 0.05초)를 넣어 경쟁 구간을 넓혔다. 실제 요청에서 같은 비율로 일어난다는 뜻이 아니라 "잠금이 없으면 일어날 수 있고, 있으면 일어나지 않는다"는 확인이다.
  - 검증 스크립트를 처음 돌렸을 때 20건이 모두 "기타 오류"로 실패했다. 원인은 **내 검증 스크립트가 `users` 모델을 불러오지 않아** SQLAlchemy가 외래키 대상을 못 찾은 것이었다(앱은 `main.py`가 모든 모델을 불러와서 해당 없음, 테스트는 `conftest.py`가 불러옴). 스크립트를 고쳐 다시 돌린 결과가 위의 표다.
- 서버를 띄워 HTTP로 전체 흐름을 확인했다. 충전 → 이체 30만 원 → 적금 납입 10만 원 → 예금 입금 20만 원 후 잔액이 400,000 / 300,000 / 100,000 / 200,000으로 합계 1,000,000원이 보존됐고, 잔액 초과(400), 자기 계좌(400), 남의 계좌(403), 없는 번호(404), 금액 0(422)이 기대대로 나왔다. 서버 로그에 오류는 없었다.
- 확인용 사용자·계좌·거래내역은 모두 삭제했다(상품 시드 3개만 남음).

#### 팀 논의 포인트
- **만기가 지난 예금·적금에도 입금된다.** `maturity_date`를 검사하지 않는다. 막으려면 `ACCOUNT_MATURED` 같은 거절을 추가해야 한다.
- **적금 납입액이 `monthly_payment`와 무관하게 자유**이고, 예금에 여러 번 입금할 수 있다. 실제 상품은 정해진 금액으로 납입하거나 한 번만 가입하는 경우가 많다.
- **적금·예금에서 돈을 빼는 방법(해지·출금)이 없다.** 넣을 수만 있고 꺼낼 수 없다. 만기 해지가 필요하면 별도 설계가 필요하다.
- **보낸 줄과 받은 줄을 묶는 이체 ID가 없다.** 두 거래내역을 연결하는 단서는 `counterpart_account`와 시각뿐이다. 이체 취소·분쟁 처리에는 이체 ID가 필요하다. 응답에도 거래 ID가 없다.
- **계좌번호 존재 확인(탐색) 가능성:** 로그인한 사용자가 `to_account_num`을 바꿔 가며 보내면 `404`와 성공을 비교해 존재하는 계좌번호를 알아낼 수 있다(잔액 부족일 때도 존재 여부는 `INSUFFICIENT_BALANCE`로 구분됨). 실제 은행은 받는 사람 이름을 보여 주고 확인받는 방식을 쓴다.
- 한 사람의 입출금 계좌끼리의 이체도 일반 이체로 처리하고 1회·1일 한도를 적용한다.
- 수수료, 예약 이체, 이체 취소는 범위 밖이다.
- 거래내역 `type` 이름(`TO_SAVINGS` 등)과 성공 응답 코드(201)는 내가 정한 값이다.

---

### C-023. cards 도메인 구현 (발급·조회·결제·청구서) + 동시성 검증

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/cards/` — `router.py`, `service.py`, `repository.py`, `schemas.py` (TODO → 구현), `kinds.py` (새 파일)
  - `src/avengers_bank/core/timezone.py` (`kst_start_utc(day)` 추가, `today_start_utc()`가 이를 사용)
  - `tests/test_cards.py` (새 파일, 테스트 15개)
  - `docs/API_ENDPOINTS.md`, `docs/ERD.md`, `README.md`, `docs/PROJECT_STRUCTURE.md`
  - 이 문서의 C-010·C-011·C-013 상태 문구(TODO 단계 → C-023에서 구현)

#### 변경 전
router·service·repository는 TODO 주석이었고, 스키마에는 `CardSummaryResponse`만 있었다. 카드 발급·결제 요청 모양, 카드번호 형식, 청구서 생성·납부의 구체적인 처리 순서는 문서에만 있었다(C-010~C-013).

#### 변경 후
문서에 정한 API 10개를 구현했다. 모두 로그인 필요.

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| POST | `/cards/credit` | 신용카드 발급: `product_id`, `checking_account_id`(결제 계좌), `payment_date`(1~31). **한도는 받지 않고 상품 한도를 복사**(C-013) |
| POST | `/cards/debit` | 체크카드 발급: `product_id`, `checking_account_id`(출금 계좌) |
| GET | `/cards` | 내 카드 전체(신용 → 체크 순, 각각 발급 순) |
| GET | `/cards/{type}/{card_id}` | 상세. 종류마다 필드가 다름(`card_type`으로 구분) |
| GET | `/cards/{type}/{card_id}/histories` | 사용내역, 최신순, `limit`·`offset` |
| POST | `/cards/{type}/{card_id}/payments` | 결제(사용) 등록: `place_of_use`, `used_amount` |
| POST | `/cards/credit/{card_id}/bills` | 청구서 생성: `year_month`("2026-10") |
| GET | `/cards/credit/{card_id}/bills` · `/{bill_id}` | 청구서 목록(최신순) · 상세(포함된 사용내역 `items`) |
| POST | `/cards/credit/{card_id}/bills/{bill_id}/payments` | 청구서 납부 |

결제의 동작:
- **체크카드:** 입출금 계좌 잠금 → 카드 잠금 → 잔액 검사 → 출금 → 입출금 거래내역(`CARD_PAYMENT`, `balance_after`) + 카드 사용내역 저장 → 누적 사용액 증가.
- **신용카드:** 카드 잠금 → `미결제액 + 결제 금액 > credit_limit`이면 `CREDIT_LIMIT_EXCEEDED` → 사용내역 저장(`bill_id` 비움) → 미결제액 증가. **돈은 나가지 않는다.**

청구서 생성(`create_bill`): 본인 카드 확인 → 이용 기간이 끝난 달인지 확인(`기간 말일 < 오늘(KST)`, 아니면 `BILLING_PERIOD_NOT_ENDED`) → **카드 잠금** → 같은 달 청구서가 이미 있으면 `BILL_ALREADY_EXISTS`(409) → 그 달(KST 1일 00:00 이상, 다음 달 1일 00:00 미만)의 미청구 사용내역 합계(0이면 `NO_UNBILLED_USAGE`) → 청구서 저장(`UNPAID`, 납부 예정일 = 다음 달 결제일, 그 달에 없는 날이면 말일) → 합산한 사용내역에 `bill_id` 기록.

청구서 납부(`pay_bill`): 본인 카드·카드의 청구서인지 확인(아니면 404) → **결제 계좌 → 카드 → 청구서 순서로 잠금**(C-017 규칙 9) → 이미 `PAID`면 `BILL_ALREADY_PAID`(409) → 잔액 검사 → 결제 계좌 출금(입출금 거래내역 `CARD_BILL_PAYMENT`, `counterpart_account`에 카드번호) → 청구서 `PAID` + `paid_at` → **카드 미결제액에서 청구 금액을 뺀다**(C-012).

카드번호: 신용 `4000-`, 체크 `5000-` + 4자리 3묶음(`4000-1234-5678-9012`, 19자). 계좌번호와 같은 방식으로 같은 테이블 안에서 겹치면 새 번호로 최대 5번 다시 시도(`CARD_NUMBER_GENERATION_FAILED` 500).

#### 이유
- **한도를 요청으로 받지 않음:** C-013에서 상품별 고정 한도로 정했다. 요청으로 받으면 사용자가 마음대로 정할 수 있게 된다.
- **연결 계좌는 본인 입출금 계좌만:** 남의 계좌에서 출금되는 카드를 만들 수 없게 한다. 발급 때 한 번만 확인하면 소유자는 바뀌지 않는다.
- **청구서 생성에서 카드를 잠그는 이유:** 같은 달 청구서 생성을 동시에 두 번 보내도 한 번만 만들어지게 한다. 잠근 뒤에 "이미 있는지"를 먼저 확인하므로 두 번째 요청은 `NO_UNBILLED_USAGE`가 아니라 의미가 정확한 `BILL_ALREADY_EXISTS`를 받는다. DB의 `(카드, 기간 시작일)` unique 제약(C-010)은 마지막 방어선으로 그대로 둔다.
- **이용 기간이 끝난 달만 청구:** 진행 중인 달을 청구하면 이후 사용분이 다음 청구에서 빠지는 문제가 생긴다. 기간 비교는 KST 날짜 기준이다(C-009와 같은 기준). 경계는 `[1일 00:00 KST, 다음 달 1일 00:00 KST)`이다.
- **사용내역을 기간으로 묶는 이유:** `time`이 UTC로 저장되므로 KST 자정을 UTC로 바꿔 비교한다. 월말 23:59 KST는 그 달에, 다음 달 1일 00:00 KST 정각은 다음 달에 들어간다(테스트로 확인).
- **납부는 카드의 결제 계좌에서만 출금:** 어느 계좌에서 낼지 요청으로 받으면 남의 계좌를 고르는 문제가 생긴다. 발급 때 본인 확인이 끝난 결제 계좌만 쓴다.
- **체크카드 결제에는 이체 한도를 적용하지 않음:** "이체 한도"는 계좌 간 이체에 대한 한도다(C-022와 같은 구분).
- **`CARD_PAYMENT` 내역에 상대 계좌를 비움:** `counterpart_account`는 20자 계좌번호용 컬럼이라 가맹점 이름(최대 100자)이 들어가지 않는다. 가맹점은 카드 사용내역에 남는다. 반면 청구서 납부는 카드번호(19자)가 들어가서 상대로 남겼다.
- **카드 종류 차이를 `kinds.py` 표로 모음:** 계좌(C-020)와 같은 방식이다.

#### 영향 범위
- 새 에러 코드: `CARD_NOT_FOUND`(404), `CARD_FORBIDDEN`(403), `CREDIT_LIMIT_EXCEEDED`(400), `BILLING_PERIOD_NOT_ENDED`(400), `NO_UNBILLED_USAGE`(400), `BILL_ALREADY_EXISTS`(409), `BILL_ALREADY_PAID`(409), `BILL_NOT_FOUND`(404), `CARD_NUMBER_GENERATION_FAILED`(500). `INSUFFICIENT_BALANCE`·`PRODUCT_TYPE_MISMATCH`·`ACCOUNT_FORBIDDEN`은 재사용.
- 입출금 거래내역 `type` 값이 2개 늘었다: `CARD_PAYMENT`, `CARD_BILL_PAYMENT`(합계 7개). 팀이 목록을 정하면 맞춘다.
- DB 구조 변경은 없다(마이그레이션 불필요).
- **`GET /cards` 응답의 `accumulated_amount`가 카드 종류에 따라 다른 뜻**이다(신용은 미결제액, 체크는 누적 사용액). C-012에서 논의 포인트로 적은 문제가 API 응답에 그대로 드러난다.
- 이로써 설계한 도메인(users, products, accounts, transfers, cards)이 모두 구현됐다.

#### 검증
- 새 테스트 15개를 추가했고, 전체 83개가 통과한다(SQLite). 확인하는 내용:
  - 발급: 신용 한도가 상품에서 복사됨, 번호 앞자리·길이, 상품 종류 불일치·없는 상품·남의 계좌·결제일 범위 오류, 번호 충돌 재시도와 5번 모두 실패 시 500, 실패한 발급은 카드를 만들지 않음
  - 조회: 내 카드만·종류 순서, 종류별 상세 필드, 403·404·잘못된 type
  - 결제: 체크는 잔액·입출금 거래내역·카드 내역·누적 사용액, 잔액 부족 시 아무것도 안 바뀜. 신용은 한도(딱 한도까지 허용, 1원 초과 거절), 계좌 잔액이 안 변함, 검증 오류(0원·빈 가맹점·상한 초과)와 남의 카드
  - 청구서: **기간 경계**(지난달 말일 23:59 KST는 포함, 이번 달 1일 00:00 정각은 제외, 지지난달은 별도 청구서), 납부 예정일 계산, 이미 청구된 내역은 다시 청구되지 않음, 청구서를 만들어도 미결제액은 그대로, 진행 중인 달·사용 없는 달·중복·잘못된 형식 오류
  - 납부: 출금·거래내역(`CARD_BILL_PAYMENT`, 카드번호)·청구서 `PAID`·미결제액 0·**한도 복구**(한도 전체를 다시 쓸 수 있음), 재납부 409, 잔액 부족이면 청구서가 `UNPAID`로 남고 아무것도 안 바뀜, 남의 카드 403, 다른 카드의 청구서 번호 404
  - 카드 결제는 항상 서버의 "지금" 시각으로 기록되므로, 과거 달의 청구서를 시험하려고 테스트에서 사용 시각만 SQL로 옮겼다.
- **동시성은 실제 PostgreSQL(compose DB)에서 따로 확인했다**(SQLite는 잠금을 무시). 요청마다 별도 세션으로 동시에 보냈다(재현: `scripts/pg_card_concurrency.py`, C-025).

| 시나리오 | 현재 코드 결과 |
|---|---|
| a. 한도 100만 원 카드로 30만 원 결제 10건 | **성공 3 / 한도 초과 7**, 미결제액 900,000 |
| b. 잔액 10만 원 체크카드로 3만 원 결제 10건 | **성공 3 / 잔액 부족 7**, 잔액 10,000, 누적 90,000, 입출금 내역 3건 |
| c. 같은 청구서(50만 원) 납부 10건 | **성공 1 / 이미 납부 9**, 잔액 1,500,000(출금 한 번), 미결제액 0 |
| d. 같은 달 청구서 생성 10건 | **성공 1 / 이미 있음 9**, 청구서 1개, 미청구 내역 0건 |
| e. 한 계좌에서 체크 결제 10 + 이체 10 + 청구서 납부 1 동시 | **21건 모두 성공, 데드락 0**, A=1,300,000 B=100,000(금액 보존) |

  - **대조군으로 이 검증이 문제를 알아볼 수 있음을 확인했다.**
    - a를 카드 잠금 없이 다시 하면 **10건이 모두 성공**했다. 합계 300만 원을 결제했는데 기록된 미결제액은 600,000원뿐이라 한도 검사가 무너진다.
    - c를 계좌·카드·청구서 잠금 없이 다시 하면 같은 청구서에 **5건이 "납부 성공"으로 응답**됐다(중복 출금 응답).
  - 대조군은 읽기와 쓰기 사이에 0.01초 양보를 넣어 경쟁 구간을 넓혔다. 실제 요청에서 같은 비율로 일어난다는 뜻이 아니라 "잠금이 없으면 일어날 수 있고 있으면 일어나지 않는다"는 확인이다.
  - 검증 스크립트가 출력한 "납부 내역 7건"은 앞선 시나리오(c, e)의 납부까지 합친 누적값이라 청구서 하나의 중복 횟수가 아니다. 중복 횟수는 "납부 성공" 응답 5건으로 본다.
- 서버를 띄워 HTTP로 전체 흐름을 확인했다. 체크 결제(3만 원) → 신용 결제(30만·20만 원) → 한도 초과 거절 → 청구서 생성(이번 달 거절·지난달 50만 원·중복 거절) → 남의 청구서 납부 거절 → 납부 → 재납부 거절 후 입출금 잔액이 470,000원(100만 − 체크 3만 − 청구 50만)이고 미결제액이 0으로 맞았다. 납부 예정일은 10월분 → 11월 25일(결제일)이었다. 서버 로그에 오류는 없었다.
- 확인용 사용자·계좌·카드·청구서·거래내역은 모두 삭제했다(상품 시드만 남음).

#### 팀 논의 포인트
- **결제(사용) API를 카드 주인이 직접 호출한다.** 가맹점·카드 네트워크와의 연동이 없는 시뮬레이션이다. 실제로는 가맹점 쪽 인증과 승인 절차가 필요하다.
- **결제 시각을 요청할 수 없고 서버 시각으로만 기록된다.** 그래서 과거 청구 기간을 시험하려면 SQL로 시각을 바꿔야 한다.
- **납부 예정일이 지나도 자동 출금이나 연체 처리가 없다**(C-010 범위 밖). `due_date`는 안내용이다.
- **입출금 거래내역에 가맹점 이름이 보이지 않는다**(체크카드 결제). 보이게 하려면 `counterpart_account`를 넓히거나 `counterpart_name` 컬럼을 추가해야 한다(C-007).
- **체크카드는 결제 한도가 없다.** 잔액이 허용하는 만큼 쓸 수 있다. 1일 사용 한도가 필요한지 정해야 한다.
- **카드 해지·분실 정지·재발급·한도 변경이 없다.** 카드가 연결된 입출금 계좌를 없애는 기능도 없다.
- **카드번호는 실제 카드번호 체계가 아니다**(Luhn 검사 없음, 앞자리 `4000-`/`5000-`은 내가 정한 값). 1인당 카드 수 제한도 없다(C-013).
- **청구서는 이용 기간이 끝난 직후(다음 달 1일 00:00 KST부터)부터 생성할 수 있고, 결제일 전에도 가능하다.** 결제일 이후에만 만들 수 있게 할지는 정하지 않았다.
- `GET /cards`의 `accumulated_amount`가 카드 종류마다 다른 뜻이다. 신용카드 쪽을 `outstanding_amount`로 바꿀지 다시 정해야 한다(C-012).

---

### C-024. users `PATCH /users/me` 구현 (이름·닉네임·전화번호 수정)

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/users/schemas.py` (`UserUpdate` 새 스키마)
  - `src/avengers_bank/domains/users/service.py` (`update_me`, TODO 주석 삭제)
  - `src/avengers_bank/domains/users/router.py` (`PATCH /users/me`, TODO 주석 삭제)
  - `tests/test_users.py` (테스트 13개 추가)
  - `docs/API_ENDPOINTS.md` (📝 → ✅, 예시), `README.md`

#### 변경 전
팀 원본에 TODO로만 있었다. 이 항목으로 소스에 남은 TODO가 없어졌다.
```python
# users/router.py
# TODO: PATCH /users/me — 내 정보 수정
# users/service.py
# TODO: PATCH /users/me — 이름, 닉네임, 전화번호 수정
```

#### 변경 후
`PATCH /users/me` (로그인 필요) → `200`, 수정된 내 정보(`GET /users/me`와 같은 모양).
```python
class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")      # 바꿀 수 없는 필드를 보내면 422
    name: str | None = Field(default=None, min_length=1, max_length=50)
    nick_name: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, min_length=9, max_length=20)
    # name·phone을 null로 보내면 422 (model_validator)
```
```python
async def update_me(self, db, current_user, data):
    async with db.begin():
        user = await user_repository.find_by_id(db, current_user.user_id)
        for field, value in data.model_dump(exclude_unset=True).items():   # 보낸 필드만
            setattr(user, field, value)
    return user
```
- **보낸 필드만 바뀐다.** 안 보낸 값은 그대로다. 빈 본문 `{}`은 아무것도 안 바꾸고 `200`이다(C-020의 계좌 수정과 같다).
- `nick_name`에 `null`을 보내면 닉네임이 지워진다. `name`·`phone`은 `null`이면 `422`.
- 길이 제한은 가입(`UserCreate`)과 같다.

#### 이유
- **`nick_name`만 지울 수 있게 한 이유:** `users.nick_name`은 NULL을 허용하는 컬럼이고, `name`·`phone`은 NOT NULL이다. `null`을 그대로 저장하려 하면 저장 단계에서 NOT NULL 위반이 나므로, 입력 검증에서 `422`로 먼저 막는다.
- **바꿀 수 없는 필드(`login_id`, `password`, `user_id` 등)를 `422`로 거절:** 조용히 무시하면 클라이언트는 `200`을 받고 "아이디가 바뀌었다"고 믿게 된다. 요청이 잘못됐다는 걸 알려 주는 편이 안전하다. 같은 이유로 비밀번호 변경은 이 API로 되지 않는다.
- **service에서 사용자를 다시 조회하는 이유:** `get_current_user`는 별도 세션으로 읽어서 `UserResponse`(복사본)만 넘긴다(C-018). 수정은 이 요청의 세션에서 ORM 객체를 읽어 바꿔야 저장된다.
- **행 잠금을 쓰지 않음:** 돈이 움직이는 처리가 아니므로 ERD 규칙 9의 대상이 아니다. 같은 사용자가 동시에 두 번 수정하면 마지막 요청이 이긴다.
- **조회 결과가 없으면 `401 INVALID_TOKEN`:** 토큰은 유효한데 사용자가 없는 경우다. 지금은 회원 탈퇴 기능이 없어서 일어나지 않지만, `get_current_user`와 같은 방어를 해 두었다.

#### 영향 범위
- 새 에러 코드 없음(`VALIDATION_ERROR`, `AUTHENTICATION_REQUIRED` 재사용). DB 구조 변경 없음(마이그레이션 불필요).
- API_ENDPOINTS.md의 users 4개 API가 모두 ✅가 됐다.
- 이전에 로그인한 토큰은 그대로 유효하다. 토큰에는 `user_id`만 들어 있어서 이름·전화번호를 바꿔도 영향이 없다.

#### 검증
- 새 테스트 13개를 추가했고, 전체 96개가 통과한다(SQLite). 확인하는 내용:
  - 이름·전화번호 수정, 닉네임만 수정, 안 보낸 값은 그대로, 다시 조회해서 실제로 저장됐는지
  - 닉네임 지우기(`null`), 빈 본문은 변화 없음
  - 거절 9가지: `name`·`phone`을 `null`로, 빈 이름, 짧은 전화번호, 51자 이름·닉네임, `login_id`·`password`·`user_id` 보내기 → 모두 `422`이고, 거절 후 이름과 아이디가 그대로
  - 다른 사용자의 정보는 바뀌지 않음, 비로그인은 `401`
- 실제 PostgreSQL을 쓰는 서버로 확인했다. 수정 후 다시 조회하면 저장돼 있었고, 닉네임 지우기, 이름 `null`·짧은 전화번호·아이디 변경 시도는 `422`, 비로그인은 `401`이었다. 수정 요청 뒤에도 원래 비밀번호로 로그인이 됐다(비밀번호는 안 바뀜). 서버 로그에 오류는 없었다. 확인용 사용자는 삭제했다.

#### 팀 논의 포인트
- **비밀번호 변경과 회원 탈퇴가 없다.** 설계에 없던 기능이라 만들지 않았다. 필요하면 비밀번호 변경은 현재 비밀번호 확인이 필요하다.
- **전화번호 형식을 검사하지 않는다.** 가입과 같이 길이(9~20자)만 본다. 숫자·하이픈 형식으로 제한할지 정해야 한다.
- 이름·닉네임에 중복 금지나 금지어 규칙은 없다(닉네임은 중복돼도 된다고 보았다).
- 아이디(`login_id`)는 바꿀 수 없게 두었다. 바꿀 수 있게 하려면 중복 검사와 로그인 영향(토큰, 다른 곳의 참조)을 따져야 한다.

---

### C-025. PostgreSQL 동시성 검증 스크립트를 저장소에 보관 (`scripts/`)

- **날짜:** 2026-11-05
- **분류:** 테스트 (+ 구조)
- **상태:** 적용
- **바뀐 파일:**
  - `scripts/_common.py` (공통 도구), `scripts/pg_charge_concurrency.py`, `scripts/pg_transfer_concurrency.py`, `scripts/pg_card_concurrency.py`, `scripts/pg_unique_violation_message.py` (모두 새 파일)
  - `scripts/README.md` (실행법·읽는 법·주의)
  - `README.md` ("동시성 검증" 절), `docs/PROJECT_STRUCTURE.md` (트리에 `scripts/`)
  - 앱 코드는 바꾸지 않았다.

#### 변경 전
C-021·C-022·C-023의 동시성 검증은 스크립트로 했는데, 그 스크립트가 **세션 전용 임시 폴더**에만 있었다. 결과는 각 항목의 "검증"에 표로 남아 있지만 **다시 돌릴 수 없었다.** 임시 버전에는 두 가지 문제도 있었다.
- 연결된 DB가 무엇이든 그대로 실행하고 `smoke%` 사용자를 지웠다.
- 번호 중복 메시지 확인(`pg_collision.py`)은 이전 실행이 남긴 계좌가 있어야만 돌아갔다(혼자서는 못 돌아감).

#### 변경 후
| 스크립트 | 확인하는 것 | 근거 |
|---|---|---|
| `pg_charge_concurrency.py` | 동시 충전 30건: 잠금이 있으면 합계가 맞고 없으면 갱신이 사라진다 | C-021 |
| `pg_transfer_concurrency.py` | 동시 이체: 잔액 경쟁, 1일 한도 경쟁, A→B / B→A 데드락 없음 + 대조군 2개 | C-022 |
| `pg_card_concurrency.py` | 신용 한도, 체크카드 잔액, 청구서 납부·생성의 "두 번 누름", 섞어서 동시에 + 대조군 2개 | C-023 |
| `pg_unique_violation_message.py` | 계좌 3종·카드 2종의 중복 오류 메시지에 `account_num`/`card_num`이 있는지, 외래키 오류가 번호 충돌로 오인되지 않는지 | C-020, C-023 |

```bash
uv run python scripts/pg_transfer_concurrency.py     # 통과 0, 실패 1 (종료 코드)
```
- 개발용 PostgreSQL(127.0.0.1)이 아니면 DB에 접속하기 전에 거부한다. 상품 시드가 없으면 안내하고 끝낸다.
- `verify_...` 이름의 사용자와 그 데이터를 만들고, **끝나면 (실패해도) 지운다.** 시작할 때도 같은 이름의 찌꺼기를 먼저 지운다. 다른 사용자의 데이터는 건드리지 않는다.
- 연결·정리·Windows 이벤트 루프(C-016) 같은 중복은 `_common.py`로 모았다.
- `pg_unique_violation_message.py`는 이번에 새로 만들었다. 스스로 데이터를 만들고, 임시 버전이 확인하지 못하던 카드 2종과 "번호 충돌이 아닌 오류" 경우도 확인한다.

#### 이유
- **이 검증이 "동시성은 SQLite로 확인할 수 없다"는 문제에 대한 유일한 근거**다(C-017 결정: pytest는 SQLite 유지). 근거를 다시 돌릴 수 없으면 코드를 바꿀 때마다 "여전히 안전한가"를 확인할 방법이 없다.
- **자동 실행(pytest)이 아니라 수동 스크립트인 이유:** pytest를 PostgreSQL로 바꾸지 않기로 했다(C-017). 대신 같은 검증을 사람이 필요할 때 실행할 수 있게 했다.
- **개발용 DB가 아니면 거부:** 이 스크립트들은 사용자와 계좌를 만들고 지운다. 실수로 다른 DB를 가리킨 `.env`로 실행하면 안 된다.
- **번호 중복 메시지를 스크립트로 확인하는 이유:** 계좌·카드번호 재시도(C-006, C-020, C-023)는 `IntegrityError` 메시지에 `account_num`/`card_num`이 있는지로 번호 충돌을 판단한다. 이 가정은 DB 종류와 버전에 따라 달라질 수 있어서, DB를 바꾸거나 업그레이드할 때 다시 확인할 수 있어야 한다.

#### 영향 범위
- pytest에는 영향이 없다(`testpaths = ["tests"]`). 앱 코드와 DB 구조 변경도 없다.
- 개발 DB에 `verify_...` 사용자가 잠깐 생겼다가 사라진다.
- 서비스 함수를 직접 호출하므로 **라우터 계층은 확인하지 않는다.** HTTP 흐름 확인은 각 항목의 "검증"에 적은 서버 확인이 따로 했던 것이고, 그 스크립트(`smoke_*.py`)는 저장소에 두지 않았다.

#### 검증
저장소 위치에서 4개 모두 실행해서 통과했다(종료 코드 0). 결과는 C-021~C-023의 표와 같은 결론이다.

| 스크립트 | 현재 코드 | 잠금을 뺀 대조군 |
|---|---|---|
| 충전 | 30건 → 잔액 30,000, 내역 30건, `balance_after` 30종류 | 잔액 3,000 (27,000원 사라짐) |
| 이체 | 잔액 경쟁 3건 성공·7건 거절, 한도 경쟁 3건 성공·7건 거절, A→B/B→A 20건 모두 성공(데드락 0) | 10건 모두 성공 응답, 데드락 20건 중 19건 |
| 카드 | 한도·잔액 3건 성공, 납부·청구서 생성 1건 성공, 섞어서 21건 모두 성공(금액 보존) | 한도 10건 모두 성공, 같은 청구서 10건 모두 "납부 성공" |
| 번호 메시지 | 5개 표 모두 `account_num`/`card_num` 포함, 외래키 오류 2종은 미포함 | — |

- **대조군의 숫자는 실행마다 다르다**(예: 충전 손실이 임시 폴더 때는 26,000원, 이번에는 27,000원). 동시 실행의 타이밍 때문이고, 스크립트는 숫자가 아니라 "문제가 재현됐는가"를 확인한다.
- 옮기는 과정에서 **스크립트 쪽 실수 2건**을 스크립트의 실패가 알려 줬고 고쳤다. 앱 문제가 아니었다.
  1. 번호 확인 스크립트: 외래키 오류를 만들려고 번호를 바꾸는 코드가 입출금 번호에는 아무것도 바꾸지 못해서, 같은 번호가 들어가 중복 오류가 났다. 새 번호를 명시했다.
  2. 카드 스크립트: 계좌를 만드는 공통 함수의 기본 이체 한도(1원) 때문에 시나리오 e의 이체 10건이 `PER_TRANSFER_LIMIT_EXCEEDED`로 거절됐다. 한도를 명시했다.
- 개발용이 아닌 호스트(`db.example.com`)를 가리키게 해서 접속 전에 거부(종료 코드 1)하는지 확인했다. 이때 메시지가 Windows 터미널에서 깨져서 표준 오류도 UTF-8로 바꿨다.
- 실행 후 개발 DB에 사용자·계좌·카드·거래내역이 모두 0이고 상품만 남아 있음을 확인했다. pytest 96개는 그대로 통과한다.
- **확인하지 못한 것:** 상품 시드가 없을 때 안내하고 끝나는 동작은 실제로 시험하지 않았다(시드를 지워야 해서).

#### 팀 논의 포인트
- **자동화:** 이 스크립트들을 CI나 pytest(PostgreSQL 마커)에 넣을지는 정하지 않았다. 지금은 사람이 서비스 코드를 바꾼 뒤 실행한다.
- 스크립트는 한 번에 돌리는 러너가 없다. 4개를 각각 실행해야 한다.
- 대조군은 저장소 함수를 실행 중에 바꿔치기(monkeypatch)해서 만든다. 잠금 코드 구조가 바뀌면 대조군도 같이 고쳐야 한다.

---

### C-026. 로그인 응답 시간으로 아이디 존재를 알 수 없게 수정 + users 401·422 테스트 (초기 리뷰 9번)

- **날짜:** 2026-11-05
- **분류:** 보안 (+ 테스트)
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/core/security.py` (`DUMMY_HASH` 추가) — 공용 파일
  - `src/avengers_bank/domains/users/service.py` (`UserService.login`)
  - `tests/test_users.py` (테스트 35개 추가)

#### 변경 전
```python
user = await user_repository.find_by_login_id(db, data.login_id)
if user is None or not await run_in_threadpool(
    verify_password, data.password, user.hashed_password
):
    raise UnauthorizedException(message="아이디 또는 비밀번호가 올바르지 않습니다.", code="INVALID_CREDENTIALS")
```
`user is None`이면 `or`가 뒤를 건너뛰어서, **없는 아이디는 비밀번호 검증(argon2)을 아예 하지 않았다.**

#### 변경 후
```python
# security.py: 서버를 시작할 때 한 번 만들어 두는 가짜 해시
DUMMY_HASH = password_hash.hash("dummy-password-for-constant-time-login")

# service.py: 없는 아이디도 가짜 해시로 같은 검증을 한다
hashed_password = user.hashed_password if user else DUMMY_HASH
password_ok = await run_in_threadpool(verify_password, data.password, hashed_password)
if user is None or not password_ok:
    raise UnauthorizedException(...)
```

#### 이유
- 응답 본문은 이미 같았다(`INVALID_CREDENTIALS`). 그런데 **걸리는 시간**이 달라서, 없는 아이디와 틀린 비밀번호를 구분할 수 있었다.
- **측정으로 확인했다** (서비스 함수를 직접 호출, SQLite, 25회 중앙값):

| | 존재하는 아이디(틀린 비밀번호) | 존재하지 않는 아이디 | 비율 |
|---|---|---|---|
| 수정 전 | 72.9 ms | 1.6 ms | **45배** |
| 수정 후 | 75.8 ms | 76.6 ms | 1.01배 |

- 재현(공격): 흔한 아이디 목록으로 로그인을 시도하고 응답 시간을 비교하면, 가입된 아이디만 골라낼 수 있다. 그 아이디들에 대해서만 비밀번호를 추측하면 된다. 45배 차이는 네트워크 잡음 속에서도 구분된다.
- **가짜 해시를 쓰는 이유:** 없는 아이디도 같은 알고리즘·같은 설정으로 검증하면 시간이 비슷해진다. 단, 가짜 해시가 올바른 argon2 형식이 아니면 검증이 곧바로 `False`로 끝나서(시간이 짧아져서) 의미가 없다. 그래서 테스트로 진짜 해시인지 확인한다.

#### 영향 범위
- API 응답 형식·상태 코드 변경 없음. DB 변경 없음. **공용 파일 `core/security.py`를 수정했다**(팀에 공유할 항목).
- 서버를 시작할 때 가짜 해시를 만드느라 약 75ms가 더 든다(한 번뿐).
- **없는 아이디로 로그인을 시도해도 이제 약 75ms의 CPU를 쓴다.** 같은 요청을 대량으로 보내면 서버 부하가 커진다(아래 논의 포인트).

#### 검증
- 테스트 35개를 추가했고, 전체 131개가 통과한다(SQLite).

| 묶음 | 확인하는 내용 |
|---|---|
| 로그인 실패 3개 | 틀린 비밀번호와 없는 아이디의 **응답 본문·헤더가 완전히 같음**, 없는 아이디도 가짜 해시로 비밀번호 검증을 함(호출을 감시), 가짜 해시가 진짜 argon2 해시임 |
| 가입 검증(422) 14개 | 아이디 3·51자, 비밀번호 7·129자, 이름 빈 값·51자, 전화번호 8·21자, 닉네임 51자, 필수 필드 4개 누락 → 모두 `422`이고 `details`가 있으며 **거절된 가입은 계정을 만들지 않음**. 경계값(아이디 4자, 비밀번호 8자, 전화번호 9자, 닉네임 50자)은 가입됨 |
| 로그인 검증(422) 6개 | 빈 아이디·비밀번호, 필드 누락, 너무 긴 값 |
| 인증(401) 11개 | 헤더 없음·Bearer 아님·토큰 없음 → `AUTHENTICATION_REQUIRED`. 엉터리 토큰, **만료**, **다른 키로 서명**, `exp` 없음, **`alg: none`**, `sub`가 숫자 아님, 없는 사용자 → `INVALID_TOKEN` |
| 대조군·위생 2개 | 테스트가 만든 정상 토큰은 `200`(거절 테스트가 토큰을 잘못 만들어서 통과하는 착시가 아님을 확인), 응답에 비밀번호·해시(`$argon2`)가 나오지 않음 |

- **테스트가 문제를 잡는지 확인했다(변이 검증).** 수정을 일부러 되돌리자 `test_login_checks_password_even_for_unknown_login_id`가 **실패**했고, 복구하자 통과했다(복구 후 파일이 원본과 같음을 해시로 확인). 나머지 로그인 테스트 2개는 응답 내용·해시 형식을 보는 것이라 시간 차이 자체는 이 테스트 하나가 잡는다. **실제 시간을 재는 테스트는 실행마다 흔들려서 만들지 않았다.** "같은 검증을 한다"는 구조를 확인하는 것으로 대신했다.
- 실제 서버(HTTP, PostgreSQL)에서 확인했다: 가입 201, 정상 로그인 200, 틀린 비밀번호와 없는 아이디 모두 `401 INVALID_CREDENTIALS`로 본문이 같았고, **응답 시간 중앙값은 130.8ms 대 123.0ms(1.06배)** 였다. 서버 로그에 오류는 없었다. 확인용 사용자는 삭제했다.
- **완전히 같지는 않다.** HTTP에서 약 8ms(6%) 차이가 남았다. 측정 잡음과 DB 조회 차이가 섞인 값으로 보이지만, 표본이 매우 많은 공격자는 작은 체계적 차이를 노릴 수도 있다. 수정 전의 45배에 비하면 실용적으로 구분하기 어려운 수준이라고 판단했다.

#### 팀 논의 포인트
- **로그인 시도 횟수 제한(rate limit)이 없다.** 비밀번호 무차별 대입이 가능하다. 더구나 이번 수정으로 없는 아이디도 argon2 비용을 쓰므로, 요청을 대량으로 보내면 서버를 느리게 만들 수 있다. 제한이 필요한지 정해야 한다.
- **회원가입은 중복 아이디를 `409 LOGIN_ID_ALREADY_EXISTS`로 알려 준다.** 이것도 아이디 존재를 알려 준다. 가입 화면에서 중복 확인이 필요해서 보통은 감수하지만, 팀이 알고 있어야 한다.
- **해시 설정이 바뀌면 시간이 어긋날 수 있다.** 가짜 해시는 서버를 시작할 때 현재 설정으로 만들어지지만, 이미 가입한 사용자의 해시는 가입 당시 설정으로 만들어졌다. 해시 라이브러리의 기본 설정을 올리면 둘의 시간이 달라질 수 있으니 그때 다시 측정해야 한다.

---

### C-027. ERD 다이어그램 v2 추가 (`AvengersBankDiagram_v2.drawio`, 모델에서 자동 생성)

- **날짜:** 2026-11-05
- **분류:** 문서
- **상태:** 적용
- **바뀐 파일:**
  - `docs/AvengersBankDiagram_v2.drawio` (새 파일, 자동 생성)
  - `scripts/generate_erd_drawio.py` (새 파일, 생성 스크립트), `scripts/README.md`
  - `docs/ERD.md` (v2 안내 한 줄), `README.md` (문서 표), `docs/PROJECT_STRUCTURE.md` (트리)
  - **원본 `docs/AvengersBankDiagram.drawio`는 수정하지 않았다** (수정 시각이 작업 시작 때인 11월 4일 10:51 그대로).

#### 변경 전
원본 drawio는 표 13개, 관계선 17개다. 그런데 **내가 바꾸기 전부터 ERD.md·코드와 달랐다.** 예를 들어 `User(회원)` 표에 `hashed_password`와 `nick_name`이 없다(ERD.md와 코드에는 있다). 지금은 C-007·C-008·C-010~C-013의 변경(청구서 표, 한도, 거래내역 컬럼 등)도 반영돼 있지 않다.

#### 변경 후
`docs/AvengersBankDiagram_v2.drawio`: 표 14개, 컬럼 99개, 관계선 19개. 원본과 같은 draw.io 표 모양으로 그렸다.
- 각 행에 `PK`·`FK`·`UK` 표시, 컬럼 이름, 타입(`BIGINT`, `VARCHAR(50)`, 비어도 되면 `NULL`)을 적었다.
- 관계선 끝은 까마귀발(여러 개), 시작은 "반드시 하나"(`NOT NULL` 외래키) 또는 "없거나 하나"(`NULL` 허용, 예: `credit_card_histories.bill_id`)이다.
- **노란 칸 22행 = 팀 초기 설계에서 바뀌었거나 새로 생긴 것:** `credit_card_bills` 표 전체(9행, C-010), `credit_card_histories.bill_id`(C-010), `credit_cards.credit_limit`·`accumulated_amount`(C-011, C-012), `card_products.credit_limit`(C-013), 거래내역 3종의 `amount`·`balance_after`·`counterpart_account`(C-007, C-008, 9행).
- 맨 위에 메모 상자로 위 내용과 기호 설명을 넣었다.
- 표 이름은 원본의 클래스풍(`User(회원)`)이 아니라 **코드의 실제 테이블 이름 + 한글**(`users(회원)`)이다. ERD.md·코드와 바로 대조할 수 있다.

#### 이유
- **원본을 고치지 않고 새 파일로:** 팀이 만든 원본이라, 2026-11-05에 "갱신하지 말고 v2로 새로 만들자"고 정했다. 원본은 팀 초기 설계의 기준으로 그대로 남는다.
- **손으로 그리지 않고 모델에서 자동 생성:** 원본이 코드와 어긋난 이유가 손으로 그려서였다. 표·컬럼·외래키를 모델에서 읽으면 어긋날 수 없고, 모델이 바뀌면 한 줄로 다시 만든다.
- **노란 칸:** 팀 회의에서 "초기 설계에서 무엇이 바뀌었나"를 이 그림 한 장으로 볼 수 있게 했다.

#### 영향 범위
- 앱 코드·DB 구조 변경 없음. pytest에 영향 없음. 스크립트는 DB에 연결하지 않는다.
- ERD.md의 안내와 README 문서 표에 v2 링크가 추가됐다. ERD.md 본문(Mermaid)은 바꾸지 않았다.

#### 검증
- 생성 결과: 표 14개, 관계선 19개(외래키 하나당 선 하나).
- XML 구조: `id`가 모두 달라 중복이 없고, 모든 `parent`·관계선의 `source`·`target`이 실제 셀(행)을 가리키며, **표끼리 겹치지 않는다.**
- **ERD.md의 Mermaid와 14개 표의 컬럼이 모두 같다.** 문서(ERD.md)와 코드(모델)가 어긋나지 않았다는 확인이기도 하다.
- 레이아웃을 그림으로 그려서 봤다(3열: 회원·상품 | 계좌·카드 | 거래내역·청구서, 노란 칸이 바뀐 곳에 들어감).
- **확인하지 못한 것:** draw.io에서 이 파일을 실제로 열어 보지는 못했다(draw.io가 설치돼 있지 않고, 웹 draw.io에 파일 내용을 올리지도 않았다). 원본과 같은 XML 패턴을 썼지만, 처음 열면 표 제목이 길어 잘리거나 관계선이 겹쳐 보일 수 있다. 그럴 땐 draw.io에서 끌어서 정리하면 된다.

#### 팀 논의 포인트
- 원본 drawio(v1)를 v2로 **대체할지, 지울지, 둘 다 둘지** 정해야 한다. 지금은 둘 다 있고 v1은 최초 설계라 지금 코드·ERD.md와 다르다.
- **자동 생성이라, draw.io에서 표 위치를 손으로 바꿔 저장해도 다시 생성하면 덮어쓴다.** 위치는 스크립트의 `TABLES`에서 고쳐야 한다.
- 인덱스와 CHECK 제약은 그림에 없다(C-003, C-004). 필요하면 표 아래에 주석으로 넣을지 정해야 한다.
- ERD.md의 Mermaid도 손으로 관리하는데, 같은 방식으로 자동 생성할 수 있다. 지금은 위 검증으로만 일치를 확인했다.

### C-028. 버전 관리 시작 (`git init` + 첫 커밋)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** 없음 (`.git/` 생성만. 첫 커밋 `b4b9c0b`)

#### 변경 전
이 폴더는 git 저장소가 아니었다. 변경 이력은 이 문서뿐이고 코드를 되돌릴 방법이 없었다.

#### 변경 후
`git init -b main` 후 80개 파일을 첫 커밋 `Initial commit: avengers-bank baseline`으로 남겼다.

#### 이유
- 이후 작업(마이그레이션, 모델 개명 등)이 파일을 많이 건드려서, 잘못되면 되돌릴 안전망이 필요했다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음. 4-11(CI)을 할 수 있는 전제가 생겼다.
- Windows라 커밋 때 "LF will be replaced by CRLF" 경고가 나온다. 동작에는 문제없고, 줄바꿈을 고정하려면 `.gitattributes`가 필요하다(하지 않음).

#### 검증
- 커밋 전에 `.gitignore`(`.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `*.db`)가 적용돼 `.env`·`.venv`·`test.db`가 스테이징에 없음을 확인했다.
- `git log`로 커밋 1개 확인. 테스트는 코드를 바꾸지 않아 다시 돌리지 않았다.

#### 팀 논의 포인트
- 원격 저장소(GitHub 등)는 아직 연결하지 않았다. 팀과 공유하려면 그때 정한다.

### C-029. 임시 값 1-1~1-7 확정 + 코드 스타일 도구(ruff) 도입 안 함

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** 코드 변경 없음 (`docs/NEXT_STEPS.md` 상태만 변경)

#### 변경 전
임시로 정해 둔 값(이체 한도, 금액 상한, 계좌·카드번호 앞자리, 시드 상품 값, 201 응답, 번호 발급 재시도 5번)이 "확정 대기"였고, 0-2(ruff)는 미정이었다.

#### 변경 후
- **1-1~1-7을 지금 값 그대로 확정:** 이체 한도 1회 100만/1일 500만 원, 금액 상한 1조 원, 계좌 앞자리 `110`/`120`/`220`, 카드 앞자리 `4000-`/`5000-`(Luhn 없음), 시드 상품 값, 이체·결제·청구서 생성 `201`, 번호 발급 최대 5번 재시도.
- **0-2: ruff를 도입하지 않기로 함(➖).** 학습·시연용이고 코드가 대체로 일관돼서 얻는 게 작다.
- 1-8(거래내역 `type` CHECK 제약)은 마이그레이션이 필요해 별도 항목으로 남겼다.

#### 이유
- 값을 바꿀 이유가 없고, 확정해 두면 이후 작업에서 다시 묻지 않는다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음.

#### 검증
- 코드를 바꾸지 않아 테스트를 다시 돌리지 않았다.

#### 팀 논의 포인트
- 서비스로 쓰게 되면 한도·상품 값은 다시 정해야 한다.

---

### C-030. 거래내역 `type`에 DB CHECK 제약 추가 (1-8)

- **날짜:** 2026-11-05
- **분류:** DB 스키마
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/domains/accounts/models.py` (거래내역 3종의 `__table_args__`)
  - `alembic/versions/a1c8e3f5b2d4_add_history_type_check.py` (새 마이그레이션)
  - `tests/test_accounts.py` (`DEPOSIT` → `DEV_CHARGE`)

#### 변경 전
거래내역 `type`은 `String(20)`이고 DB가 값을 검사하지 않았다.

#### 변경 후
- 이름 7개를 확정했다: `TRANSFER_OUT`, `TRANSFER_IN`, `TO_SAVINGS`, `TO_DEPOSIT`, `CARD_PAYMENT`, `CARD_BILL_PAYMENT`, `DEV_CHARGE`.
- `checking_account_histories.type IN (7개 전부)`, `deposit_account_histories`·`savings_account_histories`는 `type IN ('TRANSFER_IN')`. 예금·적금 쪽에는 지금 코드가 `TRANSFER_IN`만 쓴다.
- 제약 이름: `ck_{checking|deposit|savings}_account_histories_type`.

#### 이유
- 서비스에 오타가 있어도(`TRANSFER_OUTT`) DB가 막는다. 한도 합계 쿼리가 `type == TRANSFER_OUT`을 보기 때문에, 이름이 틀리면 1일 한도 집계가 조용히 어긋난다.

#### 영향 범위
- 3-1(해지·출금)을 만들 때 예금·적금 쪽에 새 type이 필요하면 마이그레이션으로 제약을 바꿔야 한다. 의도한 것이다.
- 값 목록이 `kinds.py` 상수와 마이그레이션에 따로 적혀 있어, 새 type을 추가할 때 둘 다 고쳐야 한다.
- 기존 운영 데이터가 없어 데이터 정리는 필요 없었다.

#### 검증
- pytest 131개 통과. 처음에 `test_histories_newest_first_with_paging`이 7개에 없는 `DEPOSIT`을 직접 넣어서 실패해 `DEV_CHARGE`로 고쳤다(제약이 실제로 동작한다는 확인이기도 하다).
- `alembic upgrade head`, `downgrade -1`, 다시 `upgrade head` 성공. `alembic check`에서 모델과 DB 차이 없음.
- PostgreSQL 검증 스크립트 `pg_charge`·`pg_transfer`·`pg_card` 모두 통과(실제 서비스 코드가 쓰는 type이 제약에 걸리지 않음).
- ERD v2 재생성(표 14개, 관계선 19개). CHECK는 그림에 없어서 내용 변화는 없다.

#### 팀 논의 포인트
- 예금·적금에 `TRANSFER_IN`만 허용한 것이 너무 좁은지(3-1에서 어차피 바뀜).

---

### C-031. 남의 계좌·카드도 404로 통일 (2-1)

- **날짜:** 2026-11-05
- **분류:** 보안
- **상태:** 적용
- **바뀐 파일:**
  - `domains/accounts/service.py`, `domains/cards/service.py` (`get_owned`)
  - `domains/accounts/router.py`, `accounts/dev.py`, `cards/router.py`, `transfers/router.py` (문서용 `error_responses`에서 403 제거)
  - `tests/test_accounts.py`, `test_cards.py`, `test_transfers.py`, `test_dev.py`, `docs/API_ENDPOINTS.md`

#### 변경 전
```python
if account is None:
    raise NotFoundException(code="ACCOUNT_NOT_FOUND", ...)
if account.user_id != user.user_id:
    raise ForbiddenException(code="ACCOUNT_FORBIDDEN", message="본인의 계좌가 아닙니다.")
```
카드도 같은 모양(`CARD_FORBIDDEN`).

#### 변경 후
```python
if account is None or account.user_id != user.user_id:
    raise NotFoundException(code="ACCOUNT_NOT_FOUND", ...)
```
카드는 `CARD_NOT_FOUND`. 소유 확인이 모두 `get_owned` 한 곳을 지나서 두 함수만 고치면 됐다. `ForbiddenException` 클래스는 쓰는 곳이 없어졌지만 `core/exceptions.py`에 남겼다.

#### 이유
- ID가 1, 2, 3 순서라, 로그인한 사용자가 `/accounts/checking/1`, `/2`, ...를 돌려 보며 403과 404의 차이로 "누가 몇 번 계좌를 갖고 있는지(존재 여부)"를 알 수 있었다.

#### 영향 범위
- 응답 코드가 바뀌는 API 변경이다: 남의 계좌·카드 접근이 403 → 404. 프론트가 `ACCOUNT_FORBIDDEN`·`CARD_FORBIDDEN`을 처리하고 있다면 고쳐야 한다.
- 이체·적금 납입·예금 입금·체크카드 발급에서 남의 계좌를 내 계좌로 지정한 경우도 404가 된다.
- **같은 방식으로 아직 드러나는 것:** 이체의 "받는 계좌번호"는 존재 여부가 드러난다(2-9에서 다룸, 그대로 두기로 함).
- DB·마이그레이션 변경 없음.

#### 검증
- 테스트의 403 기대값 12곳을 404로 고쳐 pytest 131개 통과.
- 돈이 움직이는 코드 앞의 소유 확인이라 PostgreSQL 검증 스크립트 `pg_charge`·`pg_transfer`·`pg_card`를 다시 돌려 모두 통과했다.
- 확인하지 못한 것: 없는 ID와 남의 ID의 응답 본문·시간이 완전히 같은지(둘 다 같은 예외와 같은 한 번의 조회라 같다고 보지만 측정하진 않았다).

#### 팀 논의 포인트
- 프론트가 403 코드를 쓰고 있는지 확인해야 한다.

---

### C-032. 입출금 계좌 한도 순서를 DB도 지키게 함 (2-2)

- **날짜:** 2026-11-05
- **분류:** DB 스키마
- **상태:** 적용
- **바뀐 파일:**
  - `domains/accounts/models.py` (`CheckingAccount.__table_args__`)
  - `alembic/versions/b7d2f9a1c3e5_add_checking_limit_order_check.py` (새 마이그레이션)
  - `tests/test_constraints.py` (`per_over_daily` 케이스 추가)

#### 변경 전
`per_transfer_limit <= daily_transfer_limit`은 개설 입력 검증과 수정 시 검사(`INVALID_TRANSFER_LIMIT`)로만 지켜졌다.

#### 변경 후
`CHECK (per_transfer_limit <= daily_transfer_limit)` (`ck_checking_accounts_limit_order`).

#### 이유
- 서비스 코드에 버그가 생기거나 SQL로 직접 값을 넣어도 1회 한도가 1일 한도보다 커지지 않게 한다.

#### 영향 범위
- 정상 API 동작은 그대로다(기존 검사가 먼저 400으로 막는다). 운영 데이터가 없어 기존 행 정리는 필요 없었다.

#### 검증
- 새 테스트로 DB가 직접 거부하는 것을 확인했다. pytest 132개 통과.
- `alembic upgrade`·`downgrade -1`·`upgrade` 성공, `alembic check` 차이 없음. ERD v2 재생성(표 변화 없음).
- 돈이 움직이는 코드는 바꾸지 않아 PG 검증 스크립트는 다시 돌리지 않았다.

#### 팀 논의 포인트
- 없음.

---

### C-033. 만기일부터 예금·적금 입금 거절 (2-3)

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용
- **바뀐 파일:**
  - `domains/transfers/service.py` (`_pay`)
  - `tests/test_transfers.py` (`test_payment_rejected_from_maturity_day`), `docs/API_ENDPOINTS.md`

#### 변경 전
예금·적금은 만기가 지나도 입금(`POST /transfers/deposit`, `/savings`)이 됐다.

#### 변경 후
```python
target = await account_service.get_owned(db, to_kind, to_id, user)
if target.maturity_date <= today_kst():
    raise BadRequestException(code="ACCOUNT_MATURED", message="만기가 지난 계좌에는 입금할 수 없습니다.")
```
잠그기 전에 확인한다(만기일은 바뀌지 않는 정보). **만기일 당일부터** 거절한다. 개설 때도 만기일이 오늘이면 거절하므로(C-020) 같은 기준이다. 오늘은 KST 기준이다(C-009).

#### 이유
- 만기가 지난 계좌에 계속 돈을 넣을 수 있으면 "만기"가 의미가 없다.

#### 영향 범위
- 입금 API 400 응답에 새 코드 `ACCOUNT_MATURED`가 생겼다. DB 변경 없음.
- 만기 후 돈을 꺼내는 방법은 아직 없다(3-1에서 다룸). 이 변경으로 만기 계좌는 입금은 안 되고 출금도 안 되는 상태가 된다.

#### 검증
- 예금·적금 각각: 만기일이 오늘이면 400이고 입출금 잔액이 그대로, 내일이면 201.
- pytest 전체 통과, `pg_transfer_concurrency.py` 통과(잠금 구조는 그대로).

#### 팀 논의 포인트
- 만기일 당일에 입금을 허용할지(지금은 거절).

---

### C-034. 적금·예금 납입 규칙은 지금 방식 유지 (2-4)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** 코드 변경 없음 (`docs/NEXT_STEPS.md` 상태만 변경)

#### 변경 전·후
적금은 자유 금액으로 여러 번, 예금도 여러 번 입금할 수 있다. 이 방식을 그대로 확정했다.

#### 이유
- `monthly_payment`와 예금 1회 입금을 정확히 모델링하려면 해지·출금(3-1)과 함께 설계해야 한다. 지금 제한하면 3-1에서 다시 바꿔야 한다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음. `monthly_payment`는 안내용 값으로 남는다.

#### 검증
- 코드를 바꾸지 않아 테스트를 다시 돌리지 않았다.

#### 팀 논의 포인트
- 3-1을 설계할 때 납입 규칙을 다시 정한다.

---

### C-035. 신용카드 `outstanding_amount` 개명 + 입출금 거래내역 `counterpart_name` 추가 (2-5, 2-6)

- **날짜:** 2026-11-05
- **분류:** DB 스키마
- **상태:** 적용
- **바뀐 파일:**
  - `domains/cards/models.py`, `schemas.py`, `service.py`, `domains/accounts/models.py`, `schemas.py`
  - `alembic/versions/c3e8a2d4f6b1_rename_outstanding_and_add_counterpart_name.py` (새 마이그레이션 하나로 묶음)
  - `tests/test_cards.py`, `tests/test_constraints.py`, `scripts/pg_card_concurrency.py`, `pg_unique_violation_message.py`, `generate_erd_drawio.py`
  - `docs/ERD.md`, `docs/API_ENDPOINTS.md`

#### 변경 전
- `credit_cards.accumulated_amount`(미결제액)와 `debit_cards.accumulated_amount`(누적 사용액)가 같은 이름에 뜻이 달랐다.
- 체크카드 결제의 입출금 거래내역에는 가맹점명이 없었다(`counterpart_account`가 20자).

#### 변경 후
- **신용카드만** `outstanding_amount`로 개명(CHECK 이름도 `ck_credit_cards_outstanding_amount_within_limit`). 체크카드는 `accumulated_amount` 그대로.
- `checking_account_histories.counterpart_name VARCHAR(100) NULL` 추가. 체크카드 결제 때 `place_of_use`를 저장하고 거래내역 응답에 `counterpart_name`으로 내려준다(다른 거래는 null).
- 마이그레이션은 컬럼 개명(`ALTER ... RENAME COLUMN`이라 데이터 유지), 제약 이름 변경, 컬럼 추가를 한 번에 한다. downgrade도 되돌린다.
- **응답 모양:** `GET /cards/credit/{id}`는 `outstanding_amount`, `GET /cards/debit/{id}`는 `accumulated_amount`를 준다. 한 목록(`GET /cards`)과 결제 응답은 두 필드를 모두 선언하고 해당하지 않는 쪽이 `null`이다.
- 결제 서비스의 공통 코드(`card.accumulated_amount += ...`)는 신용·체크로 갈라서 각자의 컬럼을 바꾼다.

#### 이유
- 같은 이름이 카드 종류에 따라 뜻이 달라 `GET /cards`에서 헷갈렸다(C-012에서 뜻만 바꾸고 이름은 남겼던 것).
- 가맹점명이 없으면 체크카드 결제가 입출금 내역에서 "누가 어디에 썼는지" 보이지 않는다.

#### 영향 범위
- 신용카드 API 응답의 필드 이름이 바뀐 API 변경이다(`accumulated_amount` → `outstanding_amount`). 프론트가 신용카드의 `accumulated_amount`를 쓰고 있다면 고쳐야 한다.
- 거래내역 응답에 `counterpart_name` 필드가 추가됐다(추가만이라 기존 사용처는 영향 없음). 예금·적금 거래내역은 이 컬럼이 없어 항상 null이다.
- 기존 데이터는 유지된다.

#### 검증
- pytest 134개 통과(체크카드 결제 후 거래내역의 `counterpart_name == "편의점"`, 체크 응답의 `outstanding_amount is None` 검사 추가).
- `alembic upgrade`, `downgrade -1`, `upgrade` 성공, `alembic check` 차이 없음.
- PostgreSQL 검증 스크립트 `pg_card_concurrency`, `pg_unique_violation_message`, `pg_transfer_concurrency` 통과(결제·청구서 납부 코드를 건드렸기 때문).
- ERD v2 재생성: `outstanding_amount`와 `counterpart_name`을 노란 칸(변경)으로 표시.

#### 팀 논의 포인트
- 신용·체크 응답을 따로 두는 대신 목록·결제 응답에서 null 필드를 쓴 것이 괜찮은지.
- 예금·적금 거래내역에도 `counterpart_name`이 필요한지(지금은 필요 없음).

---

### C-036. 카드 사용내역 `used_amount` 이름 유지 (2-7)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** 코드 변경 없음 (`docs/NEXT_STEPS.md` 상태만 변경)

#### 변경 전·후
카드 사용내역·결제 요청의 `used_amount`를 계좌 거래내역처럼 `amount`로 통일하지 않고 그대로 확정했다.

#### 이유
- 이득이 작은데 고칠 곳(모델·스키마·요청·테스트·스크립트·문서)이 많다. 카드 쪽 이름은 "사용 금액"이라 뜻도 분명하다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음. 계좌 거래내역(`amount`)과 카드 사용내역(`used_amount`)의 이름이 다른 채로 남는다.

#### 검증
- 코드를 바꾸지 않아 테스트를 다시 돌리지 않았다.

#### 팀 논의 포인트
- 프론트가 두 이름을 모두 다뤄야 한다.

---

### C-037. 청구서 생성 시점·경로 이름 유지 (2-8)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** 코드 변경 없음 (`docs/NEXT_STEPS.md` 상태만 변경)

#### 변경 전·후
청구서는 이용 기간이 끝난 직후부터 만들 수 있고(결제일 이후로 제한하지 않음), 경로 이름은 `bills`로 둔다. 지금 방식을 확정했다.

#### 이유
- 본인이 직접 호출하는 방식(C-010)이라 지금 방식이 단순하고, 날짜 제한을 넣으면 테스트와 시연이 날짜에 묶인다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음.

#### 검증
- 코드를 바꾸지 않아 테스트를 다시 돌리지 않았다.

#### 팀 논의 포인트
- 자동 청구(3-3, 스케줄러)를 만들게 되면 다시 정한다.

---

### C-038. 받는 계좌번호 존재 확인 가능성은 감수 (2-9)

- **날짜:** 2026-11-05
- **분류:** 보안
- **상태:** 적용
- **바뀐 파일:** 코드 변경 없음 (`docs/NEXT_STEPS.md` 상태만 변경)

#### 변경 전·후
이체의 받는 계좌번호가 없으면 `404`, 있으면 진행되므로, 로그인한 사용자가 번호를 바꿔 보내 보면 존재하는 계좌번호를 알 수 있다. "받는 사람 이름 확인" 단계를 추가하지 않고 이 점을 알고 감수하기로 했다.

#### 이유
- 이체 API를 조회→실행 두 단계로 바꾸는 큰 변경이고, 학습·시연용이라 이득이 작다. 2-1(남의 ID 404 통일)으로 ID 탐색은 막았지만 계좌번호 탐색은 남는다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음.

#### 검증
- 코드를 바꾸지 않아 테스트를 다시 돌리지 않았다.

#### 팀 논의 포인트
- 서비스로 쓰게 되면 이름 확인 단계와 이체 시도 횟수 제한(2-11)을 같이 검토한다.

---

### C-039. 회원가입 중복 아이디 409 유지 (2-10)

- **날짜:** 2026-11-05
- **분류:** 보안
- **상태:** 적용
- **바뀐 파일:** 코드 변경 없음 (`docs/NEXT_STEPS.md` 상태만 변경)

#### 변경 전·후
회원가입은 중복 아이디를 `409`로 알려 준다(아이디 존재가 드러남). 그대로 확정했다.

#### 이유
- 가입 화면에서 "이미 있는 아이디"를 알려 줘야 해서 보통 감수한다. 숨기려면 이메일 인증 같은 가입 흐름 변경이 필요하다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음. 로그인 쪽은 이미 아이디 존재를 숨긴다(C-026).

#### 검증
- 코드를 바꾸지 않아 테스트를 다시 돌리지 않았다.

#### 팀 논의 포인트
- 서비스로 쓰게 되면 가입 시도 횟수 제한(2-11)과 같이 본다.

---

### C-040. 로그인 실패 횟수 제한 (2-11)

- **날짜:** 2026-11-05
- **분류:** 보안
- **상태:** 적용
- **바뀐 파일:**
  - `core/login_limiter.py` (새 파일), `domains/users/router.py` (`login`), `core/responses.py` (429 예시)
  - `tests/conftest.py` (테스트마다 초기화), `tests/test_users.py` (3개 추가), `docs/API_ENDPOINTS.md`

#### 변경 전
로그인 시도 횟수 제한이 없었다. 비밀번호 무차별 대입이 가능하고, 없는 아이디도 argon2 검증(약 75ms, C-026)을 하므로 요청이 몰리면 서버가 느려질 수 있었다.

#### 변경 후
- 로그인 라우터가 `login_limiter.check(login_id, ip)`로 먼저 확인하고, 한도를 넘었으면 **비밀번호 검증 전에** `429 TOO_MANY_LOGIN_ATTEMPTS`(+`Retry-After`)로 거절한다.
- 한도: **(아이디, IP)별 15분에 5번** 실패, **IP별 15분에 20번** 실패(아이디를 바꿔 가며 찔러 보는 경우).
- 로그인 실패(`UnauthorizedException`)마다 기록하고, 성공하면 그 (아이디, IP)의 실패 횟수를 지운다.
- 프로세스 메모리의 dict로 센다. 오래된 기록은 조회할 때 치운다.

#### 이유
- 아이디 하나만으로 잠그면 남이 내 아이디로 일부러 틀려서 나를 잠글 수 있어서, (아이디, IP) 조합으로 세고 IP 전체 한도를 따로 뒀다.

#### 영향 범위
- 로그인 API에 새 응답 `429`가 생겼다. DB·마이그레이션 변경 없음.
- **한계(코드에 `shortcut:` 주석):** 서버를 재시작하면 초기화되고, 서버가 여러 개면 각자 센다. IP는 `request.client.host`라 프록시 뒤에서는 프록시 주소로 보이므로, 배포할 때 프록시 설정(`--proxy-headers`)을 같이 봐야 한다.
- 분산된 여러 IP로 한 아이디를 찌르는 공격은 (아이디, IP) 한도로는 막지 못한다.

#### 검증
- 테스트 3개 추가: 5번 실패 뒤 429(맞는 비밀번호도 거절, 다른 아이디는 영향 없음), 성공하면 횟수 초기화, 아이디를 바꿔 20번 찌르면 IP 한도로 429. pytest 137개 통과.
- 확인하지 못한 것: 실제 서버에서 동시 요청으로 부딪히는 경우(단일 이벤트 루프 안의 dict라 경합은 없다고 보지만 측정하지 않았다).

#### 팀 논의 포인트
- 한도 값(5회/20회, 15분)이 적당한지, 서비스로 쓸 때 Redis 등으로 바꿀지.

---

### C-041. 이름·전화번호는 길이 검증만 유지 (2-12)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** 코드 변경 없음 (`docs/NEXT_STEPS.md` 상태만 변경)

#### 변경 전·후
이름·전화번호는 길이만 검사한다(전화번호 9~20자). 형식(숫자·하이픈) 검증은 넣지 않고 그대로 확정했다.

#### 이유
- 학습·시연용이라 충분하고, 형식을 제한하면 해외 번호나 입력 습관(공백, 괄호)을 막을 수 있다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음. `abc-defg-hijk` 같은 값도 전화번호로 저장될 수 있다.

#### 검증
- 코드를 바꾸지 않아 테스트를 다시 돌리지 않았다.

#### 팀 논의 포인트
- 서비스로 쓰게 되면 전화번호 형식 검증(또는 본인 인증)을 다시 정한다.

---

### C-042. API 시간은 UTC로 유지 (2-13)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** 코드 변경 없음 (`docs/NEXT_STEPS.md` 상태만 변경)

#### 변경 전·후
API는 시각을 UTC(`...Z`)로 내려 주고, KST 변환은 화면에서 한다. 그대로 확정했다. 서버 안의 "오늘" 기준(1일 한도, 청구서 이용 기간)만 KST다(C-009, C-010).

#### 이유
- 시간대 변환은 화면에서 하는 것이 일반적이고, 서버가 KST로 내려주면 표준 관례(ISO 8601 UTC)와 달라진다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음. 프론트가 `date`·`time`·`created_at` 등을 KST로 변환해서 보여 줘야 한다.

#### 검증
- 코드를 바꾸지 않아 테스트를 다시 돌리지 않았다.

#### 팀 논의 포인트
- 프론트가 변환을 맡는 것에 동의하는지.

---

### C-043. 예금·적금 해지 (3-1)

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용
- **바뀐 파일:**
  - `domains/accounts/interest.py` (새 파일, 이자 계산), `service.py` (`close_account`), `router.py`, `schemas.py`, `repository.py`, `kinds.py`, `models.py`
  - `domains/transfers/service.py` (`_pay`에 해지 계좌 거절)
  - `alembic/versions/d4f1b3c5e7a9_add_account_close.py` (새 마이그레이션)
  - `tests/test_close.py` (새 파일, 12개), `scripts/pg_close_concurrency.py` (새 파일), `scripts/README.md`, `generate_erd_drawio.py`
  - `docs/API_ENDPOINTS.md`, `docs/ERD.md`

#### 변경 전
예금·적금에는 넣을 수만 있고 꺼낼 수 없었다. 이자도, 계좌 상태도 없었다.

#### 변경 후
- **API:** `POST /accounts/{deposit|savings}/{id}/close`, 본문 `{ "to_checking_account_id": N }`(내 입출금 계좌). 응답은 `principal`, `interest`, `total_amount`, `early_close`, `closed_at`, 받은 계좌번호와 그 잔액.
- **상태:** 예금·적금에 `status`(`ACTIVE`/`CLOSED`)와 `closed_at` 추가. CHECK: `status IN (...)`, `(status='CLOSED') = (closed_at IS NOT NULL)`. 해지해도 계좌와 거래내역은 남는다. `GET /accounts` 목록에도 `status`가 나온다(입출금은 null).
- **이자(단리, 일할):** 입금(`TRANSFER_IN`) 내역 한 건마다 `금액 × 연금리 × 경과일 / 365`, 합산 후 원 미만 버림. 경과일은 입금일(KST)부터 `min(해지일, 만기일)`까지라 **만기 뒤에는 이자가 늘지 않는다.** **만기일 당일 이후 해지는 전체 금리, 만기 전은 금리의 50%**(`EARLY_CLOSE_RATE_FACTOR`). 입금 내역에서 바로 계산하므로 이자용 컬럼이 없고, 예금(여러 번 입금, C-034)과 적금이 같은 계산을 쓴다.
- **돈의 이동**(한 트랜잭션, 잠금 순서 입출금 → 예금·적금): 해지 계좌에 `INTEREST`(+이자) → `CLOSE_OUT`(−합계, 잔액 0), 입출금 계좌에 `CLOSE_IN`(+합계). 잔액이 0이면 내역 없이 해지만 한다. 이자는 은행이 만들어 주는 돈이라 출처 계좌가 없다.
- **해지 계좌 거절:** 이미 해지했으면 `400 ACCOUNT_CLOSED`, 해지된 계좌에 입금해도 `400 ACCOUNT_CLOSED`. 입출금 계좌 해지는 `400 CLOSE_NOT_SUPPORTED`.
- **type CHECK(C-030) 확장:** 입출금 거래내역에 `CLOSE_IN`, 예금·적금 거래내역은 `TRANSFER_IN`에 더해 `INTEREST`, `CLOSE_OUT`.

#### 이유
- 적금·예금이 넣을 수만 있어서 의미가 반쪽이었다(NEXT_STEPS 3-1).
- 해지 계좌를 지우지 않고 `status`로 남긴 것은 거래내역이 계좌를 외래키로 참조하고, 돈의 기록이 사라지면 안 되기 때문이다.
- **상태를 잠근 뒤에 확인한다:** 해지 두 번이 동시에 오거나, 해지와 입금이 동시에 오면 잠그기 전에 읽은 상태(ACTIVE)는 이미 낡았다. 해지된 뒤에 입금이 들어가면 돈이 닫힌 계좌에 갇힌다.

#### 영향 범위
- 새 API와 새 오류 코드(`ACCOUNT_CLOSED`, `CLOSE_NOT_SUPPORTED`). 예금·적금 응답에 `status`, `closed_at`이 추가됐다(추가만).
- 이 마이그레이션의 downgrade는 `CLOSE_IN`·`INTEREST`·`CLOSE_OUT` 행이 이미 있으면 옛 type 제약을 다시 만들 때 실패한다.
- 이자는 상품 `interest_rate`의 **해지 시점 값**으로 계산한다(상품 금리 변경 API가 없어 지금은 문제없음). 개설 당시 금리를 저장하지 않는다.
- 적금의 `monthly_payment`는 여전히 안내용이다(C-034). 몇 번 넣었는지·얼마를 넣었는지와 상관없이 입금한 만큼 이자가 붙는다.
- 만기가 지난 계좌의 출금 수단이 생겼다(C-033 이후의 "입금도 출금도 안 됨" 상태 해소).

#### 검증
- 새 테스트 12개: 이자 계산 단위 테스트 4개(만기 후 일수 상한, 중도 해지 절반 금리, 건별 일수·원 미만 버림, 이자 0), API 8개(당일 해지 원금만, 만기 후 전체 금리와 거래내역 3종 순서·잔액, 중도 해지 절반 금리, 재해지·해지 후 입금 거절, 오류 시 아무것도 안 바뀜, 빈 계좌, 목록 상태). pytest 149개 통과.
- `alembic upgrade`, `downgrade -1`, `upgrade` 성공, `alembic check` 차이 없음.
- PostgreSQL `pg_close_concurrency.py`: 같은 예금 20번 동시 해지 → 정확히 1번 성공·19번 `ACCOUNT_CLOSED`, 입출금 잔액이 한 번만 늘어남. 해지와 입금(20번)을 섞어서 동시에 → 해지 후 잔액 0, 돈의 합계 그대로, 데드락 없음. 잠금을 뺀 대조군에서는 15번 해지가 성공해 검증이 문제를 알아본다. `pg_transfer`·`pg_card`·`pg_charge`도 통과(`lock_account`·`_pay`를 건드렸기 때문).
- **확인하지 못한 것:** 해지 이자를 실제 날짜가 흐르는 환경에서 본 적은 없다(입금 시각을 DB에서 과거로 바꿔서 확인). 적금 해지는 동시성 스크립트에 넣지 않았다(`lock_account`를 같이 쓰는 같은 코드 경로).

#### 팀 논의 포인트
- 중도 해지 금리 50%, 만기 후 이자 없음, 이자를 입금별 일할로 계산하는 방식(적금의 월 납입 약속과 무관)이 팀이 원하는 규칙인지.
- 개설 당시 금리를 저장할지(상품 금리가 바뀌는 기능이 생기면 필요).
- 3-3(자동 납부)이 생기면 적금 납입 규칙을 다시 본다.

---

### C-044. 카드 정지·해지 (3-4 일부)

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용
- **바뀐 파일:**
  - `domains/cards/models.py`, `schemas.py`, `service.py` (`change_status`, `_require_active`), `router.py`
  - `alembic/versions/e5a2c4d6f8b0_add_card_status.py` (새 마이그레이션)
  - `tests/test_cards.py` (6개 추가), `scripts/pg_card_concurrency.py`, `pg_unique_violation_message.py`, `generate_erd_drawio.py`
  - `docs/API_ENDPOINTS.md`, `docs/ERD.md`

#### 변경 전
발급한 카드는 그대로 쓸 수밖에 없었다. 정지·해지가 없었다.

#### 변경 후
- 신용·체크카드에 `status`(`ACTIVE`/`SUSPENDED`/`CLOSED`) 컬럼과 CHECK 제약. 카드 응답과 `GET /cards` 목록에 `status`가 나온다.
- `POST /cards/{type}/{id}/suspend`(ACTIVE→SUSPENDED), `/resume`(SUSPENDED→ACTIVE), `/close`(ACTIVE·SUSPENDED→CLOSED, 되돌릴 수 없음). 맞지 않는 상태는 `400 INVALID_CARD_STATUS`.
- 결제는 `ACTIVE`일 때만(`400 CARD_NOT_ACTIVE`). **신용카드는 `outstanding_amount`가 0이어야 해지된다**(`400 CARD_HAS_OUTSTANDING`). 미결제액에 청구 전 사용액과 미납 청구서가 모두 들어 있어서 이 한 값으로 충분하다.
- 정지 중에도 청구서 조회·납부는 된다(갚을 돈은 갚아야 한다). 청구서 생성에는 상태 검사를 넣지 않았다.
- 상태는 `lock_card`로 카드를 잠근 **뒤에** 확인한다. 정지·해지와 결제가 동시에 와도 정지된 카드로 결제가 통과하지 않게 하기 위해서다(규칙 9, 잠금 순서 입출금 계좌 → 카드).

#### 이유
- 분실·도난 때 카드를 막고, 쓰지 않는 카드를 정리할 방법이 필요했다.
- 재발급과 신용 한도 변경은 하지 않기로 했다(범위 밖): 3-4에서 "정지·해지만"을 골랐다.

#### 영향 범위
- 새 엔드포인트 3개와 오류 코드 3개. 카드 응답에 `status`가 추가됐다(추가만). 기존 카드는 마이그레이션에서 `ACTIVE`가 된다.
- 해지된 카드의 사용내역·청구서는 계속 조회된다. 체크카드가 연결된 입출금 계좌를 없애는 기능은 여전히 없다.
- 직접 SQL로 카드를 넣는 스크립트는 `status`를 같이 넣어야 한다(DB 기본값이 없다). 검증 스크립트 두 개를 고쳤다.

#### 검증
- 새 테스트 6개(정지 중 결제 거절·해제 후 결제, 해지는 되돌릴 수 없음과 상태 전이 검사, 정지 후 해지·목록 상태, 미결제액이 있으면 해지 거절, 남의 카드·없는 카드 404). pytest 156개 통과.
- `alembic upgrade`·`downgrade -1`·`upgrade` 성공, `alembic check` 차이 없음. `pg_card_concurrency`, `pg_transfer_concurrency`, `pg_unique_violation_message` 통과.
- **확인하지 못한 것:** 정지·해지와 결제가 동시에 올 때의 순서는 PostgreSQL에서 따로 검증하지 않았다(이미 검증한 "잠근 뒤에 확인" 패턴을 그대로 썼다). 또 `pg_unique_violation_message.py`가 C-043 이후 예금·적금 `status`를 넣지 않아 실패하던 것을 이번에 같이 고쳤다. C-043 때 이 스크립트는 다시 돌리지 않았다.

#### 팀 논의 포인트
- 카드 재발급, 신용 한도 변경은 아직 없다. 해지된 카드의 번호를 다시 쓰지 않는다.

---

### C-045. 비밀번호 변경 (3-7 일부)

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용
- **바뀐 파일:**
  - `domains/users/schemas.py` (`PasswordChange`), `service.py` (`change_password`), `router.py`
  - `tests/test_users.py` (7개 추가), `docs/API_ENDPOINTS.md`

#### 변경 전
가입 후 비밀번호를 바꿀 방법이 없었다. `PATCH /users/me`는 `password` 필드를 422로 거절한다(C-024).

#### 변경 후
- `PATCH /users/me/password` `{ current_password, new_password }` → `200`(`data: null`). 새 비밀번호는 가입과 같은 8~128자.
- 현재 비밀번호가 틀리면 `400 INVALID_CURRENT_PASSWORD`, 새 비밀번호가 현재와 같으면 `400 SAME_PASSWORD`. 틀렸을 때 401을 쓰지 않는 것은 프론트가 401을 "로그아웃"으로 처리할 수 있어서다.
- **현재 비밀번호를 틀린 횟수를 로그인 실패 제한(C-040)과 같은 카운터로 센다**: 훔친 토큰으로 이 API를 반복 호출해 현재 비밀번호를 알아내는 길을 막는다. 5번 틀리면 `429`, 성공하면 초기화.
- 새 해시는 트랜잭션을 열기 전에 만든다(argon2가 느려서 DB 연결을 오래 잡지 않기 위해).

#### 영향 범위
- 새 엔드포인트, 새 오류 코드 2개. DB·마이그레이션 변경 없음.
- **기존 토큰은 그대로 유효하다.** 비밀번호를 바꿔도 이미 발급된 토큰(만료 30분)은 막지 못한다(토큰 폐기 기능 없음, 4-3). 비밀번호 변경의 가장 흔한 이유(계정 탈취 의심)에는 아직 불완전하다.
- 회원 탈퇴는 하지 않았다(계좌·카드 처리 규칙이 필요해서).

#### 검증
- 테스트 7개: 변경 후 새 비밀번호로만 로그인, 틀린 현재 비밀번호·같은 비밀번호·짧은 새 비밀번호 거절 시 아무것도 안 바뀜, 로그인 필요(401), 현재 비밀번호를 5번 틀리면 429. `tests/test_users.py` 61개 통과.

#### 팀 논의 포인트
- 비밀번호 변경 때 다른 기기의 토큰을 무효화할지(4-3과 함께 정한다).

---

### C-046. `/health` 추가 + 수수료·예약 이체는 하지 않기로 함 (4-1, 3-9)

- **날짜:** 2026-11-05
- **분류:** API
- **상태:** 적용
- **바뀐 파일:** `src/avengers_bank/main.py`, `core/responses.py`, `tests/test_users.py`, `docs/API_ENDPOINTS.md`, `docs/NEXT_STEPS.md`

#### 변경 전
`GET /`가 인사말만 돌려줘서 서버가 살아 있어도 DB가 죽었는지 알 수 없었다.

#### 변경 후
- `GET /health`: `SELECT 1`이 성공하면 `200 {"status": "ok"}`, 실패하면 `503 DB_UNAVAILABLE`. 실패 원인(호스트 주소 등)은 응답에 싣지 않고 `logger.exception`으로 로그에만 남긴다.
- `get_db`를 거치지 않고 엔진에 직접 연결한다(요청 세션·트랜잭션과 무관하게 연결만 확인).
- **3-9(수수료·예약 이체)는 범위 밖으로 확정(➖).** 스케줄러와 수수료 정책이 필요한 큰 작업이고 학습·시연용이라 이득이 작다.

#### 이유
- 로드밸런서·배포 도구가 "DB까지 되는지"를 한 번의 요청으로 볼 수 있어야 한다.

#### 영향 범위
- 새 엔드포인트 하나, DB·마이그레이션 변경 없음. 인증이 없으므로 응답에는 상태만 있고 내부 정보는 없다.
- 연결 수립이 오래 걸리면 `/health`도 오래 걸린다(별도 타임아웃을 두지 않았다).

#### 검증
- 테스트: 정상이면 200, 엔진을 실패하는 대역으로 바꾸면 503이고 응답에 내부 오류 문자열이 없다. pytest 163개 통과.

#### 팀 논의 포인트
- 배포 환경의 헬스체크 경로와 타임아웃은 배포할 때 정한다.

---

### C-047. CORS 허용 주소를 환경변수로 (4-4)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** `core/config.py` (`cors_origins`, `cors_origin_list`), `main.py`, `.env.example`, `tests/test_users.py`

#### 변경 전
```python
allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
```
프론트 주소가 바뀌면 코드를 고쳐야 했다.

#### 변경 후
`CORS_ORIGINS`(쉼표로 구분)를 `.env`에서 읽는다. 없으면 이전과 같은 두 주소가 기본값이다. 공백과 빈 항목은 무시한다. `.env.example`에 예시를 넣었다.

#### 이유
- 배포 환경마다 프론트 주소가 다르다. 코드 수정 없이 설정으로 바꿀 수 있어야 한다.

#### 영향 범위
- 기존 `.env`는 그대로 동작한다(기본값 유지). DB·API 변경 없음.
- 기본값 테스트(`Settings(...)`)는 실제 `.env`나 환경변수에 `CORS_ORIGINS`가 있으면 그 값을 읽어서 실패할 수 있다.

#### 검증
- 테스트 2개: 쉼표 목록 파싱(공백·빈 항목), 허용 주소만 `access-control-allow-origin`이 붙고 다른 주소는 붙지 않음. pytest 전체 통과.

#### 팀 논의 포인트
- 운영 주소는 배포할 때 정한다. 허용 메서드·헤더는 코드에 고정이다.

---

### C-048. compose: DB 비밀번호를 `.env`에서, 공식 `postgres:17-trixie` 이미지로 (4-6)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** `docker-compose.yml`, `.env.example`, `README.md`

#### 변경 전
```yaml
image: pgvector/pgvector:pg17-trixie
POSTGRES_PASSWORD: "1234"
```
비밀번호가 파일에 박혀 있었고, 쓰지 않는 pgvector 확장 이미지를 썼다.

#### 변경 후
```yaml
image: postgres:17-trixie
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?.env에 POSTGRES_PASSWORD를 넣어 주세요 (.env.example 참고)}
```
`.env.example`에 `POSTGRES_PASSWORD=1234`를 추가했다(`DATABASE_URL`의 비밀번호와 같아야 함). 값이 없으면 `docker compose`가 안내 메시지와 함께 멈춘다.

#### 이유
- 비밀번호를 파일이 아닌 `.env`(저장소 제외)에서 읽게 하고, 쓰지 않는 확장이 든 이미지를 공식 이미지로 바꾼다.
- **`postgres:17`이 아니라 `postgres:17-trixie`로 한 이유:** 기본 `postgres:17`은 다른 Debian 버전(bookworm) 기반이라 기존 볼륨에서 글리벅(glibc) 정렬 규칙이 달라져 텍스트 인덱스(계좌번호·아이디의 unique 인덱스)가 어긋날 수 있다. 이전 이미지와 같은 trixie로 맞췄다.

#### 영향 범위
- **`.env`에 `POSTGRES_PASSWORD`가 없으면 `docker compose up/down`이 오류를 낸다.** 기존 `.env`를 쓰는 사람은 한 줄을 추가해야 한다(`POSTGRES_PASSWORD=1234`). 실제 `.env`는 건드리지 않았다.
- 비밀번호는 **볼륨을 처음 만들 때만** 적용된다. 이미 만든 DB의 비밀번호는 바뀌지 않으니, 바꾸려면 `docker compose down -v`로 볼륨을 지우고 다시 만들어야 한다(데이터 삭제).
- 앱 코드·마이그레이션·테스트 변경 없음.

#### 검증
- `docker compose config`: 변수가 없으면 안내 메시지와 함께 오류, `POSTGRES_PASSWORD=x`를 주면 새 이미지 이름과 값이 반영됨.
- **확인하지 못한 것:** 새 이미지(`postgres:17-trixie`)로 실제 컨테이너를 띄워 보지 않았다(실행 중인 개발 DB를 건드리지 않으려고 `up`을 하지 않았고, 이미지를 받지도 않았다). 처음 `up` 할 때 이미지를 받는다.

#### 팀 논의 포인트
- API 서버를 compose에 넣을지(지금은 `uv run fastapi dev`로 따로 실행).

---

### C-049. 마이그레이션 파일 이름에 날짜·시각 추가 (4-7)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** `alembic.ini`(`file_template`), `alembic/versions/*.py` 6개(이름만 변경)

#### 변경 전
`<리비전ID>_<설명>.py`(예: `e5a2c4d6f8b0_add_card_status.py`): 파일 목록을 보고는 적용 순서를 알 수 없었다.

#### 변경 후
`<년>_<월>_<일>_<시분>-<리비전ID>_<설명>.py`(예: `2026_11_05_1900-e5a2c4d6f8b0_add_card_status.py`). `alembic.ini`의 `file_template`을 켰고, 기존 6개 파일도 파일 안의 `Create Date`로 이름을 바꿨다.

#### 이유
- 파일 이름 순서가 곧 적용 순서가 되어, 목록만 봐도 최신 마이그레이션을 알 수 있다.

#### 영향 범위
- **리비전 ID와 파일 내용은 그대로라서 동작은 같다**(`alembic history`·`current`·`check` 확인). 이미 DB에 적용된 상태에도 영향이 없다.
- 이 저장소를 이미 받은 팀원은 같은 파일이 다른 이름으로 보여 git에서 이름 변경으로 나타난다. 첫 커밋 이후 파일(C-030 이후 5개)은 아직 커밋 전이라 새 이름 그대로 올라간다.
- 첫 6개 파일의 `Create Date` 시각은 작업 중 임의로 적은 값이라 실제 생성 시각과 다를 수 있다(날짜순 정렬만 맞다).
- 컬럼 DB 기본값(`server_default`)은 SQL로 직접 넣을 일이 생길 때로 미뤘다(모델의 Python 기본값만 쓴다).

#### 검증
- 이름 변경 후 `alembic heads`·`history`·`current`·`check`가 이전과 같고, `alembic revision`으로 새 파일을 만들어 새 이름 형식을 확인한 뒤 지웠다.

#### 팀 논의 포인트
- 없음.

---

### C-050. 개발용 API가 켜져 있으면 시작 때 경고 로그 + Windows `fastapi run`은 안내만 (4-9, 4-8)

- **날짜:** 2026-11-05
- **분류:** 보안
- **상태:** 적용
- **바뀐 파일:** `src/avengers_bank/main.py`(`lifespan`), `tests/test_users.py`, `docs/NEXT_STEPS.md`

#### 변경 전
`ENABLE_DEV_ENDPOINTS=true`이면 `/dev/...` 충전 API가 열리는데, 운영에서 켜져 있는지 알 방법이 없었다.

#### 변경 후
서버가 시작할 때 이 설정이 켜져 있으면 `WARNING` 로그 한 줄("개발용 충전 API가 열려 있습니다. 운영 환경에서는 꺼야 합니다.")을 남긴다. 꺼져 있으면 아무것도 남기지 않는다. 설정 기본값은 여전히 꺼짐(`False`)이다.

- **4-8(Windows `fastapi run`)은 코드를 바꾸지 않고 README 안내로 충분하다고 확정(➖).** 배포는 보통 Linux이고 개발은 `fastapi dev`로 하면 된다(C-016).

#### 이유
- 개발용 충전 API가 운영에 열려 있으면 누구나 잔액을 채울 수 있어 치명적이다. 사람이 로그에서 한눈에 볼 수 있게 한다.

#### 영향 범위
- 앱 동작·DB·API 변경 없음. 로그가 한 줄 늘어난다(개발 중에는 항상 보인다).
- **막아 주지는 않는다.** 경고일 뿐이라 켜져 있어도 서버는 뜬다. 막으려면 운영 환경 변수(예: `ENV=production`)를 따로 두고 켜져 있으면 시작을 거부해야 하는데, 지금은 환경 구분이 없어 하지 않았다.

#### 검증
- 테스트: 켜져 있을 때 경고 로그가 남고, 꺼져 있을 때는 남지 않는다. pytest 전체 통과.

#### 팀 논의 포인트
- 서비스로 쓸 때 환경 구분(`ENV`)을 두고 운영에서 이 스위치를 켜면 시작을 거부할지.

---

### C-051. 동시성 검증 수동 유지, 원본 drawio 그대로 (4-10, 4-12)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** 코드 변경 없음 (`docs/NEXT_STEPS.md` 상태만 변경)

#### 변경 전·후
- **4-10:** PostgreSQL 동시성 검증(`scripts/pg_*.py`)은 사람이 직접 실행하는 지금 방식을 유지한다. 돈이 움직이는 코드를 고치면 `scripts/README.md`대로 다시 돌린다.
- **4-12:** 원본 `AvengersBankDiagram.drawio`(v1)와 `AvengersBankDiagram_v2.drawio`를 이름도 내용도 바꾸지 않고 그대로 둔다(C-027).
- **4-11(CI)은 "나중에"로 남겼다.** 원격 저장소(GitHub)에 올릴 때 pytest만 돌리는 `.github/workflows`를 추가한다.

#### 이유
- 4-10: 스크립트가 5개로 늘었지만(`pg_charge`·`transfer`·`card`·`close`·`unique_violation`) 수동 실행으로 충분했다. 자동화는 CI와 PostgreSQL 서비스를 같이 설계할 때 한다.
- 4-12: v1은 팀 최초 설계의 기록이라 건드리지 않는 것이 맞다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음. 수동 실행이라 코드를 바꾼 뒤 스크립트를 깜빡하면 잠금 회귀를 놓칠 수 있다.

#### 검증
- 코드를 바꾸지 않았다.

#### 팀 논의 포인트
- GitHub 저장소를 만들면 4-10·4-11을 같이 정한다.

---

### C-052. AWS 배포용 Dockerfile·Caddy·운영 compose 추가 (배포 준비)

- **날짜:** 2026-11-05
- **분류:** 구조
- **상태:** 적용 (AWS에는 아직 올리지 않음)
- **바뀐 파일:** `Dockerfile`, `.dockerignore`, `docker-compose.prod.yml`, `deploy/Caddyfile`, `.env.prod.example`, `.gitignore`, `docs/RETROSPECTIVE.md`(새 문서)

#### 변경 전
운영용 이미지·프록시 설정이 없었다. `docker-compose.yml`은 로컬 DB만 띄운다.

#### 변경 후
- **`Dockerfile`:** `python:3.13-slim` + `uv sync --frozen --no-dev`. 비루트 사용자(`app`)로 실행하고 `HEALTHCHECK`는 `GET /health`를 쓴다. `uvicorn ... --proxy-headers --forwarded-allow-ips '*'`, 워커 1개. 마이그레이션과 시드를 같은 이미지에서 `alembic upgrade head`, `python -m avengers_bank.seed`로 일회성 실행할 수 있게 `alembic`을 포함했다.
- **`docker-compose.prod.yml`:** `api`(포트를 공개하지 않음)와 `caddy`(80/443, 인증서는 볼륨에 보관). DB는 포함하지 않는다(RDS 등을 `DATABASE_URL`로 연결). `--env-file .env.prod`로 실행한다.
- **`deploy/Caddyfile`:** `{$DOMAIN}`에 대해 `reverse_proxy api:8000`. 도메인만 적으면 인증서가 자동 발급·갱신된다.
- **`.env.prod.example`:** 운영 환경변수 예시(`DOMAIN`, `DATABASE_URL`, `JWT_SECRET_KEY`, `ENABLE_DEV_ENDPOINTS=false`, `CORS_ORIGINS`). `.gitignore`가 `.env.*`를 막고 예시 파일만 허용한다.
- **회고록:** `docs/RETROSPECTIVE.md`를 새로 만들고 첫 항목으로 "nginx 대신 Caddy를 쓴 이유"를 적었다.

#### 이유
- AWS(EC2)에 Docker로 올리려면 이미지와 HTTPS 프록시가 필요했다. ALB 대신 Caddy를 쓰는 이유는 회고록에 정리했다.
- `--forwarded-allow-ips '*'`는 `api` 포트를 Caddy와 같은 내부 네트워크에만 두는 전제에서만 안전하다. 그래서 compose에서 `ports` 대신 `expose`만 썼다. 이 포트를 인터넷에 열면 누구나 `X-Forwarded-For`를 조작해 로그인 실패 제한을 우회할 수 있다.

#### 영향 범위
- 앱 코드·DB·테스트 변경 없음. 개발 환경(`docker-compose.yml`, `uv run fastapi dev`)은 그대로다.
- 이미지 크기는 약 664MB다(줄이는 작업은 하지 않았다).

#### 검증
- `docker build` 성공. 로컬 컨테이너를 로컬 개발 DB에 연결해 실행: `/health` 200, `/dev/...` 404(`ENABLE_DEV_ENDPOINTS=false`), `alembic current`가 최신(head), 컨테이너 상태 `healthy`, 실행 사용자는 `app`. `X-Forwarded-For: 203.0.113.9`를 보내면 로그에 그 IP가 찍혀 프록시 헤더가 적용됨을 확인했다.
- `caddy validate`로 Caddyfile이 유효함을 확인했고, `docker compose config`로 compose가 변수를 채워 렌더링되고 `DOMAIN`이 없으면 안내와 함께 멈추는 것을 확인했다.
- **확인하지 못한 것:** Caddy를 포함한 전체 스택(`up`)을 실제로 띄워 보지 않았고, 실제 도메인에서의 인증서 발급, ARM(Graviton) 인스턴스에서의 빌드, RDS 연결은 해 보지 못했다.

#### 팀 논의 포인트
- 도메인이 없으면 Let's Encrypt가 인증서를 주지 않는다. 도메인 마련 방법(구매 또는 CloudFront)을 정해야 한다.
- DB를 RDS로 할지, 같은 EC2의 컨테이너로 할지. → C-053에서 결정

---

### C-053. 첫 배포는 도메인 없이 HTTP(`DOMAIN=:80`), DB는 RDS PostgreSQL

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (설정 예시만 바뀜, AWS에는 아직 올리지 않음)
- **바뀐 파일:** `.env.prod.example`

#### 변경 전
C-052의 Caddy 설정은 도메인이 있다는 전제였고, DB 위치는 정하지 않았다.

#### 변경 후
- **HTTP만:** 도메인 없이 EC2 IP로 접속한다. `.env.prod`에 `DOMAIN=:80`을 넣으면 Caddy가 인증서 없이 80번 포트에서 HTTP로만 프록시한다. Caddyfile·compose는 그대로다.
- **DB:** RDS PostgreSQL(무료티어 인스턴스)을 쓰고, 퍼블릭 접근은 끄고 EC2에서만 접속한다.
- `.env.prod.example`에 `DOMAIN=:80` 사용법과 `DATABASE_URL` 비밀번호 URL 인코딩 주의를 주석으로 적었다.

#### 이유
- 도메인 마련보다 먼저 서버가 실제로 뜨는지 확인하는 게 목적이다. 도메인이 생기면 `DOMAIN`만 바꾸고 다시 띄우면 HTTPS로 바뀐다.
- RDS는 백업·관리가 자동이고, EC2가 망가져도 데이터가 남는다.

#### 영향 범위
- 코드 변경 없음.
- **HTTP라서 로그인 비밀번호와 JWT가 암호화되지 않고 오간다.** 시연·확인용으로만 쓰고 실제 비밀번호는 넣지 않는다. 보안 그룹에서 443은 열지 않아도 된다.

#### 검증
- `caddy adapt`에 `DOMAIN=:80`을 넣어 보니 `:80`만 listen하고 `api:8000`으로 프록시하는 설정이 만들어졌다(TLS 없음).
- **확인하지 못한 것:** 실제 EC2·RDS에서의 실행. → 실제 배포는 HTTP 대신 HTTPS(sslip.io)로 했다(C-054). `DOMAIN=:80`은 도메인이 없을 때 쓰는 방법으로 남겨 둔다.

---

### C-054. AWS 첫 배포 완료: EC2 + RDS, sslip.io로 도메인 없이 HTTPS

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (운영 중)
- **바뀐 파일:** 없음 (AWS 리소스와 서버의 `.env.prod`만 만들었다). 저장소를 GitHub 공개 저장소 `s100422/avengers-bank`에 올렸다.

#### 변경 전
배포 파일(C-052)은 있었지만 AWS에 올린 적이 없었다. C-053에서는 첫 배포를 HTTP로만 하기로 했다.

#### 변경 후
| 항목 | 구성 |
|---|---|
| 리전 | ap-southeast-2(시드니). 서울로 하려 했지만 콘솔 리전을 확인하지 않고 만들었다. EC2·RDS가 같은 리전이라 동작에는 문제없다 |
| EC2 | Ubuntu 24.04, t3.micro, gp3 20GiB, **크레딧 사양 표준**(무제한이면 추가 요금 가능), 탄력적 IP, 스왑 2GB(메모리 1GB로 빌드가 멈추는 것 방지) |
| 보안 그룹 | 22는 내 IP만, 80·443은 전체 |
| RDS | PostgreSQL **17**(로컬 개발 DB와 같은 버전), db.t4g.micro, 단일 AZ, 20GiB, 스토리지 자동 조정·확장 모니터링 끔, 퍼블릭 액세스 없음, "EC2 컴퓨팅 리소스에 연결"로 EC2에서만 5432 접근 |
| 코드 | EC2에서 `git clone https://github.com/s100422/avengers-bank.git` |
| 도메인·HTTPS | `DOMAIN=<IP의 점을 하이픈으로>.sslip.io`. Caddy가 Let's Encrypt 인증서를 받아 HTTPS로 서비스 |
| CORS | 프론트가 아직 없어서 `CORS_ORIGINS`를 비워 기본값(localhost:5173)을 쓴다. 프론트를 배포하면 그 주소를 넣는다 |

실행 순서: `up -d --build` → `run --rm api alembic upgrade head` → `run --rm api python -m avengers_bank.seed`.

#### 이유
- **HTTP 대신 sslip.io로 HTTPS:** 도메인을 사지 않아도 IP로 만든 이름에 정식 인증서를 받을 수 있다. 나중에 HTTPS 프론트(Vercel 등)가 이 API를 부르려면 API도 HTTPS여야 한다(혼합 콘텐츠 차단). 설정은 `DOMAIN` 한 줄이다.
- **공개 저장소:** 커밋된 비밀 값이 없음을 확인했다(`.env`·`.env.prod`는 무시, `.env.example`의 비밀번호는 로컬 개발 DB용). 은행 간 연동(중계 서버)은 실행 중인 API 주소로 하므로 저장소 공개 여부와 무관하다.

#### 영향 범위
- 앱 코드 변경 없음.
- **비용:** EC2·RDS·퍼블릭 IPv4·EBS가 크레딧에서 빠진다. 안 쓸 때는 EC2·RDS를 중지할 수 있다(RDS는 7일 뒤 자동으로 다시 켜짐).

#### 겪은 문제
- **RDS "빠른 구성으로 생성"은 Aurora PostgreSQL 서버리스로 고정이다.** 처음에 그걸로 만들어 Aurora가 생겼다. Aurora는 프리 티어가 아니어서 지우고 "전체 구성으로 생성 → PostgreSQL"로 다시 만들었다.
- **`docker compose -f docker-compose.prod.yml ps`만 치면 `DOMAIN is missing`으로 멈춘다.** Compose는 기본으로 `.env`만 읽으므로 모든 명령에 `--env-file .env.prod`가 필요하다. 서버에서 `ln -s .env.prod .env`와 `COMPOSE_FILE=docker-compose.prod.yml`을 설정하면 `docker compose ps`처럼 짧게 쓸 수 있다.

#### 검증
- 컨테이너 `api`(healthy)·`caddy` 모두 Up.
- 브라우저에서 HTTPS로 `/docs` 접속, `POST /users/signup` 201(RDS에 저장됨), `POST /users/login`으로 토큰 발급, `PATCH /users/me`로 정보 수정까지 확인했다.
- **확인하지 못한 것:** 계좌·카드·이체 API를 배포 환경에서 차례로 실행해 보지는 않았다. 서버 재부팅 후 자동 재시작(`restart: unless-stopped`)도 시험하지 않았다.

---

### C-055. 프론트엔드 추가: Next.js로 핵심 화면 5개 (`frontend/`)

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인, 아직 배포하지 않음)
- **바뀐 파일:** `frontend/`(새 폴더), `README.md`(프론트 실행 방법), `.claude/launch.json`(로컬 미리보기용)

#### 변경 전
프론트가 없어서 Swagger(`/docs`)로만 API를 써 볼 수 있었다.

#### 변경 후
- **스택:** Next.js 16(App Router) + React 19 + TypeScript + Tailwind CSS 4. `create-next-app`으로 만들었다.
- **화면:** 로그인(`/login`), 회원가입(`/signup`, 가입하면 바로 로그인), 내 계좌 목록과 전체 잔액(`/accounts`), 입출금 계좌 만들기(`/accounts/new`), 이체(`/transfer`).
- **API 호출:** `frontend/lib/api.ts` 하나로 모았다. 서버의 `{ data }`와 `{ error: { message, details } }` 모양을 풀어 화면에 서버 메시지를 그대로 보여 준다(예: "잔액이 부족합니다."). 401이면 토큰을 지운다.
- **토큰:** `localStorage`에 둔다. 로그인이 필요한 화면은 `Shell`이 토큰이 없으면 `/login`으로 보낸다.
- **API 주소:** `NEXT_PUBLIC_API_BASE_URL`, 기본값은 `http://localhost:8000`.
- **CORS:** 백엔드는 바꾸지 않았다. 개발 서버를 `next dev -p 5173`으로 띄워 API의 CORS 기본값(`localhost:5173`)에 맞췄다.
- **디자인:** 서체는 IBM Plex Sans KR 하나. 색은 남색 잉크와 도자기빛 회색 바탕에, 은행 도장(인감)을 떠올리는 빨간색은 도장 모양 하나에만 썼다. 브랜드 표시와 "개설", "완료" 확인 도장에 쓰고, 도장은 찍히는 동작이 한 번 나온다(동작 줄이기 설정이면 끔). 모바일 폭에 맞춘 한 줄 배치다.

#### 이유
- **Next.js:** 국내 채용 공고에서 자주 요구하는 기술을 배우려고 골랐다. 서버 기능(서버 렌더링, API 라우트)은 FastAPI가 이미 하므로 쓰지 않고, 모든 화면을 브라우저에서 API를 부르는 클라이언트 컴포넌트로 만들었다.
- **같은 저장소의 `frontend/`:** API와 함께 보고 고치기 쉽다. Vercel에서는 루트 폴더만 `frontend`로 지정하면 된다.
- **CORS를 코드 대신 포트로 맞춤:** 백엔드·테스트·배포 설정을 건드리지 않는 가장 작은 변경이다.

#### 영향 범위
- 백엔드 코드·DB·테스트 변경 없음.
- `localStorage` 토큰은 XSS에 약하다. 실서비스라면 httpOnly 쿠키로 바꿔야 한다(코드에 `shortcut:` 주석). → **C-096에서 해결**(갱신 토큰 쿠키, 액세스 토큰 메모리).
- 계좌 만들기는 입출금만 된다. 예금·적금, 카드, 거래 내역, 내 정보 수정 화면은 아직 없다.

#### 검증
- `npm run lint`, `tsc --noEmit`, `npm run build` 통과.
- 로컬 API와 프론트를 띄워 브라우저에서 확인했다: 회원가입 → 바로 로그인되어 `/accounts`로 이동 → 빈 목록 안내 → 입출금 계좌 개설("개설" 도장) → 개발용 충전 API로 10만 원 충전 → 다른 계좌로 25,000원 이체("완료" 도장, 남은 잔액 75,000원) → 90만 원 이체는 "잔액이 부족합니다." 표시 → 목록에서 두 계좌 75,000원·25,000원, 전체 100,000원.
- 브라우저 미리보기 창에서는 `127.0.0.1:8000`에 연결되지 않아 기본 API 주소를 `localhost:8000`으로 바꿨다(일반 브라우저에서는 둘 다 동작).
- **확인하지 못한 것:** Vercel 배포와, 배포된 API(sslip.io)에 붙였을 때의 동작(운영 서버 `CORS_ORIGINS`에 프론트 주소를 넣어야 한다). 데스크톱 폭과 다크 모드 화면은 자세히 보지 않았다.

---

### C-056. 배포 정리 문서 `docs/DEPLOY.md` 추가

- **날짜:** 2026-11-06
- **분류:** 문서
- **상태:** 적용
- **바뀐 파일:** `docs/DEPLOY.md`(새 문서), `README.md`(문서 목록에 링크)

#### 변경 전
README에는 로컬 개발 방법만 있었다. 배포 명령은 `docker-compose.prod.yml` 주석과 C-052~C-054에 흩어져 있어서, SSH가 끊긴 뒤 다시 시작할 때 README의 로컬 절차와 헷갈렸다.

#### 변경 후
`docs/DEPLOY.md` 한 곳에 배포 흐름을 짧게 모았다: 구성 그림(Mermaid), 처음 배포한 순서표(어디서·무엇을·왜), 다시 접속할 때, 코드를 고쳐 다시 올릴 때, 겪은 문제, 비용 정리 순서. README 문서 목록에서 링크한다.

#### 이유
- 결정의 이유는 회고록과 이 문서에 있지만, "다음에 따라 할 순서"는 따로 있어야 한다.
- 공개 저장소라 IP·키 경로·RDS 엔드포인트·비밀번호는 `<...>` 자리 표시로만 적었다.

#### 영향 범위
- 문서만 바뀜.

#### 검증
- 문서의 명령은 실제 배포 때 실행한 것과 같다. Mermaid 그림이 GitHub에서 그려지는지는 push 뒤에 확인해야 한다.

---

### C-057. 프론트에 하단 탭 메뉴, 계좌 상세·거래 내역, 상품, 내 정보 화면 추가

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인)
- **바뀐 파일:** `frontend/components/ui.tsx`, `frontend/lib/api.ts`, `frontend/app/accounts/page.tsx`, 새 화면 `frontend/app/accounts/[type]/[id]/page.tsx`, `frontend/app/products/page.tsx`, `frontend/app/me/page.tsx`

#### 변경 전
C-055는 화면 수만 줄인 게 아니라 화면 사이를 오가는 메뉴까지 빼서, 홈의 버튼 두 개 말고는 이동할 방법이 없었다. 계좌를 눌러도 반응이 없고 로그아웃 말고는 내 정보를 볼 곳이 없어 "너무 허접하다"는 피드백을 받았다.

#### 변경 후
- **하단 탭 메뉴(홈·이체·상품·내 정보):** 로그인이 필요한 모든 화면(`Shell`)에 고정한다. 현재 탭은 굵게 표시하고 `aria-current="page"`를 단다. 계좌 상세는 홈 탭, 계좌 만들기는 상품 탭으로 본다. 로그아웃은 헤더에서 내 정보로 옮겼다.
- **계좌 상세(`/accounts/{type}/{id}`):** 목록의 계좌를 누르면 열린다. 잔액과 거래 내역(`GET /accounts/{type}/{id}/histories`)을 보여 준다. 들어온 돈은 빨간 `+`, 나간 돈은 `-`, 그 아래에 거래 후 잔액을 둔다. 거래 종류 코드는 `HISTORY_TYPE`에서 화면 이름으로 바꾼다.
- **상품(`/products`):** 계좌 상품과 카드 상품 목록. 입출금만 "가입하기"로 개설 화면에 연결하고, 나머지는 "준비 중"으로 표시한다.
- **내 정보(`/me`):** 이름·닉네임·휴대폰 수정(`PATCH /users/me`), 비밀번호 변경(`PATCH /users/me/password`), 로그아웃.
- `api()`가 세 번째 인자로 `"PATCH"`를 받는다.

#### 이유
- 은행 앱은 하단 탭으로 주요 기능을 오가는 게 익숙한 모양이다. 화면이 적어도 길이 없으면 쓸 수 없다.
- 백엔드에 이미 있는 API(거래 내역, 내 정보 수정, 비밀번호 변경, 상품 목록)를 화면으로 꺼냈다. 새 API는 만들지 않았다.

#### 영향 범위
- 백엔드 변경 없음.
- 예금·적금 개설, 카드 발급·결제 화면은 여전히 없다("준비 중").
- 계좌 상세의 "이체하기"는 출금 계좌를 미리 골라 주지 않는다(이체 화면에서 첫 계좌가 선택됨).

#### 검증
- `npm run lint`, `tsc --noEmit` 통과.
- 브라우저에서 확인했다: 로그인 → 홈 하단에 탭 4개 → 계좌를 누르면 상세(잔액 75,000원, 거래 내역 "-25,000원 이체 보냄", "+100,000원 충전(개발용)") → 상품 탭에 계좌 3개·카드 3개 → 내 정보에서 닉네임 저장 후 "저장했습니다." 표시, API로 저장값 확인.
- 처음에는 저장 뒤 폼을 다시 만들도록(`key`) 해서 "저장했습니다." 메시지가 바로 사라졌다. 폼을 다시 만들지 않게 고쳤다.
- **확인하지 못한 것:** 비밀번호 변경은 화면에서 직접 실행해 보지 않았다(API는 C-045에서 검증됨). 데스크톱 폭에서 하단 탭이 어색할 수 있다. → C-058에서 PC는 왼쪽 메뉴로 바꿈.

---

### C-058. 프론트 디자인 개편: 피치·코랄 색, Pretendard 서체, 웹/앱 반응형 (시안 A)

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인)
- **바뀐 파일:** `frontend/app/globals.css`, `frontend/app/layout.tsx`, `frontend/components/ui.tsx`, `frontend/app/accounts/page.tsx`, 그 밖의 화면은 색·모서리 클래스만, `frontend/package.json`(`pretendard` 추가)

#### 변경 전
남색과 회색 바탕에 IBM Plex Sans KR 서체였다. "밤티 난다(촌스럽다)"는 피드백을 받았다. 휴대폰 폭 기준이라 PC에서는 가운데 좁은 기둥만 보였다.

#### 변경 후
- **방향:** 사용자가 고른 참고 이미지 두 장이 기준이다. 색감은 한 은행 예금 배너(코랄 레드, 피치 바탕), 화면 구성은 한 은행 앱 메인(흰 카드, 동그란 아이콘, 알약 버튼)을 따랐다. 홈 시안 세 가지(피치 카드형, 코랄 헤더형, 화이트 미니멀형)를 웹과 앱으로 보여 주고 **A. 피치 카드형**을 골랐다. 참고 이미지의 캐릭터와 로고는 쓰지 않았다.
- **서체:** Pretendard 가변 폰트(`pretendard` 패키지, `next/font/local`로 자체 제공). 자간을 살짝 좁혔다.
- **색 토큰:** 바탕 `#fff4ee`, 카드 흰색, 글자 `#1f1a17`, 보조 글자 `#7a6d66`, 테두리 `#f2ddd2`, 주색 코랄 `#dd3b24`, 연한 코랄 `#fde3d7`. 모든 주 버튼과 선택 표시를 코랄로 바꿨다. 모서리는 `rounded-xl`과 `2xl`로 더 둥글게 했다.
- **반응형:** 같은 메뉴 컴포넌트(`Nav`)가 폭에 따라 다르게 그려진다. 휴대폰은 하단 탭, PC(768px 이상)는 왼쪽 메뉴(브랜드 + 세로 메뉴, 선택된 항목은 연한 코랄 배경)다. 홈은 넓게(`Shell wide`), 입력 화면은 읽기 좋은 폭으로 둔다.
- **홈:** 인사 문구("○○님, 전체 잔액을 확인해보세요"), 계좌 수와 합계, 계좌 카드(종류 아이콘 원, 이름, 계좌번호, 잔액, `복사`·`이체` 알약 버튼). 카드는 휴대폰 1열, PC 2~3열이고, 마지막 칸은 점선 "계좌 만들기" 카드다.

#### 이유
- 사용자가 원하는 분위기를 말 대신 이미지로 받고, 시안을 고르게 해서 방향 차이를 줄였다.
- Pretendard는 국내 서비스에서 가장 흔히 쓰는 한글 UI 서체라 "앱다운" 인상을 준다. 시스템 서체와 달리 OS에 따라 모양이 바뀌지 않는다.
- 웹과 앱을 따로 만들지 않고 한 화면을 반응형으로 만들어 코드 하나로 두 모양을 낸다.

#### 영향 범위
- 백엔드 변경 없음. 기능 변경 없음(홈의 계좌번호 복사 버튼만 새로 생김).
- **다크 모드를 뺐다**(라이트만). 피치·코랄 팔레트의 어두운 버전을 따로 잡을 때 다시 넣는다(`globals.css`에 `shortcut:` 주석).
- 흰 글자를 올리는 코랄은 대비를 위해 참고 이미지보다 조금 진하게 잡았다.

#### 검증
- `npm run lint`, `tsc --noEmit` 통과.
- 브라우저에서 휴대폰 폭(375px)과 PC 폭(1280px)으로 확인했다. 375px에서 가로 넘침이 없고(`scrollWidth` 375), 하단 탭 4개가 화면 아래에 있다. 처음엔 "계좌번호 복사" 버튼이 길어 한 줄이 넘쳐서 "복사"로 줄이고 `aria-label`에 계좌번호를 넣었다. 1280px에서 왼쪽 메뉴와 계좌 카드 격자, 이체 화면, 계좌 상세가 새 스타일로 보이고, 본문 서체가 Pretendard로 적용된 것을 확인했다.
- **확인하지 못한 것:** 실제 휴대폰 기기, 태블릿 폭(768~1024px)의 세부 배치.

---

### C-059. 프론트 브랜드 이름을 "스파이디뱅킹", 도장 글자를 "SP"로

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:** `frontend/components/ui.tsx`(`Brand`), `frontend/app/layout.tsx`(브라우저 탭 제목)

#### 변경 전
화면 왼쪽 위 브랜드가 "어벤져스은행", 도장 안 글자가 "어"였다.

#### 변경 후
브랜드는 "스파이디뱅킹", 도장 글자는 "SP"(두 글자라 11px로 줄임), 브라우저 탭 제목도 "스파이디뱅킹"이다.

#### 영향 범위
- 화면에 보이는 이름만 바뀜. 저장소·패키지·API 이름(`avengers-bank`, `avengers_bank`)과 백엔드 상품 이름("어벤져스 입출금통장" 등)은 그대로다.

#### 검증
- 로그인 화면에서 브랜드 링크가 "스파이디뱅킹", 탭 제목이 "스파이디뱅킹"이고, 도장 상자(28px) 안에 "SP"(13px 폭)가 들어가는 것을 확인했다.

---

### C-060. 이체 화면: 받는 계좌번호 아래에 "내 계좌"와 "자주 보낸 계좌" 추천

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인)
- **바뀐 파일:** `frontend/app/transfer/page.tsx`

#### 변경 전
받는 계좌번호를 매번 직접 입력해야 했다.

#### 변경 후
- 받는 계좌번호 입력칸 아래에 **"자주 사용하는 계좌 ⌄" 접기 버튼** 하나만 둔다(처음엔 접힘). 펼치면 한 상자 안에 **"내 계좌"** 묶음, 그 아래 **"자주 사용하는 계좌"** 묶음이 차례로 나온다. 하나를 누르면 입력칸이 채워지고 상자가 접힌다. 버튼에 `aria-expanded`를 단다.
  - 처음엔 두 목록을 입력칸 아래에 그대로 펼쳐 두었는데, 목록이 입력칸처럼 보여 헷갈린다는 피드백으로 접는 방식으로 바꿨다.
  - **내 계좌:** 내 입출금 계좌 중 지금 출금 계좌로 고른 것을 뺀 나머지(별명, 계좌번호, 잔액).
  - **자주 사용하는 계좌:** 내 입출금 계좌들의 거래 내역에서 "이체 보냄"(`TRANSFER_OUT`)의 상대 계좌를 모아, 보낸 횟수가 많은 순(같으면 최근 순)으로 5개. 내 계좌로 보낸 건 "내 계좌"에 이미 있으니 뺀다.
- 출금 계좌와 받는 계좌번호 입력을 상태로 관리하게 바꿨다(출금 계좌를 바꾸면 "내 계좌" 목록이 바로 바뀐다).

#### 이유
- 백엔드를 바꾸지 않고 이미 있는 거래 내역 API(`GET /accounts/checking/{id}/histories`)로 만들 수 있다.

#### 영향 범위
- 백엔드 변경 없음.
- 계좌마다 최근 100건만 보고 센다(코드에 `shortcut:` 주석). 거래가 많아지면 서버에 "자주 보낸 계좌" API를 두는 편이 맞다.
- 상대 이름은 거래 내역에 `counterpart_name`이 있을 때만 보이고, 없으면 계좌번호만 보인다.
- 예금·적금은 이체가 아니라 납입 API로 넣으므로 "내 계좌"에 넣지 않았다.

#### 검증
- `npm run lint`, `tsc --noEmit` 통과.
- 브라우저에서 확인했다: 계좌 두 개인 사용자로 들어가면 "내 계좌"에 다른 계좌 하나가 보임 → 다른 사용자 계좌로 5,000원 이체 → 이체 화면을 다시 열면 처음엔 접기 버튼만 보임 → 펼치면 "내 계좌"(다른 내 계좌), 그 아래 "자주 사용하는 계좌"(그 계좌 "1회") → 누르면 입력칸이 채워지고 상자가 접힘(`aria-expanded="false"`) → 출금 계좌를 바꾸면 "내 계좌"가 반대 계좌로 바뀜.

---

### C-061. 샘플 상품 추가(예금·적금·신용·체크카드) + 상품 가입·카드 발급·예금 입금·적금 납입 화면

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인, 배포 서버에는 아직 없음)
- **바뀐 파일:** `src/avengers_bank/seed.py`, `frontend/app/open/[kind]/[[...product]]/page.tsx`(새 화면), `frontend/app/products/page.tsx`, `frontend/app/accounts/page.tsx`, `frontend/app/accounts/[type]/[id]/page.tsx`, `frontend/app/transfer/page.tsx`·`frontend/components/ui.tsx`(링크), `frontend/app/accounts/new/`(삭제)

#### 변경 전
상품이 종류별로 1~2개뿐이었고, 화면에서는 입출금 계좌만 만들 수 있었다(나머지는 "준비 중"). 시드는 상품이 하나라도 있으면 아무것도 넣지 않아서, 상품을 늘려도 기존 DB에 들어가지 않았다.

#### 변경 후
- **샘플 상품(시드):** 시중은행 상품 구성(월급통장, 정기·특판 예금, 자유·청년 적금, 쇼핑·트래블 신용카드, 생활 할인·트래블 체크카드)을 참고해 "어벤져스" 이름으로 만들었다. 입출금 2, 예금 3, 적금 3, 신용카드 4, 체크카드 3개(기존 6개 포함 15개). **실제 은행 상품 이름과 로고는 쓰지 않았고, 금리·한도·혜택은 예시 값이다**(실제 현재 금리 아님).
- **시드 방식 변경:** 이름이 같은 상품만 건너뛰고 새 상품은 넣는다. 기존 DB에 다시 실행해도 새 상품만 추가된다.
- **가입 화면 `/open/{종류}/{상품 id}`:** 입출금·예금·적금·신용카드·체크카드 다섯 종류를 한 화면이 처리한다. 상품 목록에서 누른 상품이 미리 골라져 있고(없는 id면 첫 상품), 종류별 입력만 다르다. 입출금은 별명, 예금은 만기일(기본 1년 뒤), 적금은 매월 납입액(기본 10만 원)·납입일(기본 25일)·만기일, 신용카드는 결제 계좌·결제일(기본 14일), 체크카드는 출금 계좌다. 완료하면 "개설/가입/발급" 도장과 계좌·카드 번호를 보여 준다. 카드는 입출금 계좌가 없으면 먼저 만들라고 안내한다. 기존 `/accounts/new`는 지우고 `/open/checking`으로 바꿨다.
- **상품 탭:** 입출금·예금·적금·신용카드·체크카드 묶음으로 나누고, 상품마다 만들기·가입하기·발급하기 버튼을 둔다.
- **예금 입금·적금 납입:** 예금·적금 계좌 상세에 내 입출금 계좌에서 돈을 넣는 칸을 붙였다(`POST /transfers/deposit`, `/transfers/savings`). 적금은 매월 납입액이 기본으로 채워진다. 넣은 뒤 잔액, 거래 내역, 출금 계좌 잔액을 다시 불러온다.
- **홈:** "내 카드 N장" 목록(신용카드는 결제 예정 금액, 체크카드는 누적 사용액, 카드번호 끝 4자리, 정지된 카드 표시)을 추가했다. 점선 카드는 계좌가 있으면 "예금·적금·카드 가입"으로 상품 탭에 연결한다.

#### 이유
- 백엔드에는 이미 예금·적금 개설, 카드 발급, 입금·납입 API가 있었는데 화면이 없어 확인할 수 없었다.
- 실제 은행 상품명·로고를 공개 저장소와 공개 서버의 "가입하기" 버튼에 쓰면 실제 상품으로 오해할 수 있어, 구성만 참고했다.

#### 영향 범위
- 백엔드는 시드 스크립트만 바뀌었다(API·DB 변경 없음).
- **배포 서버에는 새 상품이 없다.** 코드를 올린 뒤 서버에서 시드를 다시 실행해야 한다(`docker compose ... run --rm api python -m avengers_bank.seed`).
- 카드 결제·정지·해지, 청구서, 예금·적금 해지 화면은 아직 없다.
- 적금 거래 내역의 받은 돈은 "입금"으로 표시된다(백엔드 거래 종류가 `TRANSFER_IN` 하나라서).

#### 검증
- 시드를 로컬 DB에 두 번 실행: 첫 번째 "계좌 상품 5개, 카드 상품 4개"를 새로 넣고, 두 번째는 0개.
- `npm run lint`, `tsc --noEmit` 통과(지운 `/accounts/new`의 오래된 생성 타입은 `next typegen`으로 다시 만들었다).
- 브라우저에서 확인했다. 상품 탭에 15개가 다섯 묶음으로 보인다. 그다음 차례로 해 봤다.
  - 스타 정기예금, 내맘대로 적금, 쇼핑 신용카드, 노리 체크카드를 가입·발급했다. 각각 번호가 나왔고, 고른 상품이 미리 선택돼 있었다.
  - 홈에 예금·적금 계좌와 "내 카드 2장"이 보였다.
  - 예금에 30,000원 입금: 잔액과 거래 내역이 바뀌었다.
  - 적금에 10만 원 납입: 출금 계좌 잔액 4만 원이라 "잔액이 부족합니다." → 2만 원 납입은 성공하고, 출금 계좌 잔액 표시가 4만 → 2만으로 바뀌었다.
  - 없는 상품 id(`/open/credit/99`)는 첫 상품이 선택된다.
- 처음엔 상품 id가 주소와 안 맞으면 아무 상품도 선택되지 않아 제출이 안 됐다. 첫 상품으로 대신 고르고 라디오에 `required`를 달았다. 또 PC의 3열 카드에서 잔액·버튼 글자가 한 글자씩 줄바꿈되던 것을 `whitespace-nowrap`과 `flex-wrap`으로 고쳤다.

---

### C-062. 카드 상세(사용 내역) 화면 + 로컬 test 계정에 예시 거래 데이터

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인)
- **바뀐 파일:** `frontend/app/cards/[type]/[id]/page.tsx`(새 화면), `frontend/app/accounts/page.tsx`(카드 줄을 상세로 연결), `frontend/components/ui.tsx`(카드 상세는 홈 탭)

#### 변경 전
카드를 발급해도 사용처·사용 내역을 볼 화면이 없었다. 테스트 계정에는 입출금 계좌 몇 개뿐이라 화면을 제대로 확인하기 어려웠다.

#### 변경 후
- **카드 상세 `/cards/{credit|debit}/{id}`:** 홈의 "내 카드" 줄을 누르면 열린다. 상품 이름, 상태(사용 중·정지됨·해지됨), 카드번호, 신용카드는 결제 예정 금액·한도·남은 한도·결제일, 체크카드는 누적 사용액, 그 아래 사용 내역(사용처, 시각, 금액)을 보여 준다.
- **예시 데이터(로컬 DB의 `test` 계정, 코드 변경 아님):** 앱과 같은 API를 부르는 일회성 스크립트로 만들었다(저장소에는 넣지 않음).
  - 입출금: 생활비 100만 원 충전, 월급통장 개설 후 320만 원 충전(급여 대신)
  - 이체: 월급통장 → 생활비 80만 원, 생활비 → 다른 사용자 5만 원
  - 예금: 스타 정기예금 "비상금 예금" 가입, 100만 원 입금
  - 적금: 내맘대로 적금 "여행 적금" 가입(월 20만 원, 25일), 두 번 납입
  - 카드: 노리 체크카드(생활비), 트래블 체크카드(월급통장), 쇼핑 신용카드(결제 계좌 생활비, 14일)
  - 카드 사용: 노리 5건(스타벅스, GS25, 서울교통공사, 이디야커피, 올리브영), 트래블 2건(김밥천국, CGV), 쇼핑 신용 4건(쿠팡, 배달의민족, 무신사, 컬리)

#### 이유
- 백엔드에 카드 사용 내역 API(`GET /cards/{type}/{id}/histories`)가 이미 있었고, 화면만 없었다.
- 데이터를 DB에 직접 넣지 않고 API로 만들어서, 데이터를 만드는 과정 자체가 계좌 개설부터 이체, 입금·납입, 카드 발급·결제까지의 통합 확인이 되게 했다.

#### 영향 범위
- 백엔드 변경 없음.
- 카드 사용 시각은 결제 API를 부른 시각이라 예시 데이터의 시각이 모두 같다(과거 날짜로 넣는 API는 없다).
- 카드 결제·정지·해지·청구서 화면은 여전히 없다.

#### 검증
- 스크립트의 모든 API 호출이 성공했고, 최종 값이 계산과 맞았다: 월급통장 320만 − 80만 − 100만 − 2.4만 = 137.6만 원, 예금 100만 원, 적금 40만 원, 신용카드 미결제 215,200원(45,900 + 28,000 + 89,000 + 52,300), 노리 누적 39,000원, 트래블 누적 24,000원.
- 브라우저에서 확인했다.
  - 홈: 계좌 5개(합계 5,092,000원)와 카드 4장
  - 신용카드 상세: 상품 이름, 결제 예정 215,200원, 남은 한도 4,784,800원, 사용처 4건
  - 노리 체크카드 상세: 누적 39,000원, 사용처 5건
  - 생활비 거래 내역: "체크카드 결제"(사용처 이름), "적금 납입", "이체 보냄", "입금", "충전"이 순서대로 나오고, 거래 후 잔액이 한 줄씩 맞음
- `npm run lint`, `tsc --noEmit` 통과.

---

### C-063. 신용카드 결제 예정 금액(청구서) 표시와 납부 버튼 + 로컬 예시 청구서

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인)
- **바뀐 파일:** `frontend/app/cards/[type]/[id]/page.tsx`, `frontend/app/accounts/page.tsx`

#### 변경 전
신용카드의 "결제 예정 금액"에 미결제액 전체(이번 달 이용분까지)를 보여 줘서, 실제로 청구된 금액·결제일과 달랐다. 청구서를 볼 화면도 없었다.

#### 변경 후
- **신용카드 상세:**
  - 큰 숫자: **결제 예정 금액**. 아직 안 낸 청구서(`UNPAID`)의 합계이고, 제목에 가장 빠른 결제일을 붙인다(예: "11월 14일 결제 예정 금액").
  - 그 아래: **이번 달 이용 금액**(미결제액 − 결제 예정 금액, 아직 청구 전인 사용분), 남은 한도 / 전체 한도, 결제일.
  - **청구서 목록:** "10월 이용분, 11월 14일 결제 예정, 금액" 줄과 **지금 납부** 버튼(`POST /cards/credit/{id}/bills/{bill_id}/payments`). 납부한 청구서는 "납부 완료"로 표시하고, 납부하면 화면을 다시 불러온다.
- **홈 "내 카드":** 신용카드 줄에 청구서가 있으면 "11월 14일 결제 예정 178,000원", 없으면 "이번 달 이용 금액"을 보여 준다.
- **예시 데이터(로컬 `test` 계정의 쇼핑 신용카드, 코드 변경 아님):**
  - 10월 사용 6건(쿠팡, 스타벅스, SK에너지, 넷플릭스, 교보문고, 배달의민족, 합계 178,000원)을 DB에 직접 넣고 미결제액도 그만큼 올렸다. 과거 날짜로 결제하는 API가 없어서다.
  - 그 뒤 API로 2026-10 청구서를 만들었다. 결과: 178,000원, 결제일 2026-11-14, `UNPAID`.

#### 이유
- 백엔드 청구서 규칙(이용 기간이 끝난 달만 청구, 결제일은 다음 달 결제일)이 이미 있었는데, 화면은 미결제액만 보여 줘 은행 앱의 "결제 예정 금액"과 뜻이 달랐다.

#### 영향 범위
- 백엔드 변경 없음.
- 청구서를 만드는 버튼은 두지 않았다(실서비스에서는 월말에 자동으로 만든다). 지금은 API로만 만든다.
- 사용 내역에는 10월 사용분이 11월 사용분 아래에 함께 나온다(청구서별 묶음 보기는 없음).

#### 검증
- 청구서 API: 2026-10은 178,000원·11월 14일 결제로 생성, 2026-11은 "아직 이용 기간이 끝나지 않았습니다."로 거절.
- 브라우저: 홈 신용카드 줄 "11월 14일 결제 예정 178,000원". 카드 상세는 결제 예정 178,000원, 이번 달 이용 215,200원, 남은 한도 4,606,800원 / 5,000,000원, 청구서 "10월 이용분"에 "지금 납부" 버튼.
- `npm run lint`, `tsc --noEmit` 통과.
- **확인하지 못한 것:** "지금 납부" 버튼은 사용자가 직접 눌러 보도록 누르지 않았다(납부 API 자체는 기존 백엔드 테스트로 검증됨).

---

### C-064. 거래 내역 검색 조건(API·화면) + 카드대금 납부 내역에 카드 이름

- **날짜:** 2026-11-06
- **분류:** API
- **상태:** 적용
- **바뀐 파일:** `src/avengers_bank/domains/accounts/{schemas,repository,service,router}.py`, `src/avengers_bank/domains/cards/service.py`, `tests/test_accounts.py`, `tests/test_cards.py`, `docs/API_ENDPOINTS.md`, `frontend/components/history-filter.tsx`(새 파일), `frontend/app/accounts/[type]/[id]/page.tsx`

#### 변경 전
- 거래 내역은 최신순 `limit`·`offset`만 있어서 사용처·기간·금액으로 찾을 수 없었다.
- 카드대금 납부 내역에는 상대 칸에 카드번호(`4000-7122-...`)만 보였다.

#### 변경 후
- **API:** `GET /accounts/{type}/{id}/histories`에 검색 조건을 더했다. 모두 선택이고 함께 쓰면 AND다.
  - `date_from`, `date_to`: KST 날짜, 양끝 포함. 그날 00:00 KST부터 다음 날 00:00 KST 전까지로 바꿔 비교한다.
  - `types`: 거래 종류 코드, 여러 개면 OR.
  - `min_amount`, `max_amount`: 0 이상.
  - `q`: 상대 계좌번호와 상대 이름(사용처)의 일부를 대소문자 없이 찾는다. 최대 100자이고, `%`·`_`는 글자 그대로 찾는다(SQLAlchemy `icontains(autoescape=True)`). 예금·적금 내역에는 이름 칸이 없어서 계좌번호만 찾는다.
  - 조건은 `HistoryFilter` 스키마 하나로 묶어 서비스·저장소로 넘긴다.
- **카드대금 납부 내역:** `counterpart_name`에 카드 상품 이름("어벤져스 쇼핑 신용카드"), `counterpart_account`에는 그대로 카드번호를 남긴다. 화면은 이름을 먼저 보여 준다.
- **화면(계좌 상세):** 거래 내역 위에 검색칸(사용처·계좌번호, Enter로 검색, 지우면 바로 전체)과 "필터" 버튼, 현재 조건 요약("1개월, 카드, 5,000원 ~")을 둔다. 필터 패널은 다음과 같다.
  - 기간: 1개월·3개월·6개월·직접입력(시작일~종료일). 기본값은 1개월.
  - 거래 유형: 전체·입금·출금·이체·카드. 화면에서 거래 종류 코드 묶음으로 바꿔 보낸다.
  - 금액: 최소~최대.
  - 초기화·적용 버튼. 필터를 적용하면 최대 200건을 받는다.

#### 이유
- 브라우저에서 받아 온 목록을 거르면 앞의 200건 안에서만 찾게 된다. 서버에서 거르면 오래된 내역도 맞게 찾는다. 나중에 MCP로 에이전트에 열 때도 "지난달 스타벅스 결제" 같은 질문을 API 하나로 처리할 수 있다.
- 거래 내역에서 사람이 알아보는 건 카드번호가 아니라 카드 이름이다.

#### 영향 범위
- 기존 파라미터(`limit`, `offset`)와 응답 모양은 그대로다. 새 파라미터를 안 보내면 예전과 같다.
- DB 스키마 변경 없음. 이번 변경 전에 생긴 카드대금 납부 내역은 이름이 비어 있다. 로컬 DB의 한 건은 SQL로 채웠다(배포 DB에는 납부 내역이 없다).
- 카드 사용 내역(`/cards/.../histories`)에는 아직 검색 조건이 없다.
- 날짜 프리셋(1·3·6개월)은 브라우저의 오늘 날짜로 계산한다.

#### 검증
- 새 테스트 `test_histories_filters`: 날짜(양끝, 40일 전 행), 종류 여러 개, 금액 범위, 이름·계좌번호 검색, `%`·`_` 글자 그대로, 조합, 음수 금액 422. `test_pay_bill_withdraws_and_restores_limit`에 카드 이름 확인을 추가했다. 전체 167개 통과.
- 로컬 PostgreSQL에서 API로 확인했다: "올리브" 검색, 카드 종류 두 개, 10만 원 이상, 오늘 하루 5천 원 이하, `%` 검색(0건).
- 브라우저: 카드대금 납부 줄이 "어벤져스 쇼핑 신용카드 / 카드대금 납부"로 보임. "스타벅스" 검색이면 1건. 필터 "카드 + 5,000원 이상"이면 3건(4,800·1,500·3,200원 제외). 직접입력 10월 한 달이면 "조건에 맞는 거래가 없습니다.".
- 테스트하다 고친 것: 검색어를 지운 뒤 필터를 열면 옛 검색어가 되살아났다. 검색칸 글자를 유지하고, 칸을 비우면 바로 전체로 다시 불러오게 했다.

---

### C-065. 홈 화면을 모바일 뱅킹 앱 형태로 개편 + 이체 내역에 상대 실명 저장

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인)
- **바뀐 파일:**
  - 백엔드: `src/avengers_bank/domains/transfers/service.py`, `tests/test_transfers.py`
  - 프론트: `frontend/app/accounts/page.tsx`(홈), 새 파일 `frontend/lib/home-prefs.ts`, `frontend/components/home/`(`AssetSummaryCard`, `AllAccounts`, `AccountCarousel`, `AccountCard`, `AccountOrderSettings`, `ConfirmModal`, `bits`)

#### 변경 전
홈은 인사 문구, 계좌 카드 격자, 카드 목록이었다. 금액을 가리거나 대표 계좌를 정하는 기능이 없었다. 이체 내역에는 상대 계좌번호만 있어서 "누구에게 보냈는지"를 알 수 없었다.

#### 변경 후
**백엔드:** 입출금 → 입출금 이체 때 상대 실명을 `counterpart_name`에 남긴다. 보낸 쪽 내역에는 받는 분 이름, 받은 쪽 내역에는 보낸 분 이름이다(사용자 `name`). 예금·적금 납입은 내 계좌라 그대로다. 로컬 DB의 기존 이체 10건은 SQL로 이름을 채웠다.

**홈 배치 순서:**
1. **내 자산 현황(`AssetSummaryCard`):** 해지 안 된 계좌 잔액 합계를 큰 카드로 보여 준다. 오른쪽 위 `숨김`·`보기` 버튼(`aria-label`, `aria-pressed`)을 누르면 `••••••원`으로 가린다. 불러오는 동안은 스켈레톤을 보여 준다.
2. **내 전체 계좌 보기(`AllAccounts`):** 접힌 버튼과 화살표다. 펼치면 총 잔액, 그다음 입출금 → 적금 → 예금 묶음이 나오고, 묶음 안은 사용자 순서다. 빈 묶음은 숨긴다.
   - 각 줄: 이름, 종류, 계좌번호, 잔액, 대표 표시(채운 별 + "대표"), 상세로 가는 줄 전체 링크, 별도의 잔액 숨김 버튼.
   - 총 잔액은 내 자산 현황 숨김을, 계좌 잔액은 계좌별 숨김을 따른다.
   - 펼치기는 `grid-template-rows` 0fr↔1fr 전환이다. `motion-reduce`면 애니메이션 없이 바뀌고, 접힌 동안은 `inert`다.
3. **계좌 카드 슬라이더(`AccountCarousel`, `AccountCard`):** 대표 계좌가 맨 앞이고 나머지는 사용자 순서다. `overflow-x-auto`와 `snap-x snap-mandatory`를 쓰고, 휴대폰에서는 옆 카드가 살짝 보이고 PC에서는 2~3장이 보인다. 아래 점(44px 버튼)과 PC 전용 이전·다음 버튼이 있다.
   - 카드 내용 순서: 이름(상세 링크, 대표 배지) → 작은 계좌번호 + 복사(1.5초간 "복사됨", 클릭이 상세 이동으로 번지지 않음) → 큰 잔액 + 숨김·보기 → 최근 이체한 분 칩 → 입출금이면 `이체` 버튼.
   - 최근 이체한 분: 그 계좌의 `TRANSFER_OUT` 내역 50건에서 `counterpart_name`만 최신순으로 모으고 중복을 뺀다. C-064의 `types` 검색 조건을 쓴다.
     - 실명 없는 내역과 내 계좌로 보낸 내역은 뺀다.
     - 넘치면 줄바꿈하지 않고 가로로 민다.
     - 없으면 "최근 이체 내역 없음"이고, 그 계좌만 실패하면 "불러오지 못했어요"이며 카드는 그대로 보인다.
4. **대표 계좌 및 순서 설정(`AccountOrderSettings`):** 한 줄에 이름, 계좌번호, 별 버튼, 세 줄 손잡이가 있다.
   - 채운 별은 해지 확인("대표 계좌를 해지할까요?"), 빈 별은 설정 확인("대표 계좌로 설정할까요?")을 띄운다. 새로 정하면 기존 대표는 자동으로 해제된다.
   - 대표 계좌는 맨 위에 고정되고 손잡이 자리에 "고정"이 보인다.
   - 손잡이: Pointer Events와 `setPointerCapture`로 터치와 마우스를 모두 받는다(`touch-none`). 끄는 줄은 코랄 테두리·배경·그림자로 표시한다. 키보드는 손잡이에 포커스한 뒤 ↑↓로 옮기고, `aria-live`로 "○○, N번째로 이동"을 알리며, 옮긴 뒤에도 포커스를 유지한다.
5. **카드 목록:** 기존과 같다(청구서 결제 예정 표시 포함). 계좌와 따로 불러와서 실패해도 계좌 영역은 보인다.

**확인 모달(`ConfirmModal`):** 브라우저 기본 `<dialog>`의 `showModal()`을 쓴다. 포커스 가두기·Esc·배경 처리는 브라우저가 하고, 첫 포커스는 "아니요"다. 새 UI 라이브러리는 추가하지 않았다.

**설정 저장(`home-prefs.ts`):** 로그인 사용자별 `localStorage` 키(`avengers_bank_home:{user_id}`)에 대표 계좌, 순서, 총자산 숨김, 계좌별 숨김을 저장한다. 계좌는 `account_type-account_id` 키로 구분한다.
- 불러올 때 지금 계좌 목록으로 정리한다. 사라진 계좌의 대표·순서·숨김은 지우고, 새 계좌는 순서 끝에 붙인다.
- 저장소를 쓸 수 없거나 값이 깨졌으면 기본값을 쓴다(`try/catch`).
- 대표를 해지하면 그 계좌는 원래 순서 자리로 돌아간다.

#### 이유
- 은행 앱 홈에서 흔한 구성(총자산·숨김, 계좌 카드 넘기기, 대표 계좌)을 요청받았다.
- 대표 계좌와 순서는 서버에 저장할 필드·API가 없어 이번엔 브라우저에 둔다(`shortcut:` 주석). 다른 기기와는 공유되지 않는다.
- 최근 이체 상대를 이름으로 보이려면 서버가 이름을 남겨야 했다. 계좌번호만으로는 "누구"인지 알 수 없다.

#### 영향 범위
- 기존 API 응답 모양은 그대로다. 이체 내역의 `counterpart_name`이 채워지기 시작할 뿐이다. 거래 내역 화면에는 이체 줄에 계좌번호 대신 이름이 보인다.
- 계좌 상세, 이체, 카드 상세 링크는 그대로다.
- 받는 쪽 내역에도 보낸 분 실명이 남는다(실제 은행과 같은 동작).

#### 검증
- 백엔드: `test_transfer_moves_money_and_records_both_sides`에 양쪽 실명 확인을 추가했다. 이체·카드 테스트 37개 통과.
- 프론트: `npm run lint`, `tsc --noEmit`, `npm run build`(프로덕션 빌드) 통과.
- 브라우저, 휴대폰 폭 375px(로컬 `test` 계정, 받는 사람 3명을 새로 만들어 이체):
  - 가로 넘침 없음(`scrollWidth` 375).
  - 최근 이체한 분 칩이 "김민준, 박지호, 이서연, 테스트"(최신순, 중복·내 계좌 제외).
  - 총자산 숨김: 총액과 펼친 목록 총 잔액이 함께 `••••••원`, 계좌 카드는 그대로.
  - 카드에서 생활비 숨김 → 목록에서도 가려짐 → 목록에서 보기 → 카드에도 보임.
  - 펼친 목록의 계좌번호가 처음엔 중간에서 줄바꿈돼, 종류를 이름 옆으로 옮기고 번호를 한 줄로 고쳤다.
  - 대표 계좌: 아니요는 변경 없음, 예는 슬라이더 첫 장. 다른 계좌를 대표로 하면 기존 대표 해제. 해지하면 원래 순서로 돌아감.
  - 순서: 키보드 ↑ 두 번(포커스 유지, 알림 문구), 실제 포인터 드래그(대표 위로는 못 감). 슬라이더에 바로 반영되고 새로고침 후에도 유지.
  - 저장소에 없는 계좌 키를 일부러 넣고 새로고침하면 지워짐.
- PC 폭 1280px: 왼쪽 메뉴와 카드 3장, 이전·다음 버튼이 보이고 가로 넘침 없음. 복사 버튼을 눌러도 상세로 이동하지 않음.
- **확인하지 못한 것:**
  - 손가락으로 밀 때 아래 점이 따라 바뀌는지. 미리보기 창이 숨겨진 상태라 브라우저가 스크롤 이벤트를 보내지 않았다. 스크롤과 스냅 자체는 동작했고, 점을 누르면 바로 바뀌게 했다.
  - "복사됨" 표시. 숨겨진 창에서는 클립보드 쓰기가 거부됐다.
  - 실제 휴대폰 기기의 터치.

---

### C-066. 홈: 순서 설정은 별도 화면, 대표 계좌는 여러 개, 슬라이더에는 대표 계좌만

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인)
- **바뀐 파일:** `frontend/app/accounts/page.tsx`, 새 화면 `frontend/app/accounts/settings/page.tsx`, 새 파일 `frontend/components/home/useHomeData.ts`, `frontend/lib/home-prefs.ts`, `frontend/components/home/{AccountOrderSettings,AccountCarousel,AccountCard,AllAccounts}.tsx`

#### 변경 전 (C-065)
- 홈에 "대표 계좌 및 순서 설정" 목록이 처음부터 펼쳐져 있어 복잡했다.
- 대표 계좌는 한 개만 정할 수 있었고, 대표 계좌는 맨 위에 고정됐다.
- 슬라이더에는 모든 계좌가 나왔다.

#### 변경 후
- **홈:** 설정 목록 대신 "대표 계좌 및 순서 설정" 한 줄과 톱니바퀴 아이콘만 둔다. 누르면 `/accounts/settings`로 간다.
- **설정 화면 `/accounts/settings`:** C-065의 별 버튼, 확인 모달, 손잡이 끌기, ↑↓ 키 순서 변경을 그대로 옮겼다. 하단 탭은 "홈"이 선택된 상태다.
- **대표 계좌 여러 개:** 별을 누를 때마다 확인 모달("대표 계좌로 설정할까요?"·"대표 계좌를 해지할까요?")을 띄운 뒤 그 계좌만 넣거나 뺀다. 다른 대표 계좌는 그대로다. 대표 계좌라고 맨 위에 고정하지 않고, 모든 계좌를 자유롭게 옮긴다.
- **슬라이더:** 대표 계좌들만, 사용자 순서대로 보여 준다. 슬라이더에 대표만 나오므로 카드의 "대표" 배지는 뺐다. 대표가 하나도 없으면 "대표 계좌를 설정하면 여기에 카드로 보여요" 안내 카드와 "대표 계좌 설정하기" 버튼(설정 화면 이동)을 보여 준다. 카드가 한 장이면 휴대폰에서 가득 차게 했다.
- **내 전체 계좌 보기:** 대표 계좌마다 별과 "대표"를 표시한다(여러 개 가능).
- **저장값:** `rep`(한 개)를 `reps`(배열)로 바꿨다. 예전 저장값의 `rep`는 읽을 때 `reps: [rep]`로 바꾼다. 홈과 설정 화면은 `useHomeData` 훅 하나로 사용자, 활성 계좌, 설정을 불러와 정리·저장한다.

#### 이유
- 순서 설정은 자주 하는 일이 아니라서 홈에서 빼 단순하게 했다(사용자 요청).
- "대표 계좌로 설정된 계좌들만 슬라이드로" 보이려면 대표가 여러 개여야 한다(사용자 확인).

#### 영향 범위
- 백엔드 변경 없음. C-065의 홈 배치 순서 중 4번(설정 목록)이 한 줄 링크로 바뀌었다.

#### 검증
- `npm run lint`, `tsc --noEmit`, `npm run build` 통과(`/accounts/settings` 정적 페이지 생성).
- 브라우저, 휴대폰 폭 375px(로컬 `test` 계정):
  - 예전 형식 저장값(`rep: 생활비`)이 `reps: [생활비]`로 바뀌고, 슬라이더에 생활비 한 장만 나옴. 홈에 설정 목록 없이 톱니바퀴 줄만 있음.
  - 톱니바퀴 → 설정 화면에서 월급통장·여행 적금을 대표로 추가(모달 "예"), 여행 적금을 ↑ 키로 맨 위로 옮김.
  - 홈으로 돌아가면 슬라이더가 "여행 적금, 생활비, 월급통장" 3장. 전체 계좌 목록에 대표 표시 3개. 가로 넘침 없음.
  - 대표를 모두 비우면 안내 카드와 "대표 계좌 설정하기" 버튼.

---

### C-067. 계좌 카드 슬라이더: 넓은 화면에서도 한 장씩

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인)
- **바뀐 파일:** `frontend/components/home/AccountCarousel.tsx`

#### 변경 전
PC 폭(768px 이상)에서는 카드가 2~3장씩 함께 보였다. 카드가 좁아 계좌번호가 "110-095-8299…"처럼 잘렸고, 아래에 가로 스크롤 막대가 보였다.

#### 변경 후
- 768px 이상에서는 카드 한 장이 슬라이더 폭을 다 쓴다(`md:w-full`). 휴대폰은 그대로 옆 카드가 살짝 보이는 86% 폭이고, 한 장뿐이면 꽉 찬다.
- 가로 스크롤 막대는 숨겼다(`scrollbar-width: none`, WebKit 스크롤바 숨김). 넘기기는 터치·트랙패드 스크롤과 아래 점, PC의 이전·다음 버튼으로 한다.

#### 이유
- 사용자 요청: 카드가 한 장씩 보이게.

#### 검증
- `npm run lint`, `tsc --noEmit` 통과.
- 브라우저 1230px: 슬라이더 폭 895px에 카드 세 장 모두 895px. 계좌번호가 잘리지 않음. "다음 계좌"를 누르면 907px(카드 + 간격) 이동하고 두 번째 점이 켜짐. 가로 넘침 없음.

---

### C-068. "최근 이체한 분" 이름을 누르면 계좌번호가 채워진 이체 화면으로

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인)
- **바뀐 파일:** `frontend/components/home/AccountCard.tsx`, `frontend/app/accounts/page.tsx`, `frontend/app/transfer/page.tsx`

#### 변경 전
홈 계좌 카드의 "최근 이체한 분" 이름은 글자뿐이라 누를 수 없었다.

#### 변경 후
- 이름 칩이 링크다: `/transfer?from={그 카드의 계좌 id}&to={그 사람에게 가장 최근에 보낸 계좌번호}`. 화면 읽기용 이름은 "○○님께 이체"이고, 누르는 영역은 44px이다.
- 최근 이체 상대 데이터가 이름만이 아니라 `{ name, account }`다. 같은 이름이 여러 번이면 가장 최근 계좌번호 하나만 쓴다.
- 이체 화면은 주소의 `from`이 내 입출금 계좌면 출금 계좌로 고르고(아니면 첫 계좌), `to`를 받는 계좌번호 칸에 채운다(최대 20자). 금액은 비워 둔다. `useSearchParams` 대신 마운트 때 `window.location.search`를 읽는다(정적 페이지라 Suspense 경계가 필요 없게).

#### 이유
- 사용자 요청: 자주 보내는 사람에게 바로 이체.

#### 영향 범위
- 백엔드 변경 없음. 주소 값은 입력칸을 채울 뿐이고, 실제 이체는 기존처럼 서버가 소유자·잔액·한도를 검사한다.
- 파라미터 없이 `/transfer`에 들어가면 예전과 같다.

#### 검증
- `npm run lint`, `tsc --noEmit` 통과.
- 브라우저: 생활비 카드의 칩 4개가 각 사람의 계좌번호로 링크됨(김민준 110-168-673711 등). "박지호"를 누르면 `/transfer?from=87&to=110-125-035683`로 가고, 받는 계좌번호 칸에 110-125-035683, 출금 계좌는 생활비. 파라미터 없이 들어가면 받는 칸이 비어 있고 출금 계좌는 첫 계좌.

---

### C-069. 상품 화면을 은행 앱 "금융상품" 형태로 (탭, 추천, 배너, 칩, 상품 카드, 찜)

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (로컬에서 확인)
- **바뀐 파일:** `frontend/app/products/page.tsx`

#### 변경 전
상품 종류별 묶음 목록에 만들기·가입하기·발급하기 버튼만 있었다.

#### 변경 후
사용자가 보낸 시중은행 앱 화면의 구성을 따랐다. 그 은행의 이름·로고·캐릭터·배너 문구는 쓰지 않았다.
- **탭(추천 / 예적금 / 입출금 / 카드):** 밑줄 표시 탭이다. WAI-ARIA 탭 패턴(`role="tablist"`·`tab`·`tabpanel`, ←→ 키)을 따른다. 고른 탭은 주소 `?tab=`에 남아, 새로고침하거나 링크로 들어와도 그 탭이 열린다.
- **추천 탭:**
  - "지금 눈여겨볼 상품": 아이콘 타일, 이름, 금리 또는 설명. 판매 데이터가 없어 "인기" 대신 월급통장과 금리가 가장 높은 적금·예금을 하나씩 고른다.
  - "추천상품" 테마 카드 4개: 연한 색 바탕, 제목, 설명, 아이콘. 누르면 해당 탭과 칩으로 간다(예: 적금 테마 → 예적금 탭 + 적금 칩).
- **예적금·입출금·카드 탭:**
  - 맨 위 배너(그 탭의 대표 상품으로 링크).
  - 종류 칩: 예적금은 전체·적금·정기예금, 카드는 전체·신용카드·체크카드.
  - "적금 3"처럼 개수.
  - 상품 카드: 이름, 설명, "적금, 연 3.8%" 또는 "신용카드, 한도 …"이고, 카드 전체가 가입 화면(`/open/...`) 링크다.
- **찜(하트):** 카드 오른쪽 위 버튼이다. 링크 밖에 두어 눌러도 가입 화면으로 넘어가지 않는다. 사용자별 `localStorage`(`avengers_bank_fav_products:{user_id}`)에 저장한다(`shortcut:` 주석).
- 아이콘은 상품 종류별 색 타일에 단순한 선 그림(통장, 막대, 자물쇠, 카드)이다.

#### 이유
- 사용자 요청: 보낸 은행 앱 화면처럼.

#### 영향 범위
- 백엔드 변경 없음. 가입 화면 링크(`/open/{kind}/{id}`)는 그대로다.
- 참고 화면의 "가입/관리" 탭, 개인/사업자 구분, 대출·퇴직연금·펀드는 기능이 없어 넣지 않았다.
- 찜은 아직 목록 거르기("찜한 상품")에 쓰이지 않는다.

#### 검증
- `npm run lint`, `tsc --noEmit`, `npm run build` 통과.
- 브라우저, 휴대폰 폭 375px(가로 넘침 없음):
  - 추천 탭: 월급통장, 청년 도약 적금 4.5%, 모바일 특판예금 3.1%가 나온다.
  - 적금 테마 카드를 누르면 `?tab=savings`로 바뀌고 적금 칩이 선택되며 "적금 3"이 된다.
  - 하트를 누르면 `aria-pressed=true`가 되고 저장되며, 화면은 이동하지 않는다.
  - 카드 탭: 배너, 칩 3개, "카드 7".
  - `?tab=savings`로 들어오면 예적금 탭이 열린다.

### C-070. AI 금융 비서 (Tool Calling, 이체는 초안 → 화면 확인)

- **날짜:** 2026-11-06
- **분류:** API · DB 스키마 · 구조
- **상태:** 적용 (실제 모델 API로는 미확인)
- **바뀐 파일:**
  - `src/avengers_bank/domains/agent/` (새 도메인: router, service, repository, schemas, models, prompts, model_client, tools/)
  - `src/avengers_bank/domains/transfers/service.py`: `transfer`를 `transfer_in_tx`(호출자 트랜잭션) + `preview`(검사만) + `_parties` + `_check_limits`로 나눔
  - `src/avengers_bank/core/config.py`: `ANTHROPIC_API_KEY`, `AGENT_MODEL`, `AGENT_EFFORT`, `AGENT_TIMEOUT_SECONDS`
  - `src/avengers_bank/main.py`, `alembic/env.py`, `tests/conftest.py`: agent 라우터·모델 등록
  - `alembic/versions/2026_11_06_1200-f6b3d5e7a9c1_add_agent_tables.py`: `agent_conversations`, `agent_messages`, `agent_transfer_drafts`
  - `pyproject.toml`, `uv.lock`: `anthropic>=1,<2`
  - `frontend/components/assistant/{Assistant,TransferCard}.tsx`, `frontend/lib/api.ts`, `frontend/app/layout.tsx`, `frontend/components/home/useHomeData.ts`
  - `tests/test_agent.py`, `scripts/pg_agent_confirm_concurrency.py`, `scripts/_common.py`(정리 순서에 agent 테이블)
  - 문서: `docs/AGENT.md`(새), `README.md`, `docs/API_ENDPOINTS.md`, `scripts/README.md`, `.env.example`, `docs/RETROSPECTIVE.md`

#### 변경 전
AI 기능 없음. 이체 검사는 `transfer()` 안에만 있어서 "검사만" 하거나 다른 트랜잭션 안에서 이체할 수 없었다.

#### 변경 후
- `POST /agent/chat`: 모델이 Tool(`get_my_accounts`, `get_financial_summary`, `get_transaction_history`, `get_card_payment_status`, `prepare_transfer`)을 골라 부르고 답한다. 모델 호출 최대 6번, Tool 최대 8개. 지난 대화는 최근 10개 메시지만 넘긴다.
- `prepare_transfer`는 기존 이체 검사(`preview`)를 통과하면 5분짜리 `PENDING` 초안만 만든다. 잔액은 바뀌지 않는다.
- `POST /agent/transfers/{id}/confirm`: 한 트랜잭션에서 초안을 조건부 UPDATE(PENDING·만료 전 → EXECUTED)로 차지하고 `transfer_in_tx`로 이체한다(잠근 뒤 잔액·한도 재검사). 실패하면 초안도 PENDING으로 되돌아간다. `/cancel`은 CANCELLED.
- 공급자 코드는 `model_client.py`에만 있다(Anthropic Claude, 기본 `claude-opus-5-5`). Tool은 공급자를 모르는 함수라 MCP에서 재사용할 수 있다.
- 메시지에는 답변, Tool 이름·성공 여부, 마스킹된 action만 저장하고 Tool 원본 결과는 저장하지 않는다.
- 프론트: 로그인 화면 어디서나 오른쪽 아래 버튼 → 패널(모바일 전체 화면, 데스크톱 오른쪽), 추천 질문, 오류·재시도, 새 대화, 이체 확인 카드(이체하기·취소). 이체 후 `accounts:changed` 이벤트로 홈 데이터를 다시 불러온다.

#### 이유
- 프로젝트 목표(은행 기능을 Agent에 공개)의 첫 단계. MCP 전에 일반 Tool Calling으로 Tool 경계와 안전장치를 정했다.
- 재현 시나리오(이중 이체): 사용자가 `이체하기`를 두 번 빠르게 누르거나 네트워크 재시도가 겹치면, 상태를 읽고 나서 바꾸는 방식은 두 요청 모두 PENDING을 보고 두 번 이체한다. 조건부 UPDATE는 하나만 성공한다.

#### 영향 범위
- `transfer()`의 동작·응답은 그대로(내부만 나눔). 기존 테스트와 `pg_transfer_concurrency.py` 통과.
- 새 테이블 3개(마이그레이션 `f6b3d5e7a9c1`). `ANTHROPIC_API_KEY`가 없으면 `/agent/chat`만 503이고 다른 기능은 영향 없음.
- `frontend/lib/api.ts`의 `api()`가 body 없는 POST를 보낼 수 있게 됨(`method` 인자).

#### 검증
- `tests/test_agent.py` 18개: 로그인 차단, 남의 대화·계좌·초안 차단, `user_id` 인자 거절, 계좌 목록·요약 계산·거래내역 필터·카드 부족액, Tool 호출 후 답변, 모델 오류·시간 초과, 호출 상한, 초안만으로 잔액 불변, 만료·중복·동시 확인 차단, 확인 때 한도·잔액 재검사, 이체 후 거래내역·잔액.
- 전체 pytest, `alembic upgrade head` + `alembic check`(PostgreSQL), `pg_transfer_concurrency.py`, `pg_agent_confirm_concurrency.py`(10번 동시 확인 → 1건, 대조군 10건).
- 프론트 `tsc --noEmit`, `npm run lint`, `npm run build` 통과. 브라우저와 실제 모델 응답은 확인하지 못함.

#### 팀 논의 포인트
- 모델·effort·비용(기본 Opus 5.5 + low). 비용을 줄이려면 `AGENT_MODEL=claude-sonnet-5-5`.
- 초안 유효 시간 5분, 지난 대화 10개, 거래 50건 상한이 적당한지.
- 오래된 대화·초안을 지우는 정책(지금은 쌓이기만 함).
- 채팅 응답 스트리밍(지금은 다 만든 뒤 한 번에).

### C-071. AI 금융 비서 모델 공급자를 Gemini로 변경

- **날짜:** 2026-11-06
- **분류:** 구조
- **상태:** 적용 (실제 Gemini API로 확인)
- **바뀐 파일:**
  - `src/avengers_bank/domains/agent/tools/transfers.py`, `prompts.py`, `tools/__init__.py`: 출금 계좌 오류 구분, account_id 추측 금지
  - `src/avengers_bank/domains/agent/model_client.py`: `AnthropicModelClient` → `GeminiModelClient`
  - `src/avengers_bank/core/config.py`: `ANTHROPIC_API_KEY`·`AGENT_EFFORT` 삭제, `GEMINI_API_KEY` 추가, `AGENT_MODEL` 기본값 `gemini-2.5-flash`
  - `pyproject.toml`, `uv.lock`: `anthropic` 제거, `google-genai>=1.30,<2` 추가
  - `tests/test_agent.py`: Gemini 변환 테스트 2개
  - `.env.example`, `docs/AGENT.md`, `docs/RETROSPECTIVE.md`

#### 변경 전
C-070에서 Anthropic Claude(`claude-opus-5-5`, effort `low`, 거절 시 서버 대체 모델)로 구현했다.

#### 변경 후
- `google-genai`의 `client.aio.models.generate_content`를 한 단계씩 부른다. 자동 함수 실행은 끄고(`automatic_function_calling.disable`), 실행·재검증·상한은 그대로 `service.py`가 한다.
- Tool 스키마는 pydantic JSON 스키마를 `parameters_json_schema`로 그대로 넘긴다.
- 모델 응답 원본(`Content`, thought signature 포함)을 같은 요청 안에서 되돌려 보낸다. 함수 결과에는 호출한 함수 이름을 붙이고, 성공은 `{"output": ...}`, 실패는 `{"error": ...}`로 보낸다. Gemini가 호출 id를 주지 않으면 우리가 만든 id(`gen:`)를 쓰고, 되돌려 보낼 때는 뺀다.
- **실제 호출에서 찾은 문제:** Gemini가 `get_my_accounts` 없이 출금 `account_id`를 추측해 `prepare_transfer`를 불렀고, 출금·수취 계좌 모두 `ACCOUNT_NOT_FOUND`라서 "받는 계좌를 찾을 수 없다"고 잘못 안내했다. 출금 계좌를 먼저 확인해 `FROM_ACCOUNT_NOT_FOUND`로 구분하고, 지침·Tool 설명에 "from_account_id는 get_my_accounts 결과만"을 넣었다. 다시 돌리니 `get_my_accounts` → `prepare_transfer` 순서로 불렀다.
- 시간 초과는 `asyncio.timeout`(`AGENT_TIMEOUT_SECONDS`)으로 `504 AGENT_TIMEOUT`, SDK·네트워크 오류는 `503 AGENT_UNAVAILABLE`, 안전 필터 차단(`SAFETY` 등)은 "도와드릴 수 없습니다" 답변.

#### 이유
- 사용자가 Gemini API로 구현하기로 정했다.

#### 영향 범위
- Tool, 서비스, API 응답, DB, 프론트엔드는 바뀌지 않았다(공급자 경계가 `model_client.py` 한 파일).
- `.env`의 `ANTHROPIC_API_KEY`·`AGENT_EFFORT`는 더 이상 읽지 않는다(있어도 무시됨). `GEMINI_API_KEY`를 넣어야 AI 비서가 켜진다.

#### 검증
- `tests/test_agent.py` 20개(기존 18개 + Gemini 변환 2개: 함수 호출·결과 변환, 시간 초과·API 오류·안전 차단), 전체 pytest.
- 실제 Gemini(`gemini-2.5-flash`)로 개발용 PostgreSQL의 임시 사용자에게 질문 7개를 보냈다(자산 요약, 계좌 수, 최근 거래, 김철수에게 보낸 돈, 카드값, 예·적금 만기, 이체). 스키마는 그대로 받아들여졌고, 질문마다 맞는 Tool을 불렀으며 응답은 2~5초였다. 이체는 초안 → 확인 API로 잔액 1,000,000 → 950,000, 받는 쪽 0 → 50,000을 확인했다. 임시 데이터는 지웠다.

#### 팀 논의 포인트
- 기본 모델(`gemini-2.5-flash`)과 비용.

### C-072. AI 금융 비서 패널이 홈을 가리지 않고 옆으로 밀기, 패널 340px로 작게

- **날짜:** 2026-11-07
- **분류:** 구조
- **상태:** 적용 (로컬 브라우저에서 확인)
- **바뀐 파일:** `frontend/components/assistant/Assistant.tsx`, `frontend/app/globals.css`

#### 변경 전
패널(400px)이 `fixed`로 떠서 데스크톱에서 홈 화면 오른쪽을 덮었다. 여는 버튼과 글자도 컸다.

#### 변경 후
- 넓은 화면(1024px 이상): 패널을 열면 `body[data-assistant-open]`에 `padding-right: 340px`을 줘서 화면이 패널 폭만큼 왼쪽으로 밀린다. 닫으면 돌아온다. 움직임은 200ms, 움직임 줄이기 설정이면 애니메이션 없음.
- 좁은 화면(1024px 미만)에서 열려 있으면 패널이 전체 화면이 되어 AI 금융 비서만 보인다(창을 줄여도 같음).
- 패널 폭 400px → 340px, 제목·메시지·추천 질문·입력 글자를 한 단계 작게, 여는 버튼도 작게. 터치 영역 44px은 유지.

#### 이유
- 사용자 요청: 비서를 열면 홈이 가려져서, 홈은 옆으로 밀리고 비서는 더 작게. 좁아지면 비서만.

#### 영향 범위
- 프론트만. 패널을 닫거나 로그아웃(언마운트)하면 속성을 지워 다른 화면에 남지 않는다.

#### 검증
- `tsc --noEmit`, `npm run lint` 통과.
- 브라우저(임시 사용자, 확인 뒤 삭제): 1440·1280px에서 본문 오른쪽 끝(940px)이 패널 왼쪽(940px)과 겹치지 않고 가로 스크롤 없음. 820px에서 패널이 820×760 전체 화면, 본문 여백 0.

### C-073. AI 금융 비서 패널 폭을 끌어서 조절

- **날짜:** 2026-11-07
- **분류:** 구조
- **상태:** 적용 (로컬 브라우저에서 확인)
- **바뀐 파일:** `frontend/components/assistant/Assistant.tsx`, `frontend/app/globals.css`

#### 변경 전
패널 폭이 340px로 고정이었다 (C-072).

#### 변경 후
- 넓은 화면(1024px 이상)에서 패널 왼쪽 경계선을 마우스로 끌면 폭이 바뀌고, 홈 화면도 같이 밀리거나 넓어진다. 경계선에 마우스를 올리거나 끄는 동안 코랄색 선이 보인다.
- 키보드: 경계선(`role="separator"`, "AI 금융 비서 폭 조절")에 포커스를 두고 ←는 넓히기, →는 좁히기(24px씩).
- 폭은 300px 이상, 본문 자리(왼쪽 메뉴 240px + 본문 320px)를 남기는 만큼까지. 창을 나중에 줄여도 CSS `clamp(300px, 폭, 100vw - 560px)`로 다시 제한된다.
- 정한 폭은 이 브라우저의 `localStorage`(`avengers_bank_assistant_width`)에 기억한다. 끄는 동안에는 밀림 애니메이션과 글자 선택을 끈다.

#### 이유
- 사용자 요청: 비서가 시작하는 선을 확장·축소할 수 있게.

#### 영향 범위
- 프론트만. 좁은 화면(전체 화면 패널)에서는 경계선이 보이지 않는다.

#### 검증
- `tsc --noEmit`, `npm run lint` 통과.
- 브라우저(1100px, 임시 사용자, 확인 뒤 삭제): 끌어서 340 → 439px(본문 여백도 439px, 저장됨), → 키 3번 367px, 최소 300px, 최대 540px, 가로 스크롤 없음. 540px로 넓힌 뒤 창을 1024px로 줄이면 464px로 줄어든다.

### C-074. AI 답변을 서식 있게 보여 주기 (굵게·목록) + 등장 애니메이션

- **날짜:** 2026-11-07
- **분류:** 구조
- **상태:** 적용 (실제 Gemini 답변으로 확인)
- **바뀐 파일:**
  - `frontend/components/assistant/RichText.tsx` (새): AI 답변의 `**굵게**`, 목록(`-` `*` `•` `1.`), 문단만 React 요소로 그린다. HTML은 해석하지 않는다.
  - `frontend/components/assistant/Assistant.tsx`: AI 답변을 `RichText`로, 답변 기다리는 동안 점 세 개 표시, 메시지에 등장 애니메이션
  - `frontend/app/globals.css`: `msg-in`(떠오르며 나타남), `typing`(점 튀기) 애니메이션. 움직임 줄이기 설정이면 끔
  - `src/avengers_bank/domains/agent/prompts.py`: 서식 규칙(첫 줄 요약, `- ` 목록, 굵게는 이름에만, 제목·표·코드 금지)

#### 변경 전
모델이 마크다운으로 답하면 `**비상금 예금 (120-***-**9722)**`, `*   ` 같은 기호가 그대로 보였다.

#### 변경 후
- 목록 항목은 연한 피치 바탕의 한 줄 카드(코랄 점, 번호 목록은 동그라미 숫자)로, 70ms 간격으로 차례로 나타난다.
- 사용자·AI 메시지와 오류는 아래에서 살짝 떠오르며 나타난다. 답변을 기다리는 동안 "답변을 만드는 중…" 글 대신 점 세 개가 튄다(화면 읽기 도구에는 글로 읽힘).
- 마스킹된 번호(`120-***-**9722`, `4000-****-****-9012`)의 `*`는 굵게 표시로 읽지 않는다. 처음에 `**`를 굵게로 잘못 읽어 번호가 깨지는 것을 실제 답변에서 발견해 고쳤다.

#### 이유
- 사용자 요청: 기호가 그대로 나와서 보기 안 좋다, 애니메이션 등으로 보기 좋게.
- 마크다운 라이브러리는 이 정도 서식에 비해 커서 넣지 않았다.

#### 영향 범위
- 프론트 표시와 모델 지침만. API·저장 데이터는 같다(답변은 여전히 마크다운 글).

#### 검증
- `tsc --noEmit`, `npm run lint` 통과. 굵게 처리 자체 확인 4건(이름만 굵게, 마스킹 번호가 들어간 굵게, 카드번호, 짝 없는 `**`).
- 실제 Gemini에 "내 예·적금 만기 알려줘": 요약 한 줄 + 예금·적금 두 줄 카드로 보이고 번호가 `120-***-**2597`로 온전함(임시 사용자, 확인 뒤 삭제).

### C-075. 상품 약관 동의(버전 보존) + 약관 검색 RAG Tool + 검증된 출처

- **날짜:** 2026-11-07
- **분류:** DB 스키마 · API · 구조
- **상태:** 적용 (로컬. 실제 Gemini 임베딩·채팅으로 확인, 운영 DB에는 적용하지 않음)
- **역할:** 약관 문서·상품 연결·평가 질문은 Codex(`docs/terms/`, 본문 수정하지 않음). 이 항목은 앱 쪽 전부.
- **바뀐 파일:**
  - `src/avengers_bank/domains/terms/` (새): `models.py`(버전·적용 집합·동의·색인 테이블, pgvector `Vector` 타입), `markdown.py`(front matter·`## [id]` 조항), `loader.py`(manifest·corpus 검증), `publish.py`(발행 명령), `service.py`(현재 집합·동의 검증/기록·가입 당시 약관), `router.py`(`/terms/...`), `schemas.py`, `embedding.py`(Gemini 임베딩 경계), `chunking.py`, `indexing.py`(색인 명령), `search.py`
  - `alembic/versions/2026_11_07_1200-a7c4e6f8b0d2_add_terms_tables.py` (새): `vector` 확장, 약관 테이블 7개, `account_products/card_products.product_code`, `agent_messages.citations`
  - `accounts/service.py` `_open`, `cards/service.py` `_issue`, 두 `schemas.py`의 `*Create`: `terms` 필수, 동의 검증·기록을 개설·발급과 같은 트랜잭션에
  - `agent/tools/terms.py` (새, `search_product_terms`·`get_terms_section`), `agent/tools/__init__.py`, `agent/tools/cards.py`(`card_id` 추가), `agent/service.py`(요청별 출처 목록·인용 추출·저장), `agent/schemas.py`(`citations`), `agent/router.py`·`repository.py`(대화 메시지 조회), `agent/prompts.py`(약관 규칙, C-074 서식 규칙 뒤에 추가)
  - `core/config.py`: `terms_root`, `embedding_model`, `embedding_dimensions`, `embedding_timeout_seconds`, `terms_min_score`
  - `docker-compose.yml`: `postgres:17-trixie` → `pgvector/pgvector:pg17-trixie` (C-048의 반대 방향, 이유는 아래)
  - 프론트: `app/open/[kind]/[[...product]]/page.tsx`(약관 동의 단계), `app/terms/[versionId]/page.tsx`(새, 전문 보기), `components/terms/TermsMarkdown.tsx`·`ConsentRecord.tsx`(새), 계좌·카드 상세(가입 당시 약관 보기), `components/assistant/Assistant.tsx`(출처 칩·대화 복원·"AI에게 질문하기"), `lib/api.ts`
  - 테스트: `tests/test_terms_consent.py`, `test_terms_rag.py`, `test_terms_pg_consent.py`, `test_terms_pg.py`, `tests/terms_helpers.py`, `tests/fixtures/terms*/`, `tests/conftest.py`
  - `scripts/eval_terms.py`(새), `docs/TERMS_RAG.md`(새, 운영 안내), `docs/TERMS_EVAL.md`(새, 평가 결과), `.env.example`

#### 변경 전
```python
class DepositAccountCreate(BaseModel):
    product_id: int
    maturity_date: date
```
가입은 상품만 고르면 됐고 약관·동의 기록이 없었다. AI 비서는 계좌·카드 조회와 이체 초안만 할 수 있어서 "중도해지하면 이자가 어떻게 돼?"에 근거 없이 답하거나 모른다고 했다.

#### 변경 후
```python
class DepositAccountCreate(BaseModel):
    product_id: int
    terms: TermsConsentIn  # {revision_id, set_hash, agreements: [{terms_version_id, agreed}]}
    maturity_date: date
```
```python
async with db.begin():
    await product_service.require_account_product(db, product_id, kind.product_type)
    current, agreed = await terms_service.check_consent(db, kind.name, product_id, terms)  # 상품 행 FOR SHARE
    account = ...; await account_repository.save(db, account)
    await terms_service.record_consent(db, user, kind.name, account_id, current, agreed)
```
- **불변 스냅샷:** 발행 명령이 `docs/terms`를 검증해 `terms_versions`에 넣는다. 같은 `(document_key, version)`의 본문이 다르면 거절한다. 버전은 지우지 않고, 현재 집합에서 빠지면 `retired`.
- **상품 연결:** 새 `product_code` 컬럼. 처음엔 `(종류, 시드 이름)`이 정확히 1개일 때만 연결하고 코드를 저장한다. 계좌·카드 상품 ID가 겹쳐서 항상 `(kind, product_id)`로 다룬다.
- **동의 검증(서버):** 사용자가 본 `revision_id·set_hash`가 지금 집합과 같은지(아니면 409 `TERMS_OUTDATED`), 항목이 집합과 정확히 같은지(중복·누락·다른 상품·없는 버전 → 400 `TERMS_INVALID`), 필수에 모두 동의했는지(400 `TERMS_REQUIRED_NOT_AGREED`), `agreed`는 StrictBool. 약관 없는 상품은 409 `TERMS_NOT_CONFIGURED`(조용히 건너뛰지 않음). 동의 거부한 선택 약관도 `agreed=false`로 기록. IP·기기 정보는 받지 않는다.
- **동시성:** 가입은 상품 행 `FOR SHARE`, 발행은 `FOR UPDATE`. 발행 중이면 가입이 기다렸다가 새 집합을 보고 `TERMS_OUTDATED`, 가입 중이면 발행이 기다린다(가입은 자신이 본 집합으로 기록).
- **기존 계좌·카드:** 동의 기록을 만들지 않는다. 조회하면 `has_record: false`.
- **검색:** 조항 단위 청크 + Gemini 임베딩(`gemini-embedding-001`, 768) + pgvector 정확 검색 + 한국어 bigram 보정, 임계값 0.6. 범위(상품·버전)는 서버가 먼저 정한다. 색인 세대를 다 만든 뒤에만 활성화. 자세한 기준은 `docs/TERMS_RAG.md`.
- **출처:** 모델은 `[[src:{버전ID}:{조항ID}]]` 표시만 하고, 서버가 이번 요청에서 검색된 ID만 `citations`로 만든다. 링크는 정확한 버전의 조항(`/terms/12#early-close`).
- **상품 이름 해석:** 모델이 상품 ID 없이 검색하면, 질문·`product_name`에 상품 이름이 정확히 하나만 나올 때만 서버가 그 상품으로 정한다(아래 "실제 확인"에서 발견해 추가).

#### 이유
- 가입 시점에 "무엇에 동의했는지"를 나중에 증명할 수 있어야 한다. 화면 체크박스만 보면 API를 직접 부르는 요청은 막을 수 없다.
- 재현 시나리오(동시성): "사용자 A가 v1 약관 화면을 열어 둔 사이 v2가 발행되면, A는 v1에 동의했는데 서버가 v2로 기록하거나, v2 집합 아래 v1 동의로 가입된다." → revision 비교 + 상품 행 잠금으로 막았다.
- 재현 시나리오(검색): "적금 질문에 예금 약관이, 새 가입자 질문에 예전 버전이 섞여 답이 틀린다." → 상품·버전 필터를 검색 전에 적용, 색인이 안 된 새 버전은 예전 버전으로 대신하지 않고 `TERMS_INDEX_NOT_READY`.
- 출처를 모델이 만들게 두면 없는 링크·다른 버전 링크가 나온다 → 서버가 검색 결과로만 만든다.
- **pgvector 이미지로 되돌린 이유:** C-048에서 "쓰지 않는 확장"이라 공식 이미지로 바꿨는데, 이번에 실제로 쓰게 됐다. 두 이미지의 PostgreSQL 빌드가 같아(`17.11 (Debian 17.11-1.pgdg13+2)`) 기존 볼륨을 그대로 썼다(바꾸기 전 `pg_dump` 백업).

#### 영향 범위
- **API 호환성 깨짐:** 가입 5개 API가 `terms` 없이 오면 422. 프론트는 함께 바꿨다. 다른 클라이언트도 `GET /terms/products/...` 결과를 보내야 한다.
- **약관을 발행하지 않은 DB에서는 가입이 막힌다**(409). 로컬 개발 DB는 마이그레이션만 했고 **아직 발행하지 않았다** — 문서가 초안이라서다. 가입을 쓰려면 발행 명령을 돌린다(`docs/TERMS_RAG.md`).
- 기존 테스트 187개는 `tests/conftest.py`의 `BankClient`가 `terms` 없는 가입 요청에 "현재 약관 모두 동의"를 붙여 그대로 통과한다(약관이 없는 테스트 상품에는 필수 약관 1개짜리 집합을 만든다). 동의 검증 자체는 `test_terms_consent.py`가 이 기능을 끄고 확인한다.
- `alembic check` 차이 없음, downgrade → upgrade 확인. downgrade는 `vector` 확장을 지우지 않는다.

#### 검증
- pytest 226개 통과(PostgreSQL 통합 테스트 포함, `TEST_PG_DATABASE_URL` 설정 시. 없으면 3개 건너뜀).
  - 동의: 5개 가입 경로 모두 필수 미동의·`terms` 없음·오래된 revision 차단, 조작(중복·누락·없는 버전·다른 상품 집합·문자열 "true"), 선택 거부 가입, 발급 실패 시 동의 롤백, 동의 기록 실패 시 계좌 롤백, v2 발행 후 이전 화면 제출 → 재동의, 예전 원문·동의 보존, 남의 기록 404, 기존 계좌 기록 없음, AI 키 없이 열람.
  - PostgreSQL 실제 잠금(`test_terms_pg_consent.py`): 발행 중 가입 → 대기 후 `TERMS_OUTDATED`, 가입 중 발행 → 대기, 가입은 v1으로 기록.
  - 검색(`test_terms_rag.py`, 가짜 임베딩): 상품·버전 필터, 공통 약관은 연결된 경우만, 표·예외 한 청크, 재색인 중복 없음, 차원 불일치, 색인 미준비, 근거 부족, 다른 상품 섞임 없음, 문서 속 프롬프트 주입, 지어낸 출처 제거, 대화 다시 열기 출처 유지, 상품 이름 해석. `test_terms_pg.py`: pgvector `<=>` 경로.
- 실제 Codex 문서: 로더 검증 통과(21개·15개 상품). 개발 DB에 `--dry-run` 발행 → 15개 상품이 시드 이름으로 정확히 연결(ID가 순서대로가 아님: `credit-shopping → credit#4`).
- 임시 DB(`avengers_bank_e2e`)에서 실제로: 발행 21개 → 다시 발행 0개 변경, 색인 21개·청크 123개 → 다시 색인 0개 처리, 가입(미동의 400 → 동의 201 → 동의 기록 3건), 실제 Gemini 채팅 질문 5개 + 새 대화 질문 4개.
- 검색 평가(`docs/TERMS_EVAL.md`, 실제 임베딩): hit@3 24/24, hit@1 23/24, 섞임 0, 근거 부족 1/1.
- 프론트: `tsc --noEmit`, `npm run lint`, `npm run build` 통과. **브라우저로 직접 눌러 보지는 않았다.**

#### 실제 확인에서 발견해 고친 것
- "어벤져스 정기예금 중도해지하면?"에 모델이 상품 ID를 몰라 후보만 다시 물었다 → 서버가 정확한 상품 이름이면 상품을 정하도록(`named_product`) 고쳤다. 종류 이름 한 단어("정기예금")나 두 상품이 같이 나오면 고르지 않는다.
- "쇼핑 신용카드 할인이 실제로 계산돼?"에 검색 없이 "명세서에서 확인하세요"라고 답했다 → 혜택·할인·수수료·가입 대상도 반드시 검색하도록 프롬프트를 고쳤다. 고친 뒤 "할인은 데모에서 계산하지 않는다"를 출처 2개와 함께 답했다.
- 같은 대화 뒤쪽 질문에서 검색을 건너뛰고 상품 소개 문구("만 19~34세만 가입")로 틀리게 답했다 → "질문마다 새로 검색" 규칙을 넣었다. 새 대화로 두 번 다시 물었을 때는 "데모에서는 나이 확인을 하지 않는다"를 출처와 함께 답했다. **규칙을 넣은 뒤 같은 대화 안에서 다시 묻는 확인은 하지 못했다.**

#### 팀 논의 포인트
- **임계값 0.6의 여유가 작다:** 기대 조항 최저 0.622, 근거 없는 질문 최고 0.594, 근거 없는 평가 질문은 1개뿐. 평가 질문을 늘리고 다시 재야 한다.
- **모델 답변 평가는 수동 9문항뿐이다.** 검색 평가는 자동이지만, "모델이 검색하고 인용하는지"는 자동 평가가 없다(실제 모델 호출 비용).
- 약관 버전을 보존해도 **가입 당시 금리는 보존되지 않는다**(해지 때 상품 테이블 금리를 읽음, `docs/terms/IMPLEMENTATION_NOTES.md`). 별도 결정이 필요하다.
- 문서가 모두 초안이다. 실제 발행일(`--effective-from`)과 운영 DB 확장 활성화는 정해야 한다.
- 출처 칩은 "인용한 것"만 보인다. 모델이 인용 표시를 빠뜨리면 근거를 썼어도 출처가 안 보인다(지어낸 출처보다 낫다고 판단).

---

### C-076. 예금 가입 때 가입 금액을 입출금 계좌에서 바로 입금

- **날짜:** 2026-11-08
- **분류:** API · 구조
- **상태:** 적용 후 C-079에서 필드를 필수로 바꿈 (SQLite pytest와 서버를 띄운 HTTP·브라우저 확인. PostgreSQL 동시성은 C-079에서 `scripts/pg_deposit_open_concurrency.py`로 확인)
- **바뀐 파일:**
  - `accounts/schemas.py` `DepositAccountCreate`: 선택 필드 `initial_amount`, `from_checking_account_id`, 하나만 오면 422하는 `_amount_with_account`
  - `accounts/service.py` `open_deposit`·`_open`: 선택 인자 `after_open(db, account)`, 약관 동의 기록 뒤 같은 트랜잭션에서 호출
  - `transfers/service.py`: `_pay`의 본체를 `_pay_in_tx`(트랜잭션을 열지 않음)로 분리, `_pay`는 `begin`으로 감싼 얇은 래퍼, `pay_deposit_in_tx` 추가
  - `accounts/router.py` `open_deposit`: `initial_amount`가 있으면 `after_open`에 `pay_deposit_in_tx`를 연결
  - `tests/test_transfers.py`: 8건 추가
  - `frontend/app/open/[kind]/[[...product]]/page.tsx`: 예금 가입 화면에 가입 금액·출금 계좌 입력
  - `docs/API_ENDPOINTS.md`: `POST /accounts/deposit` 요청·규칙·오류

#### 변경 전
```
POST /accounts/deposit  { "product_id": 2, "maturity_date": "2027-12-10" }
→ 잔액 0원 예금이 만들어지고, 돈은 나중에 POST /transfers/deposit 으로 따로 넣는다
```

#### 변경 후
```
POST /accounts/deposit  { "product_id": 2, "maturity_date": "2027-12-10",
                          "initial_amount": 3000000, "from_checking_account_id": 1 }
→ 개설·약관 동의 기록·입출금 → 예금 이체가 한 트랜잭션. balance == initial_amount
```
- `initial_amount`와 `from_checking_account_id`는 **함께 보내거나 둘 다 생략**한다(하나만 오면 422). 둘 다 생략하면 이전과 똑같이 0원 예금이다.
- 거래내역은 기존 입금과 같다: 입출금 쪽 `TO_DEPOSIT`(상대 = 예금 계좌번호), 예금 쪽 `TRANSFER_IN`(상대 = 입출금 계좌번호). 1회·1일 이체 한도는 적용하지 않는다(`/transfers/deposit`과 같은 정책).
- 실패하면 예금 계좌도 약관 동의 기록도 남지 않는다: 잔액 부족 `400 INSUFFICIENT_BALANCE`, 없는·남의 입출금 계좌 `404 ACCOUNT_NOT_FOUND`.
- 화면은 항상 두 값을 보낸다. 출금 계좌 목록에 잔액을 보여 주고, 금액이 잔액보다 크면 입력 중에 한 줄 경고를 낸다(제출은 막지 않고 서버가 최종 판단). 입출금 계좌가 없으면 먼저 만들라는 안내를 낸다.

#### 이유
- 실제 정기예금은 가입할 때 금액을 정해 한 번에 맡긴다. 기존 방식은 가입이 끝났는데 돈이 0원이라 이자도 0원인 예금이 만들어지고, 사용자가 "가입했는데 왜 금액을 안 묻지?"라고 느낀다.
- 개설과 이체를 두 번의 호출로 나누면 개설만 되고 입금이 실패한 예금이 남는다 → 한 트랜잭션으로 묶었다.
- `accounts.service`가 `transfers.service`를 import하면 순환 import가 된다 → 서비스에는 콜백 자리(`after_open`)만 두고 router에서 연결했다. 계좌번호 충돌 재시도 루프에서 롤백 뒤 다시 불려도 안전하다.

#### 영향 범위
- **API는 하위 호환이다.** 두 필드가 선택이라 금액 없이 호출하는 기존 코드·테스트(AI 비서 테스트 포함)는 그대로 동작한다.
- `_pay`의 동작과 오류 코드는 그대로다(적금 납입·예금 입금 테스트가 계속 통과).
- 잠금 순서(입출금 → 예금·적금, ERD 규칙 9)는 유지된다. 새 예금 행은 다른 트랜잭션이 볼 수 없다.
- 소유권·잔액 검사가 예금 행 INSERT **뒤**에 일어난다. 실패하면 롤백되어 결과는 같지만, 잘못된 계좌 id여도 개설 쿼리 몇 개는 먼저 실행된다.

#### 검증
- `tests/test_transfers.py` 8건: 정상 가입(잔액 감소·양쪽 거래내역), 잔액 부족 롤백(예금 없음·약관 동의 기록 없음), 남의 계좌·없는 계좌 404, 한쪽만 보냄 422, 금액 없음 → 기존 동작, 금액 0·음수 422.
- 서버를 띄워 확인: 150만 원 가입 → 생활비 통장 13,000,000 → 11,500,000, 예금 1,500,000, 예금 쪽 `TRANSFER_IN` 1건. 99,999,999원은 400 `INSUFFICIENT_BALANCE`이고 계좌 수와 잔액이 그대로. 한쪽만 보내면 422.
- **하지 않은 것:** 같은 입출금 계좌로 개설과 이체를 동시에 보내는 PostgreSQL 동시성 확인(`scripts/` 기준). 잠금 순서는 코드로만 확인했다.

#### 팀 논의 포인트
- **결정됨(2026-11-08, C-079·C-080·C-081에서 구현):** 두 필드는 필수로, 가입 후 추가 입금은 막고, 최소 가입 금액은 상품별로 둔다. 이 항목은 필드를 **선택**으로 두었던 첫 단계의 기록이다.

---

### C-077. 약관 전문 보기: 같은 탭으로 열고, 돌아와도 입력값 유지

- **날짜:** 2026-11-08
- **분류:** 구조 (프론트)
- **상태:** 적용 (브라우저에서 확인)
- **바뀐 파일:**
  - `frontend/components/terms/ConsentRecord.tsx`: 계좌·카드 상세의 "전문 보기" 링크에서 `target="_blank"` 제거
  - `frontend/app/terms/[versionId]/page.tsx`: 맨 아래 링크를 "← 이전 페이지"(브라우저 뒤로 가기, 이전 페이지가 없으면 `/products`)로. 가입 화면에서 왔으면 기존대로 "← 가입 화면으로"
  - `frontend/app/open/[kind]/[[...product]]/page.tsx`: 입력칸을 `fields` 상태로 들고 있고, 약관 전문으로 나갈 때 `sessionStorage`에 맡겼다가 돌아오면 복원

#### 변경 전
- 계좌 상세의 "전문 보기"는 새 탭으로 열려서 돌아갈 이전 페이지가 없고, 아래 링크는 `/products`로 고정이었다.
- 가입 화면에서 "전문 보기" 뒤 돌아오면 상품·금액·만기일·별명·약관 동의가 모두 초기화됐다. 입력칸이 `defaultValue`만 쓰는 비제어 입력이라 화면이 새로 그려지면 기본값으로 돌아갔다.

#### 변경 후
- "전문 보기"는 같은 탭으로 열리고, 아래 링크가 이전 페이지로 돌려보낸다.
- 입력칸(납입액·납입일·결제일·만기일·별명·가입 금액·출금 계좌)과 상품 선택은 React 상태(`fields`, `bind()`)로 들고 있다. 동의 체크는 **같은 상품·같은 약관 묶음(`set_hash`)이면 유지**하고, 약관이 새 버전이 됐으면 처음부터 다시 동의한다.
- 화면이 아예 새로 열리는 경우(링크로 이동)를 위해 "전문 보기"를 누를 때 값을 `sessionStorage`(`open-draft:{kind}`)에 맡기고, 돌아오면 한 번 꺼내 쓰고 지운다.

#### 이유
- 재현 1: 적금 가입 화면에서 납입액·별명을 넣고 "전문 보기" → "← 가입 화면으로" → 전부 기본값.
- 재현 2(처음 고쳤을 때 놓친 경로): 같은 화면에서 **브라우저 뒤로 가기**로 돌아오면 Next가 이전 화면을 다시 살려 쓰는데, 그때 비제어 입력값과 동의 체크가 초기화되고 `sessionStorage`도 읽히지 않았다. 입력값을 상태로 들고 동의 초기화 조건을 "묶음이 바뀔 때만"으로 바꿔 고쳤다.

#### 영향 범위
- 가입 화면 5종(입출금·예금·적금·신용카드·체크카드)이 같은 코드라 모두 적용된다. 백엔드 변경 없음.
- 가입에 성공해도 화면은 `sessionStorage`를 따로 지우지 않지만, 초안은 돌아올 때 한 번 꺼내면서 지워지므로 찌꺼기가 남지 않는다(브라우저에서 확인).

#### 검증
- 브라우저: 적금·예금 가입 화면에서 입력 → "전문 보기" → ① "← 가입 화면으로" ② 브라우저 뒤로 가기, 두 경로 모두 상품·입력값·동의 4개가 그대로 복원됨. 저장소는 비어 있음.
- `npx tsc --noEmit`, `npx eslint` 에러·경고 0.
- **하지 않은 것:** 계좌 상세의 "가입 당시 약관 보기 → 전문 보기 → 이전 페이지"를 브라우저로 눌러 확인하지는 않았다(코드만 확인).

#### 팀 논의 포인트
- 약관 전문에서 돌아오면 계좌 상세의 "가입 당시 약관 보기" 펼침 상태는 접힌 채로 다시 열린다.

---

### C-078. 데모 사용자·계좌 시드 스크립트 `seed_demo.py`

- **날짜:** 2026-11-08
- **분류:** 구조 (개발 편의)
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/seed_demo.py` (새): `uv run python -m avengers_bank.seed_demo [login_id] [password]`

#### 변경 전
- 상품만 `seed.py`로 넣을 수 있었고, 데모 계좌를 만들려면 가입·로그인·약관 동의·개설·충전을 손으로 반복해야 했다. 새 계정으로 로그인하면 계좌가 하나도 없어 "데이터가 없어졌다"고 느꼈다.

#### 변경 후
- 실행 중인 API로 사용자 가입(있으면 로그인)→입출금 2개(생활비 통장 **정확히 13,000,000원**, 월급 통장 2,000,000원)→정기예금(가입 금액 3,000,000원, C-076)→적금(월 30만 원)을 만들고 계좌 표를 출력한다. 생활비 통장 충전액은 예금 가입 금액만큼 더해서(16,000,000) 최종 잔액이 13,000,000원이 되게 했다.
- 서버(`fastapi dev`), 상품 시드, **약관 발행**(`terms.publish`)이 먼저 필요하고 `ENABLE_DEV_ENDPOINTS=true`여야 한다. 실행할 때마다 계좌가 새로 추가된다(중복 방지 없음).

#### 이유
- DB 직접 삽입이 아니라 실제 API를 거치므로 약관 동의·번호 발급·충전이 서비스 코드 그대로 검증된다(스크립트 자체가 끝에서 끝까지 확인 역할).

#### 영향 범위
- 앱 코드는 건드리지 않는다. 약관 발행·색인(`terms.publish`, `terms.indexing`)은 이 스크립트가 하지 않으며, 로컬 DB에 약관 청크가 없으면 AI 비서의 약관 검색이 "지금은 이용할 수 없다"고 답한다(`TERMS_RAG.md`의 색인 단계).

#### 검증
- 새 계정으로 실행해 표를 확인했다: 생활비 통장 13,000,000원, 월급 통장 2,000,000원, 목돈 예금 3,000,000원, 여행 적금 0원.

#### 팀 논의 포인트
- 이미 있는 아이디의 비밀번호를 모르면 로그인에서 멈춘다(의도). 비밀번호를 인자로 받는다.

---

### C-079. 예금 가입 금액 필수화, 가입 후 추가 입금 금지 (`POST /transfers/deposit` 삭제)

- **날짜:** 2026-11-08
- **분류:** API · 구조
- **상태:** 적용 (C-076의 결정 사항을 확정)
- **바뀐 파일:**
  - `accounts/schemas.py` `DepositAccountCreate`: `initial_amount`, `from_checking_account_id` 필수, `_amount_with_account` validator 삭제
  - `accounts/router.py` `open_deposit`: 항상 `after_open`으로 입금
  - `transfers/router.py`·`schemas.py`·`service.py`: `POST /transfers/deposit`, `DepositPaymentCreate`, `pay_deposit` 삭제 (`pay_deposit_in_tx`, `_pay_in_tx`, 적금 납입은 유지)
  - `frontend/app/accounts/[type]/[id]/page.tsx`: 예금 상세의 "예금에 입금하기" 폼 삭제, `PayIn`은 적금 전용
  - `tests/`: 개설 호출 전부 새 계약으로, 새 도우미 `tests/helpers.py`의 `open_deposit()` 하나
  - `scripts/pg_close_concurrency.py`: 시나리오 2를 예금 입금 → 적금 납입으로, `scripts/pg_deposit_open_concurrency.py`(새), `scripts/_common.py` `cleanup`에 `terms_consents` 삭제 추가, `scripts/README.md`
  - `docs/API_ENDPOINTS.md`, `docs/ERD.md`, `README.md`, `docs/PROJECT_STRUCTURE.md`

#### 변경 전
```
POST /accounts/deposit  initial_amount, from_checking_account_id 선택 (둘 다 생략하면 0원 예금)
POST /transfers/deposit 입출금 → 내 예금 입금 (만기 전 여러 번)
```

#### 변경 후
```
POST /accounts/deposit  initial_amount, from_checking_account_id 필수 (없으면 422)
POST /transfers/deposit 삭제 (404). 예금 가입 후 추가 입금 불가, 가입 금액이 곧 원금
```
- 적금 납입(`POST /transfers/savings`)은 그대로다. transfers는 3개 → 2개 엔드포인트.
- 예금 계좌 거래내역의 입금(`TRANSFER_IN`)은 가입 때 한 번만 생긴다. 입출금 쪽 `TO_DEPOSIT`도 가입 금액 입금 때만 생긴다.

#### 이유
- 사용자 결정(실제 정기예금처럼 가입 때 금액을 정하고 추가 입금은 막는다). 0원 예금이 만들어지지 않는다.

#### 영향 범위
- **하위 호환이 깨진다.** 금액 없이 예금을 여는 호출과 `/transfers/deposit` 호출은 더는 동작하지 않는다. AI 비서에는 예금 개설·입금 도구가 없어 코드 변경은 없고, 테스트의 호출만 고쳤다.
- 해지된 예금·만기 후 예금에 입금하는 경로가 없어져 `ACCOUNT_CLOSED`·`ACCOUNT_MATURED` 검사는 적금 납입에서만 의미가 있다(`_pay_in_tx`에 그대로 둠).
- **놓칠 뻔한 곳 두 가지:** ① 예금 상세 화면의 입금 폼은 경로를 `/transfers/${kind}`로 조립해서 `grep transfers/deposit`에 잡히지 않았다. 지우지 않았다면 화면에서 404가 났다. ② `scripts/pg_close_concurrency.py`가 삭제된 `DepositPaymentCreate`·`pay_deposit`를 import하고 있었다. 예금에는 입금 경로가 없으므로 시나리오 2(해지와 입금 섞기)를 **적금 해지와 납입**으로 바꿨다.

#### 검증
- `tests/`: 삭제 `test_pay_deposit`·`test_open_deposit_without_amount_is_empty`(의미가 없어짐), 예금 입금 거절 검증(해지·만기)은 적금만 남김, 추가: `/transfers/deposit` 404, 필수 필드 누락 422, 0원 예금이 불가능해져 `test_close_empty_account_records_no_history`는 적금으로. 해지 금액·이자 기대값은 그대로 나온다.
- 서버를 띄워 확인: 필수 필드 누락 422, `/transfers/deposit` 404.
- **PostgreSQL 동시성:** `scripts/pg_deposit_open_concurrency.py`: 잔액 1,000,000원에서 100,000원짜리 가입 20번 동시 → 정확히 10건 성공·10건 `INSUFFICIENT_BALANCE`, 입출금 0원·예금 합계 1,000,000원, 동의 기록 10건. 잠금을 뺀 대조군은 20건이 모두 가입돼 합계가 2,000,000원이 됨. `pg_close_concurrency.py`도 통과(적금 해지 2 + 납입 20).

#### 팀 논의 포인트
- 삭제된 `POST /transfers/deposit`를 쓰던 외부 호출이 있으면 깨진다(이 저장소에서는 프론트·테스트·스크립트를 모두 고침).

---

### C-080. 예금 상품별 최소 가입 금액 (`account_products.min_amount`)

- **날짜:** 2026-11-08
- **분류:** DB 스키마 · API
- **상태:** 적용 (개발 DB에 마이그레이션·시드 적용. 운영 DB에는 적용하지 않음)
- **바뀐 파일:**
  - `products/models.py` `AccountProduct.min_amount` + CHECK `ck_account_products_min_amount_positive`, `products/schemas.py`
  - `alembic/versions/2026_11_08_1000-b8d5f7a9c1e3_add_product_min_amount.py` (새)
  - `accounts/service.py` `open_deposit`: 돈을 옮기기 전에 최소 금액 검사
  - `seed.py`: 이미 있는 상품도 `min_amount`를 갱신
  - `frontend/app/open/[kind]/[[...product]]/page.tsx`, `app/products/page.tsx`, `lib/api.ts`
  - `tests/test_deposit_min_amount.py`(새), `tests/test_products.py`

#### 변경 전
- 최소 가입 금액이 없다(1원 이상이면 가입).

#### 변경 후
- `account_products.min_amount BIGINT NULL` (NULL = 제한 없음). 값은 예금만: 어벤져스 정기예금 100,000원, 스타 정기예금 1,000,000원, 모바일 특판예금 500,000원.
- `GET /products/accounts`, `/products/accounts/{id}` 응답에 `min_amount`.
- `POST /accounts/deposit`에서 `initial_amount < min_amount`이면 `400 BELOW_MIN_AMOUNT`("이 상품의 최소 가입 금액은 1,000,000원입니다."). 개설 트랜잭션 안에서 이체 전에 검사하므로 예금·약관 동의 기록·이체 어느 것도 남지 않는다.
- 화면: 가입 화면의 상품 카드와 입력칸 아래에 "최소 N원", 입력값이 최소보다 작으면 입력 중 경고, 입력칸 `min` 속성, 상품 목록의 예금 카드에 "최소 가입 N원". 상품을 바꾸면 안내가 바뀐다.

#### 이유
- 사용자 결정(상품별로 둔다). 상품 소개와 약관에 같은 숫자가 있어야 해서 값은 데이터(`min_amount`)가 정하고 약관(C-081)은 그 숫자를 적는다.

#### 영향 범위
- 마이그레이션은 컬럼만 추가하고 기존 행은 NULL로 둔다. **값은 `seed.py`가 채운다**(마이그레이션 뒤 `uv run python -m avengers_bank.seed` 필요). 운영 DB에는 둘 다 아직 적용하지 않았다.
- 입출금·적금 상품은 NULL이라 동작이 그대로다. 테스트 픽스처 상품도 NULL이라 기존 테스트는 영향이 없다.
- `min_amount`를 바꾸면 약관 문서의 숫자도 같이 고쳐야 한다(자동 동기화 없음).

#### 검증
- `tests/test_deposit_min_amount.py`: 정확히 최소 금액이면 성공, 미만이면 400이고 예금 계좌·동의 기록·입출금 잔액 불변, NULL 상품은 1원도 성공, 상품 API 응답에 `min_amount`.
- 서버를 띄워 확인: 스타 정기예금에 999,999원은 400 `BELOW_MIN_AMOUNT`(계좌 수 그대로), 1,000,000원은 201. 브라우저에서 카드·경고·`min` 속성이 상품 선택에 따라 바뀌는 것 확인.
- 개발 DB: `alembic upgrade head` 뒤 `seed`로 3개 상품 값 확인(100000 / 1000000 / 500000).

#### 팀 논의 포인트
- 최소 금액은 예금에만 있다. 적금의 월 납입액 최소, 최대 가입 한도는 없다.
- 약관의 숫자와 `min_amount`를 자동으로 맞추는 장치는 없다(수동).

---

### C-081. 예금 약관 개정 (1.1.0): 가입 금액·최소 금액·추가 입금 불가

- **날짜:** 2026-11-08
- **분류:** 문서 · 약관
- **상태:** 적용 (개발 DB에 발행·색인). 사용자가 `docs/terms/` 본문 수정을 명시적으로 허락함 (`docs/terms/README.md`의 "본문 임의 수정 금지" 규칙은 그대로 둠)
- **바뀐 파일:**
  - `docs/terms/corpus/common/ab.deposit.rules.md`, `corpus/products/deposit-basic.md`, `deposit-star.md`, `deposit-mobile.md`: 1.0.0 → 1.1.0
  - `docs/terms/manifest.json`: 해당 4개 문서와 상품 연결 참조를 1.1.0으로
  - `docs/terms/evaluation.json`, `docs/terms/IMPLEMENTATION_NOTES.md`

#### 변경 전
- `[funding] 입금과 납입`: "만기 전에는 현재 구현상 여러 차례 입금할 수 있습니다." 최소 가입 금액 언급 없음.

#### 변경 후
- `ab.deposit.rules@1.1.0` `[funding]`: 가입할 때 가입 금액을 정해 본인 입출금계좌에서 한 번에 입금, 잔액 부족 시 가입 안 됨(동의 기록도 안 남음), **가입 후 추가 입금 불가**, 최소 가입 금액은 상품별(상품 문서). `[opening]`에 가입 금액·출금 계좌가 필수라는 설명 추가. 섹션 id는 모두 유지.
- 상품 문서 3개의 `[conditions]`: 최소 가입 금액(100,000 / 1,000,000 / 500,000원)과 "가입 후 추가 입금 불가, 가입 금액이 곧 원금". 에이전트가 요청 범위 밖으로 `[interest]`와 `[early-close-example]`의 "각 납입 건/납입금" 표현을 "가입 금액/입금일"로 고쳤다(계산식은 그대로).
- 평가 질문: T06 질문·기대 답을 새 동작으로, T04~T08의 기대 문서 버전을 1.1.0으로, 새 질문 T28(정기예금 최소 금액)·T29(스타 정기예금 최소 금액)·T30(잔액 부족 때) 추가.
- 발행(`publish --effective-from 2026-11-08`): 문서 4개 inserted(1.1.0), 예금 3종의 약관 묶음이 revision 2, 이전 1.0.0 4개는 retired. 색인: 문서 4개·청크 25개(Gemini 임베딩).

#### 이유
- 추가 입금을 막으면 약관의 "여러 차례 입금할 수 있다"가 사실과 달라지고, AI 비서가 이 조항을 근거로 틀리게 답한다. 최소 가입 금액은 약관에 아예 없었다.
- 발행된 본문은 덮어쓸 수 없어서 새 버전(1.1.0)으로 올렸다.

#### 영향 범위
- 예금 3종의 가입 화면은 새 약관 묶음(revision 2)으로 동의를 받는다. 약관 화면을 열어 둔 사용자는 `TERMS_OUTDATED` 안내를 받고 새로 동의한다. **이미 가입한 예금의 동의 기록은 가입 당시 1.0.0 그대로**이고 "가입 당시 약관 보기"도 1.0.0을 보여 준다.
- 이미 가입한 예금은 추가 입금이 안 되는 상태가 됐다(1.0.0 약관에는 "여러 차례 입금 가능"이라고 적혀 있음). 개발 데이터라 문제는 없지만, 실제 서비스라면 기존 가입자 고지가 필요한 변경이다.

#### 검증
- `publish --dry-run`(문서 4 inserted, 예금 3종 rev 2, 4 retired) → 본 발행, `indexing --dry-run`(문서 4, 청크 25) → 본 색인(실패 0).
- AI 비서에 실제로 물어봄: "스타 정기예금 최소 가입 금액" → 1,000,000원, 출처 `스타 정기예금 상품설명 및 특약 1.1.0 #conditions`. "정기예금에 가입한 뒤 추가로 입금할 수 있어?" → 추가 입금 불가, 출처 `예금 이용약관 1.1.0 #funding`.
- **확인하지 못한 것:** 상품명 없이 "예금 가입하고 나서 돈을 더 넣을 수 있어?"라고 물으면 검색 없이 "상품에 따라 불가할 수 있다"고 얼버무리고 출처가 없었다(상품을 되묻지도 않음). 모델 답변이 매번 같지 않다는 C-075의 알려진 한계다. `scripts/eval_terms.py` 평가는 실행하지 않았다(Gemini 호출 비용; `--fake` 옵션은 있음).

#### 팀 논의 포인트
- 예금은 가입 금액이 곧 원금이라는 문장이 약관·화면·API 문서에 모두 들어갔다. 만기 후 처리 같은 다른 조항은 그대로다.
- 상품명 없는 질문에서 모델이 검색을 건너뛰는 문제는 프롬프트 강화가 필요할 수 있다.

---

### C-082. 로그인 실패 한도를 동시 요청으로 우회하던 버그 수정

- **날짜:** 2026-11-08
- **분류:** 보안 · 동시성
- **상태:** 적용 (아이디+IP 메모리 한도는 C-090에서 DB 잠금으로 대체, '검증 전에 먼저 센다'는 원리는 그대로)
- **바뀐 파일:**
  - `core/login_limiter.py`: `check`·`record_failure` → `acquire`(확인 + 실패 1회 선기록) / `reset` / `cancel`
  - `users/router.py` `login`, `change_password`: `acquire` 방식으로
  - `tests/test_login_limiter_concurrency.py` (새, 6개)

#### 변경 전
```python
login_limiter.check(data.login_id, ip)          # 한도 확인
access_token = await user_service.login(db, data)  # argon2 검증, await 약 70ms
# 실패하면 login_limiter.record_failure(...)
```

#### 변경 후
```python
attempt = login_limiter.acquire(data.login_id, ip)  # 확인 + "실패 1회" 기록을 await 없이 한 번에
tokens = await user_service.login(db, data)         # 틀리면 미리 적은 기록이 그대로 실패 1회
login_limiter.reset(data.login_id, ip, attempt)      # 맞으면 기록 삭제
```

#### 이유
- 재현: 틀린 비밀번호 로그인 30개를 동시에 보내면 30개 모두 검증 전(기록 0개)에 `check`를 통과해 **30번 검증, 429는 0번**. 한도 5가 무력했다.
- asyncio는 스레드 하나에서 `await` 지점에서만 다른 요청으로 넘어간다. `acquire()` 안에는 `await`가 없으므로 확인과 기록 사이에 끼어들 틈이 없어 락 없이 원자적이다(워커 1개 전제, 기존 shortcut 주석 유지).

#### 영향 범위
- 성공하면 아이디+IP 기록은 모두 지우고, IP 기록은 이번 시도 한 건만 뺀다(다른 아이디로 틀린 기록은 남김).
- 비밀번호 변경에서 현재 비밀번호를 틀린 게 아닌 오류(새 비밀번호 규칙 위반 등)로 끝나면 `cancel`로 되돌린다.
- 예상 밖 예외(DB 오류 등)도 실패 1회로 남는다(보수적).

#### 검증
- 동시 30개 → 401 5개·429 25개, 아이디를 바꾼 동시 30개 → 401 20개(IP 한도)·429 10개, 비밀번호 변경 동시 10개 → 400 5개·429 5개.

#### 팀 논의 포인트
- 아이디 단위 전체 한도(IP를 바꿔 가며 한 아이디를 시도하는 경우)는 넣지 않았다. 사용자가 "다른 곳에서 로그인하면 기존 세션 종료"(단일 세션) 정책과 함께 논의하기로 함.

---

### C-083. 짧은 액세스 토큰 + 갱신 토큰(회전·재사용 감지)으로 세션 구조 변경

- **날짜:** 2026-11-08
- **분류:** 보안 · DB 스키마 · API
- **상태:** 적용 (개발 DB에 마이그레이션 적용. 운영 DB에는 적용하지 않음). 학습용 설명은 `docs/AUTH.md`
- **바뀐 파일:**
  - `core/config.py`: `jwt_expire_minutes=30` → `access_token_expire_minutes=5`, `session_expire_minutes=30` 추가. `.env.example`
  - `core/security.py`: `new_refresh_token`(`secrets.token_urlsafe(32)`), `hash_refresh_token`(SHA-256)
  - `users/models.py` `RefreshToken`, `alembic/versions/2026_11_08_1100-ccd01fe5b793_add_refresh_tokens.py` (새)
  - `users/repository.py`, `users/service.py`(`login`·`refresh`·`logout`·`change_password`), `users/router.py`, `users/schemas.py`(`TokenResponse`, `RefreshRequest`, `LogoutRequest`)
  - `tests/test_auth_tokens.py` (새, 11개), `scripts/pg_refresh_concurrency.py` (새), `scripts/_common.py`(정리에 `refresh_tokens`), `scripts/README.md`

#### 변경 전
- `POST /users/login` → 30분짜리 JWT 하나. 서버에 저장하지 않아 **비밀번호를 바꾸거나 로그아웃해도 서버가 끊을 수 없었다**(재현: 비밀번호 변경 후 이전 토큰으로 `GET /users/me` → 200).

#### 변경 후
```
POST /users/login          → { access_token(5분 JWT), token_type, refresh_token, expires_in: 300, session_expires_at(+30분) }
POST /users/token/refresh  { refresh_token } → 같은 모양. 쓴 갱신 토큰은 폐기(회전)
POST /users/logout         { refresh_token } → 그 세션(family) 폐기, 멱등 200
PATCH /users/me/password   → 그 사용자의 모든 세션 폐기 + 이 기기용 새 세션(응답 data = 토큰 묶음)
```
- 갱신 토큰은 의미 없는 256비트 임의 문자열, DB에는 SHA-256만 저장. `family_id` = 로그인 한 번 = 세션 하나.
- **재사용 감지:** 이미 교체된 갱신 토큰이 다시 오면 탈취로 보고 그 family 전체를 폐기 → 401 `REFRESH_TOKEN_REUSED`. 모르는·만료·폐기된 토큰은 401 `INVALID_REFRESH_TOKEN`.
- 갱신은 그 행을 `SELECT ... FOR UPDATE`(+`populate_existing`)로 잠근 뒤 검사한다(ERD 규칙 9와 같은 원칙).
- 재사용 감지 때 폐기를 커밋해야 하므로 트랜잭션 안에서 예외를 던지지 않고 블록 밖에서 401.
- 비밀번호 변경: 새 비밀번호가 아이디와 같으면(대소문자 무시) 400 `PASSWORD_SAME_AS_LOGIN_ID`.
- **모든 기기에서 로그아웃** `POST /users/logout-all` 🔒: 그 사용자의 모든 세션(이 기기 포함) 폐기, 새 세션은 주지 않음. 사용자 결정(로그아웃 버튼은 이 기기만, 모든 기기 로그아웃은 내 정보 화면의 별도 버튼). `/users/logout`과 달리 액세스 토큰으로 본인 확인(남의 세션을 끊는 데 쓰이지 않게). 테스트 `test_logout_all_revokes_every_session_and_needs_login`, 브라우저에서 이 기기·다른 기기 갱신 토큰이 모두 401이 되는 것 확인.

#### 이유
- 사용자 결정(B안): 정석 구조를 배우려고 "토큰 하나 + `token_version` 비교"(A안) 대신 액세스/갱신 토큰 구조를 골랐다.
- 액세스 토큰은 무상태로 두어 요청마다 DB 조회가 없고, 세션을 잇는 갱신 토큰만 DB에 두어 서버가 끊을 수 있다.
- SHA-256(argon2가 아님): 원문이 256비트 임의값이라 대입이 불가능하고, 결정적 해시여야 unique 인덱스로 바로 찾는다.

#### 영향 범위
- **하위 호환:** 로그인 응답은 필드 추가뿐이라 `access_token`을 쓰는 기존 코드는 그대로 동작한다. `PATCH /users/me/password` 응답 data는 `null` → 토큰 묶음으로 바뀌었다.
- **순수 B안의 한계:** 로그아웃·비밀번호 변경 뒤에도 이미 발급된 액세스 토큰은 **최대 5분** 유효(예전 30분). → **C-087에서 요청마다 세션을 확인하도록 바꿔 해결.**
- 슬라이딩 세션이라 계속 쓰면 세션이 끝없이 이어진다(절대 만료 없음). 폐기·만료 행은 쌓인다(정리 작업 추후).
- 환경변수 `JWT_EXPIRE_MINUTES`는 이제 무시된다(이 저장소에는 쓰는 곳 없음).

#### 검증
- `tests/test_auth_tokens.py`: 응답 필드, 회전(이전 토큰 무효), 재사용 감지 후 최신 토큰도 무효, 만료, 로그아웃·멱등, 비밀번호 변경 후 다른 세션 무효·새 토큰 동작, 원문 미저장, 액세스 토큰 수명 5분.
- **PostgreSQL** `scripts/pg_refresh_concurrency.py`: 같은 토큰 10번 동시 갱신 → 1번 성공·9번 `REFRESH_TOKEN_REUSED`, 이긴 쪽 새 토큰도 폐기, 살아 있는 토큰 0개. 잠금을 뺀 대조군은 10번 모두 성공(세션 10갈래).
- 서버에서 확인: 앞뒤 공백·대문자 아이디로 로그인 → 새 응답 모양. 옛 비밀번호(`password1234`) 계정도 로그인됨.

#### 팀 논의 포인트
- 즉시 끊어야 하면 액세스 토큰에 `family_id`를 넣고 요청마다 세션 행을 확인하는 혼합 방식(요청당 조회 1번 추가).
- 토큰 보관 위치(`localStorage` → `httpOnly` 쿠키)는 별도 논의 예정. → C-096에서 적용.

---

### C-084. 아이디 정규화와 회원 정보 입력 검증 강화

- **날짜:** 2026-11-08
- **분류:** API · 보안
- **상태:** 적용
- **바뀐 파일:**
  - `users/validators.py` (새): 정규화·검사 함수와 `LoginId`·`Name`·`NickName`·`Phone`·`NewPassword` 등 Annotated 타입
  - `users/schemas.py`: `UserCreate`, `UserLogin`, `UserUpdate`, `PasswordChange`
  - `tests/conftest.py`, `tests/test_users.py`, `seed_demo.py`·`scripts/pg_deposit_open_concurrency.py`(가입 비밀번호를 새 규칙 값 `Passw0rd!23`으로)

#### 변경 전
- 아이디 4~50자 아무 문자, 대소문자 구분 → `tokenuser `(뒤 공백), `Tokenuser`가 별개 계정으로 가입됨. 휴대폰 자동 대문자로 로그인 실패 가능.
- 이름 `"   "`, 전화번호 `abcdefghij`, 비밀번호 공백 8개·아이디와 같은 비밀번호가 가입됨. 내 정보 수정도 같음.

#### 변경 후
- **아이디:** 가입·로그인 모두 앞뒤 공백 제거 + 소문자. 가입만 `^[a-z0-9_]{4,20}$` 검사. **로그인은 형식 검사 없음**(형식이 달라도 401 — 아이디 규칙을 흘리지 않고 옛 계정도 막지 않게).
- **이름:** 앞뒤 공백 제거 후 1~50자. **닉네임:** 앞뒤 공백 제거, 빈 문자열이면 null.
- **휴대폰:** 하이픈·공백을 빼고 `^01[016789]\d{7,8}$`이면 `010-1234-5678`(10자리 `011-123-4567`) 모양으로 저장.
- **비밀번호(가입·새 비밀번호):** 8~128자, **영문·숫자·특수문자(키보드 기호) 각 1자 이상**, 키보드 문자만(한글·공백·전각 문자 불가), 아이디와 같으면 거부(대소문자 무시). 로그인과 현재 비밀번호에는 강도 규칙 없음(옛 계정 호환).

#### 이유
- 사용자 결정(아이디 A안, 비밀번호는 은행 앱처럼 영문·숫자·특수문자 모두).
- 한글을 받지 않는 이유: 한/영 전환 실수와 기기마다 다른 유니코드 조합(NFC/NFD) 때문에 같은 비밀번호가 다르게 저장될 수 있다. 처음 구현은 한글을 특수문자로 쳐 주었는데(정의를 "영문·숫자·공백이 아닌 문자"로 썼음) 통합하면서 키보드 기호로 좁혔다.

#### 영향 범위
- DB 컬럼 길이(50)는 그대로, 마이그레이션 없음. 개발 DB의 기존 아이디·전화번호는 모두 새 형식을 이미 만족(확인함). 운영 DB는 미확인.
- 기존 데이터는 수정할 때만 새 규칙으로 다시 검사된다.

#### 검증
- `tests/test_users.py`: 정규화(공백·대문자 → 같은 계정), 대소문자만 다른 중복 409, 로그인은 형식 검사 없이 401, 전화번호 정규화 5가지, 이름·닉네임 공백 처리, 비밀번호 강도·아이디와 같음·키보드 문자만, 내 정보 수정도 같은 규칙, 옛 약한 비밀번호 계정도 로그인·변경 가능.
- 브라우저: `UiTest01` 가입 → `uitest01`로 저장, 이름 `"  테스트 "` → `테스트`, `01055556666` → `010-5555-6666`.

#### 팀 논의 포인트
- DB unique는 여전히 대소문자를 구분한다(정규화로 막음). 정규화 이전 데이터가 있는 DB라면 소문자 기준 unique 인덱스를 검토.

---

### C-085. 422 입력 오류 메시지를 한국어 완성 문장으로

- **날짜:** 2026-11-08
- **분류:** API
- **상태:** 적용
- **바뀐 파일:**
  - `core/exception_handlers.py`: `FIELD_LABELS`(약 55개 필드 이름표), 조사 선택(`_josa`), `korean_message()`
  - `frontend/lib/api.ts`: `details[0].msg`만 표시

#### 변경 전
```
화면: phone: String should have at most 20 characters
```

#### 변경 후
```json
{"loc": ["body", "phone"], "msg": "휴대폰 번호는 20자 이하로 입력해 주세요.", "type": "string_too_long"}
```
- 오류 종류(`missing`, `string_too_short/long`, `greater_than(_equal)`, `less_than(_equal)`, 숫자·날짜 파싱, `extra_forbidden`, `literal_error`, `json_invalid` 등)별 문장 + 필드 이름표 + `ctx`의 숫자. 직접 낸 `ValueError`는 "Value error, " 접두어를 떼고 그대로. 모르는 종류는 "입력값을 확인해 주세요: {이름표}".
- 응답 구조(`loc`, `msg`, `type`, 상위 `message`)는 그대로.

#### 이유
- 사용자 결정(A안, 서버에서): 서버 한 곳에서 바꾸면 모든 화면에 적용된다.

#### 영향 범위
- AI 비서 도구(`domains/agent/tools/`)는 이 처리기를 거치지 않고 pydantic 메시지로 자체 문구를 만들어 **여전히 영어**다(사용자에게 직접 보이는 경로는 아님).

#### 검증
- `test_validation_messages_are_korean_sentences`(7가지, "String should"·"Field required"·"Value error" 없음), 금지·모르는 필드, 숫자·날짜 오류.

#### 팀 논의 포인트
- AI 비서 도구 입력 오류도 같은 함수로 바꿀지.

---

### C-086. 화면: 세션 타이머·자동 갱신·만료 처리, 비밀번호 확인 칸

- **날짜:** 2026-11-08
- **분류:** 구조 (프론트)
- **상태:** 적용 (브라우저에서 확인)
- **바뀐 파일:**
  - `frontend/lib/api.ts`: `session`(한 키 `avengers_bank_session`에 토큰 묶음), `api()`의 401 → 갱신 → 재시도, `refreshSession`(single-flight + Web Locks), `logout`, `expireSession`, `safeNext`
  - `frontend/components/ui.tsx`: `SessionTimer`(남은 시간·연장·2분 전 예고·만료)
  - `frontend/app/login`, `signup`, `me`, `page.tsx`, `terms/[versionId]`, `components/assistant/Assistant.tsx`·`TransferCard.tsx`

#### 변경 전
- 로그인 30분 뒤부터 모든 화면이 "유효하지 않거나 만료된 토큰입니다" 문구만 띄우고 그대로였다. 내 정보 화면은 오류여도 비밀번호 변경 폼이 보였다.
- 로그아웃은 브라우저에서 토큰만 지웠다. 가입·비밀번호 변경에 확인 칸이 없었다.

#### 변경 후
- 화면 위 **"자동 로그아웃 29:41" + [연장]**. 2분 이하면 `role="alertdialog"` 예고(포커스 [연장]). 0이 되면 서버 로그아웃 → `/login?next=<보던 화면>&reason=expired` → "로그인이 만료되었습니다" 안내 → 다시 로그인하면 보던 화면으로.
- 액세스 토큰(5분)이 만료되면 조용히 갱신하고 원래 요청을 다시 보낸다. 갱신 토큰을 두 번 쓰지 않도록 같은 탭은 single-flight, 여러 탭은 Web Locks로 직렬화(잠금을 얻은 뒤 저장소를 다시 읽어 이미 갱신됐으면 건너뜀).
- 로그아웃은 서버 세션도 끊는다(이 기기만). 내 정보 화면에 **"모든 기기에서 로그아웃"** 버튼(확인 창 뒤 `POST /users/logout-all`). 비밀번호 변경 성공 시 응답의 새 토큰으로 교체.
- 가입·비밀번호 변경에 **비밀번호 확인 칸**(다르면 서버에 보내지 않음). 아이디 칸 자동 대문자·자동 수정 끔, 안내 문구.
- `next`는 같은 사이트 경로만 받는다(오픈 리다이렉트 방지).

#### 이유
- 사용자 결정(6번 B안: 30분 유지 + 남은 시간 타이머 + 만료 예고, 4번: 확인 칸 먼저, 비밀번호 찾기는 이메일·문자 인증으로 나중에).

#### 영향 범위
- 토큰 저장 키가 바뀌어 기존 로그인 사용자는 한 번 다시 로그인해야 한다(옛 키 `avengers_bank_token`은 지우지 않고 무시).
- 남은 시간은 서버의 `session_expires_at`을 기기 시계로 계산한다(기기 시계가 틀리면 그만큼 어긋남).
- 타이머는 `Shell`을 쓰는 화면에만 있다(약관 전문 화면 등에는 없음, 그래도 만료 후 API는 401 흐름으로 처리됨). Web Locks가 없는 환경(비보안 http 출처)에서는 탭 사이 직렬화가 없다.

#### 검증
- 브라우저: 가입 화면 확인 칸 불일치 → "비밀번호가 일치하지 않습니다."(서버 호출 없음), 약한 비밀번호 → 서버 한국어 문장. 가입 후 타이머 "자동 로그아웃 29:52". 액세스 토큰을 망가뜨리고 내 정보를 열면 정상 표시 + 갱신 토큰 회전 + 세션 시각 갱신. 만료 시각을 100초 뒤로 당기면 예고 창(포커스 [연장]) → 연장 → 30분. 3초 뒤로 당기면 로그인 화면(`next=/me&reason=expired`) + 서버에서도 그 갱신 토큰 폐기 → `UITEST01 `로 다시 로그인 → `/me`로 복귀.
- `npx tsc --noEmit`, `npx eslint app components lib` 에러·경고 0.

#### 팀 논의 포인트
- 은행처럼 활동과 무관한 최대 세션 시간을 둘지. 화면에서 기기 시계 보정이 필요한지.

---

### C-087. 액세스 토큰도 즉시 끊기 (요청마다 세션 확인)

- **날짜:** 2026-11-08
- **분류:** 보안
- **상태:** 적용
- **바뀐 파일:**
  - `core/security.py`: `create_access_token(user_id, session_id)`가 `sid` 클레임을 넣고, `decode_access_token`은 `sid`를 필수로 `(user_id, sid)`를 돌려준다
  - `users/repository.py` `is_session_active`, `users/service.py` `get_current_user`(그리고 logout·logout_all·change_password 주석)
  - `tests/test_auth_tokens.py`(5개 추가), `tests/test_users.py`(손으로 만든 토큰에 `sid`, 거절 사례 `no_sid`·`session_not_alive` 추가)
  - `docs/AUTH.md` 9-1장, `docs/API_ENDPOINTS.md`

#### 변경 전
- C-083의 순수 B안: 액세스 토큰은 서명·만료만 확인. 로그아웃·모든 기기 로그아웃·비밀번호 변경·재사용 감지 뒤에도 **이미 발급된 액세스 토큰은 최대 5분 더 유효**.

#### 변경 후
```python
user_id, session_id = decode_access_token(token)        # sid 필수
user = await user_repository.find_by_id(db, user_id)
if user is None or not await user_repository.is_session_active(db, user_id, session_id):
    raise UnauthorizedException(code="INVALID_TOKEN", ...)  # 끊긴 세션이면 5분이 남았어도 거절
```
- `is_session_active`: 그 `family_id`에 폐기되지 않은 갱신 토큰 행이 하나라도 있는가. 회전해도 새 행이 살아 있으므로 세션은 살아 있다. 만료 시각은 보지 않는다(액세스 5분 < 갱신 30분).
- 5분 만료는 유지(1차 방어이자 안전장치).
- `sid`가 없는 예전 액세스 토큰은 401 → 프론트가 갱신 토큰으로 새로 받는다(사용자 영향 없음).

#### 이유
- 사용자 결정: "로그아웃 뒤 5분 유효"는 은행 서비스에서 보안상 위험하다.
- 순수 JWT의 장점(DB 조회 없음)은 이 프로젝트가 원래 요청마다 사용자를 DB에서 읽고 있어 실익이 작았다. 늘어나는 비용은 인덱스 조회 하나.

#### 영향 범위
- 요청마다 `refresh_tokens` 조회 1번 추가(`family_id` 인덱스). 액세스 토큰이 "서명된 세션 참조"가 됐다.
- 나중에 "다른 곳에서 로그인하면 기존 세션 종료"(단일 세션)를 넣으면 그것도 즉시 적용된다.

#### 검증
- 테스트: 액세스 토큰의 `sid` = 세션 family, 로그아웃 즉시 401(다른 세션은 200), 회전 후에도 같은 세션의 이전 액세스 토큰 동작, 모든 기기 로그아웃·비밀번호 변경 즉시 다른 기기 401(새 세션은 200), 재사용 감지 즉시 401, `sid` 없음·모르는 세션 401. 전체 306개 통과(3 skip).
- 실행 중인 서버: 두 기기 로그인 → A 로그아웃 뒤 A 401·B 200 → 모든 기기 로그아웃 뒤 B·C 모두 401.

#### 팀 논의 포인트
- 요청량이 아주 많아지면 세션 확인을 캐시(예: 짧은 TTL의 폐기 목록)로 바꿀 수 있다. 지금 규모에서는 불필요.

---

### C-088. 단일 세션: 다른 곳에서 로그인하면 기존 세션 종료 + 사용자 행 잠금

- **날짜:** 2026-11-08
- **분류:** 보안 · 동시성 · DB 스키마
- **상태:** 적용 (개발 DB에 마이그레이션 적용)
- **바뀐 파일:**
  - `users/models.py` `RefreshToken.revoked_reason` + CHECK 2개, `alembic/versions/2026_11_08_1400-4f2a9c7e1b30_add_refresh_tokens_revoked_reason.py` (새)
  - `users/repository.py` `lock_user`, 폐기 함수가 이유를 저장
  - `users/service.py` `login`(다른 세션 폐기), `refresh`(잠금 순서 변경, `SESSION_REPLACED`), `logout`·`logout_all`·`change_password`(사용자 행 잠금)
  - `frontend/lib/api.ts`(갱신 실패 이유 기억, `reason=replaced`), `frontend/app/login/page.tsx`(안내 문구)
  - `tests/test_single_session.py` (새, 6개), `tests/test_auth_tokens.py`(`add_other_device` 도우미, 테스트 5개 수정)
  - `scripts/pg_single_session_concurrency.py` (새), `scripts/pg_refresh_concurrency.py`(대조군에서 사용자 행 잠금도 제거), `scripts/README.md`
  - `docs/AUTH.md` 9-2장, `docs/API_ENDPOINTS.md`, `docs/ERD.md` 규칙 9

#### 변경 전
- 같은 아이디로 여러 곳에서 로그인하면 세션이 기기마다 따로 생겨 모두 살아 있었다.
- (숨은 문제) 다른 기기가 갱신하는 순간 비밀번호 변경·모든 기기 로그아웃을 하면, PostgreSQL READ COMMITTED에서 폐기 UPDATE가 아직 커밋 안 된 새 토큰 행을 못 봐 그 기기가 살아남을 수 있었다.

#### 변경 후
- 로그인하면 비밀번호 검증 뒤 그 사용자의 살아 있는 갱신 토큰을 모두 폐기(`LOGIN_ELSEWHERE`)하고 새 세션을 만든다. 끊긴 기기의 액세스 토큰은 C-087로 다음 요청부터 401.
- 끊긴 세션으로 갱신하면 `401 SESSION_REPLACED`("다른 곳에서 로그인되어 로그아웃되었습니다."). 화면은 `/login?reason=replaced`로 보내 "본인이 아니라면 비밀번호를 바꿔 주세요"까지 안내.
- 폐기 이유 저장: `ROTATED`, `LOGOUT`, `LOGOUT_ALL`, `PASSWORD_CHANGED`, `REUSE_DETECTED`, `LOGIN_ELSEWHERE`.
- 세션을 바꾸는 모든 작업이 **users 행 → refresh_tokens** 순서로 잠근다. 갱신은 토큰 행을 먼저 잠그던 것을 "토큰을 잠금 없이 찾기 → users 잠금 → 토큰 다시 잠그기"로 바꿔 순서를 맞췄다(데드락 방지). 로그인은 틀린 비밀번호 요청이 사용자 행을 붙잡지 않게 검증 뒤에 잠근다.

#### 이유
- 사용자 결정(단일 세션 도입). 내 계정에 누가 들어와 있어도 내가 로그인하면 끊기고, 반대로 누가 로그인하면 내가 알게 된다.
- 아직 없는 행은 잠글 수 없어서, 같은 사용자의 세션 작업을 사용자 행 하나로 줄 세운다.

#### 영향 범위
- 같은 사용자가 두 기기를 동시에 쓸 수 없다(정책). 같은 브라우저의 여러 탭은 같은 세션이라 영향 없음.
- 마이그레이션 전에 폐기된 행은 이유가 NULL이라 `INVALID_REFRESH_TOKEN`으로 처리된다.
- 같은 사용자의 로그인·갱신·로그아웃이 사용자 행에서 줄을 선다(사용자 단위라 영향 작음). 비밀번호 변경은 argon2 검증 동안 잠금을 잡는다.
- 끊긴 기기는 **다음 요청 때** 알게 된다(화면을 그냥 열어 두면 타이머가 0이 되거나 무언가를 누를 때까지 모름).
- 기존 테스트 중 "같은 사용자로 두 번 로그인해 두 기기를 흉내 내던" 5개는 DB에 다른 기기 세션을 직접 넣는 도우미로 바꿨다(기대 동작은 그대로).

#### 검증
- 테스트: 두 번째 로그인 후 첫 세션 갱신 `SESSION_REPLACED`·액세스 401, 다른 사용자 영향 없음, 폐기 이유 6종, 로그아웃·비밀번호 변경으로 끊긴 세션은 `INVALID_REFRESH_TOKEN`. 전체 312개 통과(3 skip).
- **PostgreSQL** `pg_single_session_concurrency.py`: 10곳 동시 로그인 → 살아 있는 세션 1개, 각 기기 갱신은 1곳 OK·9곳 `SESSION_REPLACED`. 갱신 ↔ 다른 곳 로그인 동시 15라운드 → 매번 1개만 생존. 대조군(사용자 행 잠금 제거) → 10개 모두 생존. `pg_refresh_concurrency.py`도 다시 통과.
- 브라우저: 브라우저에서 로그인 → 셸에서 같은 아이디로 로그인 → 브라우저에서 내 정보를 누르자 `/login?next=/me&reason=replaced`와 안내 문구.

#### 팀 논의 포인트
- 아이디 단위 실패 한도는 C-089에서 아이디별 속도 제한으로 적용(믿을 수 있는 기기 예외는 9번 쿠키 전환 때 → C-096에서 "카운터 분리"로 적용).
- 끊긴 기기에 즉시 알리려면 주기적 확인(폴링)이나 푸시가 필요하다.

---

### C-089. 아이디별 속도 제한: 계정을 잠그지 않고 느리게

- **날짜:** 2026-11-08
- **분류:** 보안
- **상태:** C-090에서 대체 (복구 절차가 생겨 국내 규정대로 5회 잠금으로 바꿈)
- **바뀐 파일:**
  - `core/login_limiter.py`: `MAX_FAILURES_PER_ID = 10`, `SLOW_INTERVAL_SECONDS = 30`, 키 `("id", 아이디)`, `_last_slowed_attempt`
  - `tests/test_login_limiter_concurrency.py` (4개 추가)
  - `docs/AUTH.md` 6-1장, `docs/API_ENDPOINTS.md`

#### 변경 전
- 한도는 "아이디+IP 15분 5회"와 "IP 15분 20회"뿐. 공격자가 IP를 바꿔 가며 한 아이디를 찌르면 막지 못했다.

#### 변경 후
- IP와 상관없이 한 아이디가 15분에 10번 틀리면, 그 아이디는 **마지막 시도(성공 포함)로부터 30초가 지나야** 한 번 더 시도 가능. 그 전에는 429 `TOO_MANY_LOGIN_ATTEMPTS` + `Retry-After`.
- 검증 전에 먼저 기록하는 기존 방식(C-082)을 그대로 따라 동시 요청으로 우회할 수 없다.
- 주인이 성공해도 공격자가 쌓은 실패 기록은 그대로(이번 시도만 뺌).

#### 이유
- 사용자 결정(A안: 아이디별 속도 제한 지금, B안: 믿을 수 있는 기기 예외는 9번 쿠키 전환 때).
- "N번 틀리면 잠금"은 공격자가 일부러 틀려서 진짜 사용자를 못 들어오게 하는 잠금 공격이 가능하다. 느리게만 하면 주인은 최대 30초 기다리고, 공격자는 아이디당 분당 2번으로 묶인다.
- 처음 구현은 30초를 "마지막 실패" 기준으로 쟀다. 테스트에서 주인이 성공한 직후 공격자가 바로 다음 시도를 할 수 있는 구멍이 드러나 "마지막 시도(성공 포함)" 기준으로 고쳤다.

#### 영향 범위
- 공격받는 아이디의 주인도 새 기기에서는 최대 30초를 기다릴 수 있다(B안으로 해소 예정).
- 프로세스 메모리 기반이라는 기존 한계(재시작 시 초기화, 워커 1개 전제)는 같다.

#### 검증
- IP 5곳에서 2번씩 틀린 뒤 처음 보는 IP에서도 429(`Retry-After` 1~30). 30초 뒤 주인은 맞는 비밀번호로 200, 그 직후 공격 시도는 다시 429.
- 대기 중 10개 IP 동시 시도 → 모두 429. 30초 뒤 10개 IP 동시 시도 → 정확히 1개만 검증(401)·9개 429. 다른 아이디는 영향 없음.
- 실행 중인 서버로는 확인하지 못했다(로컬 요청은 모두 같은 IP라 아이디+IP 한도에 먼저 걸림). IP를 나눈 ASGI 테스트로 확인.

#### 팀 논의 포인트
- 기준(10회, 30초)은 정책값이다. 은행처럼 5회 오류 시 추가 인증(C안)은 문자·이메일 연동 때.

---

### C-090. 은행식 로그인 잠금: 5회 연속 오류 → 잠금 (DB, 원자적 선증가)

- **날짜:** 2026-11-08
- **분류:** 보안 · 동시성 · DB 스키마
- **상태:** 적용 (C-082의 아이디+IP 한도와 C-089의 아이디별 느리게를 대체)
- **바뀐 파일:**
  - `users/models.py`(`failed_login_count`, `login_locked_at`), `users/repository.py`(`count_login_attempt`, `lock_login`, `unlock_login`), `users/service.py`(`login`, `change_password`, `_busy`)
  - `core/login_limiter.py`: IP 한도만 남긴 `IpLimiter`(로그인 20회, 인증번호 발송 10회)
  - `admin.py` (새, `unlock`·`reset-password`), 개발용 `POST /dev/users/{login_id}/unlock`
  - 마이그레이션 `6b7c8d9e0f1a`(C-091과 함께)
  - `tests/test_login_lock.py`(새), `tests/test_login_limiter_concurrency.py`·`tests/test_users.py`(새 정책으로 교체), `scripts/pg_login_lock_concurrency.py`(새)

#### 변경 전
- 메모리 한도: 아이디+IP 15분 5회(C-082), IP 20회, 아이디별 15분 10회 후 30초에 1회(C-089). 잠그지 않음. 재시작하면 초기화.

#### 변경 후
- 같은 아이디로 **5회 연속** 틀리면 `login_locked_at` 설정 → 맞는 비밀번호도 403 `ACCOUNT_LOCKED`. 해제는 비밀번호 찾기(C-093)·관리자 명령·개발용 API.
- 검증 **전에** `UPDATE … SET failed_login_count = failed_login_count + 1 WHERE … AND login_locked_at IS NULL AND failed_login_count < 5 RETURNING`을 자기 트랜잭션으로 커밋(롤백 불가). 성공하면 0으로.
- 결과가 없을 때: 잠겼으면 403, 잠기지 않았는데 동시 요청들이 5번을 가져가 검증 중이면 **429 `TOO_MANY_LOGIN_ATTEMPTS`**(통합 중 수정: 처음엔 403이라 맞는 비밀번호를 동시에 6번 보낸 사용자에게 "잠김"이라는 틀린 안내가 나갔다).
- 비밀번호 변경의 현재 비밀번호 오류도 같은 카운터. 메모리 한도는 IP 15분 20회만.

#### 이유
- 조사 결과(전자금융감독규정 제33조 ②항 3호: 5회 이내 거래 중지 + 본인확인 후 재부여). 복구 절차(C-093)가 생겨 잠금 공격의 피해가 줄었다(OWASP: 잠긴 계정도 복구는 쓸 수 있게).
- DB 원자적 증가는 서버 재시작·여러 대에서도 정확하다(메모리 한도의 한계 해소).

#### 영향 범위
- 아이디만 알면 누구나 5번 틀려 잠글 수 있다(정책상 수용, 본인은 복구로 해제). 403은 있는 아이디에서만 나와 아이디 존재가 드러난다.
- 잠겨도 이미 있는 세션은 끊지 않는다.

#### 검증
- 30곳 동시 오답 → 검증 정확히 5번, 401 4개 + 나머지 403/429, 잠김, 맞는 비밀번호도 403. PostgreSQL 같은 결과, 대조군(읽고 나중에 쓰기) 30번 검증.

---

### C-091. 휴대폰 인증번호 구조 + 가입·번호 변경 시 휴대폰 확인

- **날짜:** 2026-11-08
- **분류:** 보안 · DB 스키마 · API
- **상태:** 적용 (실제 문자 발송은 아직 없음, 개발용 문자함)
- **바뀐 파일:**
  - `domains/verification/` (새): `models.py`(`verification_codes`), `sms.py`(발송기·개발용 문자함), `service.py`(`start_verification`, `verify_code`, `consume_verification`, `send_notice`), `router.py`, `dev.py`(`GET /dev/sms`)
  - `users/models.py`(`phone_verified_at`), `users/schemas.py`·`service.py`(가입·번호 변경 증표)
  - `core/config.py`(`sms_sender: Literal["dev"]`), 마이그레이션 `6b7c8d9e0f1a`
  - `tests/test_verification.py`(새), `tests/verification_helpers.py`, `tests/conftest.py`(가입 자동 인증 `auto_phone_verification`)

#### 변경 후
- `POST /verification/phone/send`(SIGNUP_PHONE), `/send-for-me` 🔒(CHANGE_PHONE, ACCOUNT_PASSWORD_RESET), `/verify` → 10분짜리 증표.
- 6자리, 10분, 5회, 1회성. 저장은 **HMAC-SHA256(서버 키, id + 코드)**(6자리는 경우의 수가 100만이라 그냥 해시면 DB 유출 시 역산됨). 틀린 시도는 비교 전에 먼저 셈.
- 1회성은 DB 조건 UPDATE(`consumed_at IS NULL`)로 보장, 용도·번호·사용자는 DB 행으로 판정.
- 발송 제한: 같은 번호 15분 3번(DB, PostgreSQL advisory lock으로 동시 요청 직렬화), IP 15분 10번.
- 가입은 `phone_verification_token` 필수, 내 정보에서 번호를 바꿀 때만 증표 필요(없으면 400 `PHONE_VERIFICATION_REQUIRED`).

#### 이유
- 복구 문자를 보낼 번호가 진짜 그 사람 것이어야 한다(NIST: 미리 검증한 주소만 복구에 사용). 실제 문자 업체 계약이 없어 발송기만 바꿔 끼우는 구조로.

#### 영향 범위
- 기존 사용자는 `phone_verified_at`이 NULL(복구 자체가 그 번호로 인증번호를 받는 과정이라 동작에 문제 없음).
- 테스트의 모든 가입은 conftest가 자동 인증(약관 자동 첨부와 같은 방식, 끌 수 있음).

#### 검증
- 발송·확인·만료·5회·1회성·용도 불일치·HMAC 저장·발송 제한(재시작 유지). PostgreSQL에서 같은 번호 동시 8번 → 3번만 발송.

---

### C-092. 계좌 비밀번호 (숫자 4자리, 돈이 나가는 곳 전부, 5회 잠금)

- **날짜:** 2026-11-08
- **분류:** 보안 · DB 스키마 · API
- **상태:** 적용
- **바뀐 파일:**
  - `accounts/password.py` (새: `validate_account_password_format`, `check_account_password`, `verify_account_password`, `set_account_password`, `reset_account_password`), `accounts/models.py`(`AccountPasswordMixin`), `schemas.py`, `service.py`, `router.py`(`POST /accounts/{type}/{id}/password`), `dev.py`
  - `transfers/`, `cards/`(청구서 납부 `BillPaymentCreate`), `agent/`(확인 본문 `DraftConfirmRequest`, 프롬프트에 "비밀번호를 대화로 묻지 말 것", `TransferAction.from_account_id`)
  - 마이그레이션 `5a6b7c8d9e0f`, `tests/test_account_password.py`(새), `tests/conftest.py`(`auto_account_password`)
  - `scripts/_common.py`·PG 스크립트 5개(계좌 비밀번호 반영), `scripts/pg_account_password_concurrency.py`(새)

#### 변경 후
- 계좌 3종 개설에 필수 `account_password`(숫자 4자리, 동일·연속 숫자 금지). 예금은 추가로 `from_account_password`(출금 계좌).
- 필수 `account_password`: `POST /transfers`, `/transfers/savings`, 해지, 카드 청구서 납부, AI 이체 확인. 체크카드 결제는 제외(카드 PIN 영역).
- 400 `ACCOUNT_PASSWORD_INCORRECT`(N/5) → 5번째 403 `ACCOUNT_PASSWORD_LOCKED`. 400 `ACCOUNT_PASSWORD_NOT_SET`(기존 계좌).
- **그 계좌 행만 잠그고 비밀번호만 검사하는 짧은 트랜잭션을 먼저 커밋**한 뒤, 맞을 때만 본 작업. 실패 횟수가 본 작업 롤백에 휩쓸려 사라지지 않게(사라지면 무한 대입 가능).
- 계좌 응답에 `password_set`, `password_locked`. 설정·재설정은 로그인 + 휴대폰 인증번호(ACCOUNT_PASSWORD_RESET).

#### 이유
- 사용자 결정(은행형 복구의 "아는 것" + 이체 시에도 요구). 감독규정 제33조 ②항 1·3호.

#### 영향 범위
- **하위 호환이 깨진다:** 계좌 개설·돈이 나가는 모든 요청에 새 필수 필드. 기존 계좌는 비밀번호를 먼저 설정해야 돈을 보낼 수 있다.
- 돈이 나가는 요청마다 짧은 트랜잭션 + argon2 약 50ms 추가. 검증과 본 작업 사이에 다른 요청이 계좌를 잠가도 이미 통과한 요청은 진행(맞는 비밀번호를 알아야만 통과하므로 대입엔 못 씀).
- 계좌번호를 아는 사람은 틀린 비밀번호로 계좌를 잠글 수 있다(로그인 잠금과 같은 대가, 본인은 로그인 + 휴대폰으로 해제).

#### 검증
- 형식 규칙, 6곳 각각 N/5·잠금·잠긴 뒤 맞는 비밀번호도 403·성공 시 0, **실패 횟수가 DB에 남는지**. PostgreSQL: 틀린 비밀번호 이체 20개 동시 → 검증 정확히 5번 → 잠김, 대조군 20번. 기존 PG 스크립트 11개 모두 계좌 비밀번호 반영 후 통과.

---

### C-093. 계정 복구: 아이디 찾기·비밀번호 찾기·계좌 비밀번호 재설정

- **날짜:** 2026-11-08
- **분류:** 보안 · API
- **상태:** 적용. 설계 근거는 `docs/ACCOUNT_RECOVERY_RESEARCH.md`
- **바뀐 파일:**
  - `domains/recovery/` (새: `router.py`, `service.py`), `verification/router.py`(send-for-me의 ACCOUNT_PASSWORD_RESET, phone 생략), `accounts/repository.py`(`lock_checking_by_account_num`), `main.py`
  - `tests/test_recovery.py`(새)

#### 변경 후
- `POST /recovery/start` `{purpose, login_id?, account_num, account_password}` → **항상 같은 200**(같은 문구·같은 모양·비슷한 응답 시간). 맞을 때만 등록 휴대폰으로 인증번호. 틀린 계좌 비밀번호는 그 계좌의 실패 횟수로 셈. 번호당 발송 제한에 걸려도 같은 200(문자만 안 보냄).
- `recovery_token`은 `ref = vid XOR HMAC(서버 키, nonce)`로 봉인한 JWT라 진짜·가짜가 구별되지 않는다. 가짜 토큰의 인증번호 오류도 진짜와 같이 (1/5)…(5/5) 후 만료(가짜 횟수는 메모리 — `ponytail:` 표시).
- `POST /recovery/verify`: 아이디 찾기는 `masked_login_id`(앞 2자 + 끝 1자) + 전체 아이디 문자, 비밀번호 찾기는 `reset_token`.
- `POST /recovery/password`: 1회성 소비, 가입 규칙·아이디와 다름·현재와 다름(`SAME_PASSWORD`). 성공하면 **잠금 해제·실패 0·모든 세션 폐기·알림 문자·자동 로그인 없음**. 만료·사용된 증표는 400 `INVALID_VERIFICATION_TOKEN`.
- 계좌 비밀번호 설정·재설정: `POST /accounts/{type}/{id}/password` 🔒 `{phone_verification_token, new_account_password}`(처음 설정 겸용, 잠금 해제 포함, 알림 문자).
- 계좌가 없거나 두 비밀번호를 모두 잊으면 온라인 복구 불가 → 관리자 명령(고객센터 흉내).

#### 이유
- 조사 결과: 국내 은행은 계좌 + 휴대폰 두 요소, NIST는 이메일 단독 인증 금지·복구 알림 필수, OWASP는 응답 동일화·자동 로그인 금지·세션 무효화.

#### 영향 범위
- 정보가 맞는 경로는 사용자 조회·발송 트랜잭션만큼 몇 ms 더 걸린다(argon2 약 70ms보다 훨씬 작음).
- 정상 사용자가 15분에 3번을 넘기면 문자 없이 같은 문구만 본다 → 화면 문구에 "문자가 오지 않으면 15분 뒤 다시"를 넣음.
- `reset_token`(verification 증표) 본문에 등록 휴대폰·사용자 번호가 보인다(이미 세 요소를 증명한 뒤라 수용).

#### 검증
- 테스트 13개(응답 동일성: 계좌 없음·비밀번호 틀림·잠김·미설정 모두 같은 응답, 가짜 토큰 오류 6개 동일, 1회성, 잠금 해제 전체 흐름, 세션 폐기, 남의 아이디+내 계좌 실패 등). 전체 pytest 통과.
- 브라우저: 휴대폰 인증 가입 → 계좌 개설(계좌 비밀번호, 연속 숫자 거부) → 이체(1/5 후 성공) → 5회 오류로 잠김(맞는 비밀번호도 거절, "비밀번호 찾기" 안내) → 비밀번호 찾기(개발용 문자함으로 인증번호) → 재설정 → 알림 문자, 새 비밀번호로 로그인, 옛 비밀번호 401. 아이디 찾기 → `re*******1` + 전체 아이디 문자, 틀린 계좌 비밀번호와 응답 문구·토큰 길이 동일.

#### 팀 논의 포인트
- 실제 문자 업체(솔라피·NHN Cloud 등) 연동 시점. 가짜 토큰 횟수·IP 한도는 프로세스 메모리(서버 여러 대면 공유 저장소).

---

### C-094. 화면: 휴대폰 인증·계좌 비밀번호·아이디/비밀번호 찾기·해지

- **날짜:** 2026-11-08
- **분류:** 구조 (프론트)
- **상태:** 적용 (브라우저에서 주요 흐름 확인)
- **바뀐 파일:**
  - `frontend/components/verify.tsx` (새: `CodeVerify`, `PhoneVerify`, 개발용 문자함), `components/account-password.tsx` (새: 4자리 입력, 규칙 검사, 오류별 안내 링크 `MoneyErrorText`)
  - `frontend/app/find-id/page.tsx`, `app/reset-password/page.tsx` (새)
  - `app/login`(잠김 안내 + 비밀번호 찾기, 아이디·비밀번호 찾기 링크, `reason=reset`), `app/signup`(휴대폰 인증), `app/me`(번호 변경 인증), `app/open/...`(계좌 비밀번호·출금 계좌 비밀번호), `app/transfer`, `app/accounts/[type]/[id]`(적금 납입, **해지 화면 신설**, 계좌 비밀번호 설정·재설정), `app/cards/[type]/[id]`(청구서 납부), `components/assistant/TransferCard.tsx`, `lib/api.ts`

#### 변경 후
- 가입: 번호 → 인증번호 → 확인해야 가입 버튼이 켜짐(번호를 바꾸면 다시 인증). 내 정보: 번호를 바꿀 때만 인증.
- 인증번호 입력칸 옆 **"개발용 문자함 보기"**(개발 모드에서만 나타남).
- 계좌 비밀번호 입력은 6곳 모두, 오류별 안내(미설정 → 설정, 잠김 → 휴대폰 인증 후 재설정, 틀림 → N/5). 계좌 비밀번호는 입력값 보존(sessionStorage 초안)에 넣지 않는다.
- 계좌 상세의 "계좌 비밀번호 설정/재설정"(휴대폰 인증 → 새 비밀번호 + 확인), 오류 링크로 들어오면 자동으로 펼침.
- 아이디 찾기·비밀번호 찾기 화면, 하단에 "입출금 계좌가 없으시면 고객센터로 문의".

#### 검증
- `npx tsc --noEmit`, `npx eslint` 에러 0. 브라우저 확인은 C-093 검증 참고.
- **하지 않은 것:** 번호 변경 인증, 해지 화면, 카드대금 납부, AI 이체 확인 카드의 계좌 비밀번호 입력은 브라우저로 직접 눌러 보지 않았다(코드·테스트만).

---

### C-095. 회원 탈퇴 (소프트 삭제, 계좌 닫기, 입금 경합 차단)

- **날짜:** 2026-11-09
- **분류:** 보안 · DB 스키마 · API · 동시성
- **상태:** 적용 (개발 DB에 마이그레이션 적용, 브라우저에서 확인)
- **바뀐 파일:**
  - `users/withdrawal.py` (새: 조건 검사·처리), `users/models.py`(`deleted_at`, 폐기 이유 `WITHDRAWN`), `users/schemas.py`·`router.py`·`service.py`·`repository.py`
  - `verification/models.py`·`router.py`(purpose `WITHDRAWAL`, 등록 번호로만 발송), `recovery/service.py`(탈퇴 회원 제외)
  - `accounts/models.py`(`CheckingAccount.closed_at`), `accounts/repository.py`·`service.py`(`require_open`), `transfers/service.py`, `cards/service.py`, `accounts/dev.py`
  - 마이그레이션 `2026_11_08_1800-8d9e0f1a2b3c_add_withdrawal.py`
  - `frontend/app/me/page.tsx`(탈퇴 영역), `frontend/app/login/page.tsx`(`reason=withdrawn`)
  - `tests/test_withdrawal.py`(새), `scripts/pg_withdrawal_concurrency.py`(새), `scripts/README.md`

#### 변경 전
- 회원 탈퇴 기능이 없었다.

#### 변경 후
- `GET /users/me/withdrawal` 🔒 → `{can_withdraw, blockers}`. 막는 사유: 해지하지 않은 예금(`ACTIVE_DEPOSIT`)·적금(`ACTIVE_SAVINGS`), 잔액이 남은 입출금 계좌(`CHECKING_BALANCE`), 신용카드 미결제(`CARD_UNPAID`, `outstanding_amount > 0`).
- `POST /users/me/withdrawal` 🔒 `{current_password, phone_verification_token}`(purpose `WITHDRAWAL`). 비밀번호는 로그인 실패 카운터와 같은 규칙(선증가, 5회 잠금). 조건 불충족은 400 `WITHDRAWAL_BLOCKED`.
- 처리(한 트랜잭션, users 행 → 입출금 계좌 ID 오름차순 → 예금·적금 → 카드 순으로 잠근 뒤 조건 재검사):
  - **가림:** `deleted_at`, 이름 "탈퇴회원", 닉네임·`phone_verified_at` NULL, 전화 빈 문자열, 비밀번호 해시는 어떤 비밀번호로도 맞지 않는 값. **`login_id`는 유지**해 재가입을 막는다(409 문구는 기존 그대로라 탈퇴한 아이디임이 드러나지 않음).
  - **닫음:** 입출금 계좌 `closed_at`, 카드 전부 `CLOSED`.
  - **폐기·삭제:** 갱신 토큰 전부(`WITHDRAWN`), AI 대화·메시지·이체 초안, 그 사용자의 인증번호 행.
  - **보존:** 계좌·거래내역·카드 사용내역·청구서·약관 동의 기록(전자금융 거래 기록 보존 의무 — 보존 기간은 법 확인 필요).
- 탈퇴 후: 로그인은 없는 아이디와 같은 401(가짜 해시, 실패도 세지 않음), 기존 토큰 즉시 401, 아이디·비밀번호 찾기는 없는 계좌와 같은 응답, **남이 그 계좌로 이체하면 없는 계좌와 같은 404**.
- 화면: 내 정보 맨 아래 "회원 탈퇴" — 막는 사유와 처리 링크(해지·이체·납부), 지워지는 것·보존되는 것·재가입 불가 안내, 현재 비밀번호 + 휴대폰 인증 + 최종 확인 → `/login?reason=withdrawn`. 저장된 토큰은 로그인 화면이 지운다(내 정보 화면에서 먼저 지우면 세션 타이머가 "다른 탭 로그아웃"으로 오해해 탈퇴 안내 없이 이동하기 때문).

#### 이유
- 사용자 결정(제안한 정책대로: 잔액 0·계좌 해지·카드 미결제 없음, 비밀번호 + 휴대폰 재확인, 소프트 삭제, 재가입 막기).
- **입금 경합:** 탈퇴가 "잔액 0"을 확인한 직후 남의 입금이 들어오면 "탈퇴했는데 돈이 남는" 계좌가 생긴다. 탈퇴와 이체가 같은 입출금 계좌 행을 `FOR UPDATE`로 잠그고, 이체는 잠근 뒤 `closed_at`을 확인(`require_open`)해서 한 줄로 세운다. 이체가 먼저면 탈퇴가 막히고, 탈퇴가 먼저면 이체가 404.

#### 영향 범위
- 이체·적금 납입·예금 가입 출금·해지금 입금·체크카드 결제·청구서 납부·개발용 충전이 잠근 뒤 `require_open`을 거친다.
- 탈퇴와 같은 순간 본인이 새 계좌를 여는 경우는 막지 못한다(개설은 users 행을 잠그지 않음, 잔액 0). 같은 사용자의 계좌 비밀번호 재설정과 탈퇴가 동시에 오면 드물게 PG 데드락 감지로 한쪽이 실패할 수 있다.
- 마이그레이션을 되돌리면 탈퇴 표시만 사라지고 가려진 정보는 돌아오지 않는다.

#### 검증
- `tests/test_withdrawal.py` 7개(조건별 막힘·사유 목록, 비밀번호 5회 잠금, 증표 거절, 성공 후 가림·재가입 409·로그인 401·토큰 401·대화 삭제·기록 보존·계좌 닫힘·카드 해지·남의 이체 404·찾기 실패). 전체 422개 통과(3 skip).
- **PostgreSQL** `pg_withdrawal_concurrency.py`: 탈퇴(잔액 0) ↔ 남의 1,000원 이체 20라운드 동시 → "탈퇴했는데 돈이 남음" 0번(탈퇴 성공·이체 404 19번, 탈퇴 막힘·이체 성공 1번). 잠금을 뺀 대조군은 20번 모두 돈이 남음. 기존 PG 스크립트 11개도 다시 통과.
- 브라우저: 잔액 1,000원 계좌가 있으면 "잔액이 남은 입출금 계좌가 있습니다: 110-…(1,000원)" + 이체 링크 → 잔액을 보낸 뒤 휴대폰 인증·비밀번호로 탈퇴 → 로그인 화면 안내, 토큰 삭제, 같은 아이디 로그인은 없는 아이디와 같은 401.

#### 팀 논의 포인트
- 거래 기록 보존 기간(전자금융거래법 기준 5년으로 알려짐)과 기간 뒤 파기 작업, 탈퇴 회원 개인정보를 얼마나 남겨야 하는지(실명 확인 등)는 법 확인이 필요하다. 상대방 거래내역의 `counterpart_name`(탈퇴 회원 실명)은 상대의 기록이라 그대로 둔다.
- 관리자 탈퇴 명령(고객센터 경로)은 정책이 정해지지 않아 만들지 않았다.

---

### C-096. 토큰 쿠키 전환 + 기기 등록

- **날짜:** 2026-11-09
- **분류:** 보안 · DB 스키마 · API · 구조
- **상태:** 적용 (기기 해제 버튼 동작·build는 미확인)
- **바뀐 파일:**
  - `core/cookies.py`(새: 쿠키 설정·삭제, Origin 확인), `core/config.py`·`security.py`·`exception_handlers.py`
  - `users/models.py`(`UserDevice`, 사용자 컬럼 추가)·`schemas.py`·`router.py`·`service.py`·`repository.py`·`withdrawal.py`, `verification/models.py`(purpose `NEW_DEVICE`)
  - 마이그레이션 `2026_11_09_1000-9e0f1a2b3c4d_add_user_devices.py`
  - `frontend/lib/api.ts`, `frontend/next.config.ts`(rewrites), `frontend/app/login`·`signup`·`me`, `.env.example`·`.env.prod.example`·`frontend/.env.example`(`API_ORIGIN`)
  - `seed_demo.py`, `tests/`(`test_devices.py`·`cookie_helpers.py` 새, 기존 인증 테스트 수정), `scripts/pg_device_channel_concurrency.py`(새)·`scripts/README.md`

#### 변경 전
- 로그인 응답 본문에 액세스 토큰과 갱신 토큰이 모두 들어 있었고, 브라우저는 둘 다 `localStorage`(`avengers_bank_session`)에 보관했다.
- `POST /users/token/refresh`, `POST /users/logout`은 본문에 갱신 토큰을 받았다.
- 로그인 실패는 사용자 하나에 카운터 하나(`failed_login_count`, `login_locked_at`)였다. 남이 5번 틀리면 주인도 잠겼다(C-090).
- 기기 개념이 없었다. 비밀번호만 맞으면 어디서든 로그인됐다.

#### 변경 후
**1. 토큰 쿠키 전환**
- 갱신 토큰: `Set-Cookie: refresh_token=…; HttpOnly; Secure; SameSite=Strict; Path=/api/users`. **JSON 본문에는 더 이상 없다.** `refresh`·`logout`은 본문 없이 쿠키만 읽는다.
- 액세스 토큰: 응답 본문으로 받아 **프론트 메모리(변수)에만** 둔다. 페이지를 새로고침하면 사라지고, 쿠키로 조용히 갱신해 다시 받는다.
- `localStorage`에는 `session_expires_at`(비밀 아님)만 남긴다. 여러 탭의 타이머·로그아웃 동기화용이다.
- `next.config.ts` rewrites가 `/api/*`를 FastAPI(서버 환경변수 `API_ORIGIN`)로 프록시한다. 브라우저에는 프론트와 **같은 주소**로 보이므로 쿠키가 first-party다.
- 쿠키를 쓰는 엔드포인트(갱신·로그아웃·기기)는 **`Origin` 헤더를 필수로 확인**한다(`cors_origins`에 있어야 통과, 없거나 다르면 403 `CSRF_ORIGIN`. 적용: 갱신·로그아웃·기기 해제).
- 여러 탭의 갱신을 한 번에 하나씩 하는 Web Locks와 같은 탭의 single-flight는 유지한다.

**2. 기기 등록(B1)**
- `user_devices`: `device_id`, `user_id`, `token_hash`(256비트 임의값의 SHA-256, unique), `label`(User-Agent에서 만든 "Chrome · Windows" 같은 이름), `created_at`, `last_used_at`, `revoked_at`.
- 기기 쿠키 `device_token`: 1년, httpOnly·Secure·SameSite=Strict, Path=/api/users.
- 로그인은 채널이 둘이다.
  | | 등록된 기기 | 새 기기 |
  |---|---|---|
  | 조건 | 유효한 기기 쿠키 + 비밀번호 | 기기 쿠키 없음·무효 |
  | 절차 | 바로 로그인 | 비밀번호 → 휴대폰 인증번호(purpose `NEW_DEVICE`) → 로그인하며 기기 등록 |
  | 실패 카운터 | `device_failed_login_count`, `device_login_locked_at` | `failed_login_count`, `login_locked_at`(기존 컬럼) |
  | 한도 | 5회 연속 오류 → 잠금 | 5회 연속 오류 → 잠금 |
- 새 기기 로그인 API: `POST /users/login`이 비밀번호가 맞고 새 기기면 로그인 대신 **챌린지 토큰**을 준다 → `POST /users/login/device/send`(챌린지로 등록 번호에 인증번호 발송) → `POST /users/login/device`(챌린지 + 인증번호 → 세션과 기기 쿠키 발급).
- 내 정보: 기기 목록(이름·마지막 사용·이 기기 표시)과 해제.
- **비밀번호 재설정(복구)과 회원 탈퇴는 모든 기기를 해제**한다. 비밀번호 변경은 기기를 **유지**한다(본인이 현재 비밀번호를 알고 바꾸는 것이므로, 기기까지 지우면 매번 문자 인증이 필요해 불편하기만 하다).
- 단일 세션 규칙(다른 곳에서 로그인하면 기존 세션 종료)은 그대로다.

**3. 구현에서 정해진 세부 (최종 API 계약)**
| 엔드포인트 | 요청 | 응답 · 쿠키 · 오류 |
|---|---|---|
| `POST /users/login` | `{login_id, password}` (+ 기기 쿠키) | `LoginOk`(`TokenResponse` + `status:"OK"`, refresh 쿠키) 또는 `DeviceChallenge`(`status:"DEVICE_VERIFICATION_REQUIRED"`, `challenge_token`, `phone_masked`; 쿠키·세션 없음). 401 `INVALID_CREDENTIALS`, 403 `ACCOUNT_LOCKED`, 429 `TOO_MANY_LOGIN_ATTEMPTS` |
| `POST /users/login/device/send` | `{challenge_token}` | `{verification_id, expires_in}`(`send-for-me`와 같은 모양·같은 발송 한도). 등록 번호로만 발송. 401 `INVALID_DEVICE_CHALLENGE` |
| `POST /users/login/device` | `{challenge_token, phone_verification_token}` | `LoginOk` + refresh·기기 쿠키. 400 `INVALID_VERIFICATION_TOKEN`, 401 `INVALID_DEVICE_CHALLENGE`, 403 `ACCOUNT_LOCKED`(새 기기 채널 잠김). 증표 소비·다른 세션 폐기·기기 등록·토큰 발급이 **한 트랜잭션** |
| `POST /users/token/refresh` | 본문 없음 | 새 refresh 쿠키. 쿠키 없음 401 `INVALID_REFRESH_TOKEN`. 세션이 죽은 401(`INVALID_REFRESH_TOKEN`·`REFRESH_TOKEN_REUSED`·`SESSION_REPLACED`)에는 쿠키 삭제(`Max-Age=0`)가 함께 간다. Origin 확인 |
| `POST /users/logout` | 본문 없음 | 항상 200, refresh 쿠키 삭제(기기 쿠키는 유지). Origin 확인이 먼저라 Origin이 없으면 403 |
| `GET /users/me/devices` | Bearer | `[{device_id, label, created_at, last_used_at, current}]`(해제 안 된 것만, 최근 사용순) |
| `DELETE /users/me/devices/{id}` | Bearer + Origin | 남의·없는·이미 해제된 기기 404 `DEVICE_NOT_FOUND`. 현재 기기면 기기 쿠키 삭제. 세션은 유지 |

- 설정: `cookie_secure`(기본 True), `refresh_cookie_path`(기본 `/api/users`), `device_cookie_days`(기본 365). **기기 쿠키도 `refresh_cookie_path`를 같이 쓴다**(따로 설정 없음). 기기 쿠키의 1년은 발급 때 정해지고 사용할 때마다 늘어나지 않는다(등록 기기 로그인은 쿠키를 새로 주지 않는다).
- **채널 판정은 비밀번호 검증 *전에*** 한다: 요청의 기기 쿠키가 로그인 대상 사용자의 해제 안 된 기기와 일치하면 등록 기기, 아니면 새 기기. 선증가(`count_login_attempt`)와 `lock_login`은 `device` 인자만 더했고 로직은 하나다. 성공은 해당 채널만 0으로 만든다. 새 기기에서 비밀번호가 맞으면 새 기기 카운터를 0으로 하고 챌린지를 준다.
- **비밀번호 변경·회원 탈퇴**의 현재 비밀번호 확인도 요청의 기기 쿠키로 채널을 정해 센다(`withdraw(..., raw_device_token)`). 탈퇴는 성공 시 두 쿠키를 모두 지우고 기기를 전부 해제한다.
- **챌린지 1회성:** 챌린지 JWT 자체는 10분 안에 다시 쓸 수 있다. 1회성은 `NEW_DEVICE` 인증 행의 `consumed_at`(조건 UPDATE 한 문장)이 보장한다. 같은 증표는 두 번 못 쓰고, 기기를 등록할 때마다 새 문자 인증이 필요하다. 챌린지 저장소(jti)는 만들지 않았다.
- 운영 코드에 "기기 인증 건너뛰기" 설정은 없다. 테스트는 `BankClient.post`가 `/users/login`에서 챌린지를 받으면 실제 경로(send → 개발용 문자함 → verify → `/login/device`)로 자동 인증한다(`auto_device_verification`). 테스트 환경에서만 `COOKIE_SECURE=false`, `REFRESH_COOKIE_PATH=/users`를 둔다(http·프록시 없음).
- `seed_demo.py`는 새 기기 챌린지를 `010-1234-5678` 개발용 문자함으로 자동 인증한다(기존 아이디의 번호가 다르면 실패, 실행마다 기기 1개 등록). PG 스크립트는 기기를 `register_device_sql`로 SQL 직접 등록한다(번호당 3회 발송 한도 때문에 실제 흐름으로는 기기를 여러 개 준비할 수 없다).

#### 이유
- **XSS와 토큰:** `localStorage`의 토큰은 페이지에서 실행되는 어떤 스크립트든 읽어서 밖으로 보낼 수 있다. 훔친 갱신 토큰은 공격자 PC에서 30분 넘게 이어 쓸 수 있다. `httpOnly` 쿠키와 메모리 보관으로 바꾸면 스크립트가 **읽을 수 없는 토큰은 훔칠 수 없다.**
  - **한계(정직하게):** XSS가 페이지에서 실행되는 동안에는 그 스크립트가 **사용자인 척 API를 호출**할 수 있다(브라우저가 쿠키를 알아서 붙인다). 쿠키 전환은 "토큰을 들고 나가 나중에 쓰는 것"을 막을 뿐, XSS 자체의 해를 없애지 않는다. 그래서 이체 때 계좌 비밀번호·휴대폰 인증을 다시 받는 기존 방어가 여전히 중요하다.
- **프록시:** 프론트(예: `app.example.com`)와 API(`api.example.com`)가 다르면 쿠키가 제3자 쿠키가 되어 브라우저가 막는다. 같은 주소로 프록시하면 쿠키가 정상이고, 프론트를 어디에 배포하든 API 주소를 바꿀 필요가 없다.
- **CSRF(쿠키는 브라우저가 알아서 붙이므로 새로 생긴 위험):** 겹쳐서 막는다.
  - `SameSite=Strict`: 다른 사이트에서 시작한 요청에는 쿠키를 붙이지 않는다. 가장 강한 방어다.
  - 쿠키 `Path=/api/users`: 다른 API 경로에는 쿠키가 아예 가지 않는다.
  - `Origin` 확인: 브라우저 버전·설정 차이나 SameSite 우회 사례가 있어도, 서버가 **요청을 보낸 사이트가 허용 목록에 있는지** 직접 본다. **Strict와 Origin을 함께 쓰는 이유:** 하나는 브라우저가 지켜 주는 약속이고 하나는 서버가 직접 하는 검사라서, 한쪽이 뚫리거나 설정이 틀려도 다른 쪽이 남는다. Origin을 필수(없으면 거절)로 한 것은 "헤더를 지우면 통과"하는 구멍을 없애기 위해서다.
  - 액세스 토큰은 `Authorization` 헤더로만 가므로 쿠키를 쓰지 않는 일반 API는 CSRF 대상이 아니다.
- **Web Locks를 유지하는 이유:** 갱신 토큰을 한 번 쓰면 폐기되고 재사용하면 세션이 끊긴다(AUTH.md 4장). 이제는 브라우저가 **항상 현재 쿠키를 보낸다**. 그래서 갱신이 *순차*로 일어나면(탭 A가 갱신하고, 그다음 탭 B가 갱신) B도 새 쿠키를 보내므로 문제없다. 위험한 건 *동시*에 두 탭이 같은 옛 쿠키를 보내는 경우뿐이고, 이것을 Web Locks가 막는다. 예전처럼 "내가 쓴 토큰이 저장소에 있는 것과 다른가" 확인할 필요는 없어졌다(토큰이 JS에 없으므로).
- **기기 등록:** 아이디만 알면 5번 틀려 잠글 수 있는 문제(AUTH.md 6-1·9-3의 한계)를, 주인이 평소 쓰는 기기에는 영향이 없게 해서 줄인다. 또 비밀번호만 유출돼도 **모르는 기기에서는 휴대폰 인증이 한 번 더** 필요하다.
- **규정 해석(팀 확인 필요):** 전자금융감독규정은 "5회 이내 오류 시 거래 중지"를 요구한다. 이를 **채널별로 적용**한다고 해석했다. 공격자는 새 기기 채널만 잠글 수 있고, 주인은 등록된 기기에서 계속 로그인하거나 복구로 푼다. 사용자 하나에 카운터 하나인 구조라면 공격자가 주인을 완전히 막는다. 이 해석이 규정의 취지에 맞는지는 확인이 필요하다.
- AUTH.md 6-1의 "다음 단계(B)"(믿을 수 있는 기기 예외)가 이것으로 해결된다. 단 방식은 "제한 면제"가 아니라 "카운터 분리"다.

#### 영향 범위
- **API 계약이 바뀐다:** 로그인·갱신 응답에서 `refresh_token`이 사라지고, 갱신·로그아웃은 본문을 받지 않는다. 프론트와 테스트(`cookie_helpers.py`)를 같이 바꿨다. 다른 클라이언트가 있다면 쿠키 저장소를 지원해야 한다.
- 프론트는 이제 **Next.js 서버(프록시)를 거친다.** `API_ORIGIN`을 서버 환경변수로 설정해야 하고, 프록시가 죽으면 API도 안 닿는다. 개발에서 Swagger(`:8000`)는 그대로 쓸 수 있다.
- 마이그레이션: `user_devices` 테이블, `users`에 `device_failed_login_count`·`device_login_locked_at`, 인증 purpose `NEW_DEVICE`. 되돌리면 등록된 기기가 모두 사라져 다음 로그인에 휴대폰 인증이 필요하다.
- **기존 사용자는 모두 새 기기로 처음 한 번 휴대폰 인증을 거친다.** `users.phone`은 필수 컬럼이라 인증 대상 번호는 항상 있다(가입 전 `phone_verified_at`이 비어 있어도 등록 번호로 보낸다).
- 복구(비밀번호 재설정)·관리자 명령은 두 채널의 잠금을 모두 풀고 기기를 전부 해제한다. 브라우저에 남은 옛 `avengers_bank_session`(토큰 포함)은 따로 지우지 않는다: 다음 로그인·로그아웃이 덮어쓰거나 지우며, 옛 갱신 토큰은 서버에서 최대 30분 뒤 만료된다.
- 돈이 움직이는 코드는 건드리지 않았다. 사용자 행 잠금 순서(users → 토큰·기기)는 같다.
- 개발 환경: 개발 `.env`에 `COOKIE_SECURE`가 없으면 기본 True다(`localhost`의 Chrome은 http에서도 받는다). Safari 등은 `COOKIE_SECURE=false`가 필요하다(`.env.example`에 안내).

#### 검증
- 전체 pytest `453 passed, 3 skipped`(기존 422, 2026-11-09, 직접 재실행).
- PostgreSQL 스크립트 5개 통과: `pg_device_channel_concurrency`(30곳 동시 오답 → 검증 정확히 5번, 등록 기기 채널만 잠김·새 기기는 영향 없음, 대조군 30번), `pg_refresh_concurrency`, `pg_single_session_concurrency`, `pg_login_lock_concurrency`, `pg_deposit_open_concurrency`.
- 브라우저(프록시 경유): 새 기기 로그인 → 인증번호 → 로그인, `document.cookie` 비어 있음, localStorage에 `session_expires_at`만, 새로고침 뒤 `token/refresh` 200으로 로그인 유지, 로그아웃 뒤 갱신 401, 같은 브라우저 재로그인은 인증번호 없이 통과, 내 정보에 기기 목록 표시.
- 미확인: 기기 해제 버튼 동작, 프록시가 낡은 8000번 서버를 가리키던 개발 환경 정리(낡은 API 서버를 내리고 새 코드로 다시 띄워 확인함), `npm run build`(`/find-id`의 `Date.now` 오류, 이번 변경 파일 아님).

#### 팀 논의 포인트
- **`Secure` 쿠키와 http:** `localhost`는 브라우저가 예외로 허용하지만 **Safari는 http에서 Secure 쿠키를 저장하지 않는다.** 개발·시연은 Chrome 또는 HTTPS로 한다. 운영은 HTTPS 전제다.
- **기기 쿠키를 잃으면:** 시크릿 창, 쿠키 삭제, 브라우저 변경 → 새 기기로 보고 휴대폰 인증을 다시 받는다(불편하지만 안전한 쪽).
- **기기를 도난당한 경우:** 기기 쿠키만으로는 로그인되지 않는다(비밀번호도 필요). 둘을 모두 가진 공격자는 등록 기기 채널로 문자 없이 들어올 수 있다. 주인이 내 정보에서 기기를 해제하거나 비밀번호를 재설정(모든 기기 해제)해야 한다.
- **공용 PC:** "이 기기 등록 안 함" 선택이 아직 없다. 새 기기 로그인을 통과하면 무조건 1년짜리가 등록된다. 공용 PC에서 쓴 사람이 해제하지 않으면 다음 사람이 비밀번호만으로 들어올 수 있다는 뜻이다. 선택 옵션을 둘지 정해야 한다.
- **비밀번호를 아는 공격자의 문자 발송:** 비밀번호를 알면 새 기기 로그인 단계에서 주인에게 인증번호 문자를 계속 보낼 수 있다. 발송 제한(번호당 15분 3번, IP 15분 10번)으로 묶었지만 주인이 문자를 받는 불편은 남는다.
- **기기 개수·정리:** 기기 등록 개수 상한과 오래된 기기 정리가 없다. 같은 브라우저가 쿠키를 잃고 다시 등록하면 옛 행이 목록에 남는다. 상한(예: 10개)과 자동 정리를 둘지 정해야 한다.
- **챌린지 JWT 재사용:** 10분 안에는 같은 챌린지로 문자를 다시 보낼 수 있다(발송 한도로 묶임). 인증 증표가 1회용이라 기기 등록은 문자 인증마다 한 번뿐이다. 챌린지 자체를 1회용으로(jti 저장) 할지는 필요해지면.
- **잠금 해석:** 위 "규정 해석"이 맞는지, 공격자가 새 기기 채널을 잠글 수 있는 점(주인이 새 기기에서 쓰려면 복구 필요)을 받아들일지.
- **XSS 한계:** 쿠키 전환은 토큰 탈취만 막는다. 페이지가 열려 있는 동안의 대리 요청은 막지 못한다(CSP 같은 XSS 자체 방어는 별도 과제).
- **갱신 쿠키 `Path=/api/users`가 `/api/users/*` 전체**에 간다. 갱신·로그아웃만이 아니라 `/api/users/me` 등에도 쿠키가 붙는다. 해당 엔드포인트들은 쿠키를 읽지 않지만, 경로를 `/api/users/token`·`/api/users/logout`처럼 더 좁히려면 API 주소 구조를 바꿔야 한다.


### C-097. 새 기기 로그인 화면에서 개발용 문자함이 안 열리던 문제

- **날짜:** 2026-11-09
- **분류:** 구조
- **상태:** 적용
- **바뀐 파일:**
  - `frontend/app/login/page.tsx` (`CodeVerify`의 `devPhone` 제거)

#### 변경 전
```tsx
<CodeVerify devPhone={challenge.phone} ... />
```
`challenge.phone`은 서버가 가려 보낸 번호(`010-****-9999`)다.

#### 변경 후
`devPhone`을 넘기지 않는다. `DevInbox`는 번호가 없으면 입력칸을 보여 주므로, 사용자가 가입한 번호를 직접 입력해 문자함을 연다.

#### 이유
- `DevInbox`는 `PHONE` 정규식을 통과해야 "개발용 문자함 보기" 버튼을 켠다. 가려진 번호는 통과하지 못해 버튼이 항상 비활성이었고, 번호가 주어졌으므로 입력칸도 숨겨졌다.
- 재현: 회원가입 후 새 기기(기기 쿠키 없음)로 로그인하면 인증번호 단계에서 문자함을 열 수 없다.

#### 영향 범위
- 개발 화면만. `/dev/sms`가 없는 운영에서는 `DevInbox` 자체가 숨겨진다. 다른 `devPhone` 사용처(`me`, 계좌 상세)는 실제 번호를 넘기므로 그대로다.

#### 검증
- 브라우저에서 새 기기 로그인 → 번호 입력 → 문자함에 인증번호 표시 → 로그인 성공 확인.

#### 팀 논의 포인트
- 서버가 개발 모드에서만 전체 번호를 같이 주게 할 수도 있지만, 개발용 기능 때문에 응답을 바꾸지 않기로 했다.


### C-098. 계좌 가입 화면 입력값 유지 (계좌 비밀번호 포함, 다른 화면에 갔다 와도)

- **날짜:** 2026-11-09
- **분류:** 구조 · 보안
- **상태:** 적용
- **바뀐 파일:**
  - `frontend/app/open/[kind]/[[...product]]/page.tsx` (`SECRET_FIELDS`·`heldSecrets`, 맡기기 effect, 비밀번호 칸을 `bind`로)

#### 변경 전
- 입력값은 "전문 보기" 링크를 누를 때만(`saveDraft`) sessionStorage에 맡기고, 돌아오면 한 번 꺼낸 뒤 지웠다.
- 계좌 비밀번호(새 비밀번호·확인·예금의 출금 계좌 비밀번호)는 비제어 입력이라 저장되지 않았다 → 약관 전문을 보고 오면 별명은 남고 비밀번호만 비었다.
- 상단 메뉴 등 다른 곳으로 나갔다 오면 아무것도 남지 않았다.

#### 변경 후
- 입력값이 바뀔 때마다 `open-draft:{kind}`에 맡긴다. 화면이 다시 열리면 채우고, **가입에 성공하면 지운다.** 어느 경로로 나갔다 와도 같다.
- 계좌 비밀번호도 상태(`fields`)로 들고 있지만, **sessionStorage에는 쓰지 않고 모듈 변수 `heldSecrets`(메모리)에만** 둔다. 앱 안 이동에는 남고, 새로고침·탭 닫기면 사라진다.
- 주소의 상품이 맡겨 둔 상품과 다르면(상품 목록에서 다른 상품을 골라 들어옴) 주소를 따른다. 약관 동의는 상품·약관 묶음(`set_hash`)이 같을 때만 되살린다(기존 규칙 그대로).
- 아무것도 안 건드린 첫 화면은 맡기지 않는다. 처음 그린 빈 값이 맡겨 둔 값을 덮지 않게 하기 위해서다(React StrictMode의 이중 마운트 포함).

#### 이유
- 사용자 제보: 약관 전문을 보고 돌아오면 입력한 계좌 비밀번호가 사라진다. 다른 곳에 다녀와도 유지되길 원함.
- 비밀번호를 sessionStorage에 두면 같은 탭의 스크립트가 언제든 읽을 수 있고 새로고침 뒤에도 남는다. 메모리에만 두면 React 상태에 있는 것과 노출 범위가 같다.

#### 영향 범위
- 입출금·예금·적금·카드 가입 화면 전부(같은 컴포넌트). 카드는 비밀번호 칸이 없어 일반 입력값만 해당.
- 가입하지 않고 떠나면 같은 탭에서는 다음에 들어올 때 값이 남아 있다(의도). 비밀번호는 메모리라 새로고침하면 사라진다.

#### 검증
- 브라우저(로컬, 테스트 계정)에서 확인:
  - 입출금: 별명·비밀번호·확인·약관 동의 입력 → 전문 보기 → "가입 화면으로" → 모두 남음. sessionStorage에는 별명·동의만 있고 비밀번호는 없음.
  - 예금: 두 번째 상품·가입 금액·두 번째 출금 계좌·만기일·별명·비밀번호 3칸·동의 → 전문 보기 → 돌아옴 → 모두 남음.
  - 적금: 상품·납입액·납입일·별명·비밀번호·동의 → 상단 "상품" 메뉴 → 뒤로 가기 → 모두 남음. 가입 성공 후 `open-draft:savings` 지워짐.
- `tsc --noEmit`, eslint 통과.

#### 팀 논의 포인트
- 떠난 가입 화면의 값을 계속 남길지, 일정 시간이 지나면 지울지.


### C-099. AI 비서 이체: 내 계좌 id를 매 턴 주고, 본인 계좌로는 to_account_id로 이체

- **날짜:** 2026-11-09
- **분류:** API · 구조 · 테스트
- **상태:** 일부 C-100에서 대체 (매 턴 계좌 목록 → 이름으로 찾기. `to_account_id` 방식도 같이 대체됨)
- **바뀐 파일:**
  - `domains/agent/tools/transfers.py` (`PrepareTransferArgs`, `_own_checking_num`, `prepare_transfer`)
  - `domains/agent/prompts.py` (`build_system_prompt`, 이체 규칙), `domains/agent/service.py` (`_checking_accounts`), `domains/agent/tools/__init__.py`(도구 설명)
  - `tests/test_agent.py` (FakeClient가 system 프롬프트를 기록, 테스트 3개 추가)

#### 변경 전
- 첫 질문 "내 계좌 목록"에서 `get_my_accounts` 결과(account_id 포함)를 보고도, 다음 질문의 모델에게는 **글자 답변만** 전달됐다(`_history`는 도구 결과를 저장·복원하지 않는다). 모델은 "이미 봤다"며 `get_my_accounts`를 건너뛰고 `from_account_id`를 짐작해 넣었고 `FROM_ACCOUNT_NOT_FOUND`로 실패했다.
- `prepare_transfer`는 받는 계좌를 **전체 번호(`to_account_num`)로만** 받았다. 도구가 마스킹된 번호만 주므로 "생활비 계좌로"처럼 본인 계좌를 가리켜도 모델이 번호를 만들 수 없었다.
- 오류가 나도 모델이 오류 문구를 그대로 사용자에게 전했다.

#### 변경 후
- **계좌 id를 매 턴 준다:** `_chat`이 로그인 사용자의 입출금 계좌 `(account_id, 이름, 마스킹된 번호)`를 읽어 시스템 프롬프트 끝(날짜 뒤)에 붙인다. 앞부분은 고정이라 프롬프트 캐시는 그대로다. **잔액은 넣지 않는다**(잔액은 도구 결과만 쓴다는 기존 규칙). 별칭은 줄바꿈을 없애고 50자로 자른다(사용자가 정한 글자라 지시문처럼 읽히지 않게).
- **받는 계좌 두 가지:** `to_account_id`(본인 입출금 계좌) 또는 `to_account_num`(다른 사람 계좌 전체 번호) 중 **정확히 하나**. 둘 다 있거나 둘 다 없으면 `INVALID_ARGUMENTS`. `to_account_id`는 서버가 소유 계좌인지 확인하고 번호를 직접 찾아 넣는다(모델은 전체 번호를 볼 필요가 없다).
- **오류 코드 분리:** 출금 계좌 `FROM_ACCOUNT_NOT_FOUND`, 받는 내 계좌 `TO_ACCOUNT_NOT_FOUND`. 남의 계좌 id도 같은 코드로 404(존재 여부를 드러내지 않음).
- 프롬프트: id는 위 목록(없으면 `get_my_accounts`)에서만 쓰고, 마스킹된 번호로 계좌번호를 만들지 않으며, 계좌를 못 찾는다는 오류면 `get_my_accounts`로 다시 확인해 한 번 더 시도한다.

#### 이유
- 사용자 제보: "월급 계좌에서 생활비 계좌로 900만원 입금해줘"에 "출금 계좌를 찾을 수 없습니다"가 나온다. 모델에게 도구 결과를 다시 보여 주는 대신, 이체에 꼭 필요한 id만 서버가 매번 정확히 알려 준다.

#### 영향 범위
- 채팅 요청마다 계좌 조회 쿼리 1회 추가(입출금·예금·적금 목록).
- 이체 실행(`confirm`)·초안 검증 규칙(잔액·한도·같은 계좌)은 그대로다. 비밀번호는 여전히 확인 카드에서만 받는다.
- 모델 응답은 비결정적이라 프롬프트만으로는 100% 막지 못한다. 서버가 id를 주는 것이 핵심 대책이고, 오류 시 재시도 규칙은 보조다.

#### 검증
- `tests/test_agent.py` 23개 통과: 본인 계좌 id로 초안 생성(번호 미노출, 초안에 서버가 찾은 번호 저장), 대상 오류 5종(남의 계좌 id·없는 출금 계좌·같은 계좌·대상 없음·둘 다 줌), 시스템 프롬프트에 내 입출금 계좌만 있고 남의 계좌·전체 번호는 없음.
- 실제 모델(Gemini)로 직접 확인: 같은 순서("내 계좌 목록" → "월급 계좌에서 생활비 계좌로 100만원 입금해줘")에서 두 번째 질문이 `get_my_accounts` 없이 `prepare_transfer`만으로 성공, 확인 카드 생성. 이체 실행은 하지 않았다.

#### 팀 논의 포인트
- 지난 대화의 도구 결과를 모델에게 계속 보여 줄지(전체 재현), 지금처럼 필요한 id만 매번 줄지. LangGraph로 옮길 때 상태(state)에 계좌 목록을 두는 방식과 함께 정한다.


### C-100. AI 비서 이체: 계좌 id 대신 이름으로 찾기 (C-099의 매 턴 계좌 목록 대체)

- **날짜:** 2026-11-09
- **분류:** API · 구조 · 테스트
- **상태:** 적용
- **바뀐 파일:**
  - `domains/agent/tools/transfers.py` (`PrepareTransferArgs`, `_key`, `_find_own_checking`, `prepare_transfer`)
  - `domains/agent/prompts.py`(이체 규칙, `build_system_prompt`에서 계좌 목록 제거), `domains/agent/service.py`(`_checking_accounts` 삭제), `domains/agent/tools/__init__.py`(도구 설명)
  - `tests/test_agent.py`, `tests/test_account_password.py`, `docs/AGENT.md`

#### 변경 전 (C-099)
- 서버가 매 요청마다 내 입출금 계좌 `(account_id, 별칭, 마스킹된 번호)`를 시스템 프롬프트 끝에 붙였다. 모델은 그 id를 `from_account_id`·`to_account_id`로 넘겼다.
- 이체 요청이 아닌 말("안녕")에도 계좌 조회가 매번 실행됐고, 사용자가 정한 별칭이 시스템 프롬프트에 들어갔다.

#### 변경 후
- `prepare_transfer`는 **이름**을 받는다: `from_account`(출금), `to_account`(받는 내 계좌) 또는 `to_account_num`(다른 사람 계좌 전체 번호). 둘 중 받는 쪽은 정확히 하나. id 인자(`from_account_id`·`to_account_id`)는 없앴다(`extra="forbid"`라 옛 인자는 `INVALID_ARGUMENTS`).
- **서버가 이름으로 찾는다**(`_find_own_checking`): 로그인 사용자의 입출금 계좌에서
  1) 이름이 같음(공백·"계좌"·"통장"을 뺀 뒤 비교: "월급 계좌"="월급 통장"="월급"),
  2) 한쪽이 다른 쪽을 포함,
  3) 번호 끝 4자리 이상 일치
  순서로 보고, 앞 단계에서 하나라도 나오면 뒤는 보지 않는다.
- **하나일 때만 진행한다.** 없으면 `FROM/TO_ACCOUNT_NOT_FOUND`, 여럿이면 `ACCOUNT_AMBIGUOUS`. 오류 메시지에 후보(이름·마스킹된 번호, id 없음)를 넣고 "사용자에게 어느 계좌인지 물어보세요"를 붙여, 모델이 임의로 고르지 않고 되묻게 한다.
- 시스템 프롬프트의 계좌 목록과 서비스의 `_checking_accounts`를 지웠다. 프롬프트 규칙은 "이름을 그대로 넣고, id·번호를 짐작하지 않는다"로 바꿨다.

#### 이유
- 모델이 순서를 지킬지(먼저 목록 조회)에 기대던 구조가 첫 실패의 원인이었고, 매 턴 목록 주입은 그 임시 대책이었다. 사용자가 말한 이름을 서버가 결정적으로 해석하면 id를 모델 쪽에서 알 필요가 없다.

#### 영향 범위
- 채팅마다 계좌 조회가 1번 줄고(이체 요청 때만 조회), 프롬프트에서 별칭 주입 통로가 없어졌다.
- 이체 검증(소유권·같은 계좌·잔액·1회/1일 한도)과 확인 카드·비밀번호 흐름은 그대로다. 잘못 고른 계좌가 있어도 확인 카드에 이름과 마스킹된 번호가 보인다.
- 부분 일치로 하나만 걸리면 그 계좌로 초안을 만든다(예: "월"만 말해도 별칭에 "월"이 들어간 계좌가 하나면 선택). 확인 카드에서 사용자가 걸러 낸다.

#### 검증
- `tests/test_agent.py`·`tests/test_account_password.py` 통과(78개): 이름 표기 6종과 번호 끝자리, 남의 계좌는 번호 끝자리로도 못 찾음(후보에 내 계좌만), 없음·여럿·같은 계좌·대상 없음/둘 다·옛 id 인자 거절, 프롬프트에 계좌 정보 없음, 본인 계좌 이체 초안에 서버가 번호를 넣음.
- 실제 모델(Gemini)로 직접 확인(로컬 테스트 계정, 이체 실행은 하지 않음): 계좌 목록을 먼저 보지 않고 "월급 계좌에서 생활비 계좌로 100만원 입금해줘" → `prepare_transfer` 한 번으로 확인 카드 생성. "생활비 통장에서 월급 통장으로 5만원"도 성공. 없는 계좌 "여행 통장으로 1만원"은 도구를 부르지 않고 출금 계좌를 되물음.

#### 팀 논의 포인트
- 이름 매칭 규칙(부분 일치 허용 범위). 더 엄격하게 하려면 2단계(포함)를 빼고 정확히 같을 때만 허용한다.


### C-101. AI 비서 모델↔도구 반복을 LangGraph로 이식

- **날짜:** 2026-11-09
- **분류:** 구조 · 테스트
- **상태:** 적용 (동작은 그대로)
- **바뀐 파일:**
  - `domains/agent/graph.py`(새), `domains/agent/service.py`(`_chat`의 for 루프와 `_respond` 삭제, 상한·문구 상수 이동)
  - `pyproject.toml`·`uv.lock`(`langgraph` 추가), `tests/test_agent.py`(상수·`TOOL_SPECS`를 graph에서 import, 테스트 내용은 그대로), `docs/AGENT.md`, `docs/RETROSPECTIVE.md`

#### 변경 전
- `service.py`의 `for _ in range(MAX_MODEL_CALLS)` 루프가 모델 호출 → 도구 실행 → 결과 전달을 반복하고, 호출·도구 상한과 이체 카드(`TransferAction`) 포착을 직접 처리했다.

#### 변경 후
`StateGraph` 노드 4개:

```
START → call_model ─┬─ 도구 호출 없음 ──────────→ finish → END
                    ├─ 도구 호출이 상한 초과 ───→ limit  → END
                    └─ 도구 호출 있음 → tools ─┬─ 모델 호출 상한 도달 → limit
                              ↑                └─ 아니면 → call_model
```

- 상태(`AgentState`): `system`, `turns`, `reply`, `model_calls`, `tool_log`, `action`, `answer`. 요청마다 다른 값(모델 클라이언트, 로그인 사용자)은 상태가 아니라 `context`(`AgentContext`)로 넘긴다.
- 상한 의미는 그대로다: 모델 호출 6번, 도구 8개. 마지막(6번째) 응답에 도구 호출이 있으면 그 도구는 실행하고 나서 "단계가 너무 많이 필요합니다"로 끝난다. 도구가 상한을 넘기는 응답은 실행하지 않고 같은 문구로 끝난다.
- `ModelTimeout`→504 `AGENT_TIMEOUT`, `ModelError`→503 `AGENT_UNAVAILABLE` 변환은 `call_model` 노드로 옮겼다.
- **그래프 밖에 둔 것:** 지난 대화 불러오기, 인용 정리, 대화 저장(DB를 만지는 일)은 `service.py`에 그대로 둔다. 그래프가 `service.py`의 `extract_citations`를 불러야 하면 순환 import가 되고, DB 접근을 한곳에 두는 편이 단순하다.
- **checkpointer는 쓰지 않는다.** 그래프 상태는 요청 하나 동안만 살고, 대화 기록은 `agent_messages`가 유일한 저장소다(같은 개인 금융 정보 사본을 하나 더 만들지 않기 위해).
- `RECURSION_LIMIT = 2*6+3`: 그래프 단계 수 상한을 명시해서, LangGraph 기본값(25)이 아니라 우리 상한이 먼저 걸리게 한다.

#### 이유
- 학습과 확장: 노드·간선으로 흐름이 보이고, 스트리밍·이체 전용 서브그래프 같은 이후 확장이 쉬워진다. 사용자에게 보이는 동작을 바꾸려는 변경이 아니다.
- **`langchain-google-genai`는 쓰지 않았다.** 설치를 시뮬레이션하니 `google-genai`를 1.75 → 3.0.0으로 올려야 했다(프로젝트는 `<2`, 약관 검색 `terms/embedding.py`도 사용). `langgraph` 단독은 충돌이 없어서, 기존 `GeminiModelClient`(생각 서명 보존 등 구현·테스트 완료)를 노드에서 그대로 부른다.

#### 영향 범위
- `ModelClient`·`tools/`·`prompts.py`·라우터·응답 스키마·프런트엔드·DB 스키마는 그대로다. `langgraph`와 함께 `langchain-core` 등 15개 패키지가 설치된다(`google-genai` 1.75.0 유지).
- 약관 출처를 모으는 `request_sources` 컨텍스트 변수가 그래프 노드 안에서도 같은 값으로 보이는지가 위험이었다 → 채팅 인용 테스트로 확인.

#### 검증
- 테스트 90개 통과(`test_agent.py` 24, `test_terms_rag.py`, `test_account_password.py`). 테스트 본문은 바꾸지 않고 상수·`TOOL_SPECS`의 import 위치만 고쳤다 — 상한, 오류 변환, 대화 이어가기·소유권, 인용 출처, 이체 초안이 모두 기존 테스트로 동등함을 확인했다.
- 실제 모델(Gemini)로 직접 확인(로컬 테스트 계정): 이체 요청은 `prepare_transfer` 한 번으로 확인 카드, 약관 질문은 `search_product_terms` 후 답변에 검증된 출처(어벤져스 입출금계좌 이용약관 › 1회·1일 이체 한도)가 붙음.
- 전체 테스트 스위트는 다시 돌리지 않았다(바뀐 곳은 에이전트 쪽).

#### 팀 논의 포인트
- 다음 확장 후보: 답변 스트리밍, 이체 전용 서브그래프, 실행 추적. 각각 따로 정한다.


### C-102. 이체 한도 오류 메시지에 한도 금액을 넣기 (AI가 한도를 지어내던 문제)

- **날짜:** 2026-11-09
- **분류:** API · 문서
- **상태:** 적용
- **바뀐 파일:** `domains/transfers/service.py`(`_check_limits`), `domains/agent/prompts.py`(규칙 1줄), `tests/test_agent.py`(검증 1줄)

#### 변경 전
- 한도를 넘으면 `"1회 이체 한도를 초과했습니다."`, `"1일 이체 한도를 초과했습니다."`처럼 금액 없는 문구만 나갔다.
- AI 비서는 이 문구만 받아서 금액을 **지어냈다**. 실제 1회 한도가 1,000,000원인 계좌에서 "1회 이체 한도는 5,000,000원입니다"라고 답했다(5,000,000원은 1일 한도). 사용자는 500만원·450만원을 연달아 시도했다가 계속 거절당했다.

#### 변경 후
- `PER_TRANSFER_LIMIT_EXCEEDED`: `"1회 이체 한도(1,000,000원)를 초과했습니다."`
- `DAILY_LIMIT_EXCEEDED`: `"1일 이체 한도(5,000,000원)를 초과했습니다. 오늘 이미 N원을 보냈습니다."`
- 프롬프트: 이체 한도 금액은 도구 결과·오류 메시지에 적힌 값만 말하고, 없으면 짐작하지 않는다.

#### 이유
- 모델은 도구가 준 말만 전할 수 있다. 값이 빠져 있으면 모델이 메우므로(환각), 서버가 정확한 값을 오류에 담는다. 일반 이체 API(`/transfers`)의 오류 문구도 같이 좋아진다(코드는 그대로라 프런트·테스트는 영향 없음).

#### 영향 범위
- 응답의 `code`는 그대로, `message`만 바뀐다. 문구 전체를 비교하는 테스트·프런트 코드는 없었다.
- 사용자 본인의 한도와 오늘 이체 합계만 담긴다.

#### 검증
- `test_agent.py`·`test_transfers.py` 47개 통과(에이전트 테스트에 한도 금액 포함 여부 검증 추가).
- 실제 모델로 확인: 1회 한도 100만원 계좌에 300만원 이체 요청 → "1회 이체 한도인 1,000,000원을 초과하여 이체할 수 없습니다."

#### 팀 논의 포인트
- 한도 안내를 한 걸음 더: 오류에 "한도는 계좌 상세에서 바꿀 수 있습니다"를 붙일지, AI가 한도 상향 방법을 안내할지.


### C-103. AI 비서: 예·적금 가입 화면을 미리 채워 이어 가기

- **날짜:** 2026-11-09
- **분류:** API · 구조 · 테스트
- **상태:** 적용
- **바뀐 파일:**
  - 백엔드: `domains/agent/tools/open_account.py`(새), `tools/__init__.py`(등록), `tools/transfers.py`(`find_own_checking`·`name_key` 공개, 이름까지 반환), `schemas.py`(`OpenAccountAction`·`SummaryRow`·`AssistantAction`), `graph.py`(카드 포착), `prompts.py`
  - 프런트: `components/assistant/OpenAccountCard.tsx`(새), `lib/open-draft.ts`(새), `Assistant.tsx`, `lib/api.ts`, `app/open/[kind]/[[...product]]/page.tsx`(저장 키를 공유)
  - `tests/test_agent.py`(테스트 3개), `docs/AGENT.md`

#### 변경 전
- 비서에게 가입 도구가 없었다. "예금 가입 안됨?"에는 "어렵습니다"라고만 답했고, "만기일은 2028년 11월 9일로 설정됩니다"처럼 마치 설정해 준 것처럼 말하기도 했다(실제로는 아무것도 한 적 없음).

#### 변경 후
- 새 도구 `prepare_open_account`: 예금·적금의 상품 이름, 금액, 만기, 적금 납입일, 예금 출금 계좌, 별명을 받아 **검증만 하고 카드를 돌려준다. 가입은 하지 않는다.**
  - 상품은 이름으로 찾는다(정확히 같음 → 포함). 이름이 없고 상품이 여럿이면 `PRODUCT_NOT_SPECIFIED`, 없으면 `PRODUCT_NOT_FOUND`, 여럿이면 `PRODUCT_AMBIGUOUS` — 모두 후보(이름·금리·최소 금액)를 메시지에 담아 되묻게 한다.
  - 만기는 `maturity_months`(몇 개월 뒤)로 받아 **서버가 날짜를 계산**한다(말일이 없으면 말일로: 1/31+1개월=2/28). 날짜를 직접 말했을 때만 `maturity_date`. 둘 다 주면 거절.
  - 검사: 만기일은 내일 이후(`MATURITY_NOT_FUTURE`), 예금 최소 가입 금액(`AMOUNT_BELOW_MINIMUM`), 출금 계좌는 C-100의 이름 찾기 재사용.
  - 비밀번호 같은 인자는 `extra="forbid"`로 거절. 입출금 계좌는 이 도구가 다루지 않는다(`kind`는 deposit/savings만).
- 응답 카드 `OpenAccountAction`(`type="OPEN_ACCOUNT"`): 상품, 금리, 표시용 요약(`summary`), 가입 화면 입력칸 값(`fields`). `action`은 `type`으로 구분하는 합집합(`AssistantAction`)이 되어, 예전에 저장된 이체 카드 기록도 그대로 읽힌다.
- 프런트 카드의 "가입 화면에서 이어서 하기": `sessionStorage`의 가입 화면 임시 저장 항목(`open-draft:{kind}`)에 값을 넣고 `/open/{kind}/{상품 id}`로 이동한다. 가입 화면이 열릴 때 그 값을 읽어 입력칸을 채운다(C-098의 기능). 좁은 화면에서는 비서 패널을 먼저 닫는다. 저장된 대화를 다시 불러올 때도 가입 카드는 다시 그린다(링크일 뿐이라 안전. 이체 카드는 기존대로 다시 그리지 않음).
- 프롬프트: 가입은 카드까지만, 약관 동의·비밀번호는 화면에서, 만기는 개월 수로, 상품 이름이 없으면 먼저 후보를 받아 보여 주기, 적금은 출금 계좌를 묻지 않기, 도구로 하지 않은 일을 했다고 말하지 않기.

#### 이유
- 가입은 약관 동의와 계좌 비밀번호를 사용자가 직접 해야 하는 일이라 채팅 안에서 끝내지 않는다(이체 초안 + 확인 카드와 같은 원칙). 대신 상품 고르기, 금액·만기 정하기를 대화로 덜어 준다. 날짜 계산은 모델이 틀릴 수 있어서 서버가 한다.

#### 영향 범위
- DB 스키마·가입 API는 그대로다. `find_own_checking`이 이름도 돌려주도록 바뀌어(`(id, 번호, 이름)`) 이체 도구도 함께 고쳤다.
- 가입 화면의 `open-draft` 항목을 비서 카드가 덮어쓴다(사용자가 같은 종류를 입력하던 중이었다면 카드의 값으로 바뀐다).

#### 검증
- `tests/test_agent.py` 27개 통과(새 3개: 예금 카드·날짜 계산·가입이 일어나지 않음·대화 다시 불러오기, 적금 카드, 오류 6종과 잘못된 인자 4종). `tsc --noEmit`, eslint 통과.
- 실제 모델(Gemini)과 화면(로컬 테스트 계정)으로 확인: 예금 카드(만기 2년 뒤 = 2028-11-09 서버 계산, 출금 계좌 이름 인식) → 버튼 → 가입 화면에 상품·금액·출금 계좌·만기일이 채워지고 비밀번호·약관은 비어 있음. 적금은 상품 없이 요청하면 후보 3개를 보여 주고, 고르면 카드(월 30만원·25일·1년 뒤) → 가입 화면에 채워짐. 가입 자체는 누르지 않았다.

#### 팀 논의 포인트
- 모델이 상품 후보를 보여 주지 않고 되묻기만 하는 경우가 있었다(긴 대화에서 앞선 답을 따라 하는 듯, 새 대화에서는 후보를 보여 줌). 프롬프트로 줄였지만 100%는 아니다.
- 채팅 안에서 가입을 끝내려면 약관 동의·비밀번호 입력 UI를 카드에 넣어야 한다(이번에는 하지 않음).


### C-104. 계좌 상세 화면 정리 + 예·적금 이자 미리 보기

- **날짜:** 2026-11-09
- **분류:** API · 구조 · 테스트
- **상태:** 적용
- **바뀐 파일:**
  - 백엔드: `domains/accounts/interest.py`(`scheduled_payment_days`), `schemas.py`(`InterestPreviewResponse`), `service.py`(`interest_preview`), `router.py`(`GET /accounts/{type}/{id}/interest-preview`)
  - 프런트: `app/accounts/[type]/[id]/page.tsx`, `components/account-password.tsx`, `app/transfer/page.tsx`, `lib/api.ts`
  - `tests/test_close.py`(테스트 5개), `docs/API_ENDPOINTS.md`

#### 변경 전
- 계좌 상세 맨 위에 "해지하기"와 "계좌 비밀번호 설정·재설정"이 큰 카드로 늘 보였다(자주 쓰지 않는 기능이 화면의 큰 자리를 차지).
- 해지 전에 받을 금액·이자를 알 방법이 없었다(해지해 봐야 알았다).
- 해지 성공 문구는 계좌를 다시 불러오는 순간 화면에서 사라졌다(해지된 계좌는 해지 칸을 그리지 않아서).

#### 변경 후
**화면**
- **해지하기:** 맨 아래 "가입 당시 약관 보기" 밑에 작은 밑줄 글자로 둔다. 누르면 펼쳐진다. 펼친 안에 "오늘 해지하면 N원을 받아요"를 보여 준다. 해지 성공 문구는 부모 화면이 들고 있어서 계좌가 닫혀도 남는다.
- **계좌 비밀번호 설정·재설정:** 평소엔 보이지 않는다. 다음 때만 나타난다 — (1) 비밀번호를 정하지 않았거나 5회 틀려 잠긴 계좌(`password_set`/`password_locked`), (2) 비밀번호 입력칸을 한 번 누른 뒤 아래에 뜨는 "비밀번호를 잊으셨나요? 계좌 비밀번호 재설정하기", (3) 오류 안내 링크(`#account-password`)로 왔을 때(처음 열 때뿐 아니라 같은 화면에서 주소만 바뀌어도 `hashchange`로 따라간다). 안내는 입력칸을 벗어나도 사라지지 않는다(링크를 누르려고 벗어나는 경우 대비).
- `AccountPasswordField`에 `resetHref`(다른 화면으로 가는 링크)·`onReset`(같은 화면에서 펼침) 속성을 추가했다. 적용: 해지(같은 화면 펼침), 적금 납입·이체 화면(선택한 출금 계좌 상세로 링크). 이체 화면은 아직 고르지 않았으면 화면에 보이는 첫 계좌를 쓴다.
- 해지가 틀려서 잠기면 계좌를 다시 불러와 재설정 칸이 자동으로 나타난다.
- **이자 미리 보기 카드**(예·적금, 해지 전): "만기까지 두면 / 오늘 해지하면" 각각 원금·이자·받을 금액. 적금 만기 값은 "매월 N원을 계속 납입한다고 가정한 예상이에요"를 붙인다.

**API** `GET /accounts/{deposit|savings}/{id}/interest-preview` (읽기만 한다)
- **오늘 해지하면**은 해지(`close_account`)와 같은 `calc_interest`를 같은 입금 내역으로 부르므로, 같은 날 실제로 해지한 값과 같다(테스트로 확인).
- **만기까지 두면:** 예금은 지금 잔액 그대로. 적금은 `monthly_deposit_date`마다 `monthly_payment`를 만기일까지 낸다고 가정해 입금 목록에 더한 뒤 만기일 기준으로 계산한다(`scheduled_payment_days`: 오늘 제외, 만기일 당일 포함, 그 달에 그 날이 없으면 말일).
- 입출금 계좌는 `INTEREST_NOT_SUPPORTED`, 해지된 계좌는 `ACCOUNT_CLOSED`, 남의 계좌는 404.

#### 이유
- 자주 쓰지 않는 파괴적 기능(해지)과 비밀번호 재설정은 평소엔 작게·숨겨 두고 필요한 순간에 문맥(비밀번호 입력칸)에서 보여 주는 편이 은행 앱의 일반적인 모습이다. 해지 결정을 하려면 이자를 먼저 알아야 한다.

#### 영향 범위
- 계좌 응답이 이미 주던 `password_set`·`password_locked`를 화면에서 처음 쓴다(스키마 변경 없음). 해지·비밀번호 API는 그대로다.
- 적금 만기 예상은 **가정**이다. 사용자가 실제로 납입하지 않거나 더 내면 달라진다(화면에 문구로 밝힘). 납입일이 오늘이고 아직 안 냈어도 "오늘은 제외"라 그 달 납입은 계산에 안 들어간다.
- 같은 화면의 `#account-password` 링크는 Next의 `Link`(`pushState`)로 이동하면 `hashchange`가 오지 않는다. 지금은 해지 오류 → 계좌 다시 불러오기로 칸이 나타나서 문제가 없다.

#### 검증
- `tests/test_close.py` 18개 통과(새 5개): 예금 미리 보기와 실제 해지 값 일치, 적금(가정한 납입 횟수·원금·이자는 `calc_interest`로 독립 계산과 일치, 실제 해지와 일치), 만기 뒤 전체 금리, 입출금·남의 계좌·해지된 계좌 거부, 납입일 계산(말일·오늘 제외·만기일 포함). `tsc`·eslint 통과.
- 브라우저(로컬 테스트 계정)로 확인: 예금·적금 상세에 이자 미리 보기, 해지하기가 맨 아래 작은 링크, 눌러서 펼치면 "오늘 해지하면 …원", 비밀번호 칸을 누르면 재설정 안내가 뜨고 누르면 재설정 칸이 나타남, 입출금 계좌는 평소 재설정 칸이 없고 `#account-password`로 들어오면 나타남, 이체 화면에서도 입력칸을 누르면 안내와 링크(`/accounts/checking/{id}#account-password`).
- 실제 해지 실행과 비밀번호 재설정 완료는 화면에서 누르지 않았다.

#### 팀 논의 포인트
- 적금 만기 예상의 가정(매월 납입 계속)을 다르게 볼지(예: 지금까지 낸 돈만 기준).
- 카드 발급·가입 화면의 출금 계좌 비밀번호 칸과 이체 확인 카드에도 같은 "재설정하기" 안내를 넣을지.

---

## 부록 A. 초기 리뷰(2026-11-04) 항목 처리 현황

처음 코드 리뷰에서 나온 9개 항목의 처리 결과다. 취소선은 처리 완료이고 오른쪽이 처리한 항목 번호다. **9개 모두 처리됐다**(9번은 보류했다가 C-026에서 처리).

1. ~~문서의 `.env.example`과 실제 파일명 `.env.examples` 불일치~~ → C-001
2. ~~이체·카드결제·적금납입 시 행 잠금(`with_for_update`) 없음 → 동시 요청 시 이중 출금, 1일 한도 우회~~ → C-017
3. ~~`alembic/versions`가 비어 있어 팀원마다 autogenerate → 리비전 충돌~~ → C-014
4. ~~회원가입 중복 검사가 조회 후 insert → 동시 요청 시 `IntegrityError`로 500~~ → C-002
5. ~~FK 컬럼(`user_id`, history의 `*_account_id`·`*_card_id`)에 인덱스 없음~~ → C-003
6. ~~`balance >= 0`, 납입일·결제일 1~31, 상품 `type` 값을 DB CHECK 제약으로 막지 않음~~ → C-004
7. ~~`get_current_user`가 `get_db` 대신 별도 세션 사용 (요청당 커넥션 2개, 단 바꾸면 `db.begin()` 충돌 주의)~~ → C-018 (지적 정정, 현 구조 유지)
8. 설계 미정: ~~계좌번호 형식~~(C-006), ~~`from_account`/`sending_account`~~(C-007), ~~`balance_after`~~(C-008), ~~1일 한도 시간대~~(C-009), ~~자기 계좌 이체 차단~~(C-005). ~~신용카드 한도·정산~~(C-010~C-012)
9. ~~로그인 시 존재하지 않는 아이디는 해시 검증을 건너뜀 (응답 시간으로 아이디 존재 추측 가능), 401·422 테스트 없음~~ → C-026 (보류했다가 처리)

---

## 부록 B. 변경 목록 (시간순)

| ID | 날짜 | 분류 | 제목 | 상태 |
|---|---|---|---|---|
| C-001 | 2026-11-04 | 문서 | 환경변수 예시 파일명을 문서와 일치 | 적용 |
| C-002 | 2026-11-05 | 동시성 | 동시 회원가입 중복 시 500 → 409 | 적용 |
| C-003 | 2026-11-05 | DB 스키마 | FK·거래내역 조회 컬럼에 인덱스 추가 | 적용 |
| C-004 | 2026-11-05 | DB 스키마 | 잔액·날짜·상품 종류 CHECK 제약 추가 | 적용 |
| C-005 | 2026-11-05 | 문서 | 이체 TODO에 자기 계좌 이체 거부 추가 | 적용 |
| C-006 | 2026-11-05 | 구조 | 계좌번호를 종류별 앞자리로 발급 (테이블 간 중복 검사 제거) | 적용 |
| C-007 | 2026-11-05 | DB 스키마 | 거래내역 `from_account`·`sending_account` → `counterpart_account` 통합 | 적용 |
| C-008 | 2026-11-05 | DB 스키마 | 거래내역 금액 컬럼 `amount`로 통일(항상 양수) + `balance_after` 추가 | 적용 |
| C-009 | 2026-11-05 | 구조 | 1일 이체 한도의 "오늘" 기준을 KST로 명시 | 적용 |
| C-010 | 2026-11-05 | DB 스키마 | 신용카드 청구서 테이블 `credit_card_bills` + 청구·납부 API 설계 | 적용 |
| C-011 | 2026-11-05 | DB 스키마 | 신용카드 한도 `credit_limit` 추가 + 결제 시 한도 검사 | 적용 |
| C-012 | 2026-11-05 | DB 스키마 | 신용카드 `accumulated_amount` 의미를 "미결제액"으로 변경 | 적용 |
| C-013 | 2026-11-05 | DB 스키마 | 신용 한도를 카드 상품별로 고정 (`card_products.credit_limit`) | 적용 |
| C-014 | 2026-11-05 | 구조 | 최초 마이그레이션 파일 생성 + README 마이그레이션 절차 변경 | 적용 |
| C-015 | 2026-11-05 | 구조 | 로컬 DB용 `docker-compose.yml` 추가 | 적용 |
| C-016 | 2026-11-05 | 문서 | DB 호스트 `localhost` → `127.0.0.1` + Windows 실행 주의사항 | 적용 |
| C-017 | 2026-11-05 | 동시성 | 돈이 움직이는 처리의 행 잠금 규칙 (ERD 규칙 9) | 적용 |
| C-018 | 2026-11-05 | 구조 | `get_current_user` 별도 세션 유지 + 이유 주석 (리뷰 지적 정정) | 적용 |
| C-019 | 2026-11-05 | API | products 도메인 구현 + 개발용 시드 스크립트 추가 | 적용 |
| C-020 | 2026-11-05 | API | accounts 도메인 구현 (개설·조회·거래내역·수정) | 적용 |
| C-021 | 2026-11-05 | API | 개발용 충전 API 추가 (`/dev/...`, 설정으로 켜고 끔) + 행 잠금 실제 검증 | 적용 |
| C-022 | 2026-11-05 | API | transfers 도메인 구현 (이체·적금 납입·예금 입금) + 동시성·데드락 검증 | 적용 |
| C-023 | 2026-11-05 | API | cards 도메인 구현 (발급·조회·결제·청구서) + 동시성 검증 | 적용 |
| C-024 | 2026-11-05 | API | users `PATCH /users/me` 구현 (이름·닉네임·전화번호 수정) | 적용 |
| C-025 | 2026-11-05 | 테스트 | PostgreSQL 동시성 검증 스크립트를 저장소에 보관 (`scripts/`) | 적용 |
| C-026 | 2026-11-05 | 보안 | 로그인 응답 시간으로 아이디 존재를 알 수 없게 수정 + users 401·422 테스트 (리뷰 9번) | 적용 |
| C-027 | 2026-11-05 | 문서 | ERD 다이어그램 v2 추가 (`AvengersBankDiagram_v2.drawio`, 모델에서 자동 생성, 원본은 그대로) | 적용 |
| C-028 | 2026-11-05 | 구조 | 버전 관리 시작 (`git init` + 첫 커밋) | 적용 |
| C-029 | 2026-11-05 | 구조 | 임시 값 1-1~1-7 확정 + ruff 도입 안 함 | 적용 |
| C-030 | 2026-11-05 | DB 스키마 | 거래내역 `type` DB CHECK 제약 추가 (1-8) | 적용 |
| C-031 | 2026-11-05 | 보안 | 남의 계좌·카드도 404로 통일 (2-1) | 적용 |
| C-032 | 2026-11-05 | DB 스키마 | 입출금 계좌 한도 순서 DB CHECK 추가 (2-2) | 적용 |
| C-033 | 2026-11-05 | API | 만기일부터 예금·적금 입금 거절 (2-3) | 적용 |
| C-034 | 2026-11-05 | 구조 | 적금·예금 납입 규칙은 지금 방식 유지 (2-4) | 적용 |
| C-035 | 2026-11-05 | DB 스키마 | 신용카드 `outstanding_amount` 개명 + 입출금 거래내역 `counterpart_name` 추가 (2-5, 2-6) | 적용 |
| C-036 | 2026-11-05 | 구조 | 카드 사용내역 `used_amount` 이름 유지 (2-7) | 적용 |
| C-037 | 2026-11-05 | 구조 | 청구서 생성 시점·경로 이름 유지 (2-8) | 적용 |
| C-038 | 2026-11-05 | 보안 | 받는 계좌번호 존재 확인 가능성은 감수 (2-9) | 적용 |
| C-039 | 2026-11-05 | 보안 | 회원가입 중복 아이디 409 유지 (2-10) | 적용 |
| C-040 | 2026-11-05 | 보안 | 로그인 실패 횟수 제한 (메모리 카운터, 429) (2-11) | 적용 |
| C-041 | 2026-11-05 | 구조 | 이름·전화번호는 길이 검증만 유지 (2-12) | 적용 |
| C-042 | 2026-11-05 | 구조 | API 시간은 UTC로 유지 (2-13) | 적용 |
| C-043 | 2026-11-05 | API | 예금·적금 해지 (단리 일할 이자, 중도 해지 50%, 상태 컬럼) (3-1) | 적용 |
| C-044 | 2026-11-05 | API | 카드 정지·해지 (status 컬럼, 해지는 미결제액 0일 때만) (3-4 일부) | 적용 |
| C-045 | 2026-11-05 | API | 비밀번호 변경 (현재 비밀번호 확인, 로그인과 같은 실패 한도) (3-7 일부) | 적용 |
| C-046 | 2026-11-05 | API | `/health` 추가 + 수수료·예약 이체는 하지 않기로 함 (4-1, 3-9) | 적용 |
| C-047 | 2026-11-05 | 구조 | CORS 허용 주소를 환경변수로 (4-4) | 적용 |
| C-048 | 2026-11-05 | 구조 | compose: DB 비밀번호를 `.env`에서, 공식 `postgres:17-trixie` 이미지로 (4-6) | 적용 |
| C-049 | 2026-11-05 | 구조 | 마이그레이션 파일 이름에 날짜·시각 추가 (4-7) | 적용 |
| C-050 | 2026-11-05 | 보안 | 개발용 API가 켜져 있으면 시작 때 경고 로그, Windows `fastapi run`은 안내만 (4-9, 4-8) | 적용 |
| C-051 | 2026-11-05 | 구조 | 동시성 검증 수동 유지, 원본 drawio 그대로 (4-10, 4-12) | 적용 |
| C-052 | 2026-11-05 | 구조 | AWS 배포용 Dockerfile·Caddy·운영 compose 추가 | 적용 |
| C-053 | 2026-11-06 | 구조 | 첫 배포는 HTTP(`DOMAIN=:80`), DB는 RDS PostgreSQL | 적용 |
| C-054 | 2026-11-06 | 구조 | AWS 첫 배포 완료 (EC2 + RDS, sslip.io HTTPS) | 적용 |
| C-055 | 2026-11-06 | 구조 | Next.js 프론트엔드 추가 (로그인·가입·계좌·개설·이체) | 적용 |
| C-056 | 2026-11-06 | 문서 | 배포 정리 문서 `docs/DEPLOY.md` 추가 | 적용 |
| C-057 | 2026-11-06 | 구조 | 프론트 하단 탭, 계좌 상세·거래 내역, 상품, 내 정보 화면 | 적용 |
| C-058 | 2026-11-06 | 구조 | 프론트 디자인 개편 (피치·코랄, Pretendard, 반응형) | 적용 |
| C-059 | 2026-11-06 | 구조 | 프론트 브랜드 이름 "스파이디뱅킹", 도장 "SP" | 적용 |
| C-060 | 2026-11-06 | 구조 | 이체 화면에 접는 "자주 사용하는 계좌"(내 계좌 + 자주 보낸 계좌) | 적용 |
| C-061 | 2026-11-06 | 구조 | 샘플 상품 15개 + 가입·발급·입금·납입 화면 | 적용 |
| C-062 | 2026-11-06 | 구조 | 카드 상세(사용 내역) 화면 + 로컬 예시 거래 데이터 | 적용 |
| C-063 | 2026-11-06 | 구조 | 신용카드 결제 예정 금액(청구서)·납부 버튼 + 예시 청구서 | 적용 |
| C-064 | 2026-11-06 | API | 거래 내역 검색 조건(날짜·종류·금액·사용처) + 카드대금 납부에 카드 이름 | 적용 |
| C-065 | 2026-11-06 | 구조 | 홈 개편(자산 현황·전체 계좌·카드 슬라이더·대표 계좌/순서) + 이체 상대 실명 저장 | 적용 |
| C-066 | 2026-11-06 | 구조 | 순서 설정은 별도 화면, 대표 계좌 여러 개, 슬라이더엔 대표 계좌만 | 적용 |
| C-067 | 2026-11-06 | 구조 | 계좌 카드 슬라이더를 넓은 화면에서도 한 장씩 | 적용 |
| C-068 | 2026-11-06 | 구조 | 최근 이체한 분 이름 → 계좌번호 채운 이체 화면 | 적용 |
| C-069 | 2026-11-06 | 구조 | 상품 화면을 금융상품 형태로(탭·추천·배너·칩·찜) | 적용 |
| C-070 | 2026-11-06 | API | AI 금융 비서(Tool Calling): 조회 Tool 4개 + 이체 초안 → 화면 확인 후 실행 | 적용 |
| C-071 | 2026-11-06 | 구조 | AI 비서 모델 공급자를 Gemini(`google-genai`, `gemini-2.5-flash`)로 변경 | 적용 |
| C-072 | 2026-11-07 | 구조 | AI 비서 패널: 홈을 옆으로 밀기, 340px로 작게, 좁으면 비서만 | 적용 |
| C-073 | 2026-11-07 | 구조 | AI 비서 패널 폭을 경계선 끌기·←→ 키로 조절 | 적용 |
| C-074 | 2026-11-07 | 구조 | AI 답변 서식(굵게·목록 카드) + 등장·입력 중 애니메이션 | 적용 |
| C-075 | 2026-11-07 | DB 스키마 | 상품 약관 동의(버전 보존·동시성) + 약관 검색 RAG Tool(pgvector) + 검증된 출처 | 적용 |
| C-076 | 2026-11-08 | API | 예금 가입 때 가입 금액·출금 계좌를 받아 개설과 같은 트랜잭션에서 입금 | 적용 |
| C-077 | 2026-11-08 | 구조 | 약관 전문 보기를 같은 탭으로, 돌아와도 가입 입력값·동의 유지 | 적용 |
| C-078 | 2026-11-08 | 구조 | 데모 사용자·계좌 시드 스크립트 `seed_demo.py` | 적용 |
| C-079 | 2026-11-08 | API | 예금 가입 금액 필수화, 가입 후 추가 입금 금지(`POST /transfers/deposit` 삭제) | 적용 |
| C-080 | 2026-11-08 | DB 스키마 | 예금 상품별 최소 가입 금액 `account_products.min_amount` | 적용 |
| C-081 | 2026-11-08 | 문서 | 예금 약관 1.1.0 개정(가입 금액·최소 금액·추가 입금 불가) + 발행·색인 | 적용 |
| C-082 | 2026-11-08 | 보안 | 로그인 실패 한도를 동시 요청으로 우회하던 버그 수정(검증 전에 시도를 먼저 셈) | 적용 |
| C-083 | 2026-11-08 | 보안 | 액세스 토큰 5분 + 갱신 토큰(회전·재사용 감지, 해시 저장) 세션 구조 | 적용 |
| C-084 | 2026-11-08 | API | 아이디 정규화, 이름·휴대폰·비밀번호(영문·숫자·특수문자) 입력 검증 | 적용 |
| C-085 | 2026-11-08 | API | 422 입력 오류 메시지를 한국어 완성 문장으로 | 적용 |
| C-086 | 2026-11-08 | 구조 | 화면: 세션 타이머·자동 갱신·만료 처리, 비밀번호 확인 칸 | 적용 |
| C-087 | 2026-11-08 | 보안 | 액세스 토큰에 세션 번호(`sid`)를 넣고 요청마다 세션 확인 → 로그아웃 등 즉시 적용 | 적용 |
| C-088 | 2026-11-08 | 보안 | 단일 세션(다른 곳 로그인 시 기존 세션 종료, `SESSION_REPLACED`) + 세션 작업의 사용자 행 잠금 | 적용 |
| C-089 | 2026-11-08 | 보안 | 아이디별 속도 제한(IP와 무관하게 15분 10회 실패 후 30초에 1회, 잠그지 않음) | C-090에서 대체 |
| C-090 | 2026-11-08 | 보안 | 은행식 로그인 잠금(5회 연속 → 잠금, DB 원자적 선증가, 동시 요청은 429) | 적용 |
| C-091 | 2026-11-08 | 보안 | 휴대폰 인증번호 구조(HMAC 저장·1회성·발송 제한·개발용 문자함) + 가입·번호 변경 확인 | 적용 |
| C-092 | 2026-11-08 | 보안 | 계좌 비밀번호(숫자 4자리, 돈이 나가는 곳 전부, 5회 잠금, 실패 횟수 커밋 보장) | 적용 |
| C-093 | 2026-11-08 | 보안 | 계정 복구: 아이디 찾기·비밀번호 찾기·계좌 비밀번호 재설정(응답 동일화) | 적용 |
| C-094 | 2026-11-08 | 구조 | 화면: 휴대폰 인증·계좌 비밀번호 입력·찾기 화면·해지 화면 | 적용 |
| C-095 | 2026-11-09 | 보안 | 회원 탈퇴(소프트 삭제·개인정보 가림·계좌 닫기·입금 경합 차단) | 적용 |
| C-096 | 2026-11-09 | 보안 | 토큰 쿠키 전환(갱신 토큰 httpOnly 쿠키·액세스 토큰 메모리·Next.js 프록시·Origin 확인) + 기기 등록(새 기기 휴대폰 인증, 채널별 5회 잠금) | 적용 (기기 해제 버튼 동작·build는 미확인) |
| C-097 | 2026-11-09 | 구조 | 새 기기 로그인의 개발용 문자함: 가려진 번호 대신 번호 직접 입력 | 적용 |
| C-098 | 2026-11-09 | 구조 | 계좌 가입 화면 입력값 유지(바뀔 때마다 맡김, 계좌 비밀번호는 메모리에만, 가입 성공 시 삭제) | 적용 |
| C-099 | 2026-11-09 | API | AI 비서 이체: 내 입출금 계좌 id를 매 턴 프롬프트에 제공, 본인 계좌로는 to_account_id(번호 없이)로 초안 생성, 출금·받는 계좌 오류 코드 분리 | 적용 |
| C-100 | 2026-11-09 | API | AI 비서 이체: 계좌 id 대신 이름으로 찾기(서버가 해석, 없음·여럿이면 후보를 돌려 되묻기). C-099의 매 턴 계좌 목록 대체 | 적용 |
| C-101 | 2026-11-09 | 구조 | AI 비서 모델↔도구 반복을 LangGraph(StateGraph)로 이식. 동작 동일, checkpointer 없음, langchain-google-genai 대신 기존 GeminiModelClient 유지 | 적용 |
| C-102 | 2026-11-09 | API | 이체 한도 오류 메시지에 한도 금액(1회·1일)과 오늘 보낸 금액을 넣음. AI가 한도를 지어내던 문제 | 적용 |
| C-103 | 2026-11-09 | API | AI 비서 예·적금 가입 준비 카드(`prepare_open_account`): 서버가 상품·계좌 이름 찾기, 만기 날짜 계산, 검증 후 가입 화면을 미리 채워 이어 가기. 가입·약관 동의·비밀번호는 화면에서 | 적용 |
| C-104 | 2026-11-09 | API | 계좌 상세 화면 정리(해지하기는 맨 아래 작은 링크, 비밀번호 재설정은 입력칸을 누를 때만) + 예·적금 이자 미리 보기 API(`interest-preview`: 오늘 해지하면 / 만기까지 두면) | 적용 |
| C-105 | 2026-11-09 | 신규 기능 | ClearingHub 연동: 타행 이체 보내기(출금 → 허브 → 완료/환불, 결과 모르면 PENDING + 확인 작업)·받기(`/interbank/*`, Ed25519 서명 검증·응답 서명, 멱등 입금) | 적용 (실제 허브 등록 전) |
| C-106 | 2026-11-09 | 화면 | 이체 완료 화면에 '또 이체하기' 버튼 추가 (완료 화면이 남아 다시 이체할 수 없던 문제) | 적용 |

분류: `문서` · `DB 스키마` · `API` · `보안` · `동시성` · `구조` · `테스트`
상태: `적용` · `되돌림` · `보류`

---

## 작성 규칙

- 변경 하나당 항목 하나. 번호는 `C-001`부터 순서대로 붙이고, 지우지 않는다 (되돌렸으면 상태를 `되돌림`으로 바꾼다).
- **변경 전 / 변경 후**는 코드나 문서를 그대로 인용한다. 말로만 요약하지 않는다.
- **이유**에는 실제로 어떤 상황에서 문제가 되는지(재현 시나리오)를 적는다.
- **팀 논의 포인트**에는 팀이 결정해야 할 것, 내가 다르게 판단할 수도 있었던 부분을 적는다.
- **한눈에 보기(1~3부)와 `docs/NEXT_STEPS.md`도 항목을 추가할 때 같이 고친다.** 이전 항목의 `상태`는 나중 항목이 구현하면 그때 갱신한다 (예: 설계만 했던 항목이 구현되면 "C-0xx에서 구현"으로).
- 1부는 **팀 설계와 달라진 것**, 2부는 **지금 구현된 것**, 3부는 **이미 정한 것**과 `NEXT_STEPS.md` 안내만 적는다(앞으로 할 것·정할 것의 현재 목록은 `NEXT_STEPS.md`). 이유와 검증 같은 자세한 내용은 4부 항목에 쓴다.

---

## 항목 템플릿

```markdown
### C-000. 제목

- **날짜:** YYYY-MM-DD
- **분류:** DB 스키마
- **상태:** 적용
- **바뀐 파일:**
  - `src/avengers_bank/...` (줄 번호 또는 함수명)

#### 변경 전
(원래 코드·문서 인용)

#### 변경 후
(바뀐 코드·문서 인용)

#### 이유
- 어떤 문제가 있었는지
- 재현 시나리오: "A가 ~ 하는 동안 B가 ~ 하면 ~ 가 된다"

#### 영향 범위
- 다른 도메인·API·마이그레이션·테스트에 미치는 영향
- 기존 데이터나 팀원 코드와 호환되는지

#### 검증
- 추가/수정한 테스트, 직접 확인한 방법

#### 팀 논의 포인트
- 팀이 정해야 할 것, 대안
```

### C-105. ClearingHub 연동: 타행 이체 보내기·받기

- **날짜:** 2026-11-09
- **분류:** 신규 기능 / DB 스키마 / 외부 연동
- **상태:** 적용 (2026-11-09 운영 허브에 은행 코드 903으로 등록, ping 통과, 화면에서 보내기·허브에서 받기 시험 성공)
- **바뀐 파일:**
  - `src/avengers_bank/domains/interbank/` (새 도메인: `signing.py`, `hub_client.py`, `service.py`, `receiver.py`, `worker.py`, `router.py`, `schemas.py`, `models.py`)
  - `src/avengers_bank/core/config.py` (허브 연동 설정), `src/avengers_bank/main.py` (라우터·미들웨어·확인 작업 연결)
  - `src/avengers_bank/domains/accounts/{kinds,models,repository}.py` (거래내역 type 3개, 상대 계좌 50자, 1일 한도 합계)
  - `alembic/versions/2026_11_09_1200-a0b1c2d3e4f5_add_interbank_transfers.py`, `alembic/env.py`
  - `frontend/app/transfer/page.tsx`, `frontend/lib/api.ts`, `frontend/components/history-filter.tsx`
  - `tests/test_interbank.py`, `tests/conftest.py`, `pyproject.toml` (`cryptography`, `httpx`)

#### 변경 전
- 이체는 같은 은행 입출금 계좌끼리(`transfer_service.transfer`)뿐이었다. 다른 은행으로 보내거나 받을 방법이 없었다.
- `checking_account_histories.type`은 `TRANSFER_OUT … CLOSE_IN`까지였고 `counterpart_account`는 20자였다.

#### 변경 후
- **보내는 쪽 (SPEC 3·6절)**: 비밀번호 확인 → `[트랜잭션] 출금 + interbank_transfers(PENDING)` → 허브 `POST /v1/transfers` → 결과 반영.
  출금을 되돌리는 것은 응답 본문 `status == "FAILED"`일 때뿐이다. 타임아웃·5xx·202·`status` 없는 4xx·**서명이 틀린 응답**은 모두 "모르는 상태"라 PENDING으로 두고, `worker.py`가 30초마다 `GET /v1/transfers/{id}`로 확인한다 (조회가 404면 되돌리지 않고 같은 `transfer_id`로 재전송).
- **받는 쪽 (SPEC 4절)**: `/interbank/inquiry`, `/interbank/receive`, `/interbank/receive/{id}`. 허브 서명을 원본 바이트로 입금 전에 검증하고, 2xx·4xx 응답(서명 실패 401 포함)에 응답 서명을 붙이는 ASGI 미들웨어(`SignResponses`)를 둔다.
  `transfer_id`가 `interbank_transfers`의 기본키라 같은 ID는 한 번만 입금된다. 동시에 온 같은 ID가 기본키에 걸리면(`IntegrityError`) **4xx로 답하지 않고** 저장된 결과를 읽어 200, 못 읽으면 503이다.
- 사용자용 API: `GET /interbank-transfers/banks`(우리 은행 제외), `POST …/inquiry`, `POST /interbank-transfers`, `GET …/{id}`. 허브 응답이 `FAILED`면 환불 후 오류 응답(`ACCOUNT_NOT_FOUND` 404 등), PENDING이면 201 + `status: "PENDING"`.
- 거래내역 type에 `INTERBANK_OUT`/`INTERBANK_IN`/`INTERBANK_REFUND`를 추가하고, 1일 이체 한도 합계(`sum_today_transfer_amount`)에 `INTERBANK_OUT`을 포함했다.
- 설정: `HUB_URL`, `HUB_PUBLIC_KEY`, `BANK_CODE`, `BANK_NAME`(SpiderBank), `BANK_API_KEY`, `BANK_PRIVATE_KEY`. 하나라도 비면 기능이 꺼지고(`503 INTERBANK_DISABLED`) 확인 작업도 시작하지 않는다.

#### 이유
- 허브(ClearingHub)와 연동해 다른 은행으로 이체하려는 요구 (`SPEC.md`).
- 재현 시나리오(되돌림 규칙): 허브가 입금을 끝냈는데 응답만 타임아웃이면, 이때 출금을 되돌리면 받은 쪽에도 돈이 있고 보낸 사람 계좌에도 돈이 있게 된다(이중 지급). 그래서 응답 서명이 틀린 경우까지 "모르는 상태"로 보고 확정 실패(`FAILED`)일 때만 환불한다.
- 재현 시나리오(동시 중복): 허브가 타임아웃 뒤 같은 `transfer_id`를 다시 보냈는데 첫 요청이 아직 처리 중이면 둘이 겹친다. 하나가 기본키에 걸렸을 때 409 같은 4xx를 주면 허브가 "입금 안 됨"으로 `FAILED` 처리해 보내는 은행이 환불한다. 그래서 200/503만 쓴다.

#### 영향 범위
- 마이그레이션 `a0b1c2d3e4f5`: 새 표, `type` CHECK 교체, `counterpart_account` 20→50자(늘리기만 하므로 기존 값 유지). 내리기(downgrade)는 타행 내역이 있으면 실패한다.
- `ENABLE_DEV_ENDPOINTS` 등 기존 설정·API는 그대로다. 키가 없는 환경(기존 개발·CI)에서는 새 기능만 꺼진다.
- 에이전트(AI 비서)에는 연결하지 않았다. SPEC 6절은 허브 호출을 LLM 도구로 주지 말고 이체 서비스 안에서만 하라고 한다.
- 운영 uvicorn 워커는 1개(Dockerfile)라 확인 작업이 프로세스 안 asyncio 태스크 하나로 돈다.

#### 검증
- `tests/test_interbank.py` 17개: SPEC 2.3·2.5 예시 서명 값 일치, 보내기(완료/확정 실패 환불/타임아웃·5xx·서명 틀림은 PENDING 유지), 확인 작업(완료·환불 1회·404 재전송), 받기(1회 입금, 응답 서명 검증, 서명 실패 401에도 서명, 없는 계좌 404 미기록, 본문 검증, 동시 같은 ID 5건에서 4xx 없음·입금 1건).
- 허브는 `httpx.MockTransport`로 흉내 냈다. **실제 허브와의 연동(등록·`ping`·902 시험·셀프 시험)은 아직 하지 않았다.**

#### 팀 논의 포인트
- 확인 작업이 30분 뒤에도 30초 간격이다(SPEC은 10분으로 늦추라 함). 거래가 늘면 늦춤 규칙과 `FOR UPDATE SKIP LOCKED`를 더한다 (`worker.py`의 `shortcut:` 주석).
- 환불 대상 계좌가 그사이 탈퇴(닫힘)했으면 닫힌 계좌에 돈이 돌아간다. 탈퇴의 "잔액 0 확인"은 PENDING 이체를 모른다 → 탈퇴 시 PENDING 타행 이체가 있으면 막는 것을 다음에 검토.
- 정산·대사(SPEC 10절), 본인 계좌 조회(9절)는 이번 범위에서 뺐다.

### C-106. 이체 완료 화면에 '또 이체하기' 버튼

- **날짜:** 2026-11-09
- **분류:** 화면 (UX 버그)
- **상태:** 적용
- **바뀐 파일:** `frontend/app/transfer/page.tsx`

#### 변경 전
- 이체가 끝나면 `result`/`inter` 상태로 완료 화면을 보여 주는데, 이 상태를 지우는 곳이 없었다. 하단 탭의 '이체'를 눌러도 같은 주소(`/transfer`)라 화면이 새로 만들어지지 않아 완료 화면이 그대로 남았다. 버튼은 '내 계좌 보기' 하나뿐이었다.

#### 변경 후
- 완료·처리 중·실패 화면에 `또 이체하기` 버튼을 더했다. 누르면 `window.location.reload()`로 입력과 잔액을 처음 상태로 되돌린다 (같은 은행·타행 화면 모두).

#### 이유
- 재현: 이체를 한 번 마치고 다시 이체하려고 탭을 누르면 계속 '완료' 화면이 뜬다 (타행 이체 시험 중 발견).

#### 영향 범위
- 프론트만. API·DB 변경 없음. 서버에는 프론트가 없어 재배포 불필요.

#### 검증
- `tsc --noEmit`과 eslint 통과. 브라우저에서 버튼을 직접 누르는 확인은 하지 않았다.

#### 팀 논의 포인트
- 탭을 눌렀을 때 완료 화면이 자동으로 닫히게 하는 방법(경로 키로 다시 만들기)도 있다. 지금은 버튼을 눌러야 한다.

