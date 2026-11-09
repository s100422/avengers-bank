"""타행 이체 거래내역의 상대 이름을 은행 이름 대신 사람 이름으로 (C-108)

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-11-09 16:00:00

예전에는 보낸 내역에 받는 은행 이름('AvengersBank')을, 받은 내역에 '은행이름 보낸분'을 저장했다.
이제 거래내역의 상대 이름은 사람 이름(실명)이나 가맹점 이름만 쓴다.
기존 행은 같은 계좌·상대 계좌·금액의 interbank_transfers 행에서 이름을 찾아 바꾸고, 못 찾으면 NULL로 둔다
(화면은 이름이 없으면 계좌번호를 보인다). 되돌릴 원본 값은 남기지 않는다.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE checking_account_histories h
        SET counterpart_name = (
            SELECT t.peer_name FROM interbank_transfers t
            WHERE t.checking_account_id = h.checking_account_id
              AND t.peer_account = h.counterpart_account
              AND t.amount = h.amount
              AND t.direction = CASE WHEN h.type = 'INTERBANK_IN' THEN 'IN' ELSE 'OUT' END
              AND t.peer_name IS NOT NULL
            LIMIT 1
        )
        WHERE h.type IN ('INTERBANK_OUT', 'INTERBANK_IN', 'INTERBANK_REFUND')
        """
    )


def downgrade() -> None:
    pass  # 이름 데이터 정리라 되돌리지 않는다
