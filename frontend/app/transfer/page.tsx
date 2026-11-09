"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AccountPasswordField, MoneyErrorText } from "@/components/account-password";
import { Button, Field, MoneyField, Shell } from "@/components/ui";
import { AccountSummary, History, api, won } from "@/lib/api";

type Result = { from_account_num: string; to_account_num: string; amount: number; balance_after: number };

export default function TransferPage() {
  return (
    <Shell>
      <Transfer />
    </Shell>
  );
}

type Recent = { account: string; name: string | null; count: number; last: string };

// 내 입출금 계좌들의 거래 내역에서 "이체 보냄"을 모아 많이 보낸 순으로 센다.
// shortcut: 계좌마다 최근 100건만 본다. 거래가 많아지면 서버에 "자주 보낸 계좌" API를 만든다.
async function loadRecent(checking: AccountSummary[]): Promise<Recent[]> {
  const mine = new Set(checking.map((a) => a.account_num));
  const lists = await Promise.all(
    checking.map((a) => api<History[]>(`/accounts/checking/${a.account_id}/histories?limit=100`)),
  );
  const byAccount = new Map<string, Recent>();
  for (const h of lists.flat()) {
    if (h.type !== "TRANSFER_OUT" || !h.counterpart_account || mine.has(h.counterpart_account)) continue;
    const r = byAccount.get(h.counterpart_account) ?? { account: h.counterpart_account, name: h.counterpart_name, count: 0, last: h.date };
    r.count += 1;
    if (h.date > r.last) r.last = h.date;
    byAccount.set(h.counterpart_account, r);
  }
  return [...byAccount.values()].sort((a, b) => b.count - a.count || b.last.localeCompare(a.last)).slice(0, 5);
}

function Transfer() {
  const [accounts, setAccounts] = useState<AccountSummary[] | null>(null);
  const [recent, setRecent] = useState<Recent[]>([]);
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    api<AccountSummary[]>("/accounts")
      .then((a) => {
        const checking = a.filter((x) => x.account_type === "checking");
        setAccounts(checking);
        // 홈의 "최근 이체한 분"에서 오면 ?from=출금 계좌 id&to=받는 계좌번호가 붙어 있다 (C-068)
        const q = new URLSearchParams(window.location.search);
        const fromId = Number(q.get("from"));
        setFrom(checking.some((x) => x.account_id === fromId) ? fromId : (checking[0]?.account_id ?? null));
        setTo(q.get("to")?.slice(0, 20) ?? "");
        return loadRecent(checking).then(setRecent);
      })
      .catch(setError);
  }, []);

  // 출금 계좌로 고른 계좌는 받는 쪽 후보에서 뺀다
  const myOthers = accounts?.filter((a) => a.account_id !== from) ?? [];

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      setResult(
        await api<Result>("/transfers", {
          from_checking_account_id: Number(f.get("from")),
          to_account_num: String(f.get("to")).trim(),
          amount: Number(f.get("amount")),
          account_password: f.get("account_password"),
        }),
      );
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }

  if (result) {
    return (
      <section className="mt-10 text-center">
        <span className="seal stamp size-20 text-lg">완료</span>
        <h1 className="mt-6 text-2xl font-semibold tabular-nums">{won(result.amount)}을 보냈습니다</h1>
        <p className="mt-2 text-slate tabular-nums">받는 계좌 {result.to_account_num}</p>
        <p className="text-slate tabular-nums">남은 잔액 {won(result.balance_after)}</p>
        <Link href="/accounts" className="mt-8 inline-block rounded-xl bg-coral px-6 py-3 font-medium text-paper">
          내 계좌 보기
        </Link>
      </section>
    );
  }

  if (accounts && accounts.length === 0) {
    return (
      <p className="mt-10 text-center text-slate">
        이체하려면 입출금 계좌가 필요합니다.{" "}
        <Link href="/open/checking" className="text-ink underline underline-offset-4">
          계좌 만들기
        </Link>
      </p>
    );
  }

  return (
    <section className="mt-4">
      <h1 className="text-2xl font-semibold">이체하기</h1>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <label className="block">
          <span className="mb-1 block text-sm text-slate">출금 계좌</span>
          <select
            name="from"
            required
            value={from ?? ""}
            onChange={(e) => setFrom(Number(e.target.value))}
            className="w-full rounded-xl border border-line bg-paper px-3 py-2.5 tabular-nums outline-none focus:border-coral"
          >
            {accounts?.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.nickname ?? a.account_num} ({won(a.balance)})
              </option>
            ))}
          </select>
        </label>
        <div>
          <Field
            label="받는 계좌번호"
            name="to"
            inputMode="numeric"
            required
            maxLength={20}
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
          <AccountPicker
            mine={myOthers.map((a) => ({ account: a.account_num, label: a.nickname ?? "입출금", note: won(a.balance) }))}
            frequent={recent.map((r) => ({ account: r.account, label: r.name ?? r.account, note: `${r.count}회` }))}
            onPick={setTo}
          />
        </div>
        <MoneyField label="금액 (원)" name="amount" min={1} required />
        <AccountPasswordField label="출금 계좌 비밀번호" />
        <MoneyErrorText error={error} accountHref={from ? `/accounts/checking/${from}` : undefined} />
        <Button busy={busy} disabled={!accounts}>
          보내기
        </Button>
      </form>
    </section>
  );
}

type Suggestion = { account: string; label: string; note: string };

// 입력칸 아래 접히는 버튼 하나. 펼치면 "내 계좌" 다음에 "자주 사용하는 계좌". 고르면 입력칸을 채우고 접힌다.
function AccountPicker({
  mine,
  frequent,
  onPick,
}: {
  mine: Suggestion[];
  frequent: Suggestion[];
  onPick: (account: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (mine.length === 0 && frequent.length === 0) return null;

  const section = (title: string, items: Suggestion[]) =>
    items.length > 0 && (
      <div>
        <p className="bg-porcelain px-4 py-2 text-xs font-medium text-slate">{title}</p>
        <ul className="divide-y divide-line">
          {items.map((s) => (
            <li key={s.account}>
              <button
                type="button"
                onClick={() => {
                  onPick(s.account);
                  setOpen(false);
                }}
                className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-coral-soft"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{s.label}</span>
                  {s.label !== s.account && <span className="block text-sm text-slate tabular-nums">{s.account}</span>}
                </span>
                <span className="shrink-0 text-sm text-slate tabular-nums">{s.note}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );

  return (
    <div className="mt-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="account-picker"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-sm font-medium text-coral"
      >
        자주 사용하는 계좌
        <svg viewBox="0 0 24 24" aria-hidden className={`size-4 fill-none stroke-current stroke-2 transition-transform ${open ? "rotate-180" : ""}`}>
          <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div id="account-picker" className="mt-2 overflow-hidden rounded-xl border border-line bg-paper">
          {section("내 계좌", mine)}
          {section("자주 사용하는 계좌", frequent)}
        </div>
      )}
    </div>
  );
}
