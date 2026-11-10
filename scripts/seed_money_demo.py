"""돈 관리 탭 시연용 거래내역을 이미 있는 로컬 사용자에게 채운다. 사람이 직접 실행한다 (pytest 아님).

실행: uv run python scripts/seed_money_demo.py <login_id> [--reset]

- 사용자에게 열린 입출금 계좌, 사용 중인 신용카드·체크카드가 있어야 한다.
- 지난 3개월 + 이번 달 오늘까지(KST)의 카드 사용내역, 체크카드 결제의 입출금 미러 행, 월급·월세·본인 이체,
  신용카드 청구서(지난달 것은 미납, 그 전은 납부)를 실제 서비스(cards/service.py)가 쓰는 모양 그대로 넣는다.
- 고정 난수 씨앗이라 같은 날 실행하면 같은 데이터가 나온다.

이 스크립트가 넣은 행 구별 (--reset은 이것만 지운다):
- 입출금 내역: request_id가 'seed-money-'로 시작 (실제 서비스는 UUID나 NULL만 쓴다)
- 카드 사용내역: time의 마이크로초가 MARK_US이고 가맹점이 이 파일의 목록에 있음
- 청구서: created_at의 마이크로초가 MARK_US이고 연결된 사용내역이 모두 위 표식을 가짐

잔액: 입출금 계좌 잔액(balance)은 바꾸지 않는다. 넣는 행의 balance_after는 "지금 잔액 - 그 뒤 넣은 거래의 순증감"으로
거꾸로 계산해 마지막 행이 지금 잔액과 맞게 한다. 중간에 음수가 되면 마지막 '내 계좌로 이체'(저축) 금액을 늘려 맞춘다.
그래서 --reset으로 지워도 잔액을 되돌릴 일이 없다.
신용카드 미결제액: 실제 서비스처럼 (미납 청구서 + 청구 전 사용액)만큼 늘린다. 체크카드 누적액도 사용액만큼 늘린다.
--reset은 그 몫을 빼고 지운다.
"""

import argparse
import calendar
import random
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from avengers_bank.core.timezone import KST, today_kst
from avengers_bank.domains.accounts.models import AccountNotification, CheckingAccount, CheckingAccountHistory
from avengers_bank.domains.cards.models import CreditCard, CreditCardBill, CreditCardHistory, DebitCard, DebitCardHistory
from avengers_bank.domains.cards.service import _due_date
from avengers_bank.domains.products.models import CardProduct
from avengers_bank.domains.users.models import User

SEED_PREFIX = "seed-money-"
MARK_US = 424242
RNG_SEED = 20261111
INCOME = {"TRANSFER_IN", "INTERBANK_IN"}

