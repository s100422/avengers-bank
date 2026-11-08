# API 엔드포인트

- 실행 중인 서버에서는 `http://127.0.0.1:8000/docs`(Swagger)에서 직접 호출해 볼 수 있습니다.
- 🔒 표시가 있는 API는 `Authorization: Bearer <access_token>` 헤더가 필요합니다.
  - 토큰은 2종입니다. **액세스 토큰**(JWT, 5분, 자기가 속한 세션 번호 `sid`를 담음)은 API 호출에 쓰고, **갱신 토큰**(임의 문자열, 30분 슬라이딩: 갱신할 때마다 다시 30분, 서버에는 SHA-256 해시만 저장)은 `POST /users/token/refresh`로 새 액세스 토큰을 받을 때만 씁니다. 수명은 `.env`의 `ACCESS_TOKEN_EXPIRE_MINUTES`·`SESSION_EXPIRE_MINUTES`로 바꿉니다. 서버는 요청마다 액세스 토큰의 세션이 살아 있는지 확인하므로, **로그아웃·모든 기기 로그아웃·비밀번호 변경은 즉시 적용**됩니다(끊긴 세션의 액세스 토큰은 다음 요청부터 `401 INVALID_TOKEN`). 자세한 구조는 [AUTH.md](AUTH.md)를 보세요.
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
| 403 | 로그인 잠김(`ACCOUNT_LOCKED`), 계좌 비밀번호 잠김(`ACCOUNT_PASSWORD_LOCKED`) | `ForbiddenException` |
| 404 | 계좌·카드·상품 없음 (남의 계좌·카드도 404, C-031) | `NotFoundException` |
| 409 | 아이디·계좌번호 중복 | `ConflictException` |
| 429 | IP당 로그인 실패·인증번호 요청이 너무 많음, 같은 아이디 동시 로그인 요청 (C-040, C-090) | `TooManyAttemptsException` / `ApiException` |
| 422 | 입력값 형식 오류 (FastAPI 자동) | — |
| 503 | `/health`에서 DB에 연결할 수 없음 (C-046) | `ApiException` |

`422 VALIDATION_ERROR`는 `details`에 잘못된 필드마다 하나씩 담깁니다. `msg`는 **필드 이름표가 들어간 한국어 완성 문장**이라 화면에 그대로 보여 줘도 됩니다(`core/exception_handlers.py`의 `FIELD_LABELS`·`korean_message`가 만듦, 이름표가 없는 필드는 "입력값"). 검증기가 직접 낸 메시지(`type: "value_error"`)는 그 문장이 그대로 나갑니다.
```json
{ "error": { "code": "VALIDATION_ERROR", "message": "입력값을 확인해 주세요.", "details": [
  { "loc": ["body", "password"], "msg": "비밀번호는 8자 이상 입력해 주세요.", "type": "string_too_short" },
  { "loc": ["body", "phone"], "msg": "휴대폰 번호를 010-1234-5678 형식으로 입력해 주세요.", "type": "value_error" }
] } }
```

`GET /health`(로그인 불필요): DB에 `SELECT 1`을 보내 정상이면 `200 { "data": { "status": "ok" } }`, 연결할 수 없으면 `503 DB_UNAVAILABLE`(원인은 응답에 싣지 않고 서버 로그에만 남김). `GET /`는 인사말만 돌려줍니다.

`code`는 `ACCOUNT_NOT_FOUND`, `DAILY_LIMIT_EXCEEDED`처럼 **대문자 스네이크 케이스**로 구체적으로 적습니다.

---

## users: 회원 (`domains/users`)

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/users/signup` | | 회원가입 (휴대폰 인증 증표 필수) |
| ✅ | POST | `/users/login` | | 로그인, 액세스·갱신 토큰 발급 |
| ✅ | POST | `/users/token/refresh` | | 갱신 토큰으로 새 토큰 묶음 받기 (갱신 토큰은 교체됨) |
| ✅ | POST | `/users/logout` | | 로그아웃 (이 기기의 세션 폐기) |
| ✅ | POST | `/users/logout-all` | 🔒 | 모든 기기에서 로그아웃 (이 사용자의 모든 세션 폐기) |
| ✅ | GET | `/users/me` | 🔒 | 내 정보 조회 |
| ✅ | PATCH | `/users/me` | 🔒 | 이름, 닉네임, 전화번호 수정 (번호를 바꿀 때만 휴대폰 인증 증표) |
| ✅ | PATCH | `/users/me/password` | 🔒 | 비밀번호 변경 (모든 세션 폐기 후 이 기기에 새 토큰) |

**입력 규칙** (가입·내 정보 수정이 같은 규칙, `domains/users/validators.py`. 어기면 `422`, `msg`에 이유 문장)
- 아이디: 앞뒤 공백 제거·소문자로 바꾼 뒤 `^[a-z0-9_]{4,20}$` (`" IronMan "` → `ironman`).
- 비밀번호: 8~128자, 영문·숫자·특수문자(`!@#$` 같은 키보드 기호) 각 1자 이상, 키보드 문자만(한글·공백 불가), 아이디와 같으면 안 됨(대소문자 무시).
- 이름: 앞뒤 공백 제거 후 1~50자. 닉네임: 최대 50자, 빈 문자열(공백만 포함)은 `null`로 저장.
- 휴대폰: 하이픈·공백은 무시하고 `01X` 휴대폰 번호(010·011·016·017·018·019, 10~11자리)만 받아 `010-1234-5678`(10자리는 `011-123-4567`) 모양으로 저장.
- **로그인의 비밀번호와 비밀번호 변경의 `current_password`에는 강도 규칙이 없습니다**(규칙 이전에 만든 계정도 로그인·변경 가능).

