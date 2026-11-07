"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, ErrorText, Field, Shell } from "@/components/ui";
import { AccountSummary, api } from "@/lib/api";

// 상품 가입(계좌 개설·카드 발급) 화면 하나로 다섯 종류를 처리한다. /open/{kind}/{상품 id(선택)}
const KINDS = {
  checking: { type: "CHECKING", title: "입출금 계좌 만들기", list: "accounts", endpoint: "/accounts/checking", stamp: "개설", done: "계좌를 만들었습니다", card: false },
  deposit: { type: "DEPOSIT", title: "예금 가입하기", list: "accounts", endpoint: "/accounts/deposit", stamp: "가입", done: "예금에 가입했습니다", card: false },
  savings: { type: "SAVINGS", title: "적금 가입하기", list: "accounts", endpoint: "/accounts/savings", stamp: "가입", done: "적금에 가입했습니다", card: false },
  credit: { type: "CREDIT", title: "신용카드 발급하기", list: "cards", endpoint: "/cards/credit", stamp: "발급", done: "신용카드를 발급했습니다", card: true },
  debit: { type: "DEBIT", title: "체크카드 발급하기", list: "cards", endpoint: "/cards/debit", stamp: "발급", done: "체크카드를 발급했습니다", card: true },
} as const;
type Kind = keyof typeof KINDS;

type Product = { product_id: number; name: string; description: string; interest_rate?: string; credit_limit?: number | null };
type Opened = { account_num?: string; card_num?: string };

// 날짜 입력칸 값(YYYY-MM-DD). 오늘에서 days일 뒤.
const dayAfter = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("sv-SE");
};

export default function OpenPage() {
  return (
    <Shell>
      <Open />
    </Shell>
  );
}

function Open() {
  const params = useParams<{ kind: string; product?: string[] }>();
  const kind = params.kind as Kind;
  const conf = KINDS[kind];
  const picked = Number(params.product?.[0]);

  const [products, setProducts] = useState<Product[]>([]);
  const [checking, setChecking] = useState<AccountSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [opened, setOpened] = useState<Opened | null>(null);

  useEffect(() => {
    if (!conf) return;
    api<Product[]>(`/products/${conf.list}?type=${conf.type}`).then(setProducts).catch((e) => setError(e.message));
    // 카드는 결제·출금할 입출금 계좌를 골라야 한다
    api<AccountSummary[]>("/accounts")
      .then((a) => setChecking(a.filter((x) => x.account_type === "checking")))
      .catch((e) => setError(e.message));
  }, [conf]);

  if (!conf) return <p className="mt-10 text-slate">없는 상품 종류입니다.</p>;
  // 주소의 상품 id가 이 종류에 없으면 첫 상품을 고른다
  const hasPicked = products.some((p) => p.product_id === picked);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const num = (k: string) => Number(f.get(k));
    const nickname = f.get("nickname") || null;
    const body = {
      checking: { product_id: num("product_id"), nickname },
      deposit: { product_id: num("product_id"), maturity_date: f.get("maturity_date"), nickname },
      savings: {
        product_id: num("product_id"),
        monthly_payment: num("monthly_payment"),
        monthly_deposit_date: num("monthly_deposit_date"),
        maturity_date: f.get("maturity_date"),
        nickname,
      },
      credit: { product_id: num("product_id"), checking_account_id: num("checking_account_id"), payment_date: num("payment_date") },
      debit: { product_id: num("product_id"), checking_account_id: num("checking_account_id") },
    }[kind];
    setBusy(true);
    setError(null);
    try {
      setOpened(await api<Opened>(conf.endpoint, body));
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy(false);
  }

  if (opened) {
    return (
      <section className="mt-10 text-center">
        <span className="seal stamp size-20 text-lg">{conf.stamp}</span>
        <h1 className="mt-6 text-2xl font-semibold">{conf.done}</h1>
        <p className="mt-2 text-slate tabular-nums">{opened.account_num ?? opened.card_num}</p>
        <Link href="/accounts" className="mt-8 inline-block rounded-xl bg-coral px-6 py-3 font-medium text-paper">
          홈으로
        </Link>
      </section>
    );
  }

  if (conf.card && checking?.length === 0) {
    return (
      <p className="mt-10 text-center text-slate">
        카드를 만들려면 결제할 입출금 계좌가 먼저 필요합니다.{" "}
        <Link href="/open/checking" className="text-ink underline underline-offset-4">
          입출금 계좌 만들기
        </Link>
      </p>
    );
  }

  return (
    <section className="mt-4">
      <Link href="/products" className="text-sm text-slate hover:text-ink">
        ← 상품
      </Link>
      <h1 className="mt-2 text-2xl font-semibold">{conf.title}</h1>
      <form onSubmit={onSubmit} className="mt-6 space-y-5">
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm text-slate">상품</legend>
          {products.map((p, i) => (
            <label
              key={p.product_id}
              className="flex cursor-pointer gap-3 rounded-xl border border-line bg-paper p-4 has-checked:border-coral"
            >
              <input
                type="radio"
                name="product_id"
                value={p.product_id}
                defaultChecked={hasPicked ? p.product_id === picked : i === 0}
                required
                className="mt-1 accent-coral"
              />
              <span>
                <span className="block font-medium">{p.name}</span>
                <span className="block text-sm text-slate">{p.description}</span>
                {p.interest_rate && <span className="block text-sm font-medium text-coral">연 {Number(p.interest_rate)}%</span>}
              </span>
            </label>
          ))}
        </fieldset>

        {conf.card && (
          <label className="block">
            <span className="mb-1 block text-sm text-slate">{kind === "credit" ? "결제 계좌" : "출금 계좌"}</span>
            <select
              name="checking_account_id"
              required
              className="w-full rounded-xl border border-line bg-paper px-3 py-2.5 outline-none focus:border-coral"
            >
              {checking?.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.nickname ?? "입출금"} {a.account_num}
                </option>
              ))}
            </select>
          </label>
        )}
        {kind === "credit" && (
          <Field label="매월 결제일 (1~31일)" name="payment_date" type="number" min={1} max={31} defaultValue={14} required />
        )}
        {kind === "savings" && (
          <>
            <Field label="매월 납입액 (원)" name="monthly_payment" type="number" min={1} step={1} defaultValue={100000} required />
            <Field label="매월 납입일 (1~31일)" name="monthly_deposit_date" type="number" min={1} max={31} defaultValue={25} required />
          </>
        )}
        {(kind === "deposit" || kind === "savings") && (
          <Field label="만기일" name="maturity_date" type="date" min={dayAfter(1)} defaultValue={dayAfter(365)} required />
        )}
        {!conf.card && <Field label="계좌 별명 (선택)" name="nickname" maxLength={50} />}

        <ErrorText message={error} />
        <Button busy={busy} disabled={products.length === 0}>
          {kind === "checking" ? "계좌 만들기" : `${conf.stamp}하기`}
        </Button>
      </form>
    </section>
  );
}