# (가맹점, 결제 수단, 한 달 건수, 최소 금액, 최대 금액, 단위)
MERCHANTS = [
    ("스타벅스 강남역점", "credit", 8, 4_500, 7_500, 100),
    ("투썸플레이스 역삼점", "credit", 3, 5_000, 8_500, 100),
    ("메가커피 삼성점", "debit", 6, 2_000, 4_500, 100),
    ("맥도날드 역삼점", "credit", 3, 6_500, 12_000, 100),
    ("김밥천국 선릉점", "debit", 4, 5_000, 9_000, 500),
    ("본죽 삼성점", "credit", 2, 9_000, 13_000, 500),
    ("교촌치킨 역삼점", "credit", 1, 20_000, 31_000, 1_000),
    ("배달의민족", "credit", 5, 15_000, 36_000, 100),
    ("요기요", "credit", 2, 14_000, 30_000, 100),
    ("GS25 삼성점", "debit", 6, 1_500, 12_000, 100),
    ("CU 역삼점", "debit", 4, 1_500, 9_000, 100),
    ("이마트 성수점", "credit", 2, 40_000, 120_000, 10),
    ("올리브영 강남본점", "credit", 2, 15_000, 50_000, 100),
    ("다이소 강남점", "debit", 1, 3_000, 15_000, 1_000),
    ("쿠팡", "credit", 5, 9_900, 80_000, 10),
    ("11번가", "credit", 1, 15_000, 45_000, 10),
    ("카카오T 택시", "credit", 3, 6_800, 25_000, 100),
    ("티머니 교통", "debit", 12, 1_250, 1_550, 150),
    ("온누리약국", "debit", 1, 4_000, 15_000, 500),
    ("연세튼튼내과의원", "credit", 1, 5_000, 15_000, 100),
    ("CGV 용산", "credit", 1, 15_000, 30_000, 1_000),
    ("교보문고 광화문점", "credit", 1, 12_000, 35_000, 100),
    ("네이버페이", "credit", 2, 10_000, 60_000, 10),
    ("주식회사 다온", "credit", 1, 30_000, 80_000, 1_000),
    ("KCP*결제", "credit", 1, 9_900, 40_000, 100),
]
# 이번 달만 늘려서 "평소보다 많음"이 보이게 하는 외식·배달
BOOSTED = {"맥도날드 역삼점", "김밥천국 선릉점", "본죽 삼성점", "교촌치킨 역삼점", "배달의민족", "요기요"}
BOOST = 2.5
FIXED_CARD = [  # (가맹점, 결제 수단, 날짜, 시, 금액) — 매달 같은 날
    ("유튜브프리미엄", "credit", 3, 4, 14_900),
    ("SKT 통신요금", "debit", 15, 6, None),  # 금액은 64,000~66,500
    ("넷플릭스", "credit", 18, 4, 17_000),
]
ONE_OFF = ("하이마트 가전", "credit", 12, 15, 890_000)  # 두 달 전에 한 번
SALARY = ("(주)스파이디컴퍼니", "301-12-345678", 2_500_000)
RENT = ("김집주인", "110-234-567890", 550_000)
FRIENDS = [(0, "이친구", 9, 30_000), (2, "박동료", 20, 45_000)]  # (몇 번째 달, 받는 사람, 날짜, 금액)
SELF_ACCOUNT = "088-110-555-123456"  # 다른 은행의 내 계좌 (이름이 본인이라 본인 이동으로 빠져야 한다)
SAVE_BASE = 750_000
NAMES = {m[0] for m in MERCHANTS} | {f[0] for f in FIXED_CARD} | {ONE_OFF[0]}


class SeedError(Exception):
    pass


@dataclass
class Ev:
    time: datetime
    source: str  # credit / debit / checking
    name: str
    amount: int
    type: str | None = None  # checking일 때
    account: str | None = None  # checking의 상대 계좌


def months_covered(today: date) -> list[tuple[int, int]]:
    """지난 3개월 + 이번 달, 오래된 순."""
    out, y, m = [], today.year, today.month
    for _ in range(4):
        out.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def _at(d: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute, second, MARK_US), tzinfo=KST)


def build_plan(today: date, now: datetime, owner_name: str) -> list[Ev]:
    """넣을 거래 목록 (청구서 납부 제외). DB를 모르는 순수 함수."""
    rng = random.Random(RNG_SEED)
    events: list[Ev] = []
    for i, (y, m) in enumerate(months_covered(today)):
        current = i == 3
        last = calendar.monthrange(y, m)[1]
        days = today.day if current else last
        for name, src, count, lo, hi, step in MERCHANTS:
            boost = BOOST if current and name in BOOSTED else 1
            for _ in range(round(count * days / last * boost)):
                d = date(y, m, rng.randint(1, days))
                t = _at(d, rng.randint(8, 22), rng.randint(0, 59), rng.randint(0, 59))
                events.append(Ev(t, src, name, rng.randrange(lo, hi + 1, step)))
        for name, src, day, hour, amount in FIXED_CARD:
            amount = amount or rng.randrange(64_000, 66_501, 10)
            events.append(Ev(_at(date(y, m, day), hour, rng.randint(0, 59)), src, name, amount))
        if i == 1:
            name, src, day, hour, amount = ONE_OFF
            events.append(Ev(_at(date(y, m, day), hour, 21), src, name, amount))
        payday = date(y, m, 25)
        events += [
            Ev(_at(payday, 9), "checking", SALARY[0], SALARY[2], "TRANSFER_IN", SALARY[1]),
            Ev(_at(payday, 9, 5), "checking", RENT[0], RENT[2], "TRANSFER_OUT", RENT[1]),
            Ev(_at(payday, 9, 10), "checking", owner_name, SAVE_BASE, "INTERBANK_OUT", SELF_ACCOUNT),
        ]
        for month_index, who, day, amount in FRIENDS:
            if month_index == i:
                events.append(Ev(_at(date(y, m, day), 19, 30), "checking", who, amount, "TRANSFER_OUT", None))
    # 오늘 날짜 이체는 넣지 않는다: 1일 이체 한도에 같이 세어져 시연 중 이체 한도가 줄어든다
    out_today = lambda e: e.type in ("TRANSFER_OUT", "INTERBANK_OUT") and e.time.astimezone(KST).date() == today  # noqa: E731
    return sorted((e for e in events if e.time < now and not out_today(e)), key=lambda e: e.time)


