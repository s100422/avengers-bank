"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { DEFAULT_FILTER, Filter, HistoryFilterBar, toQuery } from "@/components/history-filter";
import { ConsentRecord } from "@/components/terms/ConsentRecord";
import { ACCOUNT_PASSWORD_RULE, AccountPasswordField, MoneyErrorText, accountPasswordProblem } from "@/components/account-password";
import { Button, ErrorText, MoneyField, Shell } from "@/components/ui";
import { PhoneVerify } from "@/components/verify";
import { AccountSummary, HISTORY_TYPE, History, InterestPreview, KIND, TermsKind, User, api, won } from "@/lib/api";

type Account = {
  account_num: string;
  balance: number;
  nickname: string | null;
  account_type: keyof typeof KIND;
  status?: string; // 예금·적금만
  password_set?: boolean; // 계좌 비밀번호를 정했는가
  password_locked?: boolean; // 5회 틀려 잠겼는가
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
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [from, setFrom] = useState<string>("");
  const label = "납입";

  const loadChecking = () =>
    api<AccountSummary[]>("/accounts").then((a) => setChecking(a.filter((x) => x.account_type === "checking")));
  useEffect(() => {
    loadChecking();
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const form = e.currentTarget;
    const amount = Number(f.get("amount"));
    setBusy(true);
    setDone(null);
    setError(null);
    try {
      await api(`/transfers/${kind}`, {
        from_checking_account_id: Number(f.get("from")),
        [`${kind}_account_id`]: accountId,
        amount,
        account_password: f.get("account_password"),
      });
      (form.elements.namedItem("account_password") as HTMLInputElement).value = ""; // 다음 납입 때 다시 입력
      setDone(`${won(amount)}을 ${label}했습니다.`);
      onDone();
      loadChecking(); // 출금 계좌 잔액도 새로 보여 준다
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }

  if (checking.length === 0) return null;
  return (
    <form onSubmit={onSubmit} className="mt-6 space-y-3 rounded-2xl bg-paper p-5">
      <h2 className="font-semibold">적금 납입하기</h2>
      <label className="block">
        <span className="mb-1 block text-sm text-slate">출금 계좌</span>
        <select name="from" value={from || checking[0].account_id} onChange={(e) => setFrom(e.target.value)} className="w-full rounded-xl border border-line bg-paper px-3 py-2.5 outline-none focus:border-coral">
          {checking.map((a) => (
            <option key={a.account_id} value={a.account_id}>
              {a.nickname ?? a.account_num} ({won(a.balance)})
            </option>
          ))}
        </select>
      </label>
      <MoneyField label="금액 (원)" name="amount" min={1} defaultValue={suggested} required />
      <AccountPasswordField label="출금 계좌 비밀번호" resetHref={`/accounts/checking/${from || checking[0].account_id}`} />
      {done && <p role="status" className="text-sm text-slate">{done}</p>}
      <MoneyErrorText error={error} accountHref={`/accounts/checking/${from || checking[0].account_id}`} />
      <Button busy={busy}>{label}하기</Button>
    </form>
  );
}

type Closed = { principal: number; interest: number; total_amount: number; early_close: boolean; to_account_num: string };

// 이자 미리 보기: 만기까지 두면 / 오늘 해지하면. 적금 만기 값은 매월 납입을 계속한다고 가정한 예상이다
function InterestPreviewCard({ p }: { p: InterestPreview }) {
  const savings = p.account_type === "savings";
  const rows = (items: [string, string, boolean?][]) => (
    <dl className="mt-2 space-y-1 text-sm">
      {items.map(([k, v, strong]) => (
        <div key={k} className="flex justify-between gap-3">
          <dt className="text-slate">{k}</dt>
          <dd className={`text-right ${strong ? "font-semibold" : ""}`}>{v}</dd>
        </div>
      ))}
    </dl>
  );
  return (
    <div className="mt-6 rounded-2xl bg-paper p-5 tabular-nums">
      <h2 className="font-semibold">이자 미리 보기</h2>
      <p className="mt-0.5 text-xs text-slate">연 {p.interest_rate}%</p>

      <p className="mt-4 text-sm font-medium">만기({p.maturity_date})까지 두면</p>
      {rows([
        [savings && p.assumed_payments > 0 ? `원금 (앞으로 ${p.assumed_payments}회 납입 포함)` : "원금", won(p.maturity_principal)],
        ["이자", won(p.maturity_interest)],
        ["받을 금액", won(p.maturity_total), true],
      ])}
      {savings && p.monthly_payment != null && p.assumed_payments > 0 && (
        <p className="mt-1 text-xs text-slate">매월 {won(p.monthly_payment)}을 계속 납입한다고 가정한 예상이에요.</p>
      )}

      <p className="mt-4 text-sm font-medium">오늘 해지하면</p>
      {rows([
        ["원금", won(p.close_today_principal)],
        [`이자 (연 ${p.close_today_rate}%)`, won(p.close_today_interest)],
        ["받을 금액", won(p.close_today_total), true],
      ])}
      <p className="mt-1 text-xs text-slate">
        {p.close_today_early ? "만기 전에 해지하면 금리의 절반만 적용돼요." : "만기가 지나 전체 금리가 적용돼요."}
      </p>
    </div>
  );
}

// 예금·적금 해지: 원금+이자를 고른 입출금 계좌로 받는다. 해지하는 계좌의 비밀번호가 필요하다.
// 자주 쓰는 기능이 아니라서 화면 맨 아래에 작은 링크로 두고, 누르면 펼친다
function CloseAccount({
  kind,
  accountId,
  preview,
  onReset,
  onFail,
  onDone,
}: {
  kind: "deposit" | "savings";
  accountId: number;
  preview: InterestPreview | null;
  onReset: () => void;
  onFail: () => void;
  onDone: (closed: Closed) => void;
}) {
  const [checking, setChecking] = useState<AccountSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api<AccountSummary[]>("/accounts")
      .then((a) => setChecking(a.filter((x) => x.account_type === "checking")))
      .catch(setError);
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (!confirm(`${KIND[kind]}을 해지할까요? 만기 전이면 이자가 줄어듭니다.`)) return;
    setBusy(true);
    setError(null);
    try {
      onDone(
        await api<Closed>(`/accounts/${kind}/${accountId}/close`, {
          to_checking_account_id: Number(f.get("to")),
          account_password: f.get("account_password"),
        }),
      );
    } catch (err) {
      setError(err);
      onFail(); // 5번째 오류로 잠겼다면 계좌를 다시 불러와 재설정 칸을 보여 준다
    }
    setBusy(false);
  }

  if (checking.length === 0) return <MoneyErrorText error={error} />;
  return (
    <details className="mt-4 text-sm">
      <summary className="inline-block cursor-pointer text-slate underline underline-offset-4 hover:text-ink">해지하기</summary>
      <form onSubmit={onSubmit} className="mt-3 space-y-3 rounded-2xl bg-paper p-5">
        {preview && (
          <p className="tabular-nums text-slate">
            오늘 해지하면 <span className="font-semibold text-ink">{won(preview.close_today_total)}</span>을 받아요 (원금{" "}
            {won(preview.close_today_principal)} + 이자 {won(preview.close_today_interest)}).
          </p>
        )}
        <label className="block">
          <span className="mb-1 block text-sm text-slate">받을 입출금 계좌</span>
          <select name="to" className="w-full rounded-xl border border-line bg-paper px-3 py-2.5 outline-none focus:border-coral">
            {checking.map((a) => (
              <option key={a.account_id} value={a.account_id}>
                {a.nickname ?? a.account_num} ({won(a.balance)})
              </option>
            ))}
          </select>
        </label>
        <AccountPasswordField label={`해지할 ${KIND[kind]} 계좌 비밀번호`} onReset={onReset} />
        <MoneyErrorText error={error} accountHref={`/accounts/${kind}/${accountId}`} />
        <Button busy={busy}>해지하기</Button>
      </form>
    </details>
  );
}

// 계좌 비밀번호 설정·재설정: 등록된 휴대폰 인증 → 새 비밀번호. 재설정하면 5회 오류 잠금도 풀린다.
// 평소에는 보이지 않는다. 비밀번호를 정하지 않았거나 잠겼을 때, 비밀번호 입력칸의 "재설정하기"를 눌렀을 때,
// 오류 안내 링크(#account-password)로 왔을 때만 나타난다.
function AccountPasswordSetup({
  type,
  accountId,
  highlight,
  autoScroll,
  onDone,
}: {
  type: string;
  accountId: string;
  highlight: boolean;
  autoScroll: boolean;
  onDone: () => void;
}) {
  const [phone, setPhone] = useState<string | undefined>(); // 개발용 문자함에서 볼 등록 번호
  const [token, setToken] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (autoScroll) document.getElementById("account-password")?.scrollIntoView({ block: "center" });
    api<User>("/users/me").then((u) => setPhone(u.phone), () => {});
  }, [autoScroll]);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const pw = String(f.get("account_password") ?? "");
    const problem = accountPasswordProblem(pw, String(f.get("account_password_confirm") ?? ""));
    if (problem) return setError(problem);
    setBusy(true);
    setError(null);
    try {
      await api(`/accounts/${type}/${accountId}/password`, { phone_verification_token: token, new_account_password: pw });
      form.reset();
      setToken(null);
      setRound((n) => n + 1);
      setDone(true);
      onDone(); // 계좌 정보를 다시 불러온다 (이 칸은 닫히지 않고 완료 안내를 보여 준다)
    } catch (err) {
      setError((err as Error).message);
      if ((err as { code?: string }).code === "INVALID_VERIFICATION_TOKEN") {
        setToken(null);
        setRound((n) => n + 1);
      }
    }
    setBusy(false);
  }

  return (
    <section id="account-password" className={`mt-6 rounded-2xl border bg-paper p-5 ${highlight && !done ? "border-coral" : "border-transparent"}`}>
      <h2 className="font-semibold">계좌 비밀번호 설정·재설정</h2>
      <div className="mt-3 space-y-3">
        <p className="text-sm text-slate">
          비밀번호를 아직 정하지 않았거나 5회 잘못 입력해 잠겼다면, 등록된 휴대폰으로 인증한 뒤 새로 정해 주세요.
        </p>
        {done && (
          <p role="status" className="rounded-xl bg-coral-soft px-3 py-2.5 text-sm">
            계좌 비밀번호를 설정했습니다.
          </p>
        )}
        {token ? (
          <form onSubmit={onSubmit} className="space-y-3">
            <AccountPasswordField label="새 계좌 비밀번호" autoFocus />
            <AccountPasswordField label="새 계좌 비밀번호 확인" name="account_password_confirm" />
            <p className="text-sm text-slate">{ACCOUNT_PASSWORD_RULE}</p>
            <ErrorText message={error} />
            <Button busy={busy}>설정하기</Button>
          </form>
        ) : (
          <>
            <PhoneVerify
              key={round}
              path="/verification/phone/send-for-me"
              body={{ purpose: "ACCOUNT_PASSWORD_RESET" }}
              devPhone={phone}
              onVerified={(t) => {
                setDone(false);
                setToken(t);
              }}
            />
            <ErrorText message={error} />
          </>
        )}
      </div>
    </section>
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
  const [preview, setPreview] = useState<InterestPreview | null>(null);
  const [closed, setClosed] = useState<Closed | null>(null);
  // 비밀번호 설정·재설정 칸은 평소엔 숨긴다. 요청(입력칸의 재설정하기·#주소)이 있거나, 비밀번호를 정하지 않았거나 잠겼을 때만 보인다
  const [reset, setReset] = useState<null | "request">(null);

  useEffect(() => {
    api<Account>(`/accounts/${type}/${id}`).then(setAccount).catch((e) => setError(e.message));
  }, [type, id, reload]);

  useEffect(() => {
    // 주소의 #은 브라우저에서만 읽을 수 있어 마운트 뒤에 확인하고, 같은 화면에서 주소만 바뀌는 경우도 따라간다
    const check = () => location.hash === "#account-password" && setReset("request");
    check();
    window.addEventListener("hashchange", check);
    return () => window.removeEventListener("hashchange", check);
  }, []);

  const interestAccount = type === "deposit" || type === "savings";
  useEffect(() => {
    if (!interestAccount) return;
    api<InterestPreview>(`/accounts/${type}/${id}/interest-preview`)
      .then(setPreview)
      .catch(() => setPreview(null)); // 해지된 계좌 등은 보여 주지 않는다
  }, [type, id, reload, interestAccount]);

  const needsPassword = !!account && (account.password_set === false || account.password_locked === true);
  const showSetup = account?.status !== "CLOSED" && (reset !== null || needsPassword);

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
          {(account.account_type === "deposit" || account.account_type === "savings") && account.status !== "CLOSED" && preview && (
            <InterestPreviewCard p={preview} />
          )}
          {account.account_type === "savings" && account.status !== "CLOSED" && (
            <PayIn
              kind="savings"
              accountId={Number(id)}
              suggested={account.monthly_payment}
              onDone={() => setReload((n) => n + 1)}
            />
          )}
          {closed && (
            <p role="status" className="mt-6 rounded-2xl bg-paper p-5 text-sm tabular-nums">
              해지했습니다. {closed.to_account_num}으로 {won(closed.total_amount)}을 보냈습니다 (원금 {won(closed.principal)}, 이자{" "}
              {won(closed.interest)}
              {closed.early_close && ", 중도 해지"}).
            </p>
          )}
          {showSetup && (
            <AccountPasswordSetup
              type={type}
              accountId={id}
              highlight
              autoScroll={reset === "request"}
              onDone={() => {
                setReset("request"); // 완료 안내가 사라지지 않게 계속 보여 준다
                setReload((n) => n + 1);
              }}
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
      {account && (account.account_type === "deposit" || account.account_type === "savings") && account.status !== "CLOSED" && (
        <CloseAccount
          kind={account.account_type}
          accountId={Number(id)}
          preview={preview}
          onReset={() => setReset("request")}
          onFail={() => setReload((n) => n + 1)}
          onDone={(c) => {
            setClosed(c);
            setReload((n) => n + 1);
          }}
        />
      )}
    </>
  );
}
