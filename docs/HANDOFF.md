# 인수인계 (2026-11-09 갱신)

다음 세션이 이 문서부터 읽고 이어서 작업한다. 끝난 작업의 상세는 [DESIGN_CHANGES.md](DESIGN_CHANGES.md)(C-0xx), 인증 구조는 [AUTH.md](AUTH.md), 계정 복구 조사는 [ACCOUNT_RECOVERY_RESEARCH.md](ACCOUNT_RECOVERY_RESEARCH.md).

## 1. 지금 상태
- 브랜치 `feature/ai-assistant`에 C-104까지 커밋했다(origin/feature/ai-assistant보다 3개 앞섬, **푸시하지 않음**). 이 브랜치의 `24deb16`은 origin/main에 이미 있는 C-076~C-096 변경을 다시 묶은 커밋이라 **두 이력이 갈라져 있다**(내용은 같다: origin/main과의 차이는 C-097~C-104 파일 30개뿐). main에 합치기 전에 이력을 정리해야 한다(예: origin/main에서 새 브랜치를 만들어 그 차이를 커밋). 커밋: `24deb16`(C-076~C-101), `60c5da4`(C-102·C-103), `ba7dc6b`(C-104). 저장소 루트에 커밋하지 않은 `SPEC.md`가 있다(이 세션에서 만든 것이 아니다).
- 개발 DB(PostgreSQL 127.0.0.1:5435) 마이그레이션 head: `9e0f1a2b3c4d`(user_devices까지 적용됨. C-097~C-104는 스키마 변경 없음).
- 테스트: `465 passed, 3 skipped`(전체, 2026-11-09, C-104 커밋 기준). PostgreSQL 동시성 스크립트는 C-096 때 5개를 돌린 뒤 다시 돌리지 않았다(C-097~C-104는 잠금 로직을 건드리지 않았고, 이체 한도 오류 문구만 바뀜).
- PC를 다시 켜면 Docker Desktop(`%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe`)과 DB 컨테이너(`docker compose up -d --wait`)를 먼저 올려야 한다.

## 2. 끝난 작업

### 회원 탈퇴 (C-095)
조건(예금·적금 해지, 입출금 잔액 0, 카드 미결제 없음) → 비밀번호 + 휴대폰 인증 → 소프트 삭제(가림·계좌 닫기·카드 해지·세션 폐기, 거래 기록 보존, 재가입 불가). 법적 보존 기간·개인정보 보관 범위는 확인 필요.

### 토큰 쿠키 전환 + 기기 등록 (C-096)
- 갱신 토큰은 `httpOnly; Secure; SameSite=Strict; Path=/api/users` 쿠키(`refresh_token`), JSON 본문에 없음. `refresh`·`logout`은 본문 없이 쿠키만 읽고 **`Origin` 필수**(없거나 목록 밖이면 403 `CSRF_ORIGIN`). 액세스 토큰은 프론트 **메모리**에만, `localStorage`(`avengers_bank_session`)에는 `session_expires_at`만. 새로고침하면 쿠키로 조용히 갱신.
- 프론트는 Next.js `rewrites`로 `/api/*`를 FastAPI에 프록시한다(`next.config.ts`, 서버 환경변수 `API_ORIGIN`, 기본 `http://127.0.0.1:8000`). **프론트와 API를 같이 띄워야 하고, 프론트 환경변수 `NEXT_PUBLIC_API_BASE_URL`은 없어졌다.**
- 기기 등록(B1): 새 기기 로그인 = 비밀번호 → `DEVICE_VERIFICATION_REQUIRED` 챌린지 → `POST /users/login/device/send` → 문자 인증(`/verification/phone/verify`) → `POST /users/login/device`. 통과하면 1년짜리 `device_token` 쿠키(서버엔 SHA-256)가 생긴다. 실패 카운터는 **등록 기기 / 새 기기 채널을 따로** 센다(각 5회 연속 오류 → 잠금). 내 정보에 기기 목록·해제. 비밀번호 재설정(복구)·탈퇴는 기기 전부 해제, 비밀번호 변경은 유지. 최종 API 계약은 DESIGN_CHANGES C-096 "구현에서 정해진 세부".
- 설정(`core/config.py`): `cookie_secure`(기본 True), `refresh_cookie_path`(`/api/users`), `device_cookie_days`(365). 테스트는 `conftest.py`에서 `COOKIE_SECURE=false`, `REFRESH_COOKIE_PATH=/users`.
- 브라우저로 확인한 것: 새 기기 인증 로그인, `document.cookie` 비어 있음, 새로고침 뒤 자동 갱신, 로그아웃 뒤 갱신 401, 같은 브라우저 재로그인은 인증번호 없이 통과, 기기 목록 표시.

