"""약관 Markdown 형식 (docs/terms/README.md 계약): front matter + `## [section-id] 제목` 조항."""

import hashlib
import re
from dataclasses import dataclass

import yaml

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_H2 = re.compile(r"^## (.*)$", re.M)
_SECTION = re.compile(r"^\[([^\]]*)\] (\S.*?)\s*$")
_TITLE = re.compile(r"^# (\S.*?)\s*$", re.M)
SECTION_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PREAMBLE_ID = "preamble"  # 첫 조항 앞의 글(제목·안내문)


class TermsFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Section:
    section_id: str
    title: str
    start: int  # body 안 위치. 헤딩 줄부터 다음 조항 헤딩 앞까지 [start, end)
    end: int


def normalize(raw: str) -> str:
    return raw.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_front_matter(raw: str) -> tuple[dict, str]:
    """정규화한 글 → (front matter, 본문). safe_load라서 임의 객체를 만들지 않는다 (JSON도 YAML이라 그대로 읽힌다)."""
    text = normalize(raw)
    m = _FRONT.match(text)
    if m is None:
        raise TermsFormatError("front matter(--- ... ---)가 없습니다.")
    meta = yaml.safe_load(m.group(1))
    if not isinstance(meta, dict):
        raise TermsFormatError("front matter가 객체가 아닙니다.")
    return meta, text[m.end():]


def parse_sections(body: str) -> list[Section]:
    """조항 목록. 모든 `## ` 헤딩은 `## [id] 제목` 형식이어야 하고 id는 문서 안에서 고유하다."""
    heads = list(_H2.finditer(body))
    sections: list[Section] = []
    first = heads[0].start() if heads else len(body)
    if body[:first].strip():
        m = _TITLE.search(body[:first])
        sections.append(Section(PREAMBLE_ID, m.group(1) if m else "머리말", 0, first))
    for i, h in enumerate(heads):
        m = _SECTION.match(h.group(1))
        if m is None or not SECTION_ID.match(m.group(1)):
            raise TermsFormatError(f"조항 헤딩 형식 오류: {h.group(0)!r} (## [section-id] 제목)")
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        sections.append(Section(m.group(1), m.group(2), h.start(), end))
    ids = [s.section_id for s in sections]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise TermsFormatError(f"조항 ID 중복: {sorted(dup)}")
    if not heads:
        raise TermsFormatError("조항(## [id] 제목)이 하나도 없습니다.")
    return sections


def document_title(body: str) -> str | None:
    m = _TITLE.search(body)
    return m.group(1) if m else None
