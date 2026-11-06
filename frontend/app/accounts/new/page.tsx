"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Button, ErrorText, Field, Shell } from "@/components/ui";
import { Product, api } from "@/lib/api";

type Opened = { account_num: string; nickname: string | null };

export default function NewAccountPage() {
  return (
    <Shell>
      <NewAccount />
    </Shell>
  );
}

// shortcut: 입출금 계좌만 만든다. 예금·적금은 만기일 등 입력이 더 필요해서 다음 단계로 미뤘다.
function NewAccount() {
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [opened, setOpened] = useState<Opened | null>(null);

  useEffect(() => {
    api<Product[]>("/products/accounts?type=CHECKING").then(setProducts).catch((e) => setError(e.message));
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      setOpened(
        await api<Opened>("/accounts/checking", {
          product_id: Number(f.get("product_id")),
          nickname: f.get("nickname") || null,
        }),
      );
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy(false);
  }

  if (opened) {
    return (
      <section className="mt-10 text-center">
        <span className="seal stamp size-20 text-lg">개설</span>
        <h1 className="mt-6 text-2xl font-semibold">계좌를 만들었습니다</h1>
        <p className="mt-2 text-slate tabular-nums">{opened.account_num}</p>
        <Link href="/accounts" className="mt-8 inline-block rounded-md bg-ink px-6 py-3 font-medium text-paper">
          내 계좌 보기
        </Link>
      </section>
    );
  }

  return (
    <section className="mt-4">
      <h1 className="text-2xl font-semibold">입출금 계좌 만들기</h1>
      <form onSubmit={onSubmit} className="mt-6 space-y-5">
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm text-slate">상품</legend>
          {products.map((p, i) => (
            <label
              key={p.product_id}
              className="flex cursor-pointer gap-3 rounded-md border border-line bg-paper p-4 has-checked:border-ink"
            >
              <input type="radio" name="product_id" value={p.product_id} defaultChecked={i === 0} className="mt-1 accent-ink" />
              <span>
                <span className="block font-medium">{p.name}</span>
                <span className="block text-sm text-slate">{p.description}</span>
                <span className="block text-sm text-slate">연 {Number(p.interest_rate)}%</span>
              </span>
            </label>
          ))}
        </fieldset>
        <Field label="계좌 별명 (선택)" name="nickname" maxLength={50} placeholder="예: 생활비" />
        <ErrorText message={error} />
        <Button busy={busy} disabled={products.length === 0}>
          계좌 만들기
        </Button>
      </form>
    </section>
  );
}
