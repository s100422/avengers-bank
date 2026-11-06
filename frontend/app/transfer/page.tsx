"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button, ErrorText, Field, Shell } from "@/components/ui";
import { AccountSummary, api, won } from "@/lib/api";

type Result = { from_account_num: string; to_account_num: string; amount: number; balance_after: number };

export default function TransferPage() {
  return (
    <Shell>
      <Transfer />
    </Shell>
  );
}

function Transfer() {
  const [accounts, setAccounts] = useState<AccountSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    api<AccountSummary[]>("/accounts")
      .then((a) => setAccounts(a.filter((x) => x.account_type === "checking")))
      .catch((e) => setError(e.message));
  }, []);

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
        }),
      );
    } catch (err) {
      setError((err as Error).message);
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
        <Link href="/accounts" className="mt-8 inline-block rounded-md bg-ink px-6 py-3 font-medium text-paper">
          내 계좌 보기
        </Link>
      </section>
    );
  }

  if (accounts && accounts.length === 0) {
    return (
      <p className="mt-10 text-center text-slate">
        이체하려면 입출금 계좌가 필요합니다.{" "}
        <Link href="/accounts/new" className="text-ink underline underline-offset-4">
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
            className="w-full rounded-md border border-line bg-paper px-3 py-2.5 tabular-nums outline-none focus:border-ink"
          >
            {accounts?.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.nickname ?? a.account_num} ({won(a.balance)})
              </option>
            ))}
          </select>
        </label>
        <Field label="받는 계좌번호" name="to" inputMode="numeric" required maxLength={20} />
        <Field label="금액 (원)" name="amount" type="number" min={1} step={1} inputMode="numeric" required />
        <ErrorText message={error} />
        <Button busy={busy} disabled={!accounts}>
          보내기
        </Button>
      </form>
    </section>
  );
}
