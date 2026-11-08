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
| 404 | 계좌·카드·상품 없음 (남의 계좌·카드도 404, C-031) | `NotFoundException` |
| 409 | 아이디·계좌번호 중복 | `ConflictException` |
| 429 | 로그인 실패가 너무 많음 (C-040) | `TooManyAttemptsException` |
| 422 | 입력값 형식 오류 (FastAPI 자동) | — |
| 503 | `/health`에서 DB에 연결할 수 없음 (C-046) | `ApiException` |

`GET /health`(로그인 불필요): DB에 `SELECT 1`을 보내 정상이면 `200 { "data": { "status": "ok" } }`, 연결할 수 없으면 `503 DB_UNAVAILABLE`(원인은 응답에 싣지 않고 서버 로그에만 남김). `GET /`는 인사말만 돌려줍니다.

`code`는 `ACCOUNT_NOT_FOUND`, `DAILY_LIMIT_EXCEEDED`처럼 **대문자 스네이크 케이스**로 구체적으로 적습니다.

---

## users: 회원 (`domains/users`)

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/users/signup` | | 회원가입 |
| ✅ | POST | `/users/login` | | 로그인, JWT 발급 |
| ✅ | GET | `/users/me` | 🔒 | 내 정보 조회 |
| ✅ | PATCH | `/users/me` | 🔒 | 이름, 닉네임, 전화번호 수정 |
| ✅ | PATCH | `/users/me/password` | 🔒 | 비밀번호 변경 |

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

- 실패 `401 INVALID_CREDENTIALS`. **같은 아이디를 같은 IP에서 15분 안에 5번 틀리거나, 한 IP에서 20번 틀리면 `429 TOO_MANY_LOGIN_ATTEMPTS`**(`Retry-After` 헤더에 남은 초). 한도가 차면 비밀번호가 맞아도 거절하고, 성공하면 그 아이디의 실패 횟수가 지워집니다. 프로세스 메모리로 세기 때문에 서버 재시작 시 초기화됩니다.

`PATCH /users/me`: 보낸 필드만 바뀝니다. → `200`, 수정된 내 정보(`GET /users/me`와 같은 모양)

`PATCH /users/me/password`: `{ "current_password": "...", "new_password": "..." }` (새 비밀번호 8~128자) → `200`, `data: null`
- 현재 비밀번호가 틀리면 `400 INVALID_CURRENT_PASSWORD`(401은 로그아웃으로 오해될 수 있어 쓰지 않음), 새 비밀번호가 현재와 같으면 `400 SAME_PASSWORD`.
- **현재 비밀번호를 틀린 횟수는 로그인 실패와 같은 한도로 센다**(5번 틀리면 `429`). 기존에 발급된 토큰은 비밀번호를 바꿔도 만료 전까지 유효합니다(토큰 폐기는 4-3).
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

계좌 상품 응답에는 `min_amount`(최소 가입 금액, 원)가 있습니다. 예금 상품에만 값이 있고(어벤져스 정기예금 100,000 / 스타 정기예금 1,000,000 / 모바일 특판예금 500,000) 나머지는 `null`(제한 없음)입니다.
```json
{ "product_id": 3, "type": "DEPOSIT", "name": "어벤져스 정기예금", "description": "목돈을 맡기고 만기에 이자를 받는 예금", "interest_rate": "3.00", "min_amount": 100000 }
```
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
| ✅ | POST | `/accounts/{type}/{account_id}/close` | 🔒 | 예금·적금 해지 (원금+이자를 내 입출금 계좌로) |

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
`POST /accounts/deposit` → `201`: `{ "product_id": 2, "maturity_date": "2027-12-10", "initial_amount": 3000000, "from_checking_account_id": 1 }` (만기일은 오늘보다 뒤)
- `initial_amount`(가입 금액, 양의 정수 원)와 `from_checking_account_id`(출금할 내 입출금 계좌)는 **둘 다 필수**입니다. 하나라도 없거나 금액이 0 이하면 `422`. 가입 금액 없이 0원 예금을 만들 수는 없습니다.
- **계좌 개설(약관 동의 기록 포함)과 입출금 계좌 → 새 예금 이체는 같은 트랜잭션**입니다. 잔액이 모자라거나 실패하면 예금 계좌도 약관 동의 기록도 남지 않습니다(롤백). 응답의 `balance`는 `initial_amount`와 같습니다.
- **상품별 최소 가입 금액:** `initial_amount`가 상품의 `min_amount`보다 작으면 `400 BELOW_MIN_AMOUNT`("이 상품의 최소 가입 금액은 100,000원입니다."), 아무것도 만들어지지 않습니다. `min_amount`가 null이면 1원 이상이면 됩니다.
- 예금은 가입 후 **추가 입금이 불가능**합니다(가입 금액이 곧 원금).
- 거래내역: 입출금 쪽 `TO_DEPOSIT`(상대 계좌 = 예금 계좌번호), 예금 쪽 `TRANSFER_IN`(상대 계좌 = 입출금 계좌번호). 1회·1일 이체 한도는 적용하지 않습니다.
- 실패 예시: `400 INSUFFICIENT_BALANCE`, `400 BELOW_MIN_AMOUNT`, `404 ACCOUNT_NOT_FOUND`(없는 계좌·남의 입출금 계좌), `422`(필수 필드 누락, 금액 0 이하)

`POST /accounts/savings` → `201`: `{ "product_id": 3, "monthly_payment": 100000, "monthly_deposit_date": 25, "maturity_date": "2027-12-10" }`

계좌번호는 서버가 발급합니다: 입출금 `110-`, 예금 `120-`, 적금 `220-`로 시작 (`110-048-767128`).
개설 실패 예시: `400 PRODUCT_TYPE_MISMATCH`, `404 ACCOUNT_PRODUCT_NOT_FOUND`

`GET /accounts/{type}/{account_id}`는 종류별로 필드가 다릅니다(`account_type`으로 구분). 입출금은 `per_transfer_limit`·`daily_transfer_limit`, 예금은 `maturity_date`, 적금은 `monthly_payment`·`monthly_deposit_date`·`maturity_date`가 더 있습니다. 실패: `404 ACCOUNT_NOT_FOUND`(없는 계좌와 남의 계좌를 구분하지 않음)

`GET /accounts/{type}/{account_id}/histories?limit=50&offset=0`: 최신순, `limit` 1~200

검색 조건(모두 선택, 함께 쓰면 AND, C-064):

| 파라미터 | 뜻 | 예 |
|---|---|---|
| `date_from`, `date_to` | 날짜(KST), 양끝 포함 | `date_from=2026-10-01&date_to=2026-10-31` |
| `types` | 거래 종류 코드, 여러 번 쓰면 OR | `types=CARD_PAYMENT&types=CARD_BILL_PAYMENT` |
| `min_amount`, `max_amount` | 금액 범위(0 이상), 양끝 포함 | `min_amount=5000` |
| `q` | 상대 계좌번호·이름(사용처) 일부, 대소문자 무시, 최대 100자. `%`·`_`는 글자 그대로 찾음 | `q=스타벅스` |

카드대금 납부(`CARD_BILL_PAYMENT`) 내역은 `counterpart_name`에 카드 상품 이름, `counterpart_account`에 카드번호가 들어갑니다.
```json
{ "data": [ { "date": "...", "amount": 300, "balance_after": 700, "type": "TRANSFER_OUT", "counterpart_account": "110-111-222222", "counterpart_name": null } ], "message": null }
```

`PATCH /accounts/{type}/{account_id}`: 보낸 필드만 바뀝니다. `nickname`에 `null`을 보내면 별칭을 지웁니다.
```json
{ "nickname": "월급통장", "daily_transfer_limit": 3000000 }
```
실패 예시: `400 INVALID_TRANSFER_LIMIT`(1회 > 1일), `400 TRANSFER_LIMIT_NOT_SUPPORTED`(예금·적금에 한도)
</details>

**해지** `POST /accounts/{deposit|savings}/{account_id}/close`: `{ "to_checking_account_id": 1 }` (내 입출금 계좌) → `200`
```json
{ "data": { "account_type": "deposit", "account_id": 1, "principal": 300000, "interest": 3000, "total_amount": 303000, "early_close": false, "closed_at": "...", "to_account_num": "110-139-957374", "to_balance_after": 803000 }, "message": "계좌가 해지되었습니다." }
```
- 원금과 이자를 합쳐 받을 입출금 계좌로 보냅니다. 입출금 계좌는 해지할 수 없습니다(`400 CLOSE_NOT_SUPPORTED`). 이미 해지했으면 `400 ACCOUNT_CLOSED`. 남의 계좌나 없는 계좌는 `404 ACCOUNT_NOT_FOUND`.
- **이자(단리, 일할):** 입금 한 건마다 `금액 × 연금리 × 경과일 / 365`를 합산하고 원 미만은 버립니다. 경과일은 입금일(KST)부터 해지일까지이고 **만기일까지만** 셉니다(만기 뒤에는 이자가 늘지 않음). **만기일 당일 이후 해지는 전체 금리, 만기 전 해지(`early_close: true`)는 금리의 절반**입니다.
- 해지 계좌 거래내역에는 `INTEREST`(+이자), `CLOSE_OUT`(−원금+이자, 잔액 0)가, 입출금 계좌 거래내역에는 `CLOSE_IN`이 남습니다(잔액이 0이면 내역 없이 해지만 됩니다).
- 해지하면 예금·적금의 `status`가 `CLOSED`, `closed_at`이 채워집니다(`GET /accounts` 목록에도 `status`가 보임, 입출금은 null). 해지한 계좌에는 입금할 수 없습니다(`400 ACCOUNT_CLOSED`). 조회와 거래내역 조회는 계속 됩니다.

## transfers: 돈 이동 (`domains/transfers`)

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/transfers` | 🔒 | 입출금 → 입출금 이체 (잔액, 1회·1일 한도 검사) |
| ✅ | POST | `/transfers/savings` | 🔒 | 입출금 → 적금 납입 |

