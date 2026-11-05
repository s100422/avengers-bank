"""현재 SQLAlchemy 모델에서 ERD(draw.io)를 만든다: docs/AvengersBankDiagram_v2.drawio

원본(docs/AvengersBankDiagram.drawio)은 건드리지 않는다. 모델이 바뀌면 이 스크립트를 다시 실행한다. DB 연결은 필요 없다.
실행: uv run python scripts/generate_erd_drawio.py
"""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Settings가 import 때 읽히므로 (연결은 하지 않음) 임시 값을 넣는다
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ.setdefault("JWT_SECRET_KEY", "x" * 40)

from sqlalchemy.dialects import postgresql

import avengers_bank.domains.accounts.models  # noqa: F401  모든 테이블을 Base에 등록
import avengers_bank.domains.cards.models  # noqa: F401
import avengers_bank.domains.products.models  # noqa: F401
import avengers_bank.domains.users.models  # noqa: F401
from avengers_bank.core.database import Base

OUT = Path(__file__).resolve().parent.parent / "docs" / "AvengersBankDiagram_v2.drawio"

# 표 제목(한글 이름)과 위치(x, y). 가로 4열: 회원·상품 | 계좌·카드 | 거래내역·사용내역·청구서
TABLES = {
    "users": ("회원", 0, 0),
    "account_products": ("계좌 상품", 0, 330),
    "card_products": ("카드 상품", 0, 1100),
    "checking_accounts": ("입출금 계좌", 560, 0),
    "deposit_accounts": ("예금 계좌", 560, 360),
    "savings_accounts": ("적금 계좌", 560, 690),
    "credit_cards": ("신용카드", 560, 1100),
    "debit_cards": ("체크카드", 560, 1430),
    "checking_account_histories": ("입출금 거래내역", 1120, 0),
    "deposit_account_histories": ("예금 거래내역", 1120, 360),
    "savings_account_histories": ("적금 거래내역", 1120, 690),
    "credit_card_histories": ("신용카드 사용내역", 1120, 1100),
    "credit_card_bills": ("신용카드 청구서", 1120, 1370),
    "debit_card_histories": ("체크카드 사용내역", 1120, 1730),
}

# 팀 초기 설계에서 바뀌었거나 새로 생긴 것 (docs/DESIGN_CHANGES.md의 C-007, C-008, C-010~C-013)
NEW_TABLES = {"credit_card_bills"}
CHANGED = {
    ("credit_card_histories", "bill_id"),
    ("credit_cards", "credit_limit"), ("credit_cards", "outstanding_amount"),
    ("card_products", "credit_limit"),
    *{(t, c) for t in ("checking_account_histories", "deposit_account_histories", "savings_account_histories")
      for c in ("amount", "balance_after", "counterpart_account")},
    ("checking_account_histories", "counterpart_name"),
    *{(t, c) for t in ("deposit_accounts", "savings_accounts") for c in ("status", "closed_at")},
}

W_MARK, W_NAME, W_TYPE, ROW_H, HEAD_H = 40, 190, 150, 30, 30
W = W_MARK + W_NAME + W_TYPE
YELLOW, YELLOW_LINE = "#FFF2CC", "#d6b656"

NOTE = (
    "<b>AvengersBank ERD v2</b> (2026-11-05, 현재 코드의 모델에서 자동 생성: scripts/generate_erd_drawio.py)<br>"
    "원본 AvengersBankDiagram.drawio는 그대로 두었다. <b>노란 칸 = 팀 초기 설계에서 바뀌었거나 새로 생긴 것</b> (docs/DESIGN_CHANGES.md)<br>"
    "• credit_card_bills 테이블 신규, credit_card_histories.bill_id 추가 (C-010)<br>"
    "• credit_cards.credit_limit 추가 (C-011), card_products.credit_limit 추가 (C-013)<br>"
    "• credit_cards.outstanding_amount(구 accumulated_amount)의 뜻이 신용카드는 '미결제액'으로 바뀜 (C-012)<br>"
    "• 거래내역: from_account / sending_account → counterpart_account (C-007), 금액 → amount(항상 양수) + balance_after (C-008)<br>"
    "기호: PK 기본키 · FK 외래키 · UK 유일 값. 관계선 끝의 까마귀발은 '여러 개', 시작쪽 ┃는 '반드시 하나', ○┃는 '없거나 하나'. "
    "인덱스와 CHECK 제약은 그리지 않았다 (C-003, C-004)."
)


def type_label(column) -> str:
    text = column.type.compile(dialect=postgresql.dialect())
    text = text.replace("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ").replace("INTEGER", "INT").replace(", ", ",")
    return text + (" NULL" if column.nullable and not column.primary_key else "")


def markers(table) -> dict[str, str]:
    result = {}
    unique = {c.name for c in table.columns if c.unique}
    for constraint in table.constraints:
        if constraint.__class__.__name__ == "UniqueConstraint":
            unique |= {c.name for c in constraint.columns}
    for column in table.columns:
        if column.primary_key:
            result[column.name] = "PK"
        elif column.foreign_keys:
            result[column.name] = "FK"
        elif column.name in unique:
            result[column.name] = "UK"
        else:
            result[column.name] = ""
    return result


def geometry(parent, **attrs):
    ET.SubElement(parent, "mxGeometry", {k: str(v) for k, v in attrs.items()} | {"as": "geometry"})


