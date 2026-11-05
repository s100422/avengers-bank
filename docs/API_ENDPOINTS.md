# API 엔드포인트

- 실행 중인 서버에서는 `http://127.0.0.1:8000/docs`(Swagger)에서 직접 호출해 볼 수 있습니다.
- 🔒 표시가 있는 API는 `Authorization: Bearer <access_token>` 헤더가 필요합니다.
- 상태: ✅ 구현됨 / 📝 TODO (router 파일에 주석으로 자리만 잡아 둠)

## 공통 응답 형식

성공:
```json
{ "data": { ... }, "message": "회원가입이 완료되었습니다." }
```

실패:
```json
{ "error": { "code": "INSUFFICIENT_BALANCE", "message": "잔액이 부족합니다.", "details": [] } }
```

| HTTP | 언제 | 예외 클래스 (`core/exceptions.py`) |
|---|---|---|
| 400 | 잔액 부족, 한도 초과 등 처리 불가 | `BadRequestException` |
| 401 | 로그인 안 함, 토큰 만료 | `UnauthorizedException` |
| 403 | 남의 계좌·카드에 접근 | `ForbiddenException` |
| 404 | 계좌·카드·상품 없음 | `NotFoundException` |
| 409 | 아이디·계좌번호 중복 | `ConflictException` |
| 422 | 입력값 형식 오류 (FastAPI 자동) | — |

`code`는 `ACCOUNT_NOT_FOUND`, `DAILY_LIMIT_EXCEEDED`처럼 **대문자 스네이크 케이스**로 구체적으로 적습니다.

---