<details>
<summary>요청·응답 예시</summary>

`POST /users/signup`
```json
{ "login_id": "ironman", "password": "Passw0rd!23", "name": "토니 스타크", "nick_name": null, "phone": "01012345678", "phone_verification_token": "eyJhbGciOi..." }
```
- `phone_verification_token`(필수): `POST /verification/phone/send`(purpose `SIGNUP_PHONE`) → `POST /verification/phone/verify`로 받은 증표. **`phone`과 같은 번호로 받은 것**이어야 하고, 가입과 같은 트랜잭션에서 1회 사용됩니다(가입이 실패해 롤백되면 다시 쓸 수 있음). 만료·다른 번호·이미 사용·위조면 `400 INVALID_VERIFICATION_TOKEN`. 가입하면 `users.phone_verified_at`이 채워집니다.

→ `201`
```json
{ "data": { "user_id": 1, "login_id": "ironman", "name": "토니 스타크", "nick_name": null, "phone": "010-1234-5678", "created_at": "2026-11-04T10:00:00Z" }, "message": "회원가입이 완료되었습니다." }
```

`POST /users/login`
```json
{ "login_id": "ironman", "password": "Passw0rd!23" }
```
→ `200` (토큰이 담긴 응답에는 `Cache-Control: no-store` 헤더가 붙습니다. 갱신·비밀번호 변경도 같음)
```json
{ "data": { "access_token": "eyJhbGciOi...", "token_type": "bearer", "refresh_token": "Xk3...(임의 문자열)", "expires_in": 300, "session_expires_at": "2026-11-08T10:30:00Z" }, "message": null }
```
- **단일 세션:** 로그인하면 이 사용자의 **다른 모든 세션이 끊깁니다**(다른 곳에서 로그인돼 있던 기기는 다음 요청부터 401, 갱신하면 `401 SESSION_REPLACED`).
- `expires_in`: 액세스 토큰 수명(초). 프론트는 이보다 조금 일찍 갱신하면 됩니다. `session_expires_at`: 갱신 토큰 만료 시각(UTC). 그때까지 갱신하지 않으면 다시 로그인해야 합니다.
- 아이디는 앞뒤 공백 제거·소문자로 바꿔서 찾습니다. **형식 검사는 하지 않으므로** 아이디 규칙에 맞지 않는 값도 `422`가 아니라 `401`입니다(아이디 규칙을 흘리지 않고, 옛 규칙으로 만든 계정도 막지 않기 위해).
- 실패 `401 INVALID_CREDENTIALS`(없는 아이디·틀린 비밀번호 구분 없음).
- **로그인 잠금(은행식, C-090):** 같은 아이디로 **5회 연속** 틀리면 그 아이디가 잠깁니다. 5번째 실패의 응답부터 `403 ACCOUNT_LOCKED`("비밀번호를 5회 잘못 입력해 로그인이 잠겼습니다. 비밀번호 찾기에서 본인 확인 후 해제해 주세요.")이고, **잠긴 뒤에는 맞는 비밀번호도 거절**합니다. 시간이 지나도 풀리지 않습니다.
  - 해제: **비밀번호 찾기**(`POST /recovery/password`), 관리자 명령(`uv run python -m avengers_bank.admin unlock|reset-password <login_id>`), 개발용 `POST /dev/users/{login_id}/unlock`.
  - 로그인에 성공하면 실패 횟수가 0이 됩니다('연속' 실패만 셈). 비밀번호 변경에서 현재 비밀번호를 틀린 것도 **같은 카운터**로 셉니다.
  - DB(`users.failed_login_count`·`login_locked_at`)에 세므로 서버를 재시작해도, 서버가 여러 대여도 유지됩니다. 없는 아이디는 행이 없어 잠금이 없고 IP 한도만 적용됩니다.
  - **동시 요청:** 비밀번호를 검증하기 *전에* 'UPDATE ... 횟수 < 5인 행만 +1' 한 문장으로 시도를 먼저 세므로, 같은 아이디로 동시에 30개를 보내도 정확히 5번만 검증됩니다. 이미 동시 요청들이 시도 5번을 가져가 검증 중이라 잠긴 것은 아닐 때는 `429 TOO_MANY_LOGIN_ATTEMPTS`("로그인 요청이 동시에 너무 많습니다.", `Retry-After: 1`)입니다(잠긴 게 아니므로 잠시 후 다시 시도하면 됨).
- **IP 한도:** 한 IP에서 15분 안에 로그인 실패 20회면 `429 TOO_MANY_LOGIN_ATTEMPTS`(`Retry-After` 헤더에 남은 초). 아이디를 바꿔 가며 찔러 보는 공격용이고, 성공한 시도는 이번 한 건만 기록에서 빠집니다. 프로세스 메모리로 세므로 서버 재시작 시 초기화되고, 서버(워커)가 여러 개면 각자 셉니다.