예금은 가입 후 추가 입금이 불가능합니다(가입 금액이 곧 원금). 가입 금액은 `POST /accounts/deposit`에서 냅니다.

<details>
<summary>요청·응답 예시</summary>

`POST /transfers`: `TransferCreate` 스키마는 `domains/transfers/schemas.py`에 정의되어 있습니다.
```json
{ "from_checking_account_id": 1, "to_account_num": "110-555-000111", "amount": 10000 }
```
실패 예시: `400 INSUFFICIENT_BALANCE`, `400 SAME_ACCOUNT_TRANSFER`, `400 PER_TRANSFER_LIMIT_EXCEEDED`, `400 DAILY_LIMIT_EXCEEDED`, `404 ACCOUNT_NOT_FOUND`

`POST /transfers` → `201`
```json
{ "data": { "from_account_num": "110-139-957374", "to_account_num": "110-729-269723", "amount": 300000, "balance_after": 700000 }, "message": "이체가 완료되었습니다." }
```
- 받는 계좌는 **입출금 계좌번호**(`110-...`)만 가능합니다. 예금·적금 번호는 `404 ACCOUNT_NOT_FOUND`.
- 검사 순서: 내 계좌(남의 계좌도 404) → 받는 계좌(404) → 같은 계좌(400) → 잔액 → 1회 한도 → 1일 한도.
- **1일 한도**는 오늘 00:00 KST부터 이 계좌에서 나간 *이체*(`TRANSFER_OUT`)의 합계입니다. 들어온 돈과 적금·예금으로 보낸 돈은 세지 않습니다.