def _seeded_card_rows(rows) -> list:
    return [h for h in rows if h.time.microsecond == MARK_US and h.place_of_use in NAMES]


def find_seeded(session: Session, user_id: int) -> dict:
    credit_ids = list(session.scalars(select(CreditCard.credit_card_id).where(CreditCard.user_id == user_id)))
    debit_ids = list(session.scalars(select(DebitCard.debit_card_id).where(DebitCard.user_id == user_id)))
    account_ids = select(CheckingAccount.checking_account_id).where(CheckingAccount.user_id == user_id)
    checking = list(session.scalars(select(CheckingAccountHistory).where(
        CheckingAccountHistory.checking_account_id.in_(account_ids),
        CheckingAccountHistory.request_id.like(f"{SEED_PREFIX}%"),
    )))
    credit = _seeded_card_rows(session.scalars(
        select(CreditCardHistory).where(CreditCardHistory.credit_card_id.in_(credit_ids))))
    debit = _seeded_card_rows(session.scalars(
        select(DebitCardHistory).where(DebitCardHistory.debit_card_id.in_(debit_ids))))
    seeded_credit_ids = {h.credit_card_history_id for h in credit}
    bills = []
    for bill in session.scalars(select(CreditCardBill).where(
        CreditCardBill.credit_card_id.in_(credit_ids)
    )):
        if bill.created_at.microsecond != MARK_US:
            continue
        linked = set(session.scalars(select(CreditCardHistory.credit_card_history_id).where(
            CreditCardHistory.bill_id == bill.bill_id)))
        if linked and linked <= seeded_credit_ids:
            bills.append(bill)
    return {"checking": checking, "credit": credit, "debit": debit, "bills": bills}