`POST /users/token/refresh` (인증 헤더 불필요: 액세스 토큰이 만료됐을 때 부르는 API)
```json
{ "refresh_token": "Xk3..." }
```
→ `200`, 로그인과 같은 모양의 토큰 묶음. `session_expires_at`은 지금부터 다시 30분으로 연장됩니다.
- **갱신 토큰은 한 번 쓰면 교체됩니다.** 응답의 새 `refresh_token`을 저장하고, 쓴 토큰은 버립니다.
- `401 INVALID_REFRESH_TOKEN`: 모르는 토큰, 만료(30분 미사용), 로그아웃·비밀번호 변경 등으로 끊긴 세션. → 다시 로그인.
- `401 SESSION_REPLACED`("다른 곳에서 로그인되어 로그아웃되었습니다."): 같은 아이디로 다른 곳에서 로그인해 이 세션이 끊김. 화면은 본인이 아니면 비밀번호를 바꾸라고 안내합니다.
- `401 REFRESH_TOKEN_REUSED`: **이미 교체된 토큰을 다시 냄** = 토큰이 새어 나갔을 수 있으므로 그 세션(같은 로그인에서 이어진 토큰 전체)을 폐기합니다. 진짜 사용자도 다시 로그인해야 합니다.

`POST /users/logout` (인증 헤더 불필요: 액세스 토큰이 만료된 상태에서도 로그아웃할 수 있게)
```json
{ "refresh_token": "Xk3..." }
```
→ `200 { "data": null, "message": "로그아웃되었습니다." }`
- 그 토큰의 세션(이 기기)을 폐기합니다. 다른 기기의 세션은 그대로입니다.
- **멱등**: 모르는 토큰·이미 끊긴 토큰이어도 `200`.
- 그 세션의 액세스 토큰도 **다음 요청부터 바로** `401`입니다(5분이 남았어도).

`POST /users/logout-all` 🔒 (본문 없음)
→ `200 { "data": null, "message": "모든 기기에서 로그아웃되었습니다." }`
- 이 사용자의 **모든 세션(이 기기 포함)**을 폐기합니다. 비밀번호 변경과 같은 폐기이지만 새 세션은 주지 않습니다. 다른 기기에서 로그인해 둔 것이 걱정될 때 씁니다.
- `/users/logout`과 달리 **액세스 토큰이 필요**합니다(남의 모든 세션을 끊는 데 쓰이면 안 되므로). 없으면 `401`.
- 다른 기기의 액세스 토큰도 다음 요청부터 바로 `401`입니다.

`PATCH /users/me`: 보낸 필드만 바뀝니다. → `200`, 수정된 내 정보(`GET /users/me`와 같은 모양)
```json
{ "name": "페퍼 포츠", "nick_name": "CEO", "phone": "010-9999-8888" }
```
- 입력 규칙은 가입과 같습니다(위 **입력 규칙**).
- **휴대폰 번호를 바꿀 때만** `phone_verification_token`이 필요합니다: `POST /verification/phone/send-for-me`(purpose `CHANGE_PHONE`, **새 번호**) → `verify`로 받은 증표. 이 사용자가 그 새 번호로 받은 것만 통과하고 1회 사용됩니다. 번호가 바뀌는데 증표가 없으면 `400 PHONE_VERIFICATION_REQUIRED`, 증표가 틀리면 `400 INVALID_VERIFICATION_TOKEN`. 지금과 같은 번호를 보내거나 다른 필드만 바꿀 때는 필요 없습니다.
```json
{ "phone": "010-9999-8888", "phone_verification_token": "eyJhbGciOi..." }
```
- `nick_name`에 `null`이나 빈 문자열을 보내면 닉네임을 지웁니다. `name`·`phone`은 `null`로 비울 수 없습니다(`422`).
- **아이디·비밀번호 등 바꿀 수 없는 필드를 보내면 `422`**입니다(조용히 무시하지 않음). 빈 본문 `{}`은 아무것도 바꾸지 않고 `200`입니다.

`PATCH /users/me/password` 🔒
```json
{ "current_password": "Passw0rd!23", "new_password": "N3wPassw0rd!" }
```
→ `200`, 로그인과 같은 모양의 토큰 묶음 (`message`: "비밀번호가 변경되었습니다.")
- **이 사용자의 모든 세션(모든 기기의 갱신 토큰)을 폐기하고, 지금 이 기기용 새 세션을 발급합니다.** 프론트는 응답의 토큰으로 바꿔 끼웁니다. 다른 기기의 액세스 토큰도 다음 요청부터 바로 `401`입니다.
- `new_password`는 가입과 같은 강도 규칙(어기면 `422`). `current_password`는 규칙 없음.
- `400 SAME_PASSWORD`: 새 비밀번호가 현재와 같음. `400 PASSWORD_SAME_AS_LOGIN_ID`: 새 비밀번호가 아이디와 같음(대소문자 무시).
- `400 INVALID_CURRENT_PASSWORD`: 현재 비밀번호가 틀림(401은 로그아웃으로 오해될 수 있어 쓰지 않음).
- **현재 비밀번호를 틀린 횟수는 로그인 잠금과 같은 DB 카운터로 셉니다**(연속 5번째면 `403 ACCOUNT_LOCKED`로 로그인까지 잠김, 이미 잠겼으면 `403 ACCOUNT_LOCKED`, 동시 요청이 5번을 다 가져갔으면 `429 TOO_MANY_LOGIN_ATTEMPTS`). `SAME_PASSWORD`·`PASSWORD_SAME_AS_LOGIN_ID`는 실패로 세지 않습니다.
</details>