## users: 회원 (`domains/users`)

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/users/signup` | | 회원가입 |
| ✅ | POST | `/users/login` | | 로그인, JWT 발급 |
| ✅ | GET | `/users/me` | 🔒 | 내 정보 조회 |
| ✅ | PATCH | `/users/me` | 🔒 | 이름, 닉네임, 전화번호 수정 |

<details>
<summary>요청·응답 예시</summary>

`POST /users/signup`
```json
{ "login_id": "ironman", "password": "password1234", "name": "토니 스타크", "nick_name": null, "phone": "010-1234-5678" }
```
→ `201`
```json
{ "data": { "user_id": 1, "login_id": "ironman", "name": "토니 스타크", "nick_name": null, "phone": "010-1234-5678", "created_at": "2026-11-04T10:00:00Z" }, "message": "회원가입이 완료되었습니다." }
```

`POST /users/login`
```json
{ "login_id": "ironman", "password": "password1234" }
```
→ `200`
```json
{ "data": { "access_token": "eyJhbGciOi...", "token_type": "bearer" }, "message": null }
```

`PATCH /users/me`: 보낸 필드만 바뀝니다. → `200`, 수정된 내 정보(`GET /users/me`와 같은 모양)
```json
{ "name": "페퍼 포츠", "nick_name": "CEO", "phone": "010-9999-8888" }
```
- `nick_name`에 `null`을 보내면 닉네임을 지웁니다. `name`·`phone`은 `null`로 비울 수 없습니다(`422`).
- 길이 제한은 가입과 같습니다(이름 1~50자, 닉네임 최대 50자, 전화번호 9~20자).
- **아이디·비밀번호 등 바꿀 수 없는 필드를 보내면 `422`**입니다(조용히 무시하지 않음). 빈 본문 `{}`은 아무것도 바꾸지 않고 `200`입니다.
</details>

## products: 상품 (`domains/products`)

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | GET | `/products/accounts?type=` | | 계좌 상품 목록 (`type` = CHECKING·DEPOSIT·SAVINGS, 생략하면 전체) |
| ✅ | GET | `/products/accounts/{product_id}` | | 계좌 상품 상세 |
| ✅ | GET | `/products/cards?type=` | | 카드 상품 목록 (`type` = CREDIT·DEBIT, 생략하면 전체) |
| ✅ | GET | `/products/cards/{product_id}` | | 카드 상품 상세 |

## accounts: 계좌 (`domains/accounts`)

`{type}` = `checking` · `deposit` · `savings`

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | GET | `/accounts` | 🔒 | 내 계좌 전체 (3종 합쳐서) |
| ✅ | POST | `/accounts/checking` | 🔒 | 입출금 계좌 개설 |
| ✅ | POST | `/accounts/deposit` | 🔒 | 예금 계좌 개설 |
| ✅ | POST | `/accounts/savings` | 🔒 | 적금 계좌 개설 |
| ✅ | GET | `/accounts/{type}/{account_id}` | 🔒 | 계좌 상세 |
| ✅ | GET | `/accounts/{type}/{account_id}/histories` | 🔒 | 거래내역 |
| ✅ | PATCH | `/accounts/{type}/{account_id}` | 🔒 | 별칭, 이체 한도(입출금만) 변경 |

<details>
<summary>요청·응답 예시</summary>

`GET /accounts` → `200`
```json
{ "data": [
  { "account_type": "checking", "account_id": 1, "account_num": "110-123-456789", "balance": 500000, "nickname": "생활비", "created_at": "..." },
  { "account_type": "savings",  "account_id": 1, "account_num": "220-987-654321", "balance": 300000, "nickname": null, "created_at": "..." }
], "message": null }
```
`AccountSummaryResponse` 스키마는 `domains/accounts/schemas.py`에 정의되어 있습니다.

`POST /accounts/checking` (한도를 생략하면 1회 100만 원, 1일 500만 원) → `201`
```json
{ "product_id": 1, "nickname": "생활비", "per_transfer_limit": 1000000, "daily_transfer_limit": 5000000 }
```
`POST /accounts/deposit` → `201`: `{ "product_id": 2, "maturity_date": "2027-12-10" }` (만기일은 오늘보다 뒤)

`POST /accounts/savings` → `201`: `{ "product_id": 3, "monthly_payment": 100000, "monthly_deposit_date": 25, "maturity_date": "2027-12-10" }`

계좌번호는 서버가 발급합니다: 입출금 `110-`, 예금 `120-`, 적금 `220-`로 시작 (`110-048-767128`).
개설 실패 예시: `400 PRODUCT_TYPE_MISMATCH`, `404 ACCOUNT_PRODUCT_NOT_FOUND`

`GET /accounts/{type}/{account_id}`는 종류별로 필드가 다릅니다(`account_type`으로 구분). 입출금은 `per_transfer_limit`·`daily_transfer_limit`, 예금은 `maturity_date`, 적금은 `monthly_payment`·`monthly_deposit_date`·`maturity_date`가 더 있습니다. 실패: `403 ACCOUNT_FORBIDDEN`, `404 ACCOUNT_NOT_FOUND`

`GET /accounts/{type}/{account_id}/histories?limit=50&offset=0`: 최신순, `limit` 1~200
```json
{ "data": [ { "date": "...", "amount": 300, "balance_after": 700, "type": "TRANSFER_OUT", "counterpart_account": "110-111-222222" } ], "message": null }
```

`PATCH /accounts/{type}/{account_id}`: 보낸 필드만 바뀝니다. `nickname`에 `null`을 보내면 별칭을 지웁니다.
```json
{ "nickname": "월급통장", "daily_transfer_limit": 3000000 }
```
실패 예시: `400 INVALID_TRANSFER_LIMIT`(1회 > 1일), `400 TRANSFER_LIMIT_NOT_SUPPORTED`(예금·적금에 한도)
</details>

## transfers: 돈 이동 (`domains/transfers`)

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/transfers` | 🔒 | 입출금 → 입출금 이체 (잔액, 1회·1일 한도 검사) |
| ✅ | POST | `/transfers/savings` | 🔒 | 입출금 → 적금 납입 |
| ✅ | POST | `/transfers/deposit` | 🔒 | 입출금 → 예금 입금 |

<details>
<summary>요청·응답 예시</summary>

`POST /transfers`: `TransferCreate` 스키마는 `domains/transfers/schemas.py`에 정의되어 있습니다.
```json
{ "from_checking_account_id": 1, "to_account_num": "110-555-000111", "amount": 10000 }
```
실패 예시: `400 INSUFFICIENT_BALANCE`, `400 SAME_ACCOUNT_TRANSFER`, `400 PER_TRANSFER_LIMIT_EXCEEDED`, `400 DAILY_LIMIT_EXCEEDED`, `403 ACCOUNT_FORBIDDEN`, `404 ACCOUNT_NOT_FOUND`

