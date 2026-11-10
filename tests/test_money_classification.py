import json
from datetime import datetime

import pytest

from avengers_bank.domains.agent.model_client import ModelError, ModelTimeout
from avengers_bank.domains.money_management.classification import (
    RESPONSE_SCHEMA,
    classify_merchants,
    merchant_key,
    resolve,
)
from avengers_bank.domains.money_management.domain import Category, Txn

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(("name", "key"), [
    ("스타벅스 강남역점", "스타벅스"),
    ("GS25 삼성점", "gs25"),
    ("  스타벅스   강남역점 ", "스타벅스"),
    ("카카오T 택시", "카카오t 택시"),
    ("점", "점"),
    ("역삼점", "역삼점"),
    ("(주)우아한형제들", "우아한형제들"),
    ("㈜우아한형제들", "우아한형제들"),
    ("주식회사 한빛", "한빛"),
    ("주식회사", "주식회사"),
    ("(주)", "(주)"),
    ("신세계 백화점", "신세계 백화점"),
    ("영풍 서점", "영풍 서점"),
    ("ＮＥＴＦＬＩＸ", "netflix"),
    ("가" * 150, "가" * 100),
])
def test_merchant_key(name, key):
    assert merchant_key(name) == key


def txn(source="credit", merchant="스타벅스 강남역점", checking_type=None, self_transfer=False):
    return Txn(
        source=source, source_id=1, occurred_at=datetime(2026, 11, 1), amount=1000, direction="OUT",
        merchant=merchant, merchant_key=merchant_key(merchant), checking_type=checking_type,
        payment_label="x", is_self_transfer=self_transfer,
    )


def test_resolve_card_priority():
    t = txn()
    rules = {"스타벅스": Category.DINING}
    cache = {"스타벅스": Category.CAFE}
    assert resolve(t, Category.LEISURE, rules, cache) == (Category.LEISURE, "OVERRIDE")
    assert resolve(t, None, rules, cache) == (Category.DINING, "RULE")
    assert resolve(t, None, {}, cache) == (Category.CAFE, "LLM")
    assert resolve(t, None, {}, {}) == (Category.UNCLASSIFIED, "NONE")


def test_resolve_checking():
    out = txn("checking", "홍길동", "TRANSFER_OUT")
    assert resolve(out, None, {}, {"홍길동": Category.CAFE}) == (Category.TRANSFER, "TYPE")  # 캐시는 이체에 안 쓴다
    assert resolve(out, None, {"홍길동": Category.HOUSING}, {}) == (Category.HOUSING, "RULE")
    assert resolve(out, Category.MEDICAL, {"홍길동": Category.HOUSING}, {}) == (Category.MEDICAL, "OVERRIDE")
    assert resolve(txn("checking", "홍길동", "TRANSFER_OUT", self_transfer=True), None, {}, {}) == (None, "NONE")
    assert resolve(txn("checking", "홍길동", "TRANSFER_IN"), None, {}, {}) == (None, "NONE")


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)  # 배치마다 하나: 값 또는 예외
        self.prompts = []

    async def generate_json(self, system, prompt, schema):
        assert schema is RESPONSE_SCHEMA
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer(self.sent(prompt)) if callable(answer) else answer

    @staticmethod
    def sent(prompt):
        return json.loads(prompt.rsplit("\n", 1)[1])


async def test_classify_maps_by_index_and_validates():
    client = FakeClient([[
        {"index": 1, "category": "DINING", "reason": "식사" * 50},
        {"index": 0, "category": "CAFE", "reason": "커피"},
        {"index": 0, "category": "DINING", "reason": "중복"},
        {"index": 2, "category": "TRANSFER", "reason": "이체"},
        {"index": 3, "category": "FOOD", "reason": "없는 값"},
        {"index": 9, "category": "CAFE", "reason": "범위 밖"},
        "garbage",
    ]])
    result = await classify_merchants(["스타벅스 강남역점", "맥도날드", "토스", "무엇", ""], client)
    assert client.sent(client.prompts[0]) == ["스타벅스 강남역점", "맥도날드", "토스", "무엇"]
    assert result == {"스타벅스": (Category.CAFE, "커피"), "맥도날드": (Category.DINING, ("식사" * 50)[:60])}


async def test_classify_dedupes_branches():
    client = FakeClient([lambda names: [{"index": 0, "category": "CAFE", "reason": "커피"}]])
    result = await classify_merchants(["스타벅스 강남역점", "스타벅스 역삼점"], client)
    assert client.sent(client.prompts[0]) == ["스타벅스 강남역점"]
    assert result == {"스타벅스": (Category.CAFE, "커피")}


async def test_classify_partial_batch_failure():
    names = [f"가맹점{i}" for i in range(120)]
    every = lambda names: [{"index": i, "category": "ETC", "reason": "-"} for i in range(len(names))]  # noqa: E731
    client = FakeClient([every, ModelTimeout(), {"not": "a list"}])
    result = await classify_merchants(names, client)
    assert [len(client.sent(p)) for p in client.prompts] == [50, 50, 20]
    assert set(result) == {f"가맹점{i}" for i in range(50)}


async def test_classify_failure_returns_empty():
    assert await classify_merchants(["쿠팡"], FakeClient([ModelError()])) == {}
    assert await classify_merchants([], FakeClient([])) == {}