## verification: 휴대폰 인증번호 (`domains/verification`)

가입·번호 변경·계좌 비밀번호 재설정에 쓰는 문자 인증(C-090). 흐름: **발송**(`verification_id`) → **확인**(`verification_token` 증표) → 증표를 가입·번호 변경·계좌 비밀번호 요청에 넣으면 그 요청에서 **1회 사용**됩니다.

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/verification/phone/send` | | 인증번호 발송 (purpose `SIGNUP_PHONE`만) |
| ✅ | POST | `/verification/phone/send-for-me` | 🔒 | 로그인한 사용자의 인증번호 발송 (`CHANGE_PHONE`, `ACCOUNT_PASSWORD_RESET`) |
| ✅ | POST | `/verification/phone/verify` | | 인증번호 확인 → `verification_token` |

<details>
<summary>요청·응답 예시</summary>

`POST /verification/phone/send`
```json
{ "phone": "010-1234-5678", "purpose": "SIGNUP_PHONE" }
```
→ `200 { "data": { "verification_id": 12, "expires_in": 600 }, "message": "인증번호를 보냈습니다." }`
- 이미 가입된 번호인지 알려 주지 않습니다(언제나 같은 응답).

`POST /verification/phone/send-for-me` 🔒
```json
{ "purpose": "CHANGE_PHONE", "phone": "010-9999-8888" }
```
- `CHANGE_PHONE`: 바꿀 **새 번호**로 보냅니다. `phone` 필수(없으면 `422`).
- `ACCOUNT_PASSWORD_RESET`: **등록된 번호로만** 보냅니다. `phone`은 생략해도 되고, 보내도 무시합니다(훔친 세션으로 남의 번호를 넣어 계좌 비밀번호를 바꾸지 못하게). `{ "purpose": "ACCOUNT_PASSWORD_RESET" }`
- 응답은 `/send`와 같은 모양.

`POST /verification/phone/verify`
```json
{ "verification_id": 12, "code": "123456" }
```
→ `200 { "data": { "verification_token": "eyJhbGciOi..." }, "message": "인증되었습니다." }`

**규칙**
- 인증번호: 숫자 6자리, **10분** 유효, 하나당 **5회**까지 확인 가능, 확인 성공은 한 번뿐. DB에는 원문이 아니라 **서버 비밀키 HMAC-SHA256**(id + 코드)만 저장합니다.
- 증표(`verification_token`): 10분, **1회용**(DB `consumed_at`으로 보장). 용도(purpose)·번호·사용자가 맞는 요청에서만 통과합니다.
- 발송 제한: **같은 번호 15분 3번**(DB에서 셈, 모든 용도 합산), **한 IP 15분 10번**(메모리). 넘으면 `429 TOO_MANY_VERIFICATION_REQUESTS`(`Retry-After` 헤더).
- 오류:
  - `400 INVALID_VERIFICATION_CODE`: 인증번호가 틀림. 메시지에 `(N/5)`.
  - `400 VERIFICATION_EXPIRED`: 없는 `verification_id`, 10분 지남, 5회를 다 씀, 이미 확인함 → 다시 받기.
  - `400 INVALID_VERIFICATION_TOKEN`: 증표를 쓰는 쪽(가입·번호 변경·계좌 비밀번호·비밀번호 찾기)에서, 만료·위조·용도/번호/사용자 불일치·이미 사용한 증표.
  - `code`는 1~10자 아무 문자열이나 받습니다(형식이 틀려도 `422`가 아니라 틀린 시도 1회).
- 실제 문자 발송은 아직 없습니다. 개발용 발송기(`SMS_SENDER=dev`, 다른 값이면 서버가 시작되지 않음)가 **서버 로그에 찍고 메모리 문자함에 쌓습니다** → 개발용 `GET /dev/sms?phone=...`로 읽습니다(아래 dev).
</details>

## recovery: 아이디·비밀번호 찾기 (`domains/recovery`)

은행형 계정 복구: **입출금 계좌번호 + 그 계좌 비밀번호**(아는 것) + **등록 휴대폰 인증번호**(가진 것). 로그인 5회 잠금은 비밀번호 찾기로 풀립니다(그 밖에는 관리자 명령). 배경은 [ACCOUNT_RECOVERY_RESEARCH.md](ACCOUNT_RECOVERY_RESEARCH.md).

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/recovery/start` | | 정보 확인 → 맞으면 등록 휴대폰으로 인증번호 발송. 항상 같은 응답 |
| ✅ | POST | `/recovery/verify` | | 인증번호 확인 → 아이디 찾기는 끝, 비밀번호 찾기는 `reset_token` |
| ✅ | POST | `/recovery/password` | | 새 비밀번호 설정 (잠금 해제, 모든 세션 폐기) |

<details>
<summary>요청·응답 예시</summary>

