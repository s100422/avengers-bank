"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ErrorText, Shell } from "@/components/ui";
import { api, won } from "@/lib/api";

type Card = {
  card_type: "credit" | "debit";
  card_num: string;
  product_id: number;
  status: string;
  credit_limit?: number;
  outstanding_amount?: number;
  payment_date?: number;
  accumulated_amount?: number;
};
type Use = { place_of_use: string; used_amount: number; time: string };
type Bill = {
  bill_id: number;
  period_start: string;
  total_amount: number;
  due_date: string;
  status: "UNPAID" | "PAID";
  paid_at: string | null;
};

// "2026-11-14" → "11월 14일"
const dateLabel = (d: string) => `${Number(d.slice(5, 7))}월 ${Number(d.slice(8, 10))}일`;

function BillRow({ cardId, bill, onPaid }: { cardId: number; bill: Bill; onPaid: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const paid = bill.status === "PAID";

  async function pay() {
    setBusy(true);
    setError(null);
    try {
      await api(`/cards/credit/${cardId}/bills/${bill.bill_id}/payments`, {});
      onPaid();
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy(false);
  }

  return (
    <li className="px-4 py-3">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="font-medium">{Number(bill.period_start.slice(5, 7))}월 이용분</p>
          <p className="text-sm text-slate tabular-nums">
            {paid ? `납부 완료` : `${dateLabel(bill.due_date)} 결제 예정`}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className={`font-semibold tabular-nums ${paid ? "text-slate" : ""}`}>{won(bill.total_amount)}</span>
          {!paid && (
            <button
              type="button"
              onClick={pay}
              disabled={busy}
              className="rounded-full bg-coral px-3.5 py-1.5 text-sm font-medium whitespace-nowrap text-paper disabled:opacity-50"
            >
              {busy ? "처리 중…" : "지금 납부"}
            </button>
          )}
        </div>
      </div>
      <ErrorText message={error} />
    </li>
  );
}

const STATUS: Record<string, string> = { ACTIVE: "사용 중", SUSPENDED: "정지됨", CLOSED: "해지됨" };

const when = (iso: string) =>
  new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

export default function CardDetailPage() {
  return (
    <Shell>
      <CardDetail />
    </Shell>
  );
}

function CardDetail() {
  const { type, id } = useParams<{ type: string; id: string }>();
  const [card, setCard] = useState<Card | null>(null);
  const [name, setName] = useState("");
  const [uses, setUses] = useState<Use[] | null>(null);
  const [bills, setBills] = useState<Bill[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    Promise.all([api<Card>(`/cards/${type}/${id}`), api<Use[]>(`/cards/${type}/${id}/histories`)])
      .then(([c, u]) => {
        setCard(c);
        setUses(u);
        return Promise.all([
          api<{ name: string }>(`/products/cards/${c.product_id}`).then((p) => setName(p.name)),
          c.card_type === "credit" ? api<Bill[]>(`/cards/credit/${id}/bills`).then(setBills) : null,
        ]);
      })
      .catch((e) => setError(e.message));
  }, [type, id, reload]);

  const credit = card?.card_type === "credit";
  // 결제 예정 = 청구됐지만 아직 안 낸 청구서. 이번 달 이용 금액 = 미결제액 중 아직 청구 전인 부분
  const unpaid = bills.filter((b) => b.status === "UNPAID").sort((a, b) => a.due_date.localeCompare(b.due_date));
  const due = unpaid.reduce((sum, b) => sum + b.total_amount, 0);
  const usingNow = (card?.outstanding_amount ?? 0) - due;

  return (
    <>
      <Link href="/accounts" className="text-sm text-slate hover:text-ink">
        ← 홈
      </Link>
      <ErrorText message={error} />
      {card && (
        <section className="mt-4">
          <p className="text-slate">
            {name || (credit ? "신용카드" : "체크카드")} <span className="text-sm">({STATUS[card.status] ?? card.status})</span>
          </p>
          <p className="text-sm text-slate tabular-nums">{card.card_num}</p>
          {!credit && (
            <>
              <p className="mt-4 text-sm text-slate">누적 사용액</p>
              <p className="text-4xl font-semibold tabular-nums tracking-tight">{won(card.accumulated_amount ?? 0)}</p>
            </>
          )}
          {credit && (
            <>
              <p className="mt-4 text-sm text-slate">
                {unpaid.length > 0 ? `${dateLabel(unpaid[0].due_date)} 결제 예정 금액` : "결제 예정 금액"}
              </p>
              <p className="text-4xl font-semibold tabular-nums tracking-tight">{won(due)}</p>
              <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1 rounded-2xl bg-paper p-5 text-sm tabular-nums md:grid-cols-4">
                <dt className="text-slate">이번 달 이용 금액</dt>
                <dd className="text-right font-medium md:text-left">{won(usingNow)}</dd>
                <dt className="text-slate">남은 한도</dt>
                <dd className="text-right font-medium md:text-left">
                  {won((card.credit_limit ?? 0) - (card.outstanding_amount ?? 0))} / {won(card.credit_limit ?? 0)}
                </dd>
                <dt className="text-slate">결제일</dt>
                <dd className="text-right font-medium md:text-left">매월 {card.payment_date}일</dd>
              </dl>
            </>
          )}
        </section>
      )}

      {credit && bills.length > 0 && (
        <section className="mt-10">
          <h2 className="text-sm text-slate">청구서</h2>
          <ul className="mt-3 divide-y divide-line rounded-xl border border-line bg-paper">
            {bills.map((b) => (
              <BillRow key={b.bill_id} cardId={Number(id)} bill={b} onPaid={() => setReload((n) => n + 1)} />
            ))}
          </ul>
        </section>
      )}

      <section className="mt-10">
        <h2 className="text-sm text-slate">사용 내역</h2>
        {uses?.length === 0 && (
          <p className="mt-3 rounded-xl border border-dashed border-line px-4 py-8 text-center text-slate">아직 사용 내역이 없습니다.</p>
        )}
        {uses && uses.length > 0 && (
          <ul className="mt-3 divide-y divide-line rounded-xl border border-line bg-paper">
            {uses.map((u, i) => (
              <li key={i} className="flex items-baseline justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate font-medium">{u.place_of_use}</p>
                  <p className="text-sm text-slate tabular-nums">{when(u.time)}</p>
                </div>
                <p className="shrink-0 font-semibold tabular-nums">-{won(u.used_amount)}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
