"""개발용 상품 데이터를 넣는다: uv run python -m avengers_bank.seed

이름이 같은 상품이 이미 있으면 새로 넣지 않고, 예금 최소 가입 금액(min_amount)만 시드 값으로 갱신한다
(여러 번 실행해도 안전).
금리·한도·혜택은 시중은행 상품 구성을 참고해 만든 예시 값이다. 실제 상품·현재 금리가 아니다 (C-061).
"""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from avengers_bank.core.config import get_settings
from avengers_bank.domains.products.models import AccountProduct, CardProduct

ACCOUNT_PRODUCTS = [
    # 입출금
    AccountProduct(type="CHECKING", name="어벤져스 입출금통장", description="자유롭게 입출금하는 기본 계좌", interest_rate=0.10),
    AccountProduct(type="CHECKING", name="어벤져스 월급통장", description="급여가 들어오는 달은 이체·ATM 수수료 면제", interest_rate=0.20),
    # 예금
    AccountProduct(type="DEPOSIT", name="어벤져스 정기예금", description="목돈을 맡기고 만기에 이자를 받는 예금", interest_rate=3.00, min_amount=100000),
    AccountProduct(type="DEPOSIT", name="어벤져스 스타 정기예금", description="1개월~3년 중 원하는 기간으로 맡기는 기본 예금", interest_rate=2.85, min_amount=1000000),
    AccountProduct(type="DEPOSIT", name="어벤져스 모바일 특판예금", description="앱에서만 가입하는 1년 특판, 한도 소진 시 종료", interest_rate=3.10, min_amount=500000),
    # 적금
    AccountProduct(type="SAVINGS", name="어벤져스 정기적금", description="매월 일정액을 납입하는 적금", interest_rate=3.50),
    AccountProduct(type="SAVINGS", name="어벤져스 내맘대로 적금", description="납입일과 금액을 직접 정하는 6개월~3년 적금", interest_rate=3.80),
    AccountProduct(type="SAVINGS", name="어벤져스 청년 도약 적금", description="만 19~34세 대상, 월 최대 70만 원 (데모에서는 나이 확인 안 함)", interest_rate=4.50),
]
CARD_PRODUCTS = [
    # 신용카드
    CardProduct(type="CREDIT", name="어벤져스 일반 신용카드", description="한도 300만 원", credit_limit=3_000_000),
    CardProduct(type="CREDIT", name="어벤져스 프리미엄 신용카드", description="한도 1,000만 원", credit_limit=10_000_000),
    CardProduct(type="CREDIT", name="어벤져스 쇼핑 신용카드", description="온라인 쇼핑·배달앱 10% 할인, 한도 500만 원", credit_limit=5_000_000),
    CardProduct(type="CREDIT", name="어벤져스 트래블 신용카드", description="해외 결제 수수료 면제, 공항 라운지 연 2회, 한도 700만 원", credit_limit=7_000_000),
    # 체크카드
    CardProduct(type="DEBIT", name="어벤져스 체크카드", description="입출금 계좌에서 바로 출금"),
    CardProduct(type="DEBIT", name="어벤져스 노리 체크카드", description="대중교통·편의점·카페 5~10% 할인"),
    CardProduct(type="DEBIT", name="어벤져스 트래블 체크카드", description="해외 결제·해외 ATM 출금 수수료 면제"),
]


def main() -> None:
    # 시드는 단발 스크립트라 동기 엔진을 쓴다 (Windows에서 psycopg 비동기 이벤트 루프 문제를 피함).
    engine = create_engine(get_settings().database_url)
    with Session(engine) as db, db.begin():
        have_accounts = {p.name: p for p in db.scalars(select(AccountProduct))}
        updated = 0
        for p in ACCOUNT_PRODUCTS:
            row = have_accounts.get(p.name)
            if row and row.min_amount != p.min_amount:
                row.min_amount = p.min_amount
                updated += 1
        have_cards = set(db.scalars(select(CardProduct.name)))
        new_accounts = [p for p in ACCOUNT_PRODUCTS if p.name not in have_accounts]
        new_cards = [p for p in CARD_PRODUCTS if p.name not in have_cards]
        db.add_all([*new_accounts, *new_cards])
        print(f"계좌 상품 {len(new_accounts)}개, 카드 상품 {len(new_cards)}개를 새로 넣었습니다. (최소 가입 금액 갱신 {updated}개)")
    engine.dispose()


if __name__ == "__main__":
    main()