`POST /transfers` → `201`
```json
{ "data": { "from_account_num": "110-139-957374", "to_account_num": "110-729-269723", "amount": 300000, "balance_after": 700000 }, "message": "이체가 완료되었습니다." }
```
- 받는 계좌는 **입출금 계좌번호**(`110-...`)만 가능합니다. 예금·적금 번호는 `404 ACCOUNT_NOT_FOUND`.
- 검사 순서: 본인 계좌(403) → 받는 계좌(404) → 같은 계좌(400) → 잔액 → 1회 한도 → 1일 한도.
- **1일 한도**는 오늘 00:00 KST부터 이 계좌에서 나간 *이체*(`TRANSFER_OUT`)의 합계입니다. 들어온 돈과 적금·예금으로 보낸 돈은 세지 않습니다.

`POST /transfers/savings`: `{ "from_checking_account_id": 1, "savings_account_id": 1, "amount": 100000 }` → `201`, 같은 모양의 응답
`POST /transfers/deposit`: `{ "from_checking_account_id": 1, "deposit_account_id": 1, "amount": 200000 }` → `201`
- 적금·예금은 **내 계좌**에만 넣을 수 있습니다(남의 계좌 `403`). 1회·1일 이체 한도는 적용하지 않고 잔액만 검사합니다.

거래내역에는 보낸 쪽과 받은 쪽에 한 줄씩 남습니다(`type`): 이체 `TRANSFER_OUT` / `TRANSFER_IN`, 적금 납입 입출금 쪽 `TO_SAVINGS`, 예금 입금 입출금 쪽 `TO_DEPOSIT`, 받은 적금·예금 쪽 `TRANSFER_IN`.
실패 예시: `400 INSUFFICIENT_BALANCE`, `400 SAME_ACCOUNT_TRANSFER`, `400 PER_TRANSFER_LIMIT_EXCEEDED`, `400 DAILY_LIMIT_EXCEEDED`, `403 ACCOUNT_FORBIDDEN`, `404 ACCOUNT_NOT_FOUND`
</details>

## cards: 카드 (`domains/cards`)

`{type}` = `credit` · `debit`

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | GET | `/cards` | 🔒 | 내 카드 전체 |
| ✅ | POST | `/cards/credit` | 🔒 | 신용카드 발급 (`checking_account_id` = 결제 계좌) |
| ✅ | POST | `/cards/debit` | 🔒 | 체크카드 발급 (`checking_account_id` = 출금 계좌) |
| ✅ | GET | `/cards/{type}/{card_id}` | 🔒 | 카드 상세 |
| ✅ | GET | `/cards/{type}/{card_id}/histories` | 🔒 | 사용내역 |
| ✅ | POST | `/cards/{type}/{card_id}/payments` | 🔒 | 결제(사용) 등록. 체크카드는 연결 계좌에서 바로 출금, 신용카드는 한도 검사 후 미결제액 증가 |
| ✅ | POST | `/cards/credit/{card_id}/bills` | 🔒 | 청구서 생성 (지난 달 미청구 사용내역 합산) |
| ✅ | GET | `/cards/credit/{card_id}/bills` | 🔒 | 청구서 목록 |
| ✅ | GET | `/cards/credit/{card_id}/bills/{bill_id}` | 🔒 | 청구서 상세 (포함된 사용내역) |
| ✅ | POST | `/cards/credit/{card_id}/bills/{bill_id}/payments` | 🔒 | 청구서 납부 (결제 계좌에서 전액 출금) |

신용카드 청구는 스케줄러 없이 **본인이 직접 호출**합니다. 이용 기간은 전월 1일~말일(KST), 납부 예정일은 다음 달 결제일입니다. 부분 납부·연체 이자·리볼빙은 범위 밖입니다.

<details>
<summary>청구서 요청·응답 예시</summary>

`POST /cards/credit/1/bills`
```json
{ "year_month": "2026-10" }
```
→ `201`
```json
{ "data": { "bill_id": 7, "period_start": "2026-10-01", "period_end": "2026-10-31", "total_amount": 80000, "due_date": "2026-11-14", "status": "UNPAID", "paid_at": null }, "message": "청구서가 생성되었습니다." }
```
실패 예시: `400 BILLING_PERIOD_NOT_ENDED`, `400 NO_UNBILLED_USAGE`, `409 BILL_ALREADY_EXISTS`

`POST /cards/credit/1/bills/7/payments` (body 없음) → `200`, `status`가 `PAID`로 바뀐 청구서
실패 예시: `400 INSUFFICIENT_BALANCE`, `409 BILL_ALREADY_PAID`

