import calendar
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from avengers_bank.core.exceptions import (
    ApiException,
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from avengers_bank.core.timezone import kst_start_utc, today_kst
from avengers_bank.domains.accounts.kinds import KINDS as ACCOUNT_KINDS
from avengers_bank.domains.accounts.models import CheckingAccountHistory
from avengers_bank.domains.accounts.repository import account_repository
from avengers_bank.domains.accounts.service import account_service
from avengers_bank.domains.cards.kinds import CARD_BILL_PAYMENT, CARD_PAYMENT, KINDS, CardKind
from avengers_bank.domains.cards.models import CreditCardBill
from avengers_bank.domains.cards.repository import card_repository
from avengers_bank.domains.cards.schemas import (
    RESPONSES,
    BillCreate,
    BillDetailResponse,
    BillResponse,
    CardHistoryResponse,
    CardPaymentCreate,
    CardPaymentResponse,
    CardSummaryResponse,
    CreditCardCreate,
    DebitCardCreate,
)
from avengers_bank.domains.products.service import product_service
from avengers_bank.domains.terms import service as terms_service
from avengers_bank.domains.terms.schemas import TermsConsentIn
from avengers_bank.domains.users.schemas import UserResponse

MAX_NUMBER_ATTEMPTS = 5


def _as_dict(kind: CardKind, card) -> dict:
    """모델 컬럼을 응답용 dict로. 종류마다 다른 PK 이름은 card_id로 통일한다."""
    data = {c.name: getattr(card, c.name) for c in card.__table__.columns}
    data["card_id"] = data.pop(kind.id_column)
    return data


def to_response(kind: CardKind, card):
    return RESPONSES[kind.name].model_validate(_as_dict(kind, card))


def _due_date(period_end: date, payment_date: int) -> date:
    """납부 예정일 = 이용 기간 다음 달의 결제일. 그 달에 없는 날이면 말일 (예: 2월 31일 → 2월 28/29일)."""
    year, month = (period_end.year + 1, 1) if period_end.month == 12 else (period_end.year, period_end.month + 1)
    return date(year, month, min(payment_date, calendar.monthrange(year, month)[1]))


class CardService:
    # 잠금 규칙은 docs/ERD.md 규칙 9: 돈을 바꾸기 전에 잠그고, 잠근 뒤에 검사한다.
    # 잠금 순서: 입출금 계좌 → 카드 → 청구서.

    # ── 발급 ──────────────────────────────────────────────────────────

    async def issue_credit(self, db: AsyncSession, data: CreditCardCreate, user: UserResponse):
        return await self._issue(
            db, KINDS["credit"], user, data.product_id, data.checking_account_id, data.terms,
            payment_date=data.payment_date,
        )

    async def issue_debit(self, db: AsyncSession, data: DebitCardCreate, user: UserResponse):
        return await self._issue(db, KINDS["debit"], user, data.product_id, data.checking_account_id, data.terms)

    async def _issue(
        self, db: AsyncSession, kind: CardKind, user: UserResponse,
        product_id: int, checking_account_id: int, terms: TermsConsentIn, **fields,
    ):
        # 같은 테이블 안에서 번호가 겹치면 unique 제약(IntegrityError)이 막는다. 새 번호로 다시 시도한다.
        for _ in range(MAX_NUMBER_ATTEMPTS):
            try:
                async with db.begin():
                    product = await product_service.require_card_product(db, product_id, kind.product_type)
                    # 약관 동의 검증·기록은 발급과 같은 트랜잭션 (C-075)
                    current, agreed = await terms_service.check_consent(db, kind.name, product_id, terms)
                    await account_service.get_owned(db, ACCOUNT_KINDS["checking"], checking_account_id, user)
                    if kind.name == "credit":
                        fields["credit_limit"] = product.credit_limit  # 상품 한도를 카드에 복사 (C-013)
                    card = kind.model(
                        user_id=user.user_id, product_id=product_id,
                        checking_account_id=checking_account_id,
                        card_num=self._new_card_num(kind), **fields,
                    )
                    await card_repository.save(db, card)
                    await terms_service.record_consent(
                        db, user, kind.name, getattr(card, kind.id_column), current, agreed
                    )
                return to_response(kind, card)
            except IntegrityError as e:
                if "card_num" not in str(e.orig):
                    raise
        raise ApiException(500, "CARD_NUMBER_GENERATION_FAILED", "카드번호를 발급하지 못했습니다. 다시 시도해 주세요.")

    def _new_card_num(self, kind: CardKind) -> str:
        groups = [f"{secrets.randbelow(10_000):04d}" for _ in range(3)]
        return "-".join([kind.prefix, *groups])  # 4000-1234-5678-9012 (19자)

    # ── 조회 ──────────────────────────────────────────────────────────

    async def get_my_cards(self, db: AsyncSession, user: UserResponse) -> list[CardSummaryResponse]:
        cards = []
        for kind in KINDS.values():
            for card in await card_repository.find_by_user_id(db, kind, user.user_id):
                cards.append(CardSummaryResponse(card_type=kind.name, **_as_dict(kind, card)))
        return cards  # 신용 → 체크 순, 각각 발급 순

    async def get_card(self, db: AsyncSession, type: str, card_id: int, user: UserResponse):
        kind = KINDS[type]
        return to_response(kind, await self.get_owned(db, kind, card_id, user))

    async def get_histories(
        self, db: AsyncSession, type: str, card_id: int, user: UserResponse, limit: int, offset: int
    ) -> list[CardHistoryResponse]:
        kind = KINDS[type]
        await self.get_owned(db, kind, card_id, user)
        histories = await card_repository.find_histories(db, kind, card_id, limit, offset)
        return [CardHistoryResponse.model_validate(h) for h in histories]

    async def get_owned(self, db: AsyncSession, kind: CardKind, card_id: int, user: UserResponse):
        card = await card_repository.find_by_id(db, kind, card_id)
        # 남의 카드도 404로 알려서 ID가 존재하는지 드러나지 않게 한다 (C-031)
        if card is None or card.user_id != user.user_id:
            raise NotFoundException(code="CARD_NOT_FOUND", message="카드를 찾을 수 없습니다.")
        return card

    # ── 정지·해지 (C-044) ─────────────────────────────────────────────

    # 동작 → (바뀌기 전에 있어야 하는 상태, 바뀐 뒤 상태)
    _TRANSITIONS = {
        "suspend": ({"ACTIVE"}, "SUSPENDED"),
        "resume": ({"SUSPENDED"}, "ACTIVE"),
        "close": ({"ACTIVE", "SUSPENDED"}, "CLOSED"),
    }

    async def change_status(self, db: AsyncSession, type: str, card_id: int, action: str, user: UserResponse):
        kind = KINDS[type]
        allowed, new_status = self._TRANSITIONS[action]
        async with db.begin():
            await self.get_owned(db, kind, card_id, user)
            card = await card_repository.lock_card(db, kind, card_id)  # 상태는 잠근 뒤에 확인한다 (결제와 동시에 와도)
            if card.status not in allowed:
                raise BadRequestException(
                    code="INVALID_CARD_STATUS", message=f"현재 상태({card.status})에서는 할 수 없습니다."
                )
            # 미결제액에는 청구 전·청구서 미납이 모두 들어 있다. 갚기 전에 해지하면 빚이 남는다
            if action == "close" and kind.name == "credit" and card.outstanding_amount > 0:
                raise BadRequestException(
                    code="CARD_HAS_OUTSTANDING", message="미결제액이 남아 있어 해지할 수 없습니다."
                )
            card.status = new_status
        return to_response(kind, card)

    # ── 결제(사용) ────────────────────────────────────────────────────

    async def pay(
        self, db: AsyncSession, type: str, card_id: int, data: CardPaymentCreate, user: UserResponse
    ) -> CardPaymentResponse:
        kind = KINDS[type]
        amount = data.used_amount
        async with db.begin():
            card = await self.get_owned(db, kind, card_id, user)  # 소유자는 바뀌지 않는 정보라 잠그기 전에 확인
            if kind.name == "debit":
                # 체크카드: 연결 계좌에서 바로 출금한다. 입출금 계좌 → 카드 순서로 잠근다.
                (account,) = await account_repository.lock_checking_accounts(db, [card.checking_account_id])
                card = await card_repository.lock_card(db, kind, card_id)
                self._require_active(card)
                if account.balance < amount:
                    raise BadRequestException(code="INSUFFICIENT_BALANCE", message="잔액이 부족합니다.")
                account.balance -= amount
                await account_repository.save_history(
                    db,
                    CheckingAccountHistory(
                        checking_account_id=account.checking_account_id, amount=amount,
                        balance_after=account.balance, type=CARD_PAYMENT,
                        counterpart_name=data.place_of_use,
                    ),
                )
            else:
                # 신용카드: 한도 안에서 미결제액만 늘린다 (돈은 청구서를 납부할 때 나간다)
                card = await card_repository.lock_card(db, kind, card_id)
                self._require_active(card)
                if card.outstanding_amount + amount > card.credit_limit:
                    raise BadRequestException(code="CREDIT_LIMIT_EXCEEDED", message="신용 한도를 초과했습니다.")
                card.outstanding_amount += amount

            if kind.name == "debit":
                card.accumulated_amount += amount
            history = await card_repository.save_history(
                db,
                kind.history_model(
                    **{kind.id_column: card_id}, place_of_use=data.place_of_use, used_amount=amount
                ),
            )
            await db.refresh(history)  # 서버가 정한 사용 시각을 읽어 온다

        return CardPaymentResponse(
            place_of_use=history.place_of_use, used_amount=history.used_amount,
            time=history.time, **self._amount_fields(kind, card),
        )

    @staticmethod
    def _require_active(card) -> None:
        if card.status != "ACTIVE":
            raise BadRequestException(code="CARD_NOT_ACTIVE", message="사용할 수 없는 카드입니다(정지·해지).")

    @staticmethod
    def _amount_fields(kind: CardKind, card) -> dict:
        if kind.name == "credit":
            return {"outstanding_amount": card.outstanding_amount}
        return {"accumulated_amount": card.accumulated_amount}

    # ── 신용카드 청구서 (본인이 직접 호출, C-010) ────────────────────

    async def create_bill(
        self, db: AsyncSession, card_id: int, data: BillCreate, user: UserResponse
    ) -> BillResponse:
        kind = KINDS["credit"]
        year, month = (int(x) for x in data.year_month.split("-"))
        period_start = date(year, month, 1)
        period_end = date(year, month, calendar.monthrange(year, month)[1])
        async with db.begin():
            card = await self.get_owned(db, kind, card_id, user)
            if period_end >= today_kst():  # 이용 기간이 끝난 달만 청구한다
                raise BadRequestException(
                    code="BILLING_PERIOD_NOT_ENDED", message="아직 이용 기간이 끝나지 않았습니다."
                )
            # 같은 카드의 청구서 생성·납부·결제를 한 줄로 세운다. 동시에 두 번 눌러도 한 번만 만들어진다.
            card = await card_repository.lock_card(db, kind, card_id)
            if await card_repository.find_bill_by_period(db, card_id, period_start) is not None:
                raise ConflictException(code="BILL_ALREADY_EXISTS", message="이미 청구서가 있는 달입니다.")

            start = kst_start_utc(period_start)
            end = kst_start_utc(period_end + timedelta(days=1))
            total = await card_repository.sum_unbilled(db, card_id, start, end)
            if total == 0:
                raise BadRequestException(code="NO_UNBILLED_USAGE", message="청구할 사용내역이 없습니다.")

            bill = await card_repository.save_bill(
                db,
                CreditCardBill(
                    credit_card_id=card_id, period_start=period_start, period_end=period_end,
                    total_amount=total, due_date=_due_date(period_end, card.payment_date),
                ),
            )
            await card_repository.assign_bill(db, card_id, bill.bill_id, start, end)
            await db.refresh(bill)
        return BillResponse.model_validate(bill)

    async def pay_bill(
        self, db: AsyncSession, card_id: int, bill_id: int, user: UserResponse
    ) -> BillResponse:
        kind = KINDS["credit"]
        async with db.begin():
            card = await self.get_owned(db, kind, card_id, user)
            await self._get_bill_of_card(db, card_id, bill_id)  # 이 카드의 청구서인지 (없으면 404)

            # 규칙 9: 입출금 계좌 → 카드 → 청구서 순서로 잠근 뒤에 검사한다
            (account,) = await account_repository.lock_checking_accounts(db, [card.checking_account_id])
            card = await card_repository.lock_card(db, kind, card_id)
            bill = await card_repository.lock_bill(db, bill_id)

            if bill.status == "PAID":  # 납부 버튼을 두 번 눌러도 한 번만 출금된다
                raise ConflictException(code="BILL_ALREADY_PAID", message="이미 납부한 청구서입니다.")
            if account.balance < bill.total_amount:
                raise BadRequestException(code="INSUFFICIENT_BALANCE", message="잔액이 부족합니다.")

            account.balance -= bill.total_amount
            product = await product_service.get_card_product(db, card.product_id)
            await account_repository.save_history(
                db,
                CheckingAccountHistory(
                    checking_account_id=account.checking_account_id, amount=bill.total_amount,
                    balance_after=account.balance, type=CARD_BILL_PAYMENT,
                    # 거래 내역에는 카드 이름을 보여 주고, 어떤 카드인지는 카드번호로 남긴다 (C-064)
                    counterpart_account=card.card_num, counterpart_name=product.name,
                ),
            )
            bill.status = "PAID"
            bill.paid_at = datetime.now(timezone.utc)
            card.outstanding_amount -= bill.total_amount  # 미결제액에서 갚은 만큼 뺀다 (C-012)
        return BillResponse.model_validate(bill)

    async def get_bills(self, db: AsyncSession, card_id: int, user: UserResponse) -> list[BillResponse]:
        await self.get_owned(db, KINDS["credit"], card_id, user)
        return [BillResponse.model_validate(b) for b in await card_repository.find_bills(db, card_id)]

    async def get_bill(
        self, db: AsyncSession, card_id: int, bill_id: int, user: UserResponse
    ) -> BillDetailResponse:
        await self.get_owned(db, KINDS["credit"], card_id, user)
        bill = await self._get_bill_of_card(db, card_id, bill_id)
        items = await card_repository.find_bill_histories(db, bill_id)
        return BillDetailResponse(
            **BillResponse.model_validate(bill).model_dump(),
            items=[CardHistoryResponse.model_validate(h) for h in items],
        )

    async def _get_bill_of_card(self, db: AsyncSession, card_id: int, bill_id: int) -> CreditCardBill:
        bill = await card_repository.find_bill_by_id(db, bill_id)
        if bill is None or bill.credit_card_id != card_id:
            raise NotFoundException(code="BILL_NOT_FOUND", message="청구서를 찾을 수 없습니다.")
        return bill


card_service = CardService()