def cell(root, id_, parent, style, value="", **extra):
    return ET.SubElement(root, "mxCell", {"id": id_, "parent": parent, "style": style, "value": value} | extra)


def build() -> ET.ElementTree:
    missing = {t.name for t in Base.metadata.sorted_tables} ^ set(TABLES)
    assert not missing, f"TABLES와 모델이 다르다: {missing}"

    mxfile = ET.Element("mxfile", host="app.diagrams.net")
    diagram = ET.SubElement(mxfile, "diagram", name="ERD v2", id="avengers-bank-erd-v2")
    model = ET.SubElement(diagram, "mxGraphModel", dx="1414", dy="900", grid="1", gridSize="10", guides="1", tooltips="1",
                          connect="1", arrows="1", fold="1", page="1", pageScale="1", pageWidth="827", pageHeight="1169",
                          math="0", shadow="0")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    note = cell(root, "note", "1",
                f"rounded=1;whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacingLeft=10;spacingTop=6;"
                f"fillColor={YELLOW};strokeColor={YELLOW_LINE};", NOTE, vertex="1")
    geometry(note, x=0, y=-300, width=3 * W + 2 * 180, height=250)

    row_ids: dict[tuple[str, str], str] = {}
    for table in Base.metadata.sorted_tables:
        title, x, y = TABLES[table.name]
        marks = markers(table)
        table_style = ("shape=table;startSize=30;container=1;collapsible=1;childLayout=tableLayout;fixedRows=1;rowLines=0;"
                       "fontStyle=1;align=center;resizeLast=1;html=1;")
        if table.name in NEW_TABLES:
            table_style += f"fillColor={YELLOW};strokeColor={YELLOW_LINE};"
        table_cell = cell(root, f"t_{table.name}", "1", table_style, f"{table.name}({title})", vertex="1")
        geometry(table_cell, x=x, y=y, width=W, height=HEAD_H + ROW_H * len(table.columns))

        for i, column in enumerate(table.columns):
            highlight = table.name in NEW_TABLES or (table.name, column.name) in CHANGED
            fill = f"fillColor={YELLOW};" if highlight else "fillColor=none;"
            row_id = f"r_{table.name}_{column.name}"
            row_ids[(table.name, column.name)] = row_id
            bottom = 1 if column.primary_key else 0
            row = cell(root, row_id, table_cell.get("id"),
                       f"shape=tableRow;horizontal=0;startSize=0;swimlaneHead=0;swimlaneBody=0;{fill}collapsible=0;dropTarget=0;"
                       f"points=[[0,0.5],[1,0.5]];portConstraint=eastwest;top=0;left=0;right=0;bottom={bottom};", vertex="1")
            geometry(row, y=HEAD_H + ROW_H * i, width=W, height=ROW_H)

            base = f"shape=partialRectangle;connectable=0;{fill}top=0;left=0;bottom=0;right=0;overflow=hidden;whiteSpace=wrap;html=1;"
            parts = [
                (f"{row_id}_k", f"{base}fontStyle=1;", marks[column.name], 0, W_MARK),
                (f"{row_id}_n", f"{base}align=left;spacingLeft=6;fontStyle={5 if column.primary_key else 0};", column.name, W_MARK, W_NAME),
                (f"{row_id}_t", f"{base}align=left;spacingLeft=6;fontColor=#666666;fontSize=11;", type_label(column), W_MARK + W_NAME, W_TYPE),
            ]
            for id_, style, value, px, width in parts:
                part = cell(root, id_, row_id, style, value, vertex="1")
                geometry(part, x=px, width=width, height=ROW_H)

    n = 0
    for table in Base.metadata.sorted_tables:
        for foreign_key in table.foreign_keys:
            parent_col, child_col = foreign_key.column, foreign_key.parent
            source = row_ids[(parent_col.table.name, parent_col.name)]
            target = row_ids[(table.name, child_col.name)]
            sx, tx = TABLES[parent_col.table.name][1], TABLES[table.name][1]
            exit_x, entry_x = (1, 0) if tx > sx else (0, 1) if tx < sx else (1, 1)  # 같은 열이면 오른쪽으로 돌아서 연결
            start = "ERmandOne" if not child_col.nullable else "ERzeroToOne"
            n += 1
            edge = cell(root, f"e_{n}", "1",
                        f"edgeStyle=entityRelationEdgeStyle;fontSize=12;html=1;startArrow={start};startFill=0;endArrow=ERzeroToMany;"
                        f"endFill=1;rounded=0;defaultLabelBackgroundColor=page;exitX={exit_x};exitY=0.5;exitDx=0;exitDy=0;"
                        f"entryX={entry_x};entryY=0.5;entryDx=0;entryDy=0;", edge="1", source=source, target=target)
            ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
    tree = ET.ElementTree(mxfile)
    ET.indent(tree, space="  ")
    return tree


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    tree = build()
    tree.write(OUT, encoding="utf-8", xml_declaration=False)
    root = tree.getroot()
    tables = sum(1 for c in root.iter("mxCell") if str(c.get("style", "")).startswith("shape=table;"))
    edges = sum(1 for c in root.iter("mxCell") if c.get("edge") == "1")
    print(f"만들었다: {OUT.relative_to(OUT.parent.parent)} (표 {tables}개, 관계선 {edges}개)")
