"""조항 기반 청킹 (C-075). 조항(## [id])이 1차 경계이고, 긴 조항만 문단 단위로 나눈다.

- 표(| 로 시작하는 줄 묶음)와 목록 항목 하나는 절대 가르지 않는다 (예외 조건·표가 근거에서 잘려 나가지 않게).
- 청크 글 = "문서 제목 > 조항 제목" + 빈 줄 + 원문 조각. 원문 위치(char_start/end)는 body 기준이다.
- 이 규칙을 바꾸면 CHUNKER_VERSION을 올린다 → 색인 세대가 바뀌어 전체 재색인.
"""

import re
from dataclasses import dataclass

from avengers_bank.domains.terms.markdown import parse_sections

CHUNKER_VERSION = "sec-v1"
# 한국어는 토큰당 글자 수가 1~2자 정도라 보수적으로 1글자 = 1토큰으로 센다 (청크가 모델 입력 한도를 넘지 않게)
CHARS_PER_TOKEN = 1.0
MAX_TOKENS = 600  # 400~800 토큰 사이
OVERLAP_TOKENS = 80  # 50~100 토큰
MAX_CHARS = int(MAX_TOKENS * CHARS_PER_TOKEN)
OVERLAP_CHARS = int(OVERLAP_TOKENS * CHARS_PER_TOKEN)

_LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    section_id: str
    section_title: str
    heading_path: str
    char_start: int
    char_end: int
    text: str


def _atoms(body: str, start: int, end: int) -> list[tuple[int, int]]:
    """나눌 수 없는 조각들: 빈 줄로 나뉜 문단. 목록은 최상위 항목마다 따로, 표는 통째로."""
    atoms: list[list[int]] = []
    open_ = False
    pos = start
    for line in body[start:end].splitlines(keepends=True):
        s, e = pos, pos + len(line.rstrip())
        pos += len(line)
        if not line.strip():
            open_ = False
            continue
        is_table = open_ and body[atoms[-1][0]] == "|"
        if open_ and not (_LIST_ITEM.match(line) and not is_table):
            atoms[-1][1] = e
        else:
            atoms.append([s, e])
            open_ = True
    return [(s, e) for s, e in atoms]


def _spans(atoms: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """조각을 MAX_CHARS까지 이어 붙이고, 다음 청크는 앞 청크 끝의 OVERLAP_CHARS 이내 조각부터 다시 시작한다."""
    spans, i = [], 0
    while i < len(atoms):
        j = i + 1
        while j < len(atoms) and atoms[j][1] - atoms[i][0] <= MAX_CHARS:
            j += 1
        spans.append((atoms[i][0], atoms[j - 1][1]))
        if j >= len(atoms):
            break
        k = j
        while k - 1 > i and atoms[j - 1][1] - atoms[k - 1][0] <= OVERLAP_CHARS:
            k -= 1
        i = k
    return spans


def chunk_document(title: str, body: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in parse_sections(body):
        heading = f"{title} > {section.title}"
        for start, end in _spans(_atoms(body, section.start, section.end)):
            chunks.append(Chunk(len(chunks), section.section_id, section.title, heading, start, end,
                                f"{heading}\n\n{body[start:end]}"))
    return chunks