### AI 비서·계좌 상세 (C-097 ~ C-104) — 가장 최근
- **구조:** 모델↔도구 반복은 `domains/agent/graph.py`(LangGraph `StateGraph`: call_model → tools → … → finish/limit). 대화 불러오기·인용·저장은 `service.py`에 남겼다. checkpointer 없음(대화는 `agent_messages`에만). `langchain-google-genai`는 `google-genai`를 3.x로 올려야 해서 쓰지 않았다(C-101).
- **이체:** `prepare_transfer`는 계좌를 id가 아니라 **이름**(별칭·상품명·번호 끝 4자리)으로 받고 서버가 찾는다(`find_own_checking`). 없거나 여럿이면 후보(마스킹, id 없음)를 오류로 돌려 되묻게 한다(C-100). 한도 오류에는 한도 금액을 담는다(C-102).
- **가입 준비 카드:** `prepare_open_account`(예금·적금)는 검증만 하고 `OPEN_ACCOUNT` 카드를 돌려준다. 프런트 카드가 `sessionStorage`의 `open-draft:{kind}`에 값을 넣고 `/open/{kind}/{상품 id}`를 연다. 약관 동의·계좌 비밀번호는 화면에서 직접(C-103). 가입 화면은 입력값을 바뀔 때마다 보관하고 계좌 비밀번호는 메모리에만 둔다(C-098).
- **계좌 상세 화면(C-104):** 해지하기는 맨 아래 작은 링크, 비밀번호 재설정은 입력칸을 누를 때·미설정·잠김일 때만, 예·적금 이자 미리 보기(`GET /accounts/{type}/{id}/interest-preview`, 적금 만기는 매월 납입 계속 가정).
- 새 기기 로그인의 개발용 문자함은 사용자가 번호를 직접 입력해 연다(가려진 번호로는 못 열었음, C-097).
- **확인:** 새 테스트, 실제 Gemini·브라우저로 이체 카드·가입 카드·약관 인용·이자 미리 보기. 화면에서 **실제 가입·해지·비밀번호 재설정 완료는 누르지 않았다.**

## 3. 남은 일 · 결정 대기
- **새 목록은 `NEXT_STEPS.md` 5단계(AI 비서·MCP)**: MCP 서버(원래 목표), 대화 보관 정책(은행 규제 vs 탈퇴 시 삭제 C-095), 스트리밍, 채팅 안 가입, 재설정 안내 확대 등.
- **git 이력 정리:** 위 "지금 상태"의 갈라진 이력을 main에 합치기 전에 정리해야 한다.
- **이번 세션에서 확인하지 못한 것:** `npm run build`(이전부터 실패하던 `/find-id`), 운영(AWS) 반영, Docker 이미지 재빌드(`uv.lock`에 `langgraph`와 의존 패키지가 추가됨. 빌드는 해 보지 않음).
- **미확인:** 내 정보 화면의 기기 **해제 버튼 동작**(눌러 보지 않음), `npm run build` 실패(`/find-id` 프리렌더에서 `components/verify.tsx:35`의 `useState(Date.now)` → `blocking-prerender-current-time-client`. 이번에 건드린 파일이 아니고 이전부터인지 확인 못 함).
- **사용자와 정할 것(C-096 논의 포인트):** 공용 PC용 "이 기기 등록 안 함" 선택, 기기 개수 상한·오래된 기기 정리(지금은 재등록할 때마다 행이 쌓임), "5회 이내 거래 중지"를 채널별로 적용한 해석이 규정 취지에 맞는지, Safari의 Secure 쿠키(http에서 저장 안 함 → 개발은 Chrome 또는 `COOKIE_SECURE=false`), 챌린지 JWT를 1회용(jti 저장)으로 할지.
- 갱신 쿠키 `Path=/api/users`는 `/api/users/*` 전체에 붙는다(갱신·로그아웃만으로 좁히지 못함: 두 경로의 공통 접두사). 필요하면 쿠키를 둘로 나눈다.
- 문서: `API_ENDPOINTS.md`·`ERD.md`는 C-096까지 반영함. drawio(`AvengersBankDiagram_v2.drawio`)는 자동 생성물이라 `scripts/generate_erd_drawio.py`로 다시 만들어야 새 테이블이 들어간다. `docs/인수인계.md`는 DESIGN_CHANGES.md를 요약한 사람용 문서.
- 코드 정리 후보: `exception_handlers.py` `FIELD_LABELS`의 `refresh_token`(본문에 없어 안 쓰임), `verification/router.py` `SendRequest`·`accounts/dev.py`의 낡은 "2단계" 주석, `/users/login`·`/users/login/device`는 기기 쿠키를 쓰지만 Origin 확인은 안 한다(비밀번호·증표가 따로 필요해 의도됨, C-096 논의 포인트에 없음).