`POST /recovery/start`
```json
{ "purpose": "PASSWORD_RESET", "login_id": "ironman", "account_num": "110-123-456789", "account_password": "4821" }
```
→ `200` (`Cache-Control: no-store`)
```json
{ "data": { "recovery_token": "eyJhbGciOi...", "expires_in": 600 }, "message": "입력하신 정보가 맞으면 등록된 휴대폰으로 인증번호를 보냈습니다." }
```
- `purpose`: `PASSWORD_RESET`(`login_id` 필수, 없으면 `422`) 또는 `FIND_LOGIN_ID`(`login_id` 보내지 않음, 보내도 무시).
- **언제나 같은 응답:** 계좌가 없든, 계좌 비밀번호가 틀리든·미설정이든·잠겼든, 아이디가 계좌 주인과 다르든 같은 모양의 `recovery_token`이 옵니다(가짜 토큰도 진짜와 구분되지 않음). 응답 시간도 맞춥니다. **번호당 발송 제한(15분 3번)에 걸려도 같은 200**이고 문자만 보내지 않습니다(429로 알리면 정보가 맞았다는 사실이 드러나므로).
- 계좌 비밀번호는 기존 규칙대로 셉니다: 계좌가 있으면 틀릴 때마다 실패 +1, 5번째면 그 계좌가 잠깁니다(응답은 여전히 같은 200).
- `429 TOO_MANY_VERIFICATION_REQUESTS`는 **IP 한도(15분 10번)**뿐이며, 정보가 틀린 요청도 셉니다.

`POST /recovery/verify`
```json
{ "recovery_token": "eyJhbGciOi...", "code": "123456" }
```
→ `200` (`Cache-Control: no-store`)
- `FIND_LOGIN_ID`: `{ "masked_login_id": "ir****n" }` (앞 2자 + 마지막 1자). **전체 아이디는 등록 휴대폰으로 문자**가 갑니다.
- `PASSWORD_RESET`: `{ "reset_token": "eyJhbGciOi...", "expires_in": 600 }` (10분, 1회용)
- 오류는 `/verification/phone/verify`와 같습니다: `400 INVALID_VERIFICATION_CODE`(`N/5`), `400 VERIFICATION_EXPIRED`(5회 다 씀·만료·위조된 `recovery_token`). 가짜 토큰도 같은 코드·문구·횟수로 응답합니다.

`POST /recovery/password`
```json
{ "reset_token": "eyJhbGciOi...", "new_password": "N3wPassw0rd!" }
```
→ `200 { "data": null, "message": "비밀번호를 재설정했습니다. 새 비밀번호로 로그인해 주세요." }`
- 새 비밀번호로 바꾸고 **로그인 잠금 해제(실패 0)**, **모든 기기의 세션 폐기**, 등록 휴대폰으로 **알림 문자**. **자동 로그인은 하지 않습니다**(토큰을 주지 않음).
- `new_password`는 가입과 같은 강도 규칙(어기면 `422`).
- `400 INVALID_VERIFICATION_TOKEN`: `reset_token`이 만료·위조·이미 사용됨.
- `400 PASSWORD_SAME_AS_LOGIN_ID`, `400 SAME_PASSWORD`(현재 비밀번호와 같음): 이 경우 `reset_token` 사용이 되돌려지므로 고쳐서 다시 보낼 수 있습니다.
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
| ✅ | POST | `/accounts/{type}/{account_id}/password` | 🔒 | 계좌 비밀번호 설정·재설정 (휴대폰 인증 증표, 5회 잠금 해제 겸함) |

**계좌 비밀번호** (숫자 4자리, 3종 계좌 모두. `domains/accounts/password.py`)
- **개설할 때 필수** `account_password`: 숫자 4자리, 같은 숫자 4개(`1111`)·연속 숫자(`1234`, `9876`) 불가(어기면 `422`). 응답에는 절대 담기지 않고 argon2 해시만 저장합니다.
- **돈이 나가는 요청에는 필수** `account_password`(돈이 빠져나가는 계좌의 비밀번호, 형식 검사 없음 — 틀린 값은 실패 횟수로 셈):
  `POST /transfers`, `POST /transfers/savings`(보내는 입출금 계좌), `POST /accounts/{type}/{id}/close`(해지하는 예금·적금 계좌), `POST /cards/credit/{card_id}/bills/{bill_id}/payments`(카드의 결제 계좌), `POST /agent/transfers/{draft_id}/confirm`(보내는 입출금 계좌, 본문). 예금 개설은 가입 금액이 나가는 입출금 계좌의 비밀번호를 `from_account_password`로 따로 받습니다.
- 오류:
  - `400 ACCOUNT_PASSWORD_NOT_SET`: 비밀번호를 정하지 않은 계좌(예전에 만든 계좌). 계좌 상세에서 먼저 설정.
  - `400 ACCOUNT_PASSWORD_INCORRECT`: 틀림. 메시지에 `(N/5)`.
  - `403 ACCOUNT_PASSWORD_LOCKED`: **5회 틀려 잠김**(5번째 실패 응답부터). 맞는 비밀번호도 거절하고, 휴대폰 인증 후 재설정으로만 풀립니다.
- 검증은 본 작업 전에 **그 계좌 행 하나만 잠그는 짧은 트랜잭션**에서 하고 먼저 커밋합니다(실패 횟수가 롤백되지 않게, 동시에 20건을 보내도 정확히 5번만 검증). 비밀번호를 검증하기 전에 본인 계좌인지 먼저 봅니다(남의 계좌는 `404`).
- 계좌 응답(`GET /accounts` 목록과 상세 모두)에 `password_set`(정했는가, `false`면 돈이 나가지 않음)·`password_locked`(5회 틀려 잠겼는가)가 있습니다.
- **체크카드 결제(`POST /cards/debit/{id}/payments`)는 계좌 비밀번호를 받지 않습니다.** 가맹점 결제는 실제로는 카드 PIN·카드사 인증 영역이고(이 API는 가맹점 결제 흉내), 계좌 비밀번호는 은행 앱에서 계좌 돈을 직접 옮길 때 쓰는 것이기 때문입니다.