def remove_seeded(session: Session, seeded: dict) -> None:
    """넣었던 행만 지우고, 카드에 더했던 미결제액·누적액을 뺀다. 입출금 잔액은 처음부터 바꾸지 않았다."""
    bill_ids = {b.bill_id for b in seeded["bills"]}
    foreign = [h for h in seeded["credit"] if h.bill_id is not None and h.bill_id not in bill_ids]
    if foreign:
        raise SeedError("시드 사용내역이 실제로 만든 청구서에 들어가 있어 지울 수 없다 (청구서 금액이 어긋난다). 손으로 정리해야 한다.")
    owed: dict[int, int] = {}
    for h in seeded["credit"]:
        if h.bill_id is None:  # 청구 전 사용액
            owed[h.credit_card_id] = owed.get(h.credit_card_id, 0) + h.used_amount
    for b in seeded["bills"]:
        if b.status == "UNPAID":  # 사용자가 앱에서 납부했다면 실제 서비스가 이미 미결제액을 줄였다
            owed[b.credit_card_id] = owed.get(b.credit_card_id, 0) + b.total_amount
    for card_id, amount in owed.items():
        card = session.get(CreditCard, card_id, with_for_update=True)
        if card.outstanding_amount < amount:
            raise SeedError(f"신용카드 {card_id}의 미결제액({card.outstanding_amount:,})이 시드 몫({amount:,})보다 작다. 손으로 정리해야 한다.")
        card.outstanding_amount -= amount
    used: dict[int, int] = {}
    for h in seeded["debit"]:
        used[h.debit_card_id] = used.get(h.debit_card_id, 0) + h.used_amount
    for card_id, amount in used.items():
        card = session.get(DebitCard, card_id, with_for_update=True)
        card.accumulated_amount = max(0, card.accumulated_amount - amount)

    checking_ids = [h.checking_account_history_id for h in seeded["checking"]]
    session.execute(delete(AccountNotification).where(AccountNotification.checking_account_history_id.in_(checking_ids)))
    session.execute(delete(CheckingAccountHistory).where(CheckingAccountHistory.checking_account_history_id.in_(checking_ids)))
    session.execute(delete(CreditCardHistory).where(
        CreditCardHistory.credit_card_history_id.in_([h.credit_card_history_id for h in seeded["credit"]])))
    session.execute(delete(DebitCardHistory).where(
        DebitCardHistory.debit_card_history_id.in_([h.debit_card_history_id for h in seeded["debit"]])))
    session.execute(delete(CreditCardBill).where(CreditCardBill.bill_id.in_(bill_ids)))
    session.flush()