## 4. 사용자와 일하는 방식
- 한국어로 대화. **큰 작업은 먼저 설계·선택지를 제안하고 사용자가 정한 뒤 시작**한다(바로 만들지 말 것). 보안·정책은 필요하면 **먼저 조사**(이전에 계정 복구를 조사부터 함).
- 정한 뒤에는 **서브에이전트로 병렬 작업**(파일 소유권을 나눠 주고, 커밋·DB 적용은 메인이 함). 백엔드/프론트/문서처럼 서로 막히지 않는 일은 **동시에** 돌려 시간을 줄인다(사용자가 시간이 오래 걸리면 병렬로 하라고 요청함). 에이전트 보고는 믿지 말고 **전체 pytest·PG 스크립트·브라우저로 직접 확인**.
- 바뀐 것은 `docs/DESIGN_CHANGES.md`에 C-0xx 항목(변경 전/후·이유·영향·검증·논의 포인트) + 개요 표·부록 B·`NEXT_STEPS.md` 갱신. 인증 쪽은 학습용으로 `docs/AUTH.md`에 "무엇을 왜 바꿨는지"를 설명.
- 커밋은 사용자가 원할 때. 푸시는 묻고.

## 5. 개발 환경 메모
- 백엔드 `uv run fastapi dev`(127.0.0.1:8000, Windows라 `fastapi run` 금지), 프론트 `cd frontend && npm run dev`(5173), DB `docker compose up -d --wait`. **프론트는 `/api`로 프록시하므로 브라우저는 `http://localhost:5173`으로만 접속**(Swagger는 `:8000/docs` 그대로).
- **낡은 서버 주의:** 예전 세션에서 띄운 `fastapi dev`가 8000번에 남아 있으면 새 코드가 안 올라간다(이번에도 낡은 서버가 떠 있어 내리고 다시 띄움). 이상하면 `Get-NetTCPConnection -LocalPort 8000,5173 -State Listen`으로 확인.
- 테스트: `PYTHONIOENCODING=utf-8 TEST_DATABASE_URL=sqlite+aiosqlite:///./test_main.db uv run pytest -q -p no:cacheprovider`(약 4~5분, 끝나면 test_main.db 삭제). 테스트의 로그인은 `BankClient`가 새 기기 챌린지를 실제 경로로 자동 인증한다.
- PG 동시성 스크립트: `uv run python scripts/pg_*_concurrency.py`(목록은 `scripts/README.md`). 같은 개발 DB를 쓰지만 `verify_…` 사용자만 만들고 지운다.
- 인증번호는 개발 모드에서 서버 로그와 `GET /dev/sms?phone=…`(화면의 "개발용 문자함")로 본다. `ENABLE_DEV_ENDPOINTS=true` 필요.
- 관리자 명령: `uv run python -m avengers_bank.admin unlock|reset-password <login_id>`(두 채널 잠금 모두 해제, reset-password는 기기도 전부 해제).
- 실행 중인 서버 앞에서 로그인 실패를 반복하면 같은 IP(127.0.0.1)로 IP 한도(15분 20회)에 걸린다 — 실패 시험은 테스트(ASGI)나 PG 스크립트로.
- `frontend/AGENTS.md`: 이 Next.js는 버전이 달라 새 API는 `node_modules/next/dist/docs/` 확인.

## 6. 알려진 후속 과제
- 기존 계좌(`admin123` 등)는 계좌 비밀번호가 없어 이체 전에 계좌 상세에서 휴대폰 인증 후 설정해야 한다.
- `seed_demo.py`는 로그인을 먼저 시도하므로 기존 아이디엔 **본인 비밀번호를 인자로** 넣어 실행(틀리면 로그인 실패로 셈). 새 기기 챌린지는 `010-1234-5678` 개발용 문자함으로 자동 인증하고, 실행마다 기기가 하나 등록된다(기존 아이디의 번호가 다르면 실패).
- 인증번호 발송 제한(번호당 15분 3번)은 용도와 상관없이 합산된다.
- 실제 문자 업체 연동(지금은 개발용 발송기), 가짜 복구 토큰 횟수·IP 한도는 프로세스 메모리(서버 여러 대면 공유 저장소).
- AI 비서 도구의 입력 오류는 영어, 폐기·만료 토큰 행 정리, 세션 절대 만료 시간.
- 브라우저에 남은 옛 `avengers_bank_session`(토큰 포함)은 따로 지우지 않는다(다음 로그인·로그아웃이 덮어씀).
- 이 세션에서 브라우저 검증용으로 `uitest01`의 비밀번호를 새로 정했다(문서에 적지 않음. 필요하면 `uv run python -m avengers_bank.admin reset-password uitest01`). `test1109`에는 카드 2장·오늘 카드 결제 8건·월급 통장 충전을 넣어 두었다.
- 로컬 DB에 테스트 계정이 남아 있다: `demo1`·`demo2`·`demo3`·`uitest01`·`recovery01`(비밀번호 `Passw0rd!23` 또는 `password1234`, recovery01은 `N3wPassw0rd!`). `demo1`에는 이번 검증으로 기기가 하나 등록됐다.
