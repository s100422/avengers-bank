"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorText, Shell } from "@/components/ui";
import { AccountSummary, KIND, User, api, won } from "@/lib/api";

export default function AccountsPage() {
  return (
    <Shell>
      <Accounts />
    </Shell>
  );
}

function Accounts() {
  const [user, setUser] = useState<User | null>(null);
  const [accounts, setAccounts] = useState<AccountSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api<User>("/users/me"), api<AccountSummary[]>("/accounts")])
      .then(([u, a]) => {
        setUser(u);
        setAccounts(a);
      })
      .catch((e) => setError(e.message));
  }, []);

  const open = accounts?.filter((a) => a.status !== "CLOSED") ?? [];
  const total = open.reduce((sum, a) => sum + a.balance, 0);

  return (
    <>
      <section className="mt-4">
        <p className="text-slate">{user ? `${user.nick_name ?? user.name}님의 전체 잔액` : " "}</p>
        <p className="mt-1 text-4xl font-semibold tabular-nums tracking-tight">
          {accounts ? won(total) : " "}
        </p>
        <div className="mt-6 flex gap-2">
          <Link href="/transfer" className="flex-1 rounded-md bg-ink py-3 text-center font-medium text-paper">
            이체하기
          </Link>
          <Link href="/accounts/new" className="flex-1 rounded-md border border-ink py-3 text-center font-medium">
            계좌 만들기
          </Link>
        </div>
      </section>

      <ErrorText message={error} />

      <section className="mt-10">
        <h2 className="text-sm text-slate">내 계좌 {accounts && `${open.length}개`}</h2>
        {accounts && open.length === 0 && (
          <p className="mt-3 rounded-md border border-dashed border-line px-4 py-8 text-center text-slate">
            아직 계좌가 없습니다.{" "}
            <Link href="/accounts/new" className="text-ink underline underline-offset-4">
              첫 입출금 계좌를 만들어 보세요
            </Link>
          </p>
        )}
        {open.length > 0 && (
          <ul className="mt-3 divide-y divide-line rounded-md border border-line bg-paper">
            {open.map((a) => (
              <li key={`${a.account_type}-${a.account_id}`} className="flex items-baseline justify-between gap-4 px-4 py-4">
                <div className="min-w-0">
                  <p className="truncate font-medium">{a.nickname ?? `${KIND[a.account_type]} 계좌`}</p>
                  <p className="text-sm text-slate tabular-nums">
                    {KIND[a.account_type]} {a.account_num}
                  </p>
                </div>
                <p className="shrink-0 font-semibold tabular-nums">{won(a.balance)}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