<details>
<summary>요청·응답 예시</summary>

`GET /accounts` → `200`
```json
{ "data": [
  { "account_type": "checking", "account_id": 1, "account_num": "110-123-456789", "balance": 500000, "nickname": "생활비", "created_at": "...", "status": null, "password_set": true, "password_locked": false },
  { "account_type": "savings",  "account_id": 1, "account_num": "220-987-654321", "balance": 300000, "nickname": null, "created_at": "...", "status": "ACTIVE", "password_set": true, "password_locked": false }
], "message": null }
```
`AccountSummaryResponse` 스키마는 `domains/accounts/schemas.py`에 정의되어 있습니다.

`POST /accounts/checking` (한도를 생략하면 1회 100만 원, 1일 500만 원) → `201`
```json
{ "product_id": 1, "account_password": "4821", "terms": { "revision_id": 1, "set_hash": "...", "agreements": [ { "terms_version_id": 1, "agreed": true } ] }, "nickname": "생활비", "per_transfer_limit": 1000000, "daily_transfer_limit": 5000000 }
```
- `account_password`(새 계좌의 비밀번호)와 `terms`(화면에서 본 약관 집합과 항목별 동의, C-075)는 3종 개설 모두 필수입니다. 아래 예시에서는 `terms`를 줄였습니다.

`POST /accounts/deposit` → `201`: `{ "product_id": 2, "account_password": "4821", "terms": {...}, "maturity_date": "2027-12-10", "initial_amount": 3000000, "from_checking_account_id": 1, "from_account_password": "7392" }` (만기일은 오늘보다 뒤)
- `initial_amount`(가입 금액, 양의 정수 원)와 `from_checking_account_id`(출금할 내 입출금 계좌), `from_account_password`(그 입출금 계좌의 비밀번호)는 **모두 필수**입니다. 하나라도 없거나 금액이 0 이하면 `422`. 가입 금액 없이 0원 예금을 만들 수는 없습니다.
- 출금 계좌 비밀번호는 개설 트랜잭션보다 **먼저 따로 검증**합니다. 틀리면 `400 ACCOUNT_PASSWORD_INCORRECT`·`403 ACCOUNT_PASSWORD_LOCKED` 등으로 끝나고 예금은 만들어지지 않습니다(실패 횟수는 남음).
- **계좌 개설(약관 동의 기록 포함)과 입출금 계좌 → 새 예금 이체는 같은 트랜잭션**입니다. 잔액이 모자라거나 실패하면 예금 계좌도 약관 동의 기록도 남지 않습니다(롤백). 응답의 `balance`는 `initial_amount`와 같습니다.
- **상품별 최소 가입 금액:** `initial_amount`가 상품의 `min_amount`보다 작으면 `400 BELOW_MIN_AMOUNT`("이 상품의 최소 가입 금액은 100,000원입니다."), 아무것도 만들어지지 않습니다. `min_amount`가 null이면 1원 이상이면 됩니다.
- 예금은 가입 후 **추가 입금이 불가능**합니다(가입 금액이 곧 원금).
- 거래내역: 입출금 쪽 `TO_DEPOSIT`(상대 계좌 = 예금 계좌번호), 예금 쪽 `TRANSFER_IN`(상대 계좌 = 입출금 계좌번호). 1회·1일 이체 한도는 적용하지 않습니다.
- 실패 예시: `400 INSUFFICIENT_BALANCE`, `400 BELOW_MIN_AMOUNT`, `400 ACCOUNT_PASSWORD_NOT_SET`/`ACCOUNT_PASSWORD_INCORRECT`, `403 ACCOUNT_PASSWORD_LOCKED`, `404 ACCOUNT_NOT_FOUND`(없는 계좌·남의 입출금 계좌), `422`(필수 필드 누락, 금액 0 이하, 계좌 비밀번호 형식)

`POST /accounts/savings` → `201`: `{ "product_id": 3, "account_password": "4821", "terms": {...}, "monthly_payment": 100000, "monthly_deposit_date": 25, "maturity_date": "2027-12-10" }`

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

`POST /accounts/{type}/{account_id}/password` 🔒: 처음 설정과 재설정(5회 잠금 해제·실패 0 포함)을 같이 합니다.
```json
{ "phone_verification_token": "eyJhbGciOi...", "new_account_password": "4821" }
```
→ `200 { "data": null, "message": "계좌 비밀번호를 설정했습니다." }` + 등록 휴대폰으로 알림 문자
- 증표는 `POST /verification/phone/send-for-me`(purpose `ACCOUNT_PASSWORD_RESET`, 등록 번호로 발송) → `verify`로 받은 것. 이 사용자·등록 번호로 받은 것만 통과하고 같은 트랜잭션에서 1회 사용됩니다.
- 실패: `404 ACCOUNT_NOT_FOUND`(남의 계좌, 증표 사용보다 먼저 검사), `400 INVALID_VERIFICATION_TOKEN`, `422`(비밀번호 형식)
</details>

