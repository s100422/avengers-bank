"""입출금·예금·적금의 차이를 한 곳에 모아 둔다. 세 종류가 같은 흐름(개설·조회·수정)을 쓰기 때문이다."""

from dataclasses import dataclass
from typing import Literal

from avengers_bank.domains.accounts.models import (
    CheckingAccount,
    CheckingAccountHistory,
    DepositAccount,
    DepositAccountHistory,
    SavingsAccount,
    SavingsAccountHistory,
)

AccountType = Literal["checking", "deposit", "savings"]

# 계좌 거래내역 type 값 (최종 목록은 팀 결정 대기, docs/ERD.md)
TRANSFER_OUT = "TRANSFER_OUT"  # 입출금 → 입출금 이체, 보낸 쪽
TRANSFER_IN = "TRANSFER_IN"  # 이체·납입을 받은 쪽 (입출금·예금·적금 공통)
TO_SAVINGS = "TO_SAVINGS"  # 입출금 → 적금 납입, 입출금 쪽
TO_DEPOSIT = "TO_DEPOSIT"  # 입출금 → 예금 입금, 입출금 쪽
INTERBANK_OUT = "INTERBANK_OUT"  # 타행 이체, 보낸 쪽 (interbank/)
INTERBANK_IN = "INTERBANK_IN"  # 타행 이체, 받은 쪽
INTERBANK_REFUND = "INTERBANK_REFUND"  # 허브가 확정 실패(FAILED)로 답해 출금을 되돌림
CLOSE_IN = "CLOSE_IN"  # 예금·적금 해지금을 받은 입출금 쪽 (C-043)
INTEREST = "INTEREST"  # 해지 때 받은 이자 (예금·적금 쪽)
CLOSE_OUT = "CLOSE_OUT"  # 해지로 나간 원금+이자 (예금·적금 쪽)


@dataclass(frozen=True)
class AccountKind:
    name: AccountType
    model: type
    id_column: str  # 모델의 PK 컬럼 이름
    history_model: type
    history_id_column: str
    product_type: str  # account_products.type 값
    prefix: str  # 계좌번호 앞자리 (ERD 규칙 1)


KINDS: dict[str, AccountKind] = {
    "checking": AccountKind(
        "checking", CheckingAccount, "checking_account_id",
        CheckingAccountHistory, "checking_account_history_id", "CHECKING", "110",
    ),
    "deposit": AccountKind(
        "deposit", DepositAccount, "deposit_account_id",
        DepositAccountHistory, "deposit_account_history_id", "DEPOSIT", "120",
    ),
    "savings": AccountKind(
        "savings", SavingsAccount, "savings_account_id",
        SavingsAccountHistory, "savings_account_history_id", "SAVINGS", "220",
    ),
}
