"""가맹점 분류 오프라인 평가 (C-118). DB 없이 라벨 표본으로 classify_merchants를 실제 Gemini에 돌린다.

    uv run python scripts/eval_merchant_classification.py [--labels tests/fixtures/merchant_labels.json]

- GEMINI_API_KEY 필요. 표본 이름은 merchant_key로 중복 제거되므로 키가 겹치지 않게 만든다.
- "모호한데 억지로 분류": 기대가 UNCLASSIFIED인데 다른 항목을 받은 건수. 낮을수록 좋다.
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.agent.model_client import get_model_client
from avengers_bank.domains.money_management.classification import classify_merchants, merchant_key
from avengers_bank.domains.money_management.domain import Category


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="가맹점 분류 오프라인 평가")
    parser.add_argument("--labels", default="tests/fixtures/merchant_labels.json")
    args = parser.parse_args()
    try:
        client = get_model_client()
    except ApiException:
        print("GEMINI_API_KEY가 없습니다. 키를 설정하세요.")
        return 1
    cases = json.loads(Path(args.labels).read_text(encoding="utf-8"))["cases"]
    result = await classify_merchants([c["name"] for c in cases], client)

    rows = []
    for c in cases:
        got, reason = result.get(merchant_key(c["name"]), (None, "(응답 없음)"))
        rows.append({**c, "got": got, "reason": reason, "ok": got == c["expected"]})
    unclassified = [r for r in rows if r["expected"] == Category.UNCLASSIFIED]
    forced = [r for r in unclassified if r["got"] not in (None, Category.UNCLASSIFIED)]
    missing = [r for r in rows if r["got"] is None]
    wrong = [r for r in rows if not r["ok"]]

    print(f"정확도: {sum(r['ok'] for r in rows)}/{len(rows)}")
    print(f"응답 없음(실패한 배치·누락): {len(missing)}")
    print(f"모호한데 억지로 분류: {len(forced)}/{len(unclassified)}")
    print(f"분명한데 미분류로 답함: {sum(r['got'] == Category.UNCLASSIFIED and not r['ok'] for r in rows)}")
    print("\n## 혼동 (기대 → 결과)")
    for (exp, got), n in Counter((r["expected"], r["got"]) for r in wrong).most_common():
        print(f"- {exp} → {got}: {n}")
    print("\n## 틀린 사례")
    for r in wrong:
        print(f"- {r['name']}: 기대 {r['expected']}, 결과 {r['got']} ({r['reason']})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
