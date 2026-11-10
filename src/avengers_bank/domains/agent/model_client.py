"""AI 모델 공급자 경계. service.py는 아래 중립 타입과 ModelClient만 안다.

공급자를 바꾸려면 ModelClient를 구현하는 클래스를 하나 더 만들고 get_model_client에서 고른다.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import httpx
from google import genai
from google.genai import errors, types

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Any


@dataclass
class ModelReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None  # 공급자 원본 응답. 같은 요청 안에서 다음 호출에 그대로 되돌려 보낸다 (thought signature 보존)


@dataclass
class UserTurn:
    text: str


@dataclass
class AssistantTurn:
    reply: ModelReply


@dataclass
class ToolResult:
    call_id: str
    content: str
    is_error: bool


@dataclass
class ToolResultsTurn:
    results: list[ToolResult]


Turn = UserTurn | AssistantTurn | ToolResultsTurn


class ModelError(Exception):
    """모델 API 호출 실패 (인증·요청 한도·서버 오류·연결 오류)."""


class ModelTimeout(ModelError):
    pass


class ModelClient(Protocol):
    async def respond(self, system: str, turns: list[Turn], tools: list[ToolSpec]) -> ModelReply: ...

    async def generate_json(self, system: str, prompt: str, schema: dict) -> Any: ...


REFUSAL_TEXT = "죄송하지만 이 요청은 도와드릴 수 없습니다."
_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
_GENERATED_ID = "gen:"  # Gemini가 호출 id를 주지 않을 때 우리가 붙이는 id (되돌려 보낼 때는 뺀다)


def _name(value) -> str | None:
    return getattr(value, "name", None) or (str(value) if value else None)


class GeminiModelClient:
    """Google Gemini (google-genai SDK) + 직접 돌리는 function calling 루프의 한 단계."""

    def __init__(self, api_key: str, model: str, timeout: float):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.timeout = timeout

    @staticmethod
    def _contents(turns: list[Turn]) -> list[types.Content]:
        calls: dict[str, ToolCall] = {}  # function_response에는 호출한 함수 이름이 필요하다
        contents = []
        for t in turns:
            if isinstance(t, UserTurn):
                contents.append(types.Content(role="user", parts=[types.Part(text=t.text)]))
            elif isinstance(t, AssistantTurn):
                calls.update({c.id: c for c in t.reply.tool_calls})
                contents.append(
                    t.reply.raw if t.reply.raw is not None
                    else types.Content(role="model", parts=[types.Part(text=t.reply.text)])
                )
            else:
                parts = []
                for r in t.results:
                    data = json.loads(r.content)
                    parts.append(types.Part(function_response=types.FunctionResponse(
                        id=None if r.call_id.startswith(_GENERATED_ID) else r.call_id,
                        name=calls[r.call_id].name,
                        response=data if r.is_error else {"output": data},  # Gemini 권장 키: output / error
                    )))
                contents.append(types.Content(role="user", parts=parts))
        return contents

    async def respond(self, system: str, turns: list[Turn], tools: list[ToolSpec]) -> ModelReply:
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.input_schema)
                for t in tools
            ])],
            # SDK가 함수를 알아서 실행하지 않게 한다. 실행·검증·상한은 service.py가 맡는다
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.client.aio.models.generate_content(
                    model=self.model, contents=self._contents(turns), config=config
                )
        except TimeoutError as e:
            raise ModelTimeout() from e
        except (errors.APIError, httpx.HTTPError) as e:
            # 키·프롬프트가 섞일 수 있는 원문은 사용자에게 보내지 않고 로그에만 남긴다
            logger.warning("Gemini API 오류: %s", type(e).__name__)
            raise ModelError() from e

        candidate = response.candidates[0] if response.candidates else None
        finish = _name(candidate.finish_reason) if candidate else None
        if candidate is None or finish in _BLOCKED:
            blocked = response.prompt_feedback and response.prompt_feedback.block_reason
            return ModelReply(text=REFUSAL_TEXT if blocked or finish in _BLOCKED else "")
        parts = (candidate.content.parts if candidate.content else None) or []
        text = "".join(p.text for p in parts if p.text and not p.thought)
        if finish == "MAX_TOKENS":
            return ModelReply(text=text)  # 잘린 함수 호출은 실행하지 않는다
        calls = [
            ToolCall(p.function_call.id or f"{_GENERATED_ID}{i}", p.function_call.name, dict(p.function_call.args or {}))
            for i, p in enumerate(parts) if p.function_call
        ]
        return ModelReply(text=text, tool_calls=calls, raw=candidate.content)

    async def generate_json(self, system: str, prompt: str, schema: dict) -> Any:
        """도구 없는 한 번의 호출. 응답을 schema(JSON Schema)로 제한하고 파싱한 값을 돌려준다."""
        config = types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json", response_json_schema=schema
        )
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.client.aio.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
        except TimeoutError as e:
            raise ModelTimeout() from e
        except (errors.APIError, httpx.HTTPError) as e:
            logger.warning("Gemini API 오류: %s", type(e).__name__)
            raise ModelError() from e

        candidate = response.candidates[0] if response.candidates else None
        if candidate is None or _name(candidate.finish_reason) in _BLOCKED | {"MAX_TOKENS"}:
            raise ModelError()
        parts = (candidate.content.parts if candidate.content else None) or []
        try:
            return json.loads("".join(p.text for p in parts if p.text and not p.thought))
        except ValueError as e:
            raise ModelError() from e


@lru_cache
def _gemini_client(api_key: str, model: str, timeout: float) -> GeminiModelClient:
    return GeminiModelClient(api_key, model, timeout)


def get_model_client() -> ModelClient:
    """FastAPI 의존성. 테스트는 app.dependency_overrides로 가짜 클라이언트를 넣는다."""
    s = get_settings()
    if s.gemini_api_key is None or not s.gemini_api_key.get_secret_value():
        raise ApiException(503, "AGENT_UNAVAILABLE", "AI 비서가 아직 설정되지 않았습니다.")
    return _gemini_client(s.gemini_api_key.get_secret_value(), s.agent_model, s.agent_timeout_seconds)
