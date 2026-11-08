# 인수인계 (2026-11-09 갱신)

다음 세션이 이 문서부터 읽고 이어서 작업한다. 끝난 작업의 상세는 [DESIGN_CHANGES.md](DESIGN_CHANGES.md)(C-0xx), 인증 구조는 [AUTH.md](AUTH.md), 계정 복구 조사는 [ACCOUNT_RECOVERY_RESEARCH.md](ACCOUNT_RECOVERY_RESEARCH.md).

## 1. 지금 상태
- `main` 브랜치, **푸시 안 함**. 인증 작업 C-082~C-094와 회원 탈퇴 C-095까지 커밋됨(`git log`로 확인).
- 개발 DB(PostgreSQL 127.0.0.1:5435) 마이그레이션 head: `8d9e0f1a2b3c`(회원 탈퇴까지 적용됨).
- 테스트: `422 passed, 3 skipped`. PostgreSQL 동시성 스크립트 12개 모두 통과(2026-11-09).
- PC를 다시 켜면 Docker Desktop(`%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe`)과 DB 컨테이너(`docker compose up -d --wait`)를 먼저 올려야 한다.

## 2. 끝난 작업: 회원 탈퇴 (C-095)
조건(예금·적금 해지, 입출금 잔액 0, 카드 미결제 없음) → 비밀번호 + 휴대폰 인증 → 소프트 삭제(가림·계좌 닫기·카드 해지·세션 폐기, 거래 기록 보존, 재가입 불가). 법적 보존 기간·개인정보 보관 범위는 확인 필요(DESIGN_CHANGES C-095 논의 포인트).

## 3. 결정 대기: 토큰 쿠키 전환 + 기기 등록(B1)
- 사용자에게 원리를 설명했고(XSS가 생겨도 토큰을 못 훔쳐 가게), **진행 여부 답을 기다리는 중**. 시작 전에 사용자에게 확인한다.
- 추천 설계: 갱신 토큰 → `httpOnly; Secure; SameSite=Strict` 쿠키(갱신·로그아웃 경로에만), 액세스 토큰 → 프론트 **메모리**에만(새로고침 시 쿠키로 조용히 갱신), **Next.js rewrites로 `/api/*`를 FastAPI로 프록시**해 같은 주소로(제3자 쿠키 차단 회피, 프론트 배포 위치와 무관), CSRF는 SameSite + 쿠키 경로 제한 + `Origin` 확인. 여러 탭의 갱신 직렬화(Web Locks)는 유지.
- 기기 등록 B1(사용자가 선택): 새 기기 로그인 시 휴대폰 인증번호 추가, 통과한 기기에 1년 `httpOnly` 기기 쿠키(서버엔 해시), 로그인 실패를 **등록 기기와 새 기기를 따로** 센다(남이 잠가도 주인은 등록 기기로 로그인 — "5회 이내 거래 중지"를 채널별로 적용한다는 해석을 문서에 명시), 내 정보에 기기 목록·해제, 비밀번호 재설정 시 전부 해제. 쿠키 전환과 같은 기반이라 함께 만든다.

## 4. 사용자와 일하는 방식
- 한국어로 대화. **큰 작업은 먼저 설계·선택지를 제안하고 사용자가 정한 뒤 시작**한다(바로 만들지 말 것). 보안·정책은 필요하면 **먼저 조사**(이전에 계정 복구를 조사부터 함).
- 정한 뒤에는 **서브에이전트로 병렬 작업**(파일 소유권을 나눠 주고, 커밋·DB 적용은 메인이 함). 에이전트 보고는 믿지 말고 **전체 pytest·PG 스크립트·브라우저로 직접 확인**.
- 바뀐 것은 `docs/DESIGN_CHANGES.md`에 C-0xx 항목(변경 전/후·이유·영향·검증·논의 포인트) + 개요 표·부록 B·`NEXT_STEPS.md` 갱신. 인증 쪽은 학습용으로 `docs/AUTH.md`에 "무엇을 왜 바꿨는지"를 설명.
- 커밋은 사용자가 원할 때. 푸시는 묻고.

## 5. 개발 환경 메모
- 백엔드 `uv run fastapi dev`(127.0.0.1:8000, Windows라 `fastapi run` 금지), 프론트 `cd frontend && npm run dev`(5173), DB `docker compose up -d --wait`.
- 테스트: `PYTHONIOENCODING=utf-8 TEST_DATABASE_URL=sqlite+aiosqlite:///./test_main.db uv run pytest -q -p no:cacheprovider`(약 5분, 끝나면 test_main.db 삭제).
- PG 동시성 스크립트: `uv run python scripts/pg_*_concurrency.py`(목록은 `scripts/README.md`). 같은 개발 DB를 쓰지만 `verify_…` 사용자만 만들고 지운다.
- 인증번호는 개발 모드에서 서버 로그와 `GET /dev/sms?phone=…`(화면의 "개발용 문자함")로 본다. `ENABLE_DEV_ENDPOINTS=true` 필요.
- 관리자 명령: `uv run python -m avengers_bank.admin unlock|reset-password <login_id>`.
- 실행 중인 서버 앞에서 로그인 실패를 반복하면 같은 IP(127.0.0.1)로 IP 한도(15분 20회)에 걸린다 — 실패 시험은 테스트(ASGI)나 PG 스크립트로.
- `frontend/AGENTS.md`: 이 Next.js는 버전이 달라 새 API는 `node_modules/next/dist/docs/` 확인.

## 6. 알려진 후속 과제
- 기존 계좌(`admin123` 등)는 계좌 비밀번호가 없어 이체 전에 계좌 상세에서 휴대폰 인증 후 설정해야 한다.
- `seed_demo.py`는 로그인을 먼저 시도하므로 기존 아이디엔 **본인 비밀번호를 인자로** 넣어 실행(틀리면 로그인 실패로 셈).
- 인증번호 발송 제한(번호당 15분 3번)은 용도와 상관없이 합산된다.
- 실제 문자 업체 연동(지금은 개발용 발송기), 가짜 복구 토큰 횟수·IP 한도는 프로세스 메모리(서버 여러 대면 공유 저장소).
- `docs/ERD.md`에 `refresh_tokens`·agent·terms 테이블이 빠져 있음, drawio 미반영, AI 비서 도구의 입력 오류는 영어, 폐기·만료 토큰 행 정리, 세션 절대 만료 시간.
- 로컬 DB에 테스트 계정이 남아 있다: `demo1`·`demo2`·`demo3`·`uitest01`·`recovery01`(비밀번호 `Passw0rd!23` 또는 `password1234`, recovery01은 `N3wPassw0rd!`).