**해지** `POST /accounts/{deposit|savings}/{account_id}/close`: `{ "to_checking_account_id": 1, "account_password": "4821" }` (내 입출금 계좌, **해지하는 예금·적금 계좌**의 비밀번호) → `200`
```json
{ "data": { "account_type": "deposit", "account_id": 1, "principal": 300000, "interest": 3000, "total_amount": 303000, "early_close": false, "closed_at": "...", "to_account_num": "110-139-957374", "to_balance_after": 803000 }, "message": "계좌가 해지되었습니다." }
```
- 원금과 이자를 합쳐 받을 입출금 계좌로 보냅니다. 입출금 계좌는 해지할 수 없습니다(`400 CLOSE_NOT_SUPPORTED`). 계좌 비밀번호 오류는 위 **계좌 비밀번호**의 코드(`400 ACCOUNT_PASSWORD_NOT_SET`/`ACCOUNT_PASSWORD_INCORRECT`, `403 ACCOUNT_PASSWORD_LOCKED`). 이미 해지했으면 `400 ACCOUNT_CLOSED`. 남의 계좌나 없는 계좌는 `404 ACCOUNT_NOT_FOUND`.
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
{ "from_checking_account_id": 1, "to_account_num": "110-555-000111", "amount": 10000, "account_password": "4821" }
```
- `account_password`(필수): 보내는 입출금 계좌의 비밀번호. 다른 검사보다 먼저 확인합니다(오류 코드는 accounts의 **계좌 비밀번호**).

실패 예시: `400 ACCOUNT_PASSWORD_INCORRECT`, `403 ACCOUNT_PASSWORD_LOCKED`, `400 INSUFFICIENT_BALANCE`, `400 SAME_ACCOUNT_TRANSFER`, `400 PER_TRANSFER_LIMIT_EXCEEDED`, `400 DAILY_LIMIT_EXCEEDED`, `404 ACCOUNT_NOT_FOUND`

`POST /transfers` → `201`
```json
{ "data": { "from_account_num": "110-139-957374", "to_account_num": "110-729-269723", "amount": 300000, "balance_after": 700000 }, "message": "이체가 완료되었습니다." }
```
- 받는 계좌는 **입출금 계좌번호**(`110-...`)만 가능합니다. 예금·적금 번호는 `404 ACCOUNT_NOT_FOUND`.
- 검사 순서: 내 계좌(남의 계좌도 404) → 계좌 비밀번호 → 받는 계좌(404) → 같은 계좌(400) → 잔액 → 1회 한도 → 1일 한도.
- **1일 한도**는 오늘 00:00 KST부터 이 계좌에서 나간 *이체*(`TRANSFER_OUT`)의 합계입니다. 들어온 돈과 적금·예금으로 보낸 돈은 세지 않습니다.

`POST /transfers/savings`: `{ "from_checking_account_id": 1, "savings_account_id": 1, "amount": 100000, "account_password": "4821" }` (보내는 입출금 계좌의 비밀번호) → `201`, 같은 모양의 응답
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

`POST /cards/credit/1/bills/7/payments`
```json
{ "account_password": "4821" }
```
→ `200`, `status`가 `PAID`로 바뀐 청구서. `account_password`는 카드 **결제 계좌**(입출금)의 비밀번호입니다(없는 청구서면 비밀번호를 세기 전에 `404`).
실패 예시: `400 ACCOUNT_PASSWORD_INCORRECT`, `403 ACCOUNT_PASSWORD_LOCKED`, `400 INSUFFICIENT_BALANCE`, `409 BILL_ALREADY_PAID`

결제(사용) 실패 예시(신용카드): `400 CREDIT_LIMIT_EXCEEDED`
</details>

**발급**
`POST /cards/credit` → `201`: `{ "product_id": 1, "terms": {...}, "checking_account_id": 1, "payment_date": 25 }` (`terms`는 계좌 개설과 같은 약관 동의, 필수). 신용 한도는 요청으로 받지 않고 **상품의 한도가 카드로 복사**됩니다(응답에 `credit_limit`).
`POST /cards/debit` → `201`: `{ "product_id": 3, "terms": {...}, "checking_account_id": 1 }`
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
- **체크카드:** 연결 계좌에서 바로 출금하고, 입출금 거래내역에 `CARD_PAYMENT`이 남습니다. 잔액이 부족하면 `400 INSUFFICIENT_BALANCE`. 1회·1일 이체 한도는 적용하지 않고, **계좌 비밀번호도 받지 않습니다**(가맹점 결제는 카드 PIN 영역, accounts의 **계좌 비밀번호** 참고).
- **신용카드:** 돈은 나가지 않고 미결제액만 늡니다. `미결제액 + 결제 금액`이 한도를 넘으면 `400 CREDIT_LIMIT_EXCEEDED`(딱 한도까지는 허용).

**청구서 납부** `POST /cards/credit/{card_id}/bills/{bill_id}/payments` (`{ "account_password": "..." }`, 결제 계좌 비밀번호) → `200`: 카드의 **결제 계좌**에서 청구 금액이 출금되고(입출금 거래내역 `CARD_BILL_PAYMENT`, 상대 계좌에 카드번호), 청구서가 `PAID`가 되며, 카드의 미결제액이 그만큼 줄어 한도가 돌아옵니다. 다른 카드의 청구서 번호는 `404 BILL_NOT_FOUND`.
청구서 생성은 이용 기간이 끝난 달만 가능합니다(`BILLING_PERIOD_NOT_ENDED`).


## agent: AI 금융 비서 (`domains/agent`)

자세한 요청·응답, Tool 목록, 이체 확인 흐름은 [AGENT.md](AGENT.md).

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/agent/chat` | 🔒 | 채팅 질문. 이체 요청이면 실행하지 않고 `action`(이체 확인 카드)을 돌려줌 |
| ✅ | POST | `/agent/transfers/{draft_id}/confirm` | 🔒 | 사용자가 확인 카드에서 계좌 비밀번호를 넣고 누른 이체 실행 (잔액·한도 재검사, 한 번만) |
| ✅ | POST | `/agent/transfers/{draft_id}/cancel` | 🔒 | 이체 초안 취소 |

