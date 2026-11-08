"""약관 검색 오프라인 평가 (C-075). DB·발행 없이 docs/terms 초안 코퍼스를 평가한다.

    uv run python scripts/eval_terms.py [--root docs/terms] [--fake] [--top-k 3] [--min-score 0.5] [--out report.md]

- 경로: load_corpus → chunk_document → 임베딩 → 사례마다 그 상품의 manifest 집합으로 범위 제한 → 운영과 같은 rank().
- 임베딩: 기본은 설정의 Gemini 모델(GEMINI_API_KEY 필요). --fake는 글자 2-gram 해시(의미 검색 아님)라 숫자를 품질로 읽지 않는다.
- --out: 마크다운 보고서. 같은 이름의 .json도 함께 쓴다.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from avengers_bank.core.config import get_settings
from avengers_bank.core.exceptions import ApiException
from avengers_bank.domains.terms.chunking import CHUNKER_VERSION, chunk_document
from avengers_bank.domains.terms.embedding import HashingEmbeddingClient, get_embedding_client
from avengers_bank.domains.terms.loader import load_corpus
from avengers_bank.domains.terms.search import Candidate, cosine, rank

SWEEP = [round(0.30 + 0.05 * i, 2) for i in range(11)]  # 0.30 ~ 0.80


async def evaluate(root: Path, embedder, top_k: int, min_score: float) -> dict:
    corpus = load_corpus(root)
    cases = json.loads((root / "evaluation.json").read_text(encoding="utf-8"))["cases"]
    chunks = [(doc, c) for doc in corpus.documents.values() for c in chunk_document(doc.title, doc.body)]
    doc_vecs = await embedder.embed([c.text for _, c in chunks], "document")
    query_vecs = await embedder.embed([case["query"] for case in cases], "query")
    scopes = {p.product_code: {(t.document_key, t.version) for t in p.terms} for p in corpus.products}

    rows = []
    for case, qv in zip(cases, query_vecs):
        behavior, code = case["expected_behavior"], case["product_code"]
        row = {"id": case["id"], "behavior": behavior, "product_code": code, "query": case["query"]}
        if code is None:  # 상품을 모르면 검색하지 않고 후보를 묻는다 (search_product_terms의 need_product)
            row.update(route="need_product", ok=behavior == "clarify_product")
            rows.append(row)
            continue
        scope = scopes[code]
        candidates = [
            Candidate((doc.document_key, doc.version, c.section_id), cosine(qv, v), c.text, c.section_id, c.section_title)
            for (doc, c), v in zip(chunks, doc_vecs) if (doc.document_key, doc.version) in scope
        ]
        everything = rank(case["query"], [Candidate(**{**c.__dict__}) for c in candidates], len(candidates), -1.0)
        hits = rank(case["query"], candidates, top_k, min_score)
        expected = {(s["document_key"], s["version"], s["section_id"]) for s in case["expected_sources"]}
        keys = [h.key for h in hits]
        row.update(
            top=[f"{k[0]}#{k[2]} ({h.vector_score:.3f})" for k, h in zip(keys, hits)],
            best_vector=max((c.vector_score for c in candidates), default=0.0),
            expected_vector=max((c.vector_score for c in candidates if c.key in expected), default=None),
            # 범위 밖 문서가 섞였는지 (범위를 먼저 거르므로 0이어야 한다)
            contamination=sum(1 for k in keys if (k[0], k[1]) not in scope),
            hit1=bool(keys) and keys[0] in expected, hitk=bool(expected & set(keys)),
            rank_unthresholded=next((i + 1 for i, c in enumerate(everything) if c.key in expected), None),
            insufficient=not hits,
        )
        if behavior == "answer_with_citation":
            row["ok"] = row["hitk"]
        elif behavior == "insufficient_evidence":
            row["ok"] = row["insufficient"]
        else:  # lookup_owned_agreement: 서버가 가입 당시 동의 버전(my_contract)으로 범위를 정한다. 여기서는 경로만 확인
            row.update(route="my_contract", ok=True)
        rows.append(row)

    answer = [r for r in rows if r["behavior"] == "answer_with_citation"]
    insufficient = [r for r in rows if r["behavior"] == "insufficient_evidence"]
    sweep = []
    for t in SWEEP:
        kept = sum(1 for r in answer if r["expected_vector"] is not None and r["expected_vector"] >= t)
        rejected = sum(1 for r in insufficient if r["best_vector"] < t)
        sweep.append({"threshold": t, "answer_cases_with_expected_above": kept, "answer_cases": len(answer),
                      "insufficient_cases_rejected": rejected, "insufficient_cases": len(insufficient)})
    return {
        "embedding": {"model": embedder.model_id, "dimensions": embedder.dimensions,
                      "fake": isinstance(embedder, HashingEmbeddingClient)},
        "chunker_version": CHUNKER_VERSION, "top_k": top_k, "min_score": min_score,
        "documents": len(corpus.documents), "chunks": len(chunks),
        "summary": {
            "answer_cases": len(answer),
            "hit@1": sum(r["hit1"] for r in answer), f"hit@{top_k}": sum(r["hitk"] for r in answer),
            "contamination": sum(r.get("contamination", 0) for r in rows),
            "insufficient_detected": f"{sum(r['insufficient'] for r in insufficient)}/{len(insufficient)}",
            "answer_cases_wrongly_insufficient": sum(r["insufficient"] for r in answer),
            "clarify_product_routed": f"{sum(r.get('route') == 'need_product' for r in rows)}"
                                      f"/{sum(r['behavior'] == 'clarify_product' for r in rows)}",
            "lookup_owned_agreement_routed": f"{sum(r.get('route') == 'my_contract' for r in rows)}"
                                             f"/{sum(r['behavior'] == 'lookup_owned_agreement' for r in rows)}",
            "cases_ok": f"{sum(r['ok'] for r in rows)}/{len(rows)}",
        },
        "sweep": sweep,
        "cases": rows,
    }


def markdown(report: dict) -> str:
    e, s = report["embedding"], report["summary"]
    kind = "FAKE (글자 2-gram 해시, 의미 검색 아님 — 품질 지표로 읽지 말 것)" if e["fake"] else "REAL (Gemini API)"
    lines = [
        "# 약관 검색 오프라인 평가", "",
        f"- 실행 종류: **{kind}**",
        f"- 임베딩: {e['model']}, {e['dimensions']}차원 / 청커 {report['chunker_version']}",
        f"- 문서 {report['documents']}개, 청크 {report['chunks']}개, top_k={report['top_k']}, min_score={report['min_score']}",
        "- 점수는 코사인 유사도이며 정답 확률이 아니다.", "",
        "## 요약", "", "| 항목 | 값 |", "|---|---|", *[f"| {k} | {v} |" for k, v in s.items()], "",
        "## 임계값 스윕 (terms_min_score 조정용)", "",
        "| 임계값 | 답변 사례 중 기대 조항이 임계값 이상 | 근거 부족 사례 중 거절 |", "|---|---|---|",
        *[f"| {w['threshold']:.2f} | {w['answer_cases_with_expected_above']}/{w['answer_cases']} | "
          f"{w['insufficient_cases_rejected']}/{w['insufficient_cases']} |" for w in report["sweep"]], "",
        "## 사례별", "", "| id | 기대 동작 | 결과 | 기대 조항 순위(임계값 무시) | 기대 조항 점수 | 최고 점수 | 상위 결과 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report["cases"]:
        exp = r.get("expected_vector")
        lines.append(
            f"| {r['id']} | {r['behavior']} | {'OK' if r['ok'] else 'MISS'} | {r.get('rank_unthresholded') or r.get('route', '-')} | "
            f"{'-' if exp is None else f'{exp:.3f}'} | {r['best_vector']:.3f} | {'<br>'.join(r.get('top', []))} |"
            if "best_vector" in r else
            f"| {r['id']} | {r['behavior']} | {'OK' if r['ok'] else 'MISS'} | {r['route']} | - | - | - |"
        )
    return "\n".join(lines) + "\n"


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="약관 검색 오프라인 평가 (초안 코퍼스, DB 없음)")
    parser.add_argument("--root", default=get_settings().terms_root)
    parser.add_argument("--fake", action="store_true", help="외부 API 없이 해시 임베딩으로 돌린다")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=get_settings().terms_min_score)
    parser.add_argument("--out", help="마크다운 보고서 경로 (같은 이름의 .json도 쓴다)")
    args = parser.parse_args()
    try:
        embedder = HashingEmbeddingClient() if args.fake else get_embedding_client()
    except ApiException:
        print("GEMINI_API_KEY가 없습니다. --fake로 돌리거나 키를 설정하세요.")
        return 1
    report = await evaluate(Path(args.root), embedder, args.top_k, args.min_score)
    text = markdown(report)
    print(text)
    if args.out:
        out = Path(args.out)
        out.write_text(text, encoding="utf-8")
        out.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
