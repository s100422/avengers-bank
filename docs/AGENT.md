# AI 금융 비서 (Tool Calling, C-070)

로그인한 사용자가 채팅으로 자기 금융 상태를 물으면, AI가 필요한 **은행 Tool**을 골라 실제 데이터를 조회하고 자연어로 답합니다.
이체 요청은 **초안만** 만들고, 사용자가 화면의 확인 카드에서 `이체하기`를 눌러야 실행됩니다.

> MCP 서버는 아직 없습니다. Tool의 비즈니스 로직은 AI 공급자와 분리된 평범한 Python 함수라서, 나중에 MCP Tool이 같은 함수를 그대로 부를 수 있습니다([아래](#mcp로-공개할-때)).

## 실행

1. [Google AI Studio](https://aistudio.google.com/apikey)에서 Gemini API 키를 받아 `.env`에 넣습니다(키는 커밋하지 않습니다. `.env`는 `.gitignore`에 있음).
   ```
   GEMINI_API_KEY=...
   ```
2. 마이그레이션(대화·이체 초안 테이블)을 적용하고 서버를 띄웁니다.
   ```bash
   uv sync
   uv run alembic upgrade head
   uv run fastapi dev
   ```
3. 프론트엔드(`cd frontend && npm run dev`)에 로그인하면 오른쪽 아래에 **AI 금융 비서** 버튼이 생깁니다.

키가 없으면 `/agent/chat`은 `503 AGENT_UNAVAILABLE`("AI 비서가 아직 설정되지 않았습니다.")을 돌려주고, 나머지 은행 기능은 그대로 동작합니다.

## 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | (없음) | Gemini API 키. 없으면 AI 비서만 꺼짐 |
| `AGENT_MODEL` | `gemini-2.5-flash` | Gemini 모델 ID. 더 깊은 추론이 필요하면 `gemini-2.5-pro` 등 (AI Studio의 모델 목록 참고) |
| `AGENT_TIMEOUT_SECONDS` | `30` | 모델 호출 한 번의 제한 시간(초). 넘으면 `504 AGENT_TIMEOUT` |

## 모델 공급자

- **Google Gemini**(공식 Python SDK `google-genai`)를 씁니다(C-071). 처음에는 Anthropic Claude로 만들었다가 사용자 결정으로 바꿨습니다. 이유는 [RETROSPECTIVE.md](RETROSPECTIVE.md)의 기술 선택 기록에 적었습니다.
- SDK의 자동 함수 실행(automatic function calling)은 끕니다. 함수 실행, 인자 재검증, 호출 상한은 우리 `service.py`가 맡습니다.
- 모델 응답 원본(`Content`)을 같은 요청 안의 다음 호출에 그대로 되돌려 보내서 생각 서명(thought signature)이 유지되게 합니다. 함수 결과는 `{"output": ...}`, 실패는 `{"error": ...}`로 보냅니다.
- 공급자 코드는 `domains/agent/model_client.py` 한 파일에만 있습니다. `service.py`는 공급자 중립 타입(`ModelReply`, `ToolCall`, `UserTurn` …)과 `ModelClient` 인터페이스만 압니다.
- **다른 공급자로 바꾸기:** `respond(system, turns, tools) -> ModelReply`를 구현한 클래스를 만들고 `get_model_client()`에서 그 클래스를 돌려주면 됩니다. Tool·서비스·테스트는 바꾸지 않습니다.
- Gemini가 안전 필터로 답을 막으면(`SAFETY` 등) "도와드릴 수 없습니다"라고 답합니다.

## API

모두 🔒 로그인 필요. 응답은 다른 API와 같은 `{ "data": ..., "message": ... }` / `{ "error": { "code", "message" } }` 형식입니다.

### `POST /agent/chat`

```json
{ "message": "내 자산을 요약해 줘.", "conversation_id": null }
```
→ `200`
```json
{ "data": { "conversation_id": 1, "answer": "현재 보유한 계좌는 3개이며 총 잔액은 3,500,000원입니다.", "action": null } }
```

이체 요청이면 실행하지 않고 `action`을 돌려줍니다.
```json
{
  "data": {
    "conversation_id": 1,
    "answer": "아래 확인 카드에서 내용을 확인한 뒤 이체하기를 눌러 주세요.",
    "action": {
      "type": "TRANSFER_CONFIRMATION",
      "draft_id": "Qm1c…(43자 임의 문자열)",
      "from_account_name": "생활비 통장",
      "from_account_num_masked": "110-***-**7890",
      "recipient_name": "김철수",
      "to_account_num_masked": "110-***-**1234",
      "amount": 50000,
      "expected_balance_after": 950000,
      "expires_at": "2026-11-06T03:05:00Z"
    }
  }
}
```

- `message`: 1~1000자. `conversation_id`를 보내면 그 대화를 이어 갑니다(남의 대화·없는 대화는 `404 CONVERSATION_NOT_FOUND`).
- 실패: `503 AGENT_UNAVAILABLE`(키 없음·모델 API 오류), `504 AGENT_TIMEOUT`. 내부 오류 원문·프롬프트·키는 응답에 싣지 않습니다.

### `POST /agent/transfers/{draft_id}/confirm`

사용자가 확인 카드에서 `이체하기`를 눌렀을 때만 프론트엔드가 부릅니다. **Tool로 등록하지 않습니다.**
→ `200 { "draft_id", "status": "EXECUTED", "from_account_num_masked", "to_account_num_masked", "recipient_name", "amount", "balance_after" }`

| 오류 | 언제 |
|---|---|
| `404 DRAFT_NOT_FOUND` | 없는 초안, 남의 초안 |
| `409 DRAFT_EXPIRED` | 만료 시각(만든 뒤 5분)이 지남. 초안은 `EXPIRED`가 된다 |
| `409 DRAFT_NOT_PENDING` | 이미 실행·취소·만료된 초안, 같은 초안을 동시에 두 번 누름 |
| `400 INSUFFICIENT_BALANCE` / `PER_TRANSFER_LIMIT_EXCEEDED` / `DAILY_LIMIT_EXCEEDED` | 확인 시점에 다시 검사해서 실패. 초안은 `PENDING`으로 남아 다시 시도할 수 있다 |

### `POST /agent/transfers/{draft_id}/cancel`

→ `200 { "draft_id", "status": "CANCELLED" }`. 이미 처리된 초안은 `409 DRAFT_NOT_PENDING`.

## 등록된 Tool

| Tool | 인자 | 돌려주는 것 |
|---|---|---|
| `get_my_accounts` | 없음 | 활성 계좌: 종류, `account_id`, 이름(별칭 또는 상품명), 마스킹된 번호, 잔액, 예·적금 만기일, 상태 |
| `get_financial_summary` | 없음 | 활성 계좌 수, 전체·입출금·예금·적금 잔액 합계, 신용카드 미결제액, 미납 청구서 합계, 가장 가까운 카드 결제 예정일, 예·적금 만기(남은 일수) |
| `get_transaction_history` | 계좌 종류, `account_id`, 시작·종료일(KST), 거래 유형, 상대방 이름, 개수(기본 20, 최대 50) | 거래일, 계좌, 유형, 금액, 거래 후 잔액, 마스킹된 상대 계좌, 상대방 이름, 더 있는지(`has_more`) |
| `get_card_payment_status` | 없음 | 카드별 종류·마스킹 번호·미결제액·미납 청구서·다음 결제일, 결제계좌별 이름·마스킹 번호·잔액·**부족 금액** |
| `prepare_transfer` | 출금 `account_id`, 받는 계좌번호, 금액 | 이체 초안(`draft_id`, 출금 계좌 이름·마스킹 번호, 받는 분 실명, 마스킹된 받는 계좌, 금액, 예상 잔액, 만료 시각) |

- **`user_id` 인자는 없습니다.** 모든 Tool은 서버가 JWT로 확인한 로그인 사용자로만 동작하고, 정의되지 않은 인자(`user_id` 등)를 보내면 `INVALID_ARGUMENTS`로 거절합니다.
- 합계·부족 금액·남은 일수는 모두 백엔드 코드가 계산합니다. 모델에게는 계산하지 말고 Tool 값을 쓰라고 지시합니다.
- `execute_transfer` 같은 실행 Tool은 없습니다.

## Agent 흐름

```
사용자 ──POST /agent/chat──▶ AgentService.chat
                               │  지난 대화(최근 10개 메시지) + 새 질문
                               ▼
                         ModelClient.respond ──▶ (Gemini)
                               │  tool 호출이 있으면
                               ▼
                         run_tool(name, args, 로그인 사용자)
                               │  인자 재검증(pydantic) → Tool 함수(기존 서비스 재사용) → 결과 JSON
                               ▼
                         결과를 모델에 돌려주고 반복 (모델 호출 최대 6번, Tool 최대 8개)
                               │  tool 호출이 없으면 끝
                               ▼
                         답변 + (prepare_transfer가 성공했으면) action 저장 후 응답
```

- Tool 실패(소유권, 잔액, 한도 등)는 예외로 끝내지 않고 `{ "error": { code, message } }`를 모델에 돌려줘서, 모델이 쉬운 말로 설명하게 합니다.
- 상한에 걸리면 "질문을 처리하는 데 단계가 너무 많이 필요합니다…"라고 답합니다.
- Tool마다 DB 세션을 따로 열고 바로 닫아서, 모델 응답을 기다리는 동안 DB 커넥션을 잡지 않습니다.

## 이체 확인 흐름

1. 사용자가 "생활비 통장에서 김철수에게 5만 원 보내줘"라고 말합니다.
2. 모델이 `get_my_accounts`로 출금 계좌를 찾고 `prepare_transfer`를 부릅니다.
3. 서버가 **기존 이체 코드(`transfer_service.preview`)** 로 출금 계좌 소유권, 받는 계좌 존재, 같은 계좌 여부, 잔액, 1회·1일 한도, 금액 범위를 검사하고, 받는 분 실명을 찾아 `PENDING` 초안(유효 5분)을 저장합니다. **잔액은 바뀌지 않습니다.**
4. 응답의 `action`을 프론트엔드가 **별도 확인 카드**로 보여 줍니다(채팅 글로 확인을 받지 않음).
5. 사용자가 `이체하기`를 누르면 `/confirm`이 한 트랜잭션 안에서
   - 초안을 `PENDING → EXECUTED`로 **조건부 UPDATE**(상태가 PENDING이고 만료 전일 때만)하고,
   - 기존 `transfer_service.transfer_in_tx`로 계좌를 잠근 뒤 잔액·한도를 **다시 검사**하고 이체합니다.
   - 이체가 실패하면 트랜잭션이 통째로 되돌아가 초안은 `PENDING`으로 남습니다.
6. 성공하면 최종 잔액이 채팅에 표시되고 계좌 화면이 새로 고쳐집니다. `취소`는 `/cancel`로 `CANCELLED`가 됩니다.

같은 초안을 여러 번(동시에) 눌러도 조건부 UPDATE를 먼저 차지한 요청만 이체합니다. PostgreSQL에서 `scripts/pg_agent_confirm_concurrency.py`로 확인했습니다(10번 동시 확인 → 1건 성공, 대조군은 10건 이체).

## 저장하는 것

| 테이블 | 내용 |
|---|---|
| `agent_conversations` | 대화 소유 사용자, 생성 시각 |
| `agent_messages` | 사용자 질문, AI 답변, 호출한 Tool 이름과 성공 여부(`[{"name", "ok"}]`), 이체 확인 action(마스킹된 값만), 생성 시각 |
| `agent_transfer_drafts` | 초안: 소유자, 출금 계좌, 받는 계좌번호, 받는 분, 금액, 상태, 만료·실행 시각 |

Tool의 원본 결과(잔액 목록, 거래내역 등)는 저장하지 않습니다. 모델에 넘기는 지난 대화는 최근 10개 메시지(답변 글만)입니다.

## 보안 고려사항

- 모든 Agent API는 로그인 필요. 대화·초안은 소유자만 쓰고, 남의 것은 404로 숨깁니다.
- 사용자는 Tool 인자가 아니라 서버의 인증 정보에서 옵니다. Tool 인자와 모델 출력은 믿지 않고 pydantic으로 다시 검증하고, 계좌 소유권은 기존 서비스(`get_owned`)가 확인합니다.
- 계좌·카드번호는 Tool 결과부터 마스킹(`110-***-**6789`, `4000-****-****-9012`)해서 모델에 전체 번호가 가지 않습니다. 거래내역은 최대 50건까지만 넘깁니다.
- 실제 이체는 사용자가 누르는 확인 API로만 실행되고, 그때 잔액·한도를 다시 검사합니다. 초안 ID는 추측할 수 없는 43자 임의 문자열이고 5분 뒤 만료됩니다.
- 응답에는 시스템 프롬프트, API 키, JWT, 내부 오류 원문을 싣지 않습니다(모델 API 오류는 종류만 로그에 남김).
- 시스템 지침: 로그인 사용자 정보만 다루기, Tool 결과에 없는 것 추측 금지, 직접 계산 금지, 수익 보장 표현 금지, 번호 마스킹, 묻지 않은 개인정보 노출 금지, 이체는 `prepare_transfer`까지만, Tool 오류는 쉬운 말로(`domains/agent/prompts.py`).

## 코드 위치

```
src/avengers_bank/domains/agent/
├── router.py          # /agent/chat, /agent/transfers/{id}/confirm|cancel
├── service.py         # Agent 루프(상한), 대화 저장, 초안 확인·취소
├── repository.py      # 대화·메시지 조회, 초안 조건부 상태 변경
├── schemas.py         # 요청·응답, TransferAction
├── models.py          # 대화·메시지·이체 초안 테이블
├── prompts.py         # 시스템 지침
├── model_client.py    # 공급자 경계 (중립 타입, ModelClient, GeminiModelClient)
└── tools/
    ├── __init__.py    # TOOLS 목록과 run_tool (공급자를 모름)
    ├── common.py      # 인자 기본형(extra 금지), 마스킹, 계좌 이름
    ├── accounts.py    # get_my_accounts
    ├── summary.py     # get_financial_summary
    ├── transactions.py# get_transaction_history
    ├── cards.py       # get_card_payment_status
    └── transfers.py   # prepare_transfer
```

## 테스트

```bash
uv run pytest tests/test_agent.py
uv run python scripts/pg_agent_confirm_concurrency.py   # PostgreSQL 동시 확인 (수동)
```

테스트는 실제 모델을 부르지 않고, `app.dependency_overrides[get_model_client]`로 정해 둔 응답을 돌려주는 `FakeClient`를 씁니다. Gemini 어댑터의 변환(함수 호출·결과, 시간 초과, API 오류, 안전 차단)은 SDK 호출을 바꿔치기해서 네트워크 없이 확인합니다.

## MCP로 공개할 때

`tools/__init__.py`의 `TOOLS`(이름, 설명, 인자 모델, 함수)와 `run_tool`은 AI 공급자를 모릅니다. MCP 서버를 만들 때는

- 각 `Tool.input_schema`(pydantic JSON 스키마)를 MCP Tool 스키마로 그대로 쓰고,
- 호출이 오면 MCP 세션의 인증된 사용자로 `run_tool(name, args, user)`를 부르면 됩니다.

MCP 쪽에서도 이체 실행 Tool은 만들지 않고, 확인은 사용자 화면의 확인 API로만 하는 원칙을 유지합니다.