`POST /transfers/savings`: `{ "from_checking_account_id": 1, "savings_account_id": 1, "amount": 100000 }` → `201`, 같은 모양의 응답
- 적금은 **내 계좌**에만 넣을 수 있습니다(남의 계좌는 `404`). 1회·1일 이체 한도는 적용하지 않고 잔액만 검사합니다. 만기일 당일부터는 `400 ACCOUNT_MATURED`로 거절합니다.

거래내역에는 보낸 쪽과 받은 쪽에 한 줄씩 남습니다(`type`): 이체 `TRANSFER_OUT` / `TRANSFER_IN`, 적금 납입 입출금 쪽 `TO_SAVINGS`, 받은 적금 쪽 `TRANSFER_IN`. (예금 가입 금액의 `TO_DEPOSIT`은 `POST /accounts/deposit` 참고)
실패 예시: `400 INSUFFICIENT_BALANCE`, `400 SAME_ACCOUNT_TRANSFER`, `400 PER_TRANSFER_LIMIT_EXCEEDED`, `400 DAILY_LIMIT_EXCEEDED`, `400 ACCOUNT_MATURED`, `404 ACCOUNT_NOT_FOUND`
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
| ✅ | POST | `/cards/{type}/{card_id}/suspend` | 🔒 | 카드 정지 |
| ✅ | POST | `/cards/{type}/{card_id}/resume` | 🔒 | 카드 정지 해제 |
| ✅ | POST | `/cards/{type}/{card_id}/close` | 🔒 | 카드 해지 |
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
- 연결 계좌는 **내 입출금 계좌**여야 합니다(남의 계좌는 `404 ACCOUNT_NOT_FOUND`). 상품 종류가 다르면 `400 PRODUCT_TYPE_MISMATCH`.

**조회**: `GET /cards`(신용 → 체크 순), `GET /cards/{type}/{card_id}`(종류별 필드가 다름: 신용은 `credit_limit`·`payment_date`), `GET /cards/{type}/{card_id}/histories?limit=50&offset=0`(최신순). 남의 카드와 없는 카드는 모두 `404 CARD_NOT_FOUND`.

