"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ACCOUNT_PASSWORD_RULE, AccountPasswordField, MoneyErrorText, accountPasswordProblem } from "@/components/account-password";
import { Button, Field, MoneyField, Shell } from "@/components/ui";
import { AccountSummary, ApiError, TermsSet, api, termsHref, won } from "@/lib/api";

// 상품 가입(계좌 개설·카드 발급) 화면 하나로 다섯 종류를 처리한다. /open/{kind}/{상품 id(선택)}
const KINDS = {
  checking: { type: "CHECKING", title: "입출금 계좌 만들기", list: "accounts", endpoint: "/accounts/checking", stamp: "개설", done: "계좌를 만들었습니다", card: false },
  deposit: { type: "DEPOSIT", title: "예금 가입하기", list: "accounts", endpoint: "/accounts/deposit", stamp: "가입", done: "예금에 가입했습니다", card: false },
  savings: { type: "SAVINGS", title: "적금 가입하기", list: "accounts", endpoint: "/accounts/savings", stamp: "가입", done: "적금에 가입했습니다", card: false },
  credit: { type: "CREDIT", title: "신용카드 발급하기", list: "cards", endpoint: "/cards/credit", stamp: "발급", done: "신용카드를 발급했습니다", card: true },
  debit: { type: "DEBIT", title: "체크카드 발급하기", list: "cards", endpoint: "/cards/debit", stamp: "발급", done: "체크카드를 발급했습니다", card: true },
} as const;
type Kind = keyof typeof KINDS;

