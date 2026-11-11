"""AI 비서의 '모델 ↔ 도구' 반복을 LangGraph로 돌린다 (C-101).

    START → call_model ─┬─ 도구 호출 없음 ─────────────→ finish ─→ END
                        ├─ 도구 호출이 상한 초과 ──────→ limit  ─→ END
                        └─ 도구 호출 있음 → tools ─┬─ 모델 호출 상한 도달 → limit
                                  ↑                 └─ 아니면 ─→ call_model
                                  └───────────────────────────────┘

이전에는 service.py의 for 루프가 하던 일이다. 동작은 같다: 모델은 질문 하나에 최대 MAX_MODEL_CALLS번, 도구는 최대
MAX_TOOL_CALLS개까지만 쓴다. 대화 불러오기·인용 정리·저장은 DB를 만지는 일이라 service.py에 두었다.
상태는 요청 하나 동안만 산다(checkpointer 없음) — 대화 기록은 agent_messages가 유일한 저장소다.
"""

import logging
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.agent.model_client import (
    AssistantTurn,
    ModelClient,
    ModelError,
    ModelReply,
    ModelTimeout,
    ToolResult,
    ToolResultsTurn,
    ToolSpec,
    Turn,
)
from avengers_bank.domains.agent.reports import report_from_tool
from avengers_bank.domains.agent.schemas import FinancialReport, OpenAccountAction, TransferAction
from avengers_bank.domains.agent.tools import TOOLS, run_tool
from avengers_bank.domains.users.schemas import UserResponse

logger = logging.getLogger(__name__)

MAX_MODEL_CALLS = 6  # 질문 하나에 모델을 부르는 최대 횟수 (무한 반복 방지)
MAX_TOOL_CALLS = 8  # 질문 하나에 실행하는 Tool 최대 개수
RECURSION_LIMIT = 2 * MAX_MODEL_CALLS + 3  # 그래프 단계 상한. 위 두 상한이 먼저 걸리게 넉넉히 둔다

LIMIT_TEXT = "질문을 처리하는 데 단계가 너무 많이 필요합니다. 조금 더 구체적으로 나눠서 물어봐 주세요."
EMPTY_TEXT = "답변을 만들지 못했습니다. 다시 질문해 주세요."

TOOL_SPECS = [ToolSpec(t.name, t.description, t.input_schema) for t in TOOLS.values()]


@dataclass
class AgentContext:
    """요청마다 다른 값. 상태(state)가 아니라 실행 환경이라 따로 넘긴다."""

    client: ModelClient
    user: UserResponse


class AgentState(TypedDict, total=False):
    system: str
    turns: list[Turn]  # 모델에 보내는 대화 (지난 대화 + 이번 질문 + 이번 요청의 도구 호출·결과)
    reply: ModelReply  # 방금 받은 모델 응답
    model_calls: int
    tool_log: list[dict]  # [{"name", "ok"}] — 결과 값은 남기지 않는다
    action: TransferAction | OpenAccountAction | None  # prepare_transfer·prepare_open_account가 만든 카드
    reports: list[FinancialReport]
    answer: str


async def call_model(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    try:
        reply = await runtime.context.client.respond(state["system"], state["turns"], TOOL_SPECS)
    except ModelTimeout:
        raise ApiException(504, "AGENT_TIMEOUT", "AI 비서의 응답이 늦어지고 있습니다. 잠시 후 다시 시도해 주세요.") from None
    except ModelError:
        raise ApiException(503, "AGENT_UNAVAILABLE", "AI 비서를 지금 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.") from None
    return {"reply": reply, "model_calls": state["model_calls"] + 1}


def after_model(state: AgentState) -> str:
    calls = state["reply"].tool_calls
    if not calls:
        return "finish"
    if len(state["tool_log"]) + len(calls) > MAX_TOOL_CALLS:
        return "limit"  # 이 호출들은 실행하지 않는다
    return "tools"


async def run_tools(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    reply = state["reply"]
    tool_log, action, results = list(state["tool_log"]), state.get("action"), []
    reports = list(state.get("reports", []))
    for call in reply.tool_calls:
        outcome = await run_tool(call.name, call.arguments, runtime.context.user)
        tool_log.append({"name": call.name if call.name in TOOLS else "unknown", "ok": outcome.ok})
        if isinstance(outcome.result, (TransferAction, OpenAccountAction)):
            action = outcome.result
        elif outcome.ok:
            report = report_from_tool(outcome.result)
            if report is not None:
                values = report.model_dump(exclude={"captured_at"})
                reports = [item for item in reports if item.model_dump(exclude={"captured_at"}) != values]
                reports.append(report)
        results.append(ToolResult(call.id, outcome.content, not outcome.ok))
    return {
        "turns": [*state["turns"], AssistantTurn(reply), ToolResultsTurn(results)],
        "tool_log": tool_log,
        "action": action,
        "reports": reports,
    }


def after_tools(state: AgentState) -> str:
    return "limit" if state["model_calls"] >= MAX_MODEL_CALLS else "call_model"


async def finish(state: AgentState) -> dict:
    return {"answer": state["reply"].text.strip() or EMPTY_TEXT}


async def limit(state: AgentState, runtime: Runtime[AgentContext]) -> dict:
    logger.warning("agent 호출 상한 도달 (user_id=%s)", runtime.context.user.user_id)
    return {"answer": LIMIT_TEXT, "reports": []}


def _build():
    graph = StateGraph(AgentState, context_schema=AgentContext)
    graph.add_node("call_model", call_model)
    graph.add_node("tools", run_tools)
    graph.add_node("finish", finish)
    graph.add_node("limit", limit)
    graph.add_edge(START, "call_model")
    graph.add_conditional_edges("call_model", after_model, ["tools", "finish", "limit"])
    graph.add_conditional_edges("tools", after_tools, ["call_model", "limit"])
    graph.add_edge("finish", END)
    graph.add_edge("limit", END)
    return graph.compile()


agent_graph = _build()