**정지·해지** `POST /cards/{type}/{card_id}/suspend`, `/resume`, `/close` (본문 없음) → `200`, 바뀐 카드(`GET /cards/{type}/{card_id}`와 같은 모양). 카드 응답에는 `status`(`ACTIVE`/`SUSPENDED`/`CLOSED`)가 있습니다.
- 정지는 `ACTIVE`에서만, 해제는 `SUSPENDED`에서만, 해지는 `ACTIVE`·`SUSPENDED`에서 할 수 있습니다. 해지는 되돌릴 수 없고, 맞지 않는 상태에서 부르면 `400 INVALID_CARD_STATUS`.
- **신용카드는 미결제액(`outstanding_amount`)이 0이어야 해지됩니다**(`400 CARD_HAS_OUTSTANDING`). 청구 전 사용액과 미납 청구서가 모두 미결제액에 들어 있습니다.
- 정지·해지된 카드로 결제하면 `400 CARD_NOT_ACTIVE`. 정지 중에도 청구서 조회·납부는 됩니다.
신용카드는 `outstanding_amount`(미결제액: 결제하면 늘고 청구서를 납부하면 줆), 체크카드는 `accumulated_amount`(누적 사용액)를 줍니다. `GET /cards` 목록과 결제 응답에서는 해당하지 않는 쪽이 `null`입니다. 체크카드 결제는 입출금 거래내역의 `counterpart_name`에 가맹점명이 남습니다.

**결제(사용)** `POST /cards/{type}/{card_id}/payments`: `{ "place_of_use": "편의점", "used_amount": 30000 }` → `201`
```json
{ "data": { "place_of_use": "편의점", "used_amount": 30000, "time": "...", "outstanding_amount": null, "accumulated_amount": 30000 }, "message": "결제가 등록되었습니다." }
```
- **체크카드:** 연결 계좌에서 바로 출금하고, 입출금 거래내역에 `CARD_PAYMENT`이 남습니다. 잔액이 부족하면 `400 INSUFFICIENT_BALANCE`. 1회·1일 이체 한도는 적용하지 않습니다.
- **신용카드:** 돈은 나가지 않고 미결제액만 늡니다. `미결제액 + 결제 금액`이 한도를 넘으면 `400 CREDIT_LIMIT_EXCEEDED`(딱 한도까지는 허용).

**청구서 납부** `POST /cards/credit/{card_id}/bills/{bill_id}/payments` (body 없음) → `200`: 카드의 **결제 계좌**에서 청구 금액이 출금되고(입출금 거래내역 `CARD_BILL_PAYMENT`, 상대 계좌에 카드번호), 청구서가 `PAID`가 되며, 카드의 미결제액이 그만큼 줄어 한도가 돌아옵니다. 다른 카드의 청구서 번호는 `404 BILL_NOT_FOUND`.
청구서 생성은 이용 기간이 끝난 달만 가능합니다(`BILLING_PERIOD_NOT_ENDED`).


## agent: AI 금융 비서 (`domains/agent`)

자세한 요청·응답, Tool 목록, 이체 확인 흐름은 [AGENT.md](AGENT.md).

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/agent/chat` | 🔒 | 채팅 질문. 이체 요청이면 실행하지 않고 `action`(이체 확인 카드)을 돌려줌 |
| ✅ | POST | `/agent/transfers/{draft_id}/confirm` | 🔒 | 사용자가 확인 카드에서 누른 이체 실행 (잔액·한도 재검사, 한 번만) |
| ✅ | POST | `/agent/transfers/{draft_id}/cancel` | 🔒 | 이체 초안 취소 |

실패 예시: `503 AGENT_UNAVAILABLE`, `504 AGENT_TIMEOUT`, `404 CONVERSATION_NOT_FOUND` / `DRAFT_NOT_FOUND`, `409 DRAFT_EXPIRED` / `DRAFT_NOT_PENDING`

---

## dev: 개발용 (`domains/accounts/dev.py`)

`.env`에 `ENABLE_DEV_ENDPOINTS=true`일 때만 열립니다(기본은 꺼짐). **운영 환경에서는 켜지 않습니다.** 팀 설계에는 없던 API이고, 외부 입금 수단이 없어서 이체·결제를 시험할 잔액을 만들기 위한 것입니다.

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/dev/accounts/checking/{account_id}/charge` | 🔒 | 내 입출금 계좌 잔액 충전 |

`POST /dev/accounts/checking/1/charge`: `{ "amount": 100000 }` → `200`, 갱신된 입출금 계좌(상세 응답과 같은 모양). 거래내역에는 `type` = `DEV_CHARGE`, `balance_after`와 함께 남습니다.
실패 예시: `404 ACCOUNT_NOT_FOUND`, `422`(금액 0 이하 또는 1조 원 초과)

---

## 새 API를 추가하는 순서

1. `schemas.py`: 요청·응답 모양 정의
2. `repository.py`: 필요한 DB 조회·저장 메서드
3. `service.py`: 규칙 검사와 처리 (돈이 움직이면 `async with db.begin():`)
4. `router.py`: 경로 연결, `SuccessResponse[...]`로 감싸서 반환
5. `tests/`에 테스트 추가
6. 이 문서의 상태를 📝 → ✅로 변경
