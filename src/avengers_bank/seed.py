"""개발용 상품 데이터를 넣는다: uv run python -m avengers_bank.seed

상품이 하나라도 있으면 아무것도 하지 않는다(여러 번 실행해도 안전).
한도·금리 값은 임시 예시다. 팀이 정하면 이 파일만 고친다.
"""

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from avengers_bank.core.config import get_settings
from avengers_bank.domains.products.models import AccountProduct, CardProduct

ACCOUNT_PRODUCTS = [
    AccountProduct(type="CHECKING", name="어벤져스 입출금통장", description="자유롭게 입출금하는 기본 계좌", interest_rate=0.10),
    AccountProduct(type="DEPOSIT", name="어벤져스 정기예금", description="목돈을 맡기고 만기에 이자를 받는 예금", interest_rate=3.00),
    AccountProduct(type="SAVINGS", name="어벤져스 정기적금", description="매월 일정액을 납입하는 적금", interest_rate=3.50),
]
CARD_PRODUCTS = [
    CardProduct(type="CREDIT", name="어벤져스 일반 신용카드", description="한도 300만 원", credit_limit=3_000_000),
    CardProduct(type="CREDIT", name="어벤져스 프리미엄 신용카드", description="한도 1,000만 원", credit_limit=10_000_000),
    CardProduct(type="DEBIT", name="어벤져스 체크카드", description="입출금 계좌에서 바로 출금"),
]


def main() -> None:
    # 시드는 단발 스크립트라 동기 엔진을 쓴다 (Windows에서 psycopg 비동기 이벤트 루프 문제를 피함).
    engine = create_engine(get_settings().database_url)
    with Session(engine) as db, db.begin():
        if db.scalar(select(func.count()).select_from(AccountProduct)) or db.scalar(
            select(func.count()).select_from(CardProduct)
        ):
            print("상품이 이미 있어서 건너뜁니다.")
            return
        db.add_all([*ACCOUNT_PRODUCTS, *CARD_PRODUCTS])
        print(f"계좌 상품 {len(ACCOUNT_PRODUCTS)}개, 카드 상품 {len(CARD_PRODUCTS)}개를 넣었습니다.")
    engine.dispose()


if __name__ == "__main__":
    main()