결제(사용) 실패 예시(신용카드): `400 CREDIT_LIMIT_EXCEEDED`
</details>

**발급**
`POST /cards/credit` → `201`: `{ "product_id": 1, "checking_account_id": 1, "payment_date": 25 }`. 신용 한도는 요청으로 받지 않고 **상품의 한도가 카드로 복사**됩니다(응답에 `credit_limit`).
`POST /cards/debit` → `201`: `{ "product_id": 3, "checking_account_id": 1 }`
- 카드번호는 서버가 발급합니다: 신용 `4000-`, 체크 `5000-`로 시작 (`4000-1234-5678-9012`).
- 연결 계좌는 **내 입출금 계좌**여야 합니다(남의 계좌 `403 ACCOUNT_FORBIDDEN`). 상품 종류가 다르면 `400 PRODUCT_TYPE_MISMATCH`.

**조회**: `GET /cards`(신용 → 체크 순), `GET /cards/{type}/{card_id}`(종류별 필드가 다름: 신용은 `credit_limit`·`payment_date`), `GET /cards/{type}/{card_id}/histories?limit=50&offset=0`(최신순). 남의 카드 `403 CARD_FORBIDDEN`, 없는 카드 `404 CARD_NOT_FOUND`.
`accumulated_amount`의 뜻은 카드마다 다릅니다: **신용카드는 미결제액**(결제하면 늘고 청구서를 납부하면 줆), **체크카드는 누적 사용액**.

**결제(사용)** `POST /cards/{type}/{card_id}/payments`: `{ "place_of_use": "편의점", "used_amount": 30000 }` → `201`
```json
{ "data": { "place_of_use": "편의점", "used_amount": 30000, "time": "...", "accumulated_amount": 30000 }, "message": "결제가 등록되었습니다." }
```
- **체크카드:** 연결 계좌에서 바로 출금하고, 입출금 거래내역에 `CARD_PAYMENT`이 남습니다. 잔액이 부족하면 `400 INSUFFICIENT_BALANCE`. 1회·1일 이체 한도는 적용하지 않습니다.
- **신용카드:** 돈은 나가지 않고 미결제액만 늡니다. `미결제액 + 결제 금액`이 한도를 넘으면 `400 CREDIT_LIMIT_EXCEEDED`(딱 한도까지는 허용).

**청구서 납부** `POST /cards/credit/{card_id}/bills/{bill_id}/payments` (body 없음) → `200`: 카드의 **결제 계좌**에서 청구 금액이 출금되고(입출금 거래내역 `CARD_BILL_PAYMENT`, 상대 계좌에 카드번호), 청구서가 `PAID`가 되며, 카드의 미결제액이 그만큼 줄어 한도가 돌아옵니다. 다른 카드의 청구서 번호는 `404 BILL_NOT_FOUND`.
청구서 생성은 이용 기간이 끝난 달만 가능합니다(`BILLING_PERIOD_NOT_ENDED`).


## dev: 개발용 (`domains/accounts/dev.py`)

`.env`에 `ENABLE_DEV_ENDPOINTS=true`일 때만 열립니다(기본은 꺼짐). **운영 환경에서는 켜지 않습니다.** 팀 설계에는 없던 API이고, 외부 입금 수단이 없어서 이체·결제를 시험할 잔액을 만들기 위한 것입니다.

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/dev/accounts/checking/{account_id}/charge` | 🔒 | 내 입출금 계좌 잔액 충전 |

`POST /dev/accounts/checking/1/charge`: `{ "amount": 100000 }` → `200`, 갱신된 입출금 계좌(상세 응답과 같은 모양). 거래내역에는 `type` = `DEV_CHARGE`, `balance_after`와 함께 남습니다.
실패 예시: `403 ACCOUNT_FORBIDDEN`, `404 ACCOUNT_NOT_FOUND`, `422`(금액 0 이하 또는 1조 원 초과)

---

## 새 API를 추가하는 순서

1. `schemas.py`: 요청·응답 모양 정의
2. `repository.py`: 필요한 DB 조회·저장 메서드
3. `service.py`: 규칙 검사와 처리 (돈이 움직이면 `async with db.begin():`)
4. `router.py`: 경로 연결, `SuccessResponse[...]`로 감싸서 반환
5. `tests/`에 테스트 추가
6. 이 문서의 상태를 📝 → ✅로 변경
