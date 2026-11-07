"""은행 Tool 목록과 실행기. AI 공급자 코드를 모른다.

각 Tool은 (db, 로그인 사용자, 검증된 인자) → pydantic 결과를 돌려주는 평범한 async 함수다.
나중에 MCP 서버를 붙일 때 TOOLS와 run_tool을 그대로 재사용한다.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from avengers_bank.core.database import SessionLocal
from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.agent.tools.accounts import NoArgs, get_my_accounts
from avengers_bank.domains.agent.tools.cards import get_card_payment_status
from avengers_bank.domains.agent.tools.summary import get_financial_summary
from avengers_bank.domains.agent.tools.transactions import HistoryArgs, get_transaction_history
from avengers_bank.domains.agent.tools.transfers import PrepareTransferArgs, prepare_transfer
from avengers_bank.domains.users.schemas import UserResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[..., Awaitable[BaseModel]]

    @property
    def input_schema(self) -> dict:
        return self.args.model_json_schema()


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("get_my_accounts", "로그인한 사용자의 활성 계좌 목록(종류, 이름, 마스킹된 번호, 잔액, 만기일, 상태)을 조회한다.",
         NoArgs, get_my_accounts),
    Tool("get_financial_summary", "로그인한 사용자의 전체 금융 상태 요약: 계좌 수, 종류별·전체 잔액 합계, 신용카드 미결제액, "
         "미납 청구서 합계, 가장 가까운 카드 결제 예정일, 예·적금 만기. 모든 합계는 서버가 계산한다.",
         NoArgs, get_financial_summary),
    Tool("get_transaction_history", "로그인한 사용자의 계좌 거래내역을 조건(계좌 종류·계좌·기간·유형·상대방 이름·개수)으로 최신순 검색한다.",
         HistoryArgs, get_transaction_history),
    Tool("get_card_payment_status", "로그인한 사용자의 카드 결제 상태: 미결제액, 미납 청구서, 결제 예정일, 결제계좌 잔액과 부족 금액. "
         "부족 금액은 서버가 계산한다.",
         NoArgs, get_card_payment_status),
    Tool("prepare_transfer", "이체 초안만 만든다(실제 이체 아님). 출금 계좌·수취 계좌·잔액·한도를 서버가 검증하고, "
         "사용자가 화면의 확인 카드에서 직접 승인해야 실행된다. from_account_id는 먼저 get_my_accounts로 확인한 값만 쓴다.",
         PrepareTransferArgs, prepare_transfer),
]}


@dataclass
class ToolOutcome:
    ok: bool
    content: str  # 모델에 돌려줄 JSON 문자열
    result: Any = None


def _error(code: str, message: str) -> ToolOutcome:
    return ToolOutcome(False, json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False))


async def run_tool(name: str, raw_args: Any, user: UserResponse) -> ToolOutcome:
    """모델이 보낸 이름·인자를 믿지 않고 다시 검증한 뒤 실행한다. 오류는 예외 대신 결과로 돌려준다."""
    tool = TOOLS.get(name)
    if tool is None:
        return _error("UNKNOWN_TOOL", "없는 도구입니다.")
    try:
        args = tool.args.model_validate(raw_args or {})
    except ValidationError as e:
        # 입력값을 되풀이하지 않고 위치와 이유만 알려 준다
        detail = "; ".join(f"{'.'.join(map(str, err['loc'])) or '입력'}: {err['msg']}" for err in e.errors())
        return _error("INVALID_ARGUMENTS", detail[:300])
    try:
        # Tool마다 세션을 따로 열고 바로 닫는다. 모델 응답을 기다리는 동안 DB 커넥션을 잡지 않는다
        async with SessionLocal() as db:
            result = await tool.run(db, user, args)
    except ApiException as e:
        return _error(e.code, e.message)
    except Exception:
        logger.exception("agent tool 실패: %s", name)
        return _error("TOOL_FAILED", "도구 실행 중 오류가 발생했습니다.")
    return ToolOutcome(True, result.model_dump_json(), result)