- 이체 확인 카드(`action`, `type: "TRANSFER_CONFIRMATION"`)에는 `from_account_id`(보내는 입출금 계좌 id)가 있습니다. 비밀번호 미설정·잠김 안내 링크를 그 계좌 상세로 보낼 때 씁니다(이 필드가 생기기 전에 저장된 대화 기록에서는 `null`).
```json
{ "type": "TRANSFER_CONFIRMATION", "draft_id": "...", "from_account_id": 1, "from_account_name": "생활비", "from_account_num_masked": "110-***-**6789", "recipient_name": "...", "to_account_num_masked": "...", "amount": 10000, "expected_balance_after": 490000, "expires_at": "..." }
```
- `POST /agent/transfers/{draft_id}/confirm` 본문: `{ "account_password": "4821" }`(보내는 입출금 계좌의 비밀번호, 필수). 확인 카드에서 사용자가 직접 입력하며 **대화(LLM)로는 절대 받지 않습니다.** 오류 코드는 accounts의 **계좌 비밀번호**.

실패 예시: `503 AGENT_UNAVAILABLE`, `504 AGENT_TIMEOUT`, `404 CONVERSATION_NOT_FOUND` / `DRAFT_NOT_FOUND`, `409 DRAFT_EXPIRED` / `DRAFT_NOT_PENDING`, `400 ACCOUNT_PASSWORD_INCORRECT`, `403 ACCOUNT_PASSWORD_LOCKED`

---

## dev: 개발용 (`domains/accounts/dev.py`, `domains/verification/dev.py`)

`.env`에 `ENABLE_DEV_ENDPOINTS=true`일 때만 열립니다(기본은 꺼짐). **운영 환경에서는 켜지 않습니다**(문자함이 열리면 남의 인증번호를 읽을 수 있고, 잠금 해제가 열리면 비밀번호 대입을 무한히 할 수 있음). 팀 설계에는 없던 API입니다: 외부 입금 수단이 없어 이체·결제를 시험할 잔액을 만들고, 실제 문자 발송이 없어 인증번호를 확인하기 위한 것입니다.

| 상태 | 메서드 | 경로 | 인증 | 설명 |
|---|---|---|---|---|
| ✅ | POST | `/dev/accounts/checking/{account_id}/charge` | 🔒 | 내 입출금 계좌 잔액 충전 |
| ✅ | POST | `/dev/accounts/{type}/{account_id}/password` | 🔒 | 휴대폰 인증 없이 내 계좌 비밀번호 설정 (잠금도 풀림) |
| ✅ | GET | `/dev/sms?phone=` | | 그 번호로 보낸 최근 문자 (개발용 문자함) |
| ✅ | POST | `/dev/users/{login_id}/unlock` | | 로그인 잠금 해제 + 실패 횟수 0 |

`POST /dev/accounts/checking/1/charge`: `{ "amount": 100000 }` → `200`, 갱신된 입출금 계좌(상세 응답과 같은 모양). 거래내역에는 `type` = `DEV_CHARGE`, `balance_after`와 함께 남습니다.
실패 예시: `404 ACCOUNT_NOT_FOUND`, `422`(금액 0 이하 또는 1조 원 초과)

`POST /dev/accounts/{type}/1/password`: `{ "account_password": "4821" }` → `200`, 바뀐 계좌(상세 응답과 같은 모양, `password_set: true`). 비밀번호 없이 만든 예전 계좌를 시험할 때 씁니다. 실패: `404 ACCOUNT_NOT_FOUND`(남의 계좌), `422`(형식)

`GET /dev/sms?phone=010-1234-5678` → `200 { "data": [ { "text": "[AvengersBank] 인증번호 123456 (10분 안에 입력). 타인에게 알려 주지 마세요.", "sent_at": "..." } ] }` (최신순, 최대 20건). 서버 메모리에 쌓은 것이라 재시작하면 비워집니다. 같은 내용이 서버 로그에도 `[개발용 문자]`로 찍힙니다. 화면의 '개발용 문자함'이 이 API를 씁니다.

`POST /dev/users/ironman/unlock` (본문 없음) → `200 { "data": null, "message": "로그인 잠금을 해제했습니다." }`. 없는 아이디면 `404 USER_NOT_FOUND`.

---

## 새 API를 추가하는 순서

1. `schemas.py`: 요청·응답 모양 정의
2. `repository.py`: 필요한 DB 조회·저장 메서드
3. `service.py`: 규칙 검사와 처리 (돈이 움직이면 `async with db.begin():`)
4. `router.py`: 경로 연결, `SuccessResponse[...]`로 감싸서 반환
5. `tests/`에 테스트 추가
6. 이 문서의 상태를 📝 → ✅로 변경
