"""약관 검색용 임베딩 경계 (C-075). 색인·검색은 EmbeddingClient만 안다.

Gemini 임베딩 (공식 문서 https://ai.google.dev/gemini-api/docs/embeddings → aistudio.google.com/docs/embeddings,
API https://ai.google.dev/api/embeddings, 2026-11-07 확인):
- gemini-embedding-001: 텍스트 전용, 입력 2,048토큰, task_type(RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY) 지원.
  기본 3,072차원, output_dimensionality 128~3072 (권장 768·1536·3072). 3072가 아니면 직접 정규화해야 한다.
- gemini-embedding-2: 최신 안정판(멀티모달, 8,192토큰). task_type을 받지 않고 글 앞에 작업을 적는다.
  여러 입력을 contents 목록 하나로 보내면 하나로 합쳐지므로 입력마다 Content로 감싼다.
문서·질의는 반드시 같은 모델·차원으로 만든다. 벡터는 항상 L2 정규화해서 돌려준다.
"""

import asyncio
import hashlib
import logging
import math
from functools import lru_cache
from typing import Literal, Protocol

import httpx
from google import genai
from google.genai import errors, types

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException

logger = logging.getLogger(__name__)

Task = Literal["document", "query"]
# shortcut: 공식 문서에 요청당 개수 한도가 없다. batchEmbedContents가 100개를 넘기면 거절해 온 값을 쓴다
BATCH_SIZE = 100


class EmbeddingError(Exception):
    """임베딩 실패. 메시지에 키·원문 응답을 넣지 않는다."""


class EmbeddingClient(Protocol):
    model_id: str
    dimensions: int

    async def embed(self, texts: list[str], task: Task) -> list[list[float]]: ...


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise EmbeddingError("영벡터")
    return [x / norm for x in vector]


def check_vectors(vectors: list[list[float]], count: int, dimensions: int) -> list[list[float]]:
    if len(vectors) != count or any(len(v) != dimensions for v in vectors):
        raise EmbeddingError(f"벡터 개수·차원이 설정과 다릅니다 (기대 {count}×{dimensions})")
    return [normalize(v) for v in vectors]


class GeminiEmbeddingClient:
    def __init__(self, api_key: str, model: str, dimensions: int, timeout: float):
        self.client = genai.Client(api_key=api_key)
        self.model_id = model
        self.dimensions = dimensions
        self.timeout = timeout

    def _request(self, texts: list[str], task: Task) -> tuple[list[types.Content], types.EmbedContentConfig]:
        if self.model_id.startswith("gemini-embedding-2"):
            texts = [f"task: search result | query: {t}" if task == "query" else f"title: none | text: {t}" for t in texts]
            task_type = None
        else:
            task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
        contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]
        return contents, types.EmbedContentConfig(task_type=task_type, output_dimensionality=self.dimensions)

    async def embed(self, texts: list[str], task: Task) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            contents, config = self._request(batch, task)
            try:
                async with asyncio.timeout(self.timeout):
                    response = await self.client.aio.models.embed_content(
                        model=self.model_id, contents=contents, config=config
                    )
            except TimeoutError as e:
                raise EmbeddingError("임베딩 응답 시간 초과") from e
            except (errors.APIError, httpx.HTTPError) as e:
                logger.warning("Gemini 임베딩 오류: %s", type(e).__name__)
                raise EmbeddingError(f"임베딩 API 오류 ({type(e).__name__})") from e
            out += check_vectors([list(e.values or []) for e in response.embeddings or []], len(batch), self.dimensions)
        return out


class HashingEmbeddingClient:
    """외부 API 없는 결정적 임베딩 (글자 2-gram을 해시해 차원에 더한다). 오프라인 평가 --fake 전용. 의미 검색이 아니다."""

    def __init__(self, dimensions: int = 256):
        self.model_id = f"fake-hashing-{dimensions}"
        self.dimensions = dimensions

    async def embed(self, texts: list[str], task: Task) -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dimensions
            s = "".join(text.split())
            for gram in {s[i:i + 2] for i in range(len(s) - 1)}:
                v[int(hashlib.md5(gram.encode()).hexdigest(), 16) % self.dimensions] += 1.0
            v[0] += 1e-6  # 빈 글도 영벡터가 되지 않게
            out.append(normalize(v))
        return out


_override: EmbeddingClient | None = None


def set_embedding_client(client: EmbeddingClient | None) -> None:
    """테스트·스크립트가 가짜 클라이언트를 넣는다. None이면 설정의 Gemini로 돌아간다."""
    global _override
    _override = client


@lru_cache
def _gemini(api_key: str, model: str, dimensions: int, timeout: float) -> GeminiEmbeddingClient:
    return GeminiEmbeddingClient(api_key, model, dimensions, timeout)


def get_embedding_client() -> EmbeddingClient:
    if _override is not None:
        return _override
    s = get_settings()
    if s.gemini_api_key is None or not s.gemini_api_key.get_secret_value():
        raise ApiException(503, "TERMS_SEARCH_UNAVAILABLE", "약관 검색이 아직 설정되지 않았습니다.")
    return _gemini(s.gemini_api_key.get_secret_value(), s.embedding_model, s.embedding_dimensions,
                   s.embedding_timeout_seconds)
