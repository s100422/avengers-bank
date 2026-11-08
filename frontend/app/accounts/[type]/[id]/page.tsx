"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { DEFAULT_FILTER, Filter, HistoryFilterBar, toQuery } from "@/components/history-filter";
import { ConsentRecord } from "@/components/terms/ConsentRecord";
import { Button, ErrorText, MoneyField, Shell } from "@/components/ui";
import { AccountSummary, HISTORY_TYPE, History, KIND, TermsKind, api, won } from "@/lib/api";

type Account = {
  account_num: string;
  balance: number;
  nickname: string | null;
  account_type: keyof typeof KIND;
  status?: string; // 예금·적금만
  monthly_payment?: number; // 적금만
};

// 적금 납입: 내 입출금 계좌에서 이 계좌로 돈을 옮긴다 (예금은 가입 때 한 번만 넣는다)
function PayIn({
  kind,
  accountId,
  suggested,
  onDone,
}: {
  kind: "savings";
  accountId: number;
  suggested?: number;
  onDone: () => void;
}) {
  const [checking, setChecking] = useState<AccountSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const label = "납입";

  const loadChecking = () =>
    api<AccountSummary[]>("/accounts").then((a) => setChecking(a.filter((x) => x.account_type === "checking")));
  useEffect(() => {
    loadChecking();
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const amount = Number(f.get("amount"));
    setBusy(true);
    try {
      await api(`/transfers/${kind}`, {
        from_checking_account_id: Number(f.get("from")),
        [`${kind}_account_id`]: accountId,
        amount,
      });
      setMsg({ ok: true, text: `${won(amount)}을 ${label}했습니다.` });
      onDone();
      loadChecking(); // 출금 계좌 잔액도 새로 보여 준다
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
    setBusy(false);
  }

  if (checking.length === 0) return null;
  return (
    <form onSubmit={onSubmit} className="mt-6 space-y-3 rounded-2xl bg-paper p-5">
      <h2 className="font-semibold">적금 납입하기</h2>
      <label className="block">
        <span className="mb-1 block text-sm text-slate">출금 계좌</span>
        <select name="from" className="w-full rounded-xl border border-line bg-paper px-3 py-2.5 outline-none focus:border-coral">
          {checking.map((a) => (
            <option key={a.account_id} value={a.account_id}>
              {a.nickname ?? a.account_num} ({won(a.balance)})
            </option>
          ))}
        </select>
      </label>
      <MoneyField label="금액 (원)" name="amount" min={1} defaultValue={suggested} required />
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-slate" : "text-seal"}`}>{msg.text}</p>}
      <Button busy={busy}>{label}하기</Button>
    </form>
  );
}

export default function AccountDetailPage() {
  return (
    <Shell>
      <AccountDetail />
    </Shell>
  );
}

const when = (iso: string) =>
  new Date(iso).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

function AccountDetail() {
  const { type, id } = useParams<{ type: string; id: string }>();
  const [account, setAccount] = useState<Account | null>(null);
  const [histories, setHistories] = useState<History[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [filter, setFilter] = useState<Filter>(DEFAULT_FILTER);

  useEffect(() => {
    api<Account>(`/accounts/${type}/${id}`).then(setAccount).catch((e) => setError(e.message));
  }, [type, id, reload]);

  useEffect(() => {
    api<History[]>(`/accounts/${type}/${id}/histories?${toQuery(filter)}`)
      .then(setHistories)
      .catch((e) => setError(e.message));
  }, [type, id, reload, filter]);

  return (
    <>
      <Link href="/accounts" className="text-sm text-slate hover:text-ink">
        ← 내 계좌
      </Link>
      <ErrorText message={error} />
      {account && (
        <section className="mt-4">
          <p className="text-slate">{account.nickname ?? `${KIND[account.account_type]} 계좌`}</p>
          <p className="text-sm text-slate tabular-nums">
            {KIND[account.account_type]} {account.account_num}
          </p>
          <p className="mt-2 text-4xl font-semibold tabular-nums tracking-tight">{won(account.balance)}</p>
          {account.account_type === "checking" && (
            <Link href="/transfer" className="mt-6 block rounded-xl bg-coral py-3 text-center font-medium text-paper">
              이체하기
            </Link>
          )}
          {account.account_type === "savings" && account.status !== "CLOSED" && (
            <PayIn
              kind="savings"
              accountId={Number(id)}
              suggested={account.monthly_payment}
              onDone={() => setReload((n) => n + 1)}
            />
          )}
        </section>
      )}

      <section className="mt-10">
        <h2 className="text-sm text-slate">거래 내역</h2>
        <HistoryFilterBar value={filter} onApply={setFilter} />
        {histories?.length === 0 && (
          <p className="mt-3 rounded-xl border border-dashed border-line px-4 py-8 text-center text-slate">
            조건에 맞는 거래가 없습니다.
          </p>
        )}
        {histories && histories.length > 0 && (
          <ul className="mt-3 divide-y divide-line rounded-xl border border-line bg-paper">
            {histories.map((h, i) => {
              const [label, out] = HISTORY_TYPE[h.type] ?? [h.type, false];
              return (
                <li key={i} className="flex items-baseline justify-between gap-4 px-4 py-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{h.counterpart_name ?? h.counterpart_account ?? label}</p>
                    <p className="text-sm text-slate tabular-nums">
                      {when(h.date)}
                      {(h.counterpart_name ?? h.counterpart_account) && ` ${label}`}
                    </p>
                  </div>
                  <div className="shrink-0 text-right tabular-nums">
                    <p className={`font-semibold ${out ? "" : "text-seal"}`}>
                      {out ? "-" : "+"}
                      {won(h.amount)}
                    </p>
                    <p className="text-sm text-slate">{won(h.balance_after)}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      {(["checking", "deposit", "savings"] as string[]).includes(type) && <ConsentRecord kind={type as TermsKind} subjectId={id} />}
    </>
  );
}
