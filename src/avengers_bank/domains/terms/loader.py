"""docs/terms/(manifest.json + corpus/**/*.md)를 읽고 검증한다. DB를 모른다.

검증 실패는 첫 오류에서 멈추지 않고 모두 모아 TermsSourceError로 알린다.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from avengers_bank.domains.terms.markdown import Section, TermsFormatError, parse_sections, sha256, split_front_matter
from avengers_bank.domains.terms.models import PRODUCT_KINDS

DOCUMENT_TYPES = ("common_terms", "category_terms", "product_terms")
STATUSES = ("draft", "published", "retired")


class TermsSourceError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class SourceDocument:
    document_key: str
    version: str
    path: str  # 루트 기준 상대경로
    title: str
    document_type: str
    product_kinds: tuple[str, ...]
    effective_from: date | None
    meta: dict
    body: str
    body_sha256: str
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class TermsLink:
    document_key: str
    version: str
    required: bool
    order: int


@dataclass(frozen=True)
class ProductSpec:
    product_code: str
    kind: str
    seed_name: str
    terms: tuple[TermsLink, ...]


@dataclass(frozen=True)
class Corpus:
    documents: dict[tuple[str, str], SourceDocument]
    products: tuple[ProductSpec, ...]


def _document(root: Path, entry: dict, errors: list[str]) -> SourceDocument | None:
    key, version, rel = entry.get("document_key"), entry.get("version"), entry.get("path")
    where = f"documents[{key}@{version}]"
    if not (isinstance(key, str) and isinstance(version, str) and isinstance(rel, str)):
        errors.append(f"{where}: document_key·version·path는 문자열이어야 합니다.")
        return None
    if len(key) > 100 or len(version) > 20:
        errors.append(f"{where}: document_key는 100자, version은 20자 이하여야 합니다.")
    corpus = (root / "corpus").resolve()
    path = (root / rel).resolve()
    # corpus/ 밖(README·평가 질문·출처 등)은 사용자 검색 대상이 아니므로 읽지 않는다
    if not path.is_relative_to(corpus) or path.suffix != ".md":
        errors.append(f"{where}: path는 corpus/ 아래의 .md여야 합니다: {rel}")
        return None
    if not path.is_file():
        errors.append(f"{where}: 파일이 없습니다: {rel}")
        return None
    try:
        meta, body = split_front_matter(path.read_text(encoding="utf-8"))
        sections = parse_sections(body)
    except (TermsFormatError, UnicodeDecodeError, yaml.YAMLError) as e:
        errors.append(f"{where}: {e}")
        return None

    def bad(msg: str):
        errors.append(f"{where}: {msg}")

    if meta.get("schema_version") != 1:
        bad("schema_version은 1이어야 합니다.")
    if meta.get("document_key") != key or str(meta.get("version")) != version:
        bad("front matter의 document_key·version이 manifest와 다릅니다.")
    title = meta.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        bad("title이 없거나 200자를 넘습니다.")
    if meta.get("status") not in STATUSES:
        bad(f"status는 {STATUSES} 중 하나여야 합니다.")
    if meta.get("demo_only") is not True:
        bad("demo_only: true가 필요합니다.")
    if meta.get("document_type") not in DOCUMENT_TYPES:
        bad(f"document_type은 {DOCUMENT_TYPES} 중 하나여야 합니다.")
    kinds = meta.get("product_kinds")
    if not isinstance(kinds, list) or not kinds or not set(kinds) <= set(PRODUCT_KINDS):
        bad(f"product_kinds는 {PRODUCT_KINDS}의 부분집합이어야 합니다.")
        kinds = []
    if not isinstance(meta.get("source_ids", []), list):
        bad("source_ids는 배열이어야 합니다.")
    effective = meta.get("effective_from")
    if effective is not None and not isinstance(effective, date):
        try:
            effective = date.fromisoformat(str(effective))
        except ValueError:
            bad("effective_from은 null 또는 YYYY-MM-DD여야 합니다.")
            effective = None
    return SourceDocument(
        key, version, rel, str(title), str(meta.get("document_type")), tuple(kinds), effective,
        json.loads(json.dumps(meta, default=str)), body, sha256(body), tuple(sections),
    )


def load_corpus(root: Path | str) -> Corpus:
    root = Path(root)
    errors: list[str] = []
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise TermsSourceError([f"manifest.json을 읽을 수 없습니다: {e}"]) from None
    if manifest.get("schema_version") != 1:
        errors.append("manifest schema_version은 1이어야 합니다.")

    documents: dict[tuple[str, str], SourceDocument] = {}
    for entry in manifest.get("documents") or []:
        doc = _document(root, entry, errors)
        if doc is None:
            continue
        if (doc.document_key, doc.version) in documents:
            errors.append(f"문서 중복: {doc.document_key}@{doc.version}")
        documents[(doc.document_key, doc.version)] = doc

    listed = {(root / d.path).resolve() for d in documents.values()}
    for path in sorted((root / "corpus").rglob("*.md")):
        if path.resolve() not in listed:
            errors.append(f"manifest에 없는 corpus 문서: {path.relative_to(root).as_posix()}")

    products: list[ProductSpec] = []
    codes: set[str] = set()
    for p in manifest.get("products") or []:
        code, kind, name = p.get("product_code"), p.get("kind"), p.get("seed_name")
        where = f"products[{code}]"
        if not (isinstance(code, str) and code and isinstance(name, str) and name):
            errors.append(f"{where}: product_code·seed_name이 필요합니다.")
            continue
        if code in codes:
            errors.append(f"{where}: product_code 중복")
        codes.add(code)
        if kind not in PRODUCT_KINDS:
            errors.append(f"{where}: kind는 {PRODUCT_KINDS} 중 하나여야 합니다.")
            continue
        links: list[TermsLink] = []
        for t in p.get("terms") or []:
            ref = (t.get("document_key"), t.get("version"))
            doc = documents.get(ref)
            if doc is None:
                errors.append(f"{where}: 없는 문서를 참조합니다: {ref[0]}@{ref[1]}")
            elif kind not in doc.product_kinds:
                errors.append(f"{where}: {ref[0]}의 product_kinds에 {kind}가 없습니다.")
            if not isinstance(t.get("required"), bool) or not isinstance(t.get("order"), int):
                errors.append(f"{where}: {ref[0]}의 required(bool)·order(int)가 필요합니다.")
                continue
            links.append(TermsLink(ref[0], ref[1], t["required"], t["order"]))
        keys = [link.document_key for link in links]
        orders = [link.order for link in links]
        if len(set(keys)) != len(keys) or len(set(orders)) != len(orders):
            errors.append(f"{where}: 같은 문서 또는 같은 order가 두 번 나옵니다.")
        if not any(link.required for link in links):
            errors.append(f"{where}: 필수 약관이 하나도 없습니다.")
        products.append(ProductSpec(code, kind, name, tuple(sorted(links, key=lambda x: x.order))))

    if errors:
        raise TermsSourceError(errors)
    return Corpus(documents, tuple(products))