type Product = { product_id: number; name: string; description: string; interest_rate?: string; credit_limit?: number | null; min_amount?: number | null };
type Opened = { account_num?: string; card_num?: string };
// 약관 전문을 보러 나갈 때 입력값을 sessionStorage에 맡겼다가, 돌아오면 한 번만 꺼내 채운다.
// 계좌 비밀번호는 fields에 넣지 않는다(비제어 입력) → 저장소에 남지 않고, 돌아오면 비밀번호만 다시 입력한다
type Draft = { productId: number | null; setHash?: string; agreed: Record<number, boolean>; fields: Record<string, string> };

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
  const [error, setError] = useState<unknown>(null); // Error 또는 ApiError (계좌 비밀번호 오류면 링크를 붙인다)
  const [busy, setBusy] = useState(false);
  const [opened, setOpened] = useState<Opened | null>(null);
  const [productId, setProductId] = useState<number | null>(null);
  // 약관: key(종류:상품:다시 부른 횟수)가 지금 고른 상품과 같을 때만 보여 준다 → 다른 상품 약관이 섞이지 않는다
  const [termsReload, setTermsReload] = useState(0);
  const [terms, setTerms] = useState<{ key: string; data?: TermsSet; error?: string; code?: string } | null>(null);
  const [agreed, setAgreed] = useState<Record<number, boolean>>({});
  // 입력칸 값은 상태로 들고 있다 → 화면이 다시 살아나도(뒤로 가기 등) 그대로다. 안 건드린 칸은 기본값
  const [fields, setFields] = useState<Record<string, string>>({});
  const bind = (name: string, fallback: string | number = "") => ({
    name,
    value: fields[name] ?? String(fallback),
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setFields((f) => ({ ...f, [name]: e.target.value })),
  });
  const needsChecking = conf?.card || kind === "deposit"; // 카드는 결제·출금 계좌, 예금은 가입 금액을 뺄 계좌
  const fromAcc = checking?.find((a) => String(a.account_id) === (fields.checking_account_id ?? String(checking[0]?.account_id)));
  const draftKey = `open-draft:${kind}`;
  const draftRef = useRef<Draft | null>(null); // 전문을 보러 나갈 때 맡겨 둔 값. 다시 새로 열린 화면이 한 번 꺼내 쓴다
  const agreedFor = useRef<string | null>(null); // 지금 동의 상태가 어느 상품·약관 묶음의 것인지

  useEffect(() => {
    let d: Draft | null = null;
    try {
      const raw = sessionStorage.getItem(draftKey);
      if (raw) d = JSON.parse(raw);
      sessionStorage.removeItem(draftKey);
    } catch {}
    if (!d) return;
    draftRef.current = d;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sessionStorage는 마운트 뒤에만 읽을 수 있다
    setFields(d.fields);
    setProductId(d.productId);
  }, [draftKey]);

  // 주소의 상품 id가 이 종류에 없으면 첫 상품을 고른다
  const has = (id: number | null) => products.some((p) => p.product_id === id);
  const selected = has(productId) ? productId : has(picked) ? picked : products[0]?.product_id;
  const termsKey = `${kind}:${selected}:${termsReload}`;
  const selectedMin = products.find((p) => p.product_id === selected)?.min_amount ?? null; // 예금만 값이 온다
  const minAmount = selectedMin ?? 1;

  useEffect(() => {
    if (!conf || !selected) return;
    let alive = true; // 늦게 온 이전 상품 응답은 버린다
    const key = `${kind}:${selected}:${termsReload}`;
    api<TermsSet>(`/terms/products/${kind}/${selected}`)
      .then((d) => {
        if (!alive) return;
        if (d.product_kind !== kind || d.product_id !== selected) throw new Error("약관을 불러오지 못했습니다.");
        setTerms({ key, data: d });
        // 상품이나 약관 묶음이 바뀌면 동의는 처음부터. 같은 묶음이면 그대로 둔다 (전문을 보고 돌아온 경우 포함)
        const sig = `${selected}:${d.set_hash}`;
        const back = draftRef.current;
        if (agreedFor.current !== sig) {
          setAgreed(back && back.productId === selected && back.setHash === d.set_hash ? back.agreed : {});
          agreedFor.current = sig;
        }
        draftRef.current = null;
      })
      .catch((e) => alive && setTerms({ key, error: e.message, code: e instanceof ApiError ? e.code : undefined }));
    return () => {
      alive = false;
    };
  }, [conf, kind, selected, termsReload]);

  const termsNow = terms?.key === termsKey ? terms : null; // null이면 불러오는 중
  const items = termsNow?.data?.items.toSorted((a, b) => a.order - b.order) ?? [];
  const required = items.filter((t) => t.required);
  const allRequired = !!termsNow?.data && required.every((t) => agreed[t.terms_version_id]);

  useEffect(() => {
    if (!conf) return;
    api<Product[]>(`/products/${conf.list}?type=${conf.type}`).then(setProducts).catch(setError);
    // 카드는 결제·출금할 입출금 계좌를 골라야 한다
    api<AccountSummary[]>("/accounts")
      .then((a) => setChecking(a.filter((x) => x.account_type === "checking")))
      .catch(setError);
  }, [conf]);

  if (!conf) return <p className="mt-10 text-slate">없는 상품 종류입니다.</p>;

  function saveDraft() {
    const d: Draft = { productId: selected ?? null, setHash: termsNow?.data?.set_hash, agreed, fields };
    try {
      sessionStorage.setItem(draftKey, JSON.stringify(d));
    } catch {}
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const num = (k: string) => Number(f.get(k));
    const nickname = f.get("nickname") || null;
    const account_password = String(f.get("account_password") ?? "");
    if (!conf.card) {
      const problem = accountPasswordProblem(account_password, String(f.get("account_password_confirm") ?? ""));
      if (problem) return setError(new Error(problem));
    }
    const body = {
      checking: { product_id: num("product_id"), nickname, account_password },
      deposit: {
        product_id: num("product_id"),
        initial_amount: num("initial_amount"),
        from_checking_account_id: num("checking_account_id"),
        from_account_password: f.get("from_account_password"),
        maturity_date: f.get("maturity_date"),
        nickname,
        account_password,
      },
      savings: {
        product_id: num("product_id"),
        monthly_payment: num("monthly_payment"),
        monthly_deposit_date: num("monthly_deposit_date"),
        maturity_date: f.get("maturity_date"),
        nickname,
        account_password,
      },
      credit: { product_id: num("product_id"), checking_account_id: num("checking_account_id"), payment_date: num("payment_date") },
      debit: { product_id: num("product_id"), checking_account_id: num("checking_account_id") },
    }[kind];
    const set = termsNow?.data;
    if (!set) return;
    const termsBody = {
      revision_id: set.revision_id,
      set_hash: set.set_hash,
      agreements: set.items.map((t) => ({ terms_version_id: t.terms_version_id, agreed: !!agreed[t.terms_version_id] })),
    };
    setBusy(true);
    setError(null);
    try {
      setOpened(await api<Opened>(conf.endpoint, { ...body, terms: termsBody }));
    } catch (err) {
      if (err instanceof ApiError && err.code === "TERMS_OUTDATED") {
        setError(new Error("약관이 변경되었습니다. 최신 약관을 확인하고 다시 동의해 주세요."));
        setTermsReload((n) => n + 1);
      } else setError(err);
    }
    setBusy(false);
  }

  if (opened) {
    return (
      <section className="mt-10 text-center">
        <span className="seal stamp size-20 text-lg">{conf.stamp}</span>
        <h1 className="mt-6 text-2xl font-semibold">{conf.done}</h1>
        <p className="mt-2 text-slate tabular-nums">{opened.account_num ?? opened.card_num}</p>
        {kind === "deposit" && <p className="mt-1 text-sm text-slate tabular-nums">가입 금액 {won(Number(fields.initial_amount))}</p>}
        <Link href="/accounts" className="mt-8 inline-block rounded-xl bg-coral px-6 py-3 font-medium text-paper">
          홈으로
        </Link>
      </section>
    );
  }

  if (needsChecking && checking?.length === 0) {
    return (
      <p className="mt-10 text-center text-slate">
        {kind === "deposit" ? "가입하려면 출금할 입출금 계좌가 먼저 필요합니다." : "카드를 만들려면 결제할 입출금 계좌가 먼저 필요합니다."}{" "}
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
          {products.map((p) => (
            <label
              key={p.product_id}
              className="flex cursor-pointer gap-3 rounded-xl border border-line bg-paper p-4 has-checked:border-coral"
            >
              <input
                type="radio"
                name="product_id"
                value={p.product_id}
                checked={p.product_id === selected}
                onChange={() => setProductId(p.product_id)}
                required
                className="mt-1 accent-coral"
              />
              <span>
                <span className="block font-medium">{p.name}</span>
                <span className="block text-sm text-slate">{p.description}</span>
                {p.interest_rate && <span className="block text-sm font-medium text-coral">연 {Number(p.interest_rate)}%</span>}
                {kind === "deposit" && p.min_amount != null && (
                  <span className="block text-sm text-slate tabular-nums">최소 가입 {won(p.min_amount)}</span>
                )}
              </span>
            </label>
          ))}
        </fieldset>

        {kind === "deposit" && (
          <div>
            <MoneyField label="가입 금액 (원)" min={minAmount} {...bind("initial_amount")} required />
            {selectedMin != null && <span className="mt-1 block text-sm text-slate tabular-nums">최소 {won(selectedMin)}</span>}
            {selectedMin != null && fields.initial_amount && Number(fields.initial_amount) < selectedMin && (
              <span className="mt-1 block text-sm text-seal">이 상품의 최소 가입 금액은 {won(selectedMin)}입니다.</span>
            )}
          </div>
        )}
        {needsChecking && (
          <label className="block">
            <span className="mb-1 block text-sm text-slate">{kind === "credit" ? "결제 계좌" : "출금 계좌"}</span>
            <select
              {...bind("checking_account_id", checking?.[0]?.account_id ?? "")}
              onChange={(e) => setFields((f) => ({ ...f, checking_account_id: e.target.value }))}
              required
              className="w-full rounded-xl border border-line bg-paper px-3 py-2.5 outline-none focus:border-coral"
            >
              {checking?.map((a) => (
                <option key={a.account_id} value={a.account_id}>
                  {a.nickname ?? "입출금"} {a.account_num}{kind === "deposit" && ` · ${won(a.balance)}`}
                </option>
              ))}
            </select>
            {kind === "deposit" && fromAcc && Number(fields.initial_amount) > fromAcc.balance && (
              <span className="mt-1 block text-sm text-seal">출금 계좌 잔액({won(fromAcc.balance)})보다 큽니다.</span>
            )}
          </label>
        )}
        {kind === "credit" && (
          <Field label="매월 결제일 (1~31일)" type="number" min={1} max={31} {...bind("payment_date", 14)} required />
        )}
        {kind === "savings" && (
          <>
            <MoneyField label="매월 납입액 (원)" min={1} {...bind("monthly_payment", 100000)} required />
            <Field label="매월 납입일 (1~31일)" type="number" min={1} max={31} {...bind("monthly_deposit_date", 25)} required />
          </>
        )}
        {(kind === "deposit" || kind === "savings") && (
          <Field label="만기일" type="date" min={dayAfter(1)} {...bind("maturity_date", dayAfter(365))} required />
        )}
        {!conf.card && <Field label="계좌 별명 (선택)" maxLength={50} {...bind("nickname")} />}
        {!conf.card && (
          <div className="space-y-3">
            <AccountPasswordField label="새 계좌 비밀번호" />
            <AccountPasswordField label="새 계좌 비밀번호 확인" name="account_password_confirm" />
            <p className="text-sm text-slate">{ACCOUNT_PASSWORD_RULE}. 이체·납입·해지할 때 입력합니다.</p>
          </div>
        )}
        {kind === "deposit" && <AccountPasswordField label="출금 계좌 비밀번호" name="from_account_password" />}

        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm text-slate">약관 동의</legend>
          {!termsNow && selected && <p className="text-sm text-slate">약관을 불러오는 중…</p>}
          {termsNow?.error && (
            <div role="alert" className="flex items-center gap-2 rounded-xl border border-seal/40 bg-paper px-4 py-2 text-sm text-seal">
              <span className="flex-1">{termsNow.error}</span>
              {/* 약관이 없는 상품은 다시 불러와도 같다 → 버튼을 보이지 않는다 */}
              {termsNow.code !== "TERMS_NOT_CONFIGURED" && (
                <button type="button" onClick={() => setTermsReload((n) => n + 1)} className="min-h-11 shrink-0 rounded-xl border border-seal px-3 font-medium">
                  다시 시도
                </button>
              )}
            </div>
          )}
          {items.length > 0 && (
            <div className="rounded-xl border border-line bg-paper">
              <label className="flex cursor-pointer items-center gap-3 border-b border-line px-4 py-3 font-medium">
                <input
                  type="checkbox"
                  checked={allRequired}
                  onChange={() =>
                    setAgreed((a) => ({ ...a, ...Object.fromEntries(required.map((t) => [t.terms_version_id, !allRequired])) }))
                  }
                  className="size-4 accent-coral"
                />
                필수 약관 모두 동의
              </label>
              <ul className="divide-y divide-line">
                {items.map((t) => {
                  // 전문 화면의 "돌아가기"가 지금 고른 상품의 가입 화면으로 오게 한다
                  const doc = termsHref(t.terms_version_id);
                  const href = doc && `${doc}?from=${encodeURIComponent(`/open/${kind}/${selected}`)}`;
                  return (
                    <li key={t.terms_version_id} className="flex items-center gap-3 px-4 py-3 text-sm">
                      <label className="flex flex-1 cursor-pointer items-center gap-3">
                        <input
                          type="checkbox"
                          checked={!!agreed[t.terms_version_id]}
                          onChange={(e) => setAgreed((a) => ({ ...a, [t.terms_version_id]: e.target.checked }))}
                          className="size-4 accent-coral"
                        />
                        <span>
                          <span className={t.required ? "text-coral" : "text-slate"}>[{t.required ? "필수" : "선택"}]</span> {t.title}
                          <span className="block text-xs text-slate tabular-nums">
                            {t.version} · 시행일 {t.effective_from}
                          </span>
                        </span>
                      </label>
                      {href && (
                        <Link href={href} onClick={saveDraft} className="shrink-0 text-slate underline underline-offset-4 hover:text-ink">
                          전문 보기
                        </Link>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </fieldset>

        {/* 예금 가입에서 계좌 비밀번호를 확인하는 곳은 출금 입출금 계좌뿐이다 */}
        <MoneyErrorText error={error} accountHref={fromAcc ? `/accounts/checking/${fromAcc.account_id}` : undefined} />
        <Button busy={busy} disabled={products.length === 0 || !allRequired}>
          {kind === "checking" ? "계좌 만들기" : `${conf.stamp}하기`}
        </Button>
      </form>
    </section>
  );
}