def fill_balances(rows: list[CheckingAccountHistory], balance: int) -> None:
    """한 계좌의 넣을 행(오래된 순)에 balance_after를 채운다. 마지막 행이 지금 잔액(balance)과 맞는다.

    행의 거래 후 잔액 = balance - (그 뒤 행들의 순증감). 그 값이 어디서든 음수면 마지막 본인 이체(저축)를 늘린다:
    그보다 뒤에는 수입이 없으므로 그 행을 포함하는 모든 구간이 그만큼 줄어든다.
    """
    def nets():
        return [r.amount if r.type in INCOME else -r.amount for r in rows]

    suffix, worst = 0, 0
    for net in reversed(nets()):
        suffix += net
        worst = max(worst, suffix)
    if worst > balance:
        saves = [i for i, r in enumerate(rows) if r.type == "INTERBANK_OUT"]
        incomes = [i for i, r in enumerate(rows) if r.type in INCOME]
        if not saves or saves[-1] < incomes[-1]:
            raise SeedError("잔액을 맞출 본인 이체가 마지막 수입 뒤에 없다 (월급날 아침에 실행했다면 조금 뒤에 다시).")
        extra = -(-(worst - balance) // 10_000) * 10_000
        rows[saves[-1]].amount += extra
    after = balance
    for r, net in zip(reversed(rows), reversed(nets())):
        r.balance_after = after
        after -= net
    assert after >= 0, "시작 잔액이 음수"


def _request_id() -> str:
    return SEED_PREFIX + uuid.uuid4().hex[:25]


def seed(session: Session, login_id: str, reset: bool = False, now: datetime | None = None) -> dict:
    """한 트랜잭션 안에서 호출한다 (호출한 쪽이 commit). 요약 dict를 돌려준다."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(KST).date()
    user = session.scalar(select(User).where(User.login_id == login_id))
    if user is None:
        raise SeedError(f"사용자가 없다: {login_id}")

    open_accounts = select(CheckingAccount.checking_account_id).where(
        CheckingAccount.user_id == user.user_id, CheckingAccount.closed_at.is_(None))
    credit = session.scalar(select(CreditCard).where(
        CreditCard.user_id == user.user_id, CreditCard.status == "ACTIVE",
        CreditCard.checking_account_id.in_(open_accounts)).order_by(CreditCard.credit_card_id).with_for_update())
    debit = session.scalar(select(DebitCard).where(
        DebitCard.user_id == user.user_id, DebitCard.status == "ACTIVE",
        DebitCard.checking_account_id.in_(open_accounts)).order_by(DebitCard.debit_card_id).with_for_update())
    missing = [label for label, ok in (
        ("열린 입출금 계좌", session.scalar(open_accounts.limit(1)) is not None),
        ("사용 중인 신용카드(열린 결제 계좌 연결)", credit is not None),
        ("사용 중인 체크카드(열린 출금 계좌 연결)", debit is not None),
    ) if not ok]
    if missing:
        raise SeedError(f"{login_id}에게 없는 것: {', '.join(missing)}. 앱에서 먼저 만들어 주세요.")

    seeded = find_seeded(session, user.user_id)
    removed = {k: len(v) for k, v in seeded.items()}
    if any(removed.values()):
        if not reset:
            raise SeedError(f"이미 시드 데이터가 있다 ({removed}). 다시 넣으려면 --reset")
        remove_seeded(session, seeded)

    months = months_covered(today)
    periods = [(date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])) for y, m in months[:-1]]
    taken = session.scalars(select(CreditCardBill.period_start).where(
        CreditCardBill.credit_card_id == credit.credit_card_id,
        CreditCardBill.period_start.in_([p[0] for p in periods]))).all()
    if taken:
        raise SeedError(f"이 신용카드에 이미 실제 청구서가 있는 달: {', '.join(d.strftime('%Y-%m') for d in taken)}")

    plan = build_plan(today, now, user.name)
    product_name = session.get(CardProduct, credit.product_id).name
    main_id, bill_account_id = debit.checking_account_id, credit.checking_account_id
    checking_rows: dict[int, list[CheckingAccountHistory]] = {main_id: [], bill_account_id: []}
    credit_rows, debit_rows, bills = [], [], []
    notes = []

    # 청구서: 지난 달들. 마지막(지난달)은 미납, 그 전은 납부일에 납부
    by_month = {}
    for e in plan:
        if e.source == "credit":
            by_month.setdefault((e.time.year, e.time.month), []).append(e)
    for idx, (start, end) in enumerate(periods):
        items = by_month.get((start.year, start.month), [])
        total = sum(e.amount for e in items)
        due = _due_date(end, credit.payment_date)
        unpaid = idx == len(periods) - 1
        if unpaid and due <= today:
            due = today + timedelta(days=7)
            notes.append(f"결제일({credit.payment_date}일)이 이미 지나서 미납 청구서 납부 예정일을 {due}로 둠")
        if not unpaid and _at(due, 9) >= now:
            unpaid = True  # 아직 납부일 전이면 실제로도 미납이다
        paid_at = None if unpaid else _at(due, 9)
        bill = CreditCardBill(
            credit_card_id=credit.credit_card_id, period_start=start, period_end=end, total_amount=total,
            due_date=due, status="UNPAID" if unpaid else "PAID", paid_at=paid_at, created_at=_at(end + timedelta(days=1), 9),
        )
        bills.append((bill, items))
        if paid_at:
            checking_rows[bill_account_id].append(CheckingAccountHistory(
                checking_account_id=bill_account_id, date=paid_at, amount=total, type="CARD_BILL_PAYMENT",
                counterpart_account=credit.card_num, counterpart_name=product_name, request_id=_request_id(),
            ))
    session.add_all([b for b, _ in bills])
    session.flush()
    billed = {}
    for bill, items in bills:
        for e in items:
            billed[id(e)] = bill.bill_id

    for e in plan:
        if e.source == "credit":
            credit_rows.append(CreditCardHistory(
                credit_card_id=credit.credit_card_id, place_of_use=e.name, used_amount=e.amount, time=e.time,
                bill_id=billed.get(id(e))))
        elif e.source == "debit":
            debit_rows.append(DebitCardHistory(
                debit_card_id=debit.debit_card_id, place_of_use=e.name, used_amount=e.amount, time=e.time))
            # 실제 체크카드 결제는 같은 트랜잭션에서 입출금 CARD_PAYMENT 행을 쓴다
            checking_rows[main_id].append(CheckingAccountHistory(
                checking_account_id=main_id, date=e.time, amount=e.amount, type="CARD_PAYMENT",
                counterpart_name=e.name, request_id=_request_id()))
        else:
            checking_rows[main_id].append(CheckingAccountHistory(
                checking_account_id=main_id, date=e.time, amount=e.amount, type=e.type,
                counterpart_account=e.account, counterpart_name=e.name, request_id=_request_id()))

    all_rows = checking_rows  # 결제 계좌가 같으면 위 dict가 키 하나라 같은 목록에 모인다
    for account_id, rows in all_rows.items():
        rows.sort(key=lambda r: r.date)
        account = session.get(CheckingAccount, account_id, with_for_update=True)
        fill_balances(rows, account.balance)

    unbilled = sum(h.used_amount for h in credit_rows if h.bill_id is None)
    unpaid_total = sum(b.total_amount for b, _ in bills if b.status == "UNPAID")
    if credit.outstanding_amount + unbilled + unpaid_total > credit.credit_limit:
        raise SeedError(f"신용 한도 초과: 지금 미결제액 {credit.outstanding_amount:,} + 시드 {unbilled + unpaid_total:,}"
                        f" > 한도 {credit.credit_limit:,}")
    credit.outstanding_amount += unbilled + unpaid_total
    debit.accumulated_amount += sum(h.used_amount for h in debit_rows)
    inserted_checking = [r for rows in all_rows.values() for r in rows]
    session.add_all(credit_rows + debit_rows + inserted_checking)
    session.flush()

    # 자체 점검: 청구서 금액 = 연결된 사용내역 합, 마지막 행 잔액 = 지금 잔액
    for bill, items in bills:
        assert bill.total_amount == sum(h.used_amount for h in credit_rows if h.bill_id == bill.bill_id) > 0
    for account_id, rows in all_rows.items():
        if rows:
            assert rows[-1].balance_after == session.get(CheckingAccount, account_id).balance
    assert 0 <= credit.outstanding_amount <= credit.credit_limit

    return {
        "removed": removed if reset else None,
        "months": [f"{y}-{m:02d}" for y, m in months],
        "credit_card_histories": len(credit_rows),
        "debit_card_histories": len(debit_rows),
        "checking_account_histories": len(inserted_checking),
        "credit_card_bills": [f"{b.period_start:%Y-%m} {b.total_amount:,}원 {b.status} (납부 예정 {b.due_date})" for b, _ in bills],
        "outstanding_amount": credit.outstanding_amount,
        "notes": notes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="돈 관리 탭 시연 데이터 채우기 (기본은 로컬 PostgreSQL 전용)")
    parser.add_argument("login_id")
    parser.add_argument("--reset", action="store_true", help="이 스크립트가 넣은 데이터만 지우고 다시 넣는다")
    parser.add_argument(
        "--target-host", help="로컬이 아닌 DB(운영 시연 계정)에 쓸 때만. DATABASE_URL의 호스트를 정확히 적어야 통과한다"
    )
    args = parser.parse_args()

    import _common  # DB 호스트 확인 (아니면 여기서 끝난다)

    _common.connect(allowed_host=args.target_host)
    try:
        with Session(_common._engine) as session, session.begin():
            summary = seed(session, args.login_id, args.reset)
    except SeedError as e:
        sys.exit(str(e))
    print(f"{args.login_id}: 돈 관리 시연 데이터를 넣었다 (기준일 {today_kst()}, KST)")
    if summary["removed"]:
        print(f"  지운 이전 시드: {summary['removed']}")
    print(f"  기간: {summary['months'][0]} ~ {summary['months'][-1]}")
    for table in ("credit_card_histories", "debit_card_histories", "checking_account_histories"):
        print(f"  {table}: {summary[table]}행")
    print("  credit_card_bills:")
    for line in summary["credit_card_bills"]:
        print(f"    {line}")
    print(f"  신용카드 미결제액: {summary['outstanding_amount']:,}원")
    for note in summary["notes"]:
        print(f"  참고: {note}")


if __name__ == "__main__":
    main()
