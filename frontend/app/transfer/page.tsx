"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AccountPasswordField, MoneyErrorText } from "@/components/account-password";
import { Button, Shell } from "@/components/ui";
import {
  AccountSummary,
  ApiError,
  FavoriteRecipient,
  InterbankResult,
  RecentRecipient,
  Recipient,
  User,
  api,
  won,
} from "@/lib/api";
import { useFreshOnLeave } from "@/lib/fresh";

type OwnResult = { from_account_num: string; to_account_num: string; amount: number; balance_after: number };
type Bank = { bank_code: string; name: string };
type Target = Recipient & { shown: string }; // shown = 화면에 보일 받는 분 이름 (이미 마스킹됨)
type StoredTransferIntent = {
  requestVersion?: 2;
  user_id: number;
  intent: string;
  requestId: string;
  from: number;
  bank_code: string;
  bank_name: string;
  account: string;
  shown: string;
  amount: number;
};

const MAX = 100_000_000;
const OWN_BANK = "SpiderBank";
const TRANSFER_INTENT_KEY = "avengers_bank_pending_transfer";

export default function TransferPage() {
  // 숨겨졌다 돌아오면 지난 이체의 완료 화면이 보이던 문제 때문에 매 방문을 새로 시작한다 (lib/fresh.ts)
  return (
    <Shell>
      <Transfer key={useFreshOnLeave()} />
    </Shell>
  );
}

// 김철수 -> 김*수, 김수 -> 김*
const mask = (n: string) => (n.length < 2 ? n : n[0] + "*".repeat(Math.max(1, n.length - 2)) + (n.length > 2 ? n.slice(-1) : ""));

const inputBox = "w-full rounded-xl border border-line bg-paper px-3 py-3 outline-none focus:border-coral";

function Back({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="-ml-1 flex min-h-11 items-center gap-1 text-sm text-slate">
      <svg viewBox="0 0 24 24" aria-hidden className="size-4 fill-none stroke-current stroke-2">
        <path d="m15 6-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      이전
    </button>
  );
}

function Star({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={on ? "자주 쓰는 계좌에서 빼기" : "자주 쓰는 계좌에 담기"}
      aria-pressed={on}
      onClick={onClick}
      className="flex size-11 shrink-0 items-center justify-center text-coral"
    >
      <svg viewBox="0 0 24 24" aria-hidden className={`size-6 stroke-current stroke-2 ${on ? "fill-current" : "fill-none"}`}>
        <path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z" strokeLinejoin="round" />
      </svg>
    </button>
  );
}

function Transfer() {
  const [accounts, setAccounts] = useState<AccountSummary[] | null>(null);
  const [from, setFrom] = useState<number | null>(null);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [tab, setTab] = useState<"recent" | "fav" | "mine">("recent");
  const [recent, setRecent] = useState<RecentRecipient[]>([]);
  const [favs, setFavs] = useState<FavoriteRecipient[]>([]);
  const [banks, setBanks] = useState<Bank[]>([]);
  const [banksUnavailable, setBanksUnavailable] = useState(false);
  const [bank, setBank] = useState(""); // "" = 우리 은행
  const [acct, setAcct] = useState("");
  const [target, setTarget] = useState<Target | null>(null);
  const [amount, setAmount] = useState(0);
  const [sheet, setSheet] = useState<null | "confirm" | "password">(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [own, setOwn] = useState<OwnResult | null>(null);
  const [inter, setInter] = useState<InterbankResult | null>(null);
  const [recoveringRequest, setRecoveringRequest] = useState(true);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const [legacyRequest, setLegacyRequest] = useState(false);
  const [currentUserId, setCurrentUserId] = useState<number | null>(null);

  const [myName, setMyName] = useState<string | null>(null); // 내 실명: 내 계좌로 보낼 때 받는 분 이름은 통장 별명이 아니라 이것이다
  const requestRef = useRef<{ intent: string; requestId: string } | null>(null);

  useEffect(() => {
    const userP = api<User>("/users/me").then((u) => {
      setMyName(u.name);
      setCurrentUserId(u.user_id);
      return u;
    });
    api<RecentRecipient[]>("/transfers/recent").then(setRecent).catch(() => {});
    api<FavoriteRecipient[]>("/transfers/favorites").then(setFavs).catch(() => {});
    const banksP = api<Bank[]>("/interbank-transfers/banks")
      .then((list) => {
        setBanksUnavailable(false);
        setBanks(list);
        return list;
      })
      .catch(() => {
        setBanksUnavailable(true);
        return null;
      });
    api<AccountSummary[]>("/accounts")
      .then(async (a) => {
        let currentUser: User;
        try {
          currentUser = await userP;
        } catch (e) {
          sessionStorage.removeItem(TRANSFER_INTENT_KEY);
          requestRef.current = null;
          setRecoveringRequest(false);
          setError(e);
          return;
        }
        const checking = a.filter((x) => x.account_type === "checking");
        setAccounts(checking);
        // 홈의 "최근 이체한 분"에서 오면 ?from=출금 계좌 id&to=받는 계좌번호가 붙어 있다 (C-068)
        const q = new URLSearchParams(window.location.search);
        const fromId = Number(q.get("from"));
        setFrom(checking.some((x) => x.account_id === fromId) ? fromId : (checking[0]?.account_id ?? null));
        if (await recoverPriorRequest(currentUser.user_id)) return;
        const to = q.get("to")?.slice(0, 50);
        if (to) {
          // 홈의 최근 이체한 분에서 오면 ?bank=(타행 코드, 우리 은행은 빈 값)가 같이 온다
          const wanted = (q.get("bank") ?? "").replace(/\D/g, "").slice(0, 3);
          const known = await banksP;
          if (wanted && (!known || !known.some((b) => b.bank_code === wanted))) {
            setBank(wanted);
            setAcct(to);
            setStep(2);
            setError(new Error(known ? `은행 코드 ${wanted}를 찾을 수 없습니다. 은행 목록을 다시 불러오거나 은행을 직접 선택해 주세요.` : "은행 목록을 불러오지 못했습니다. 다시 시도해 주세요."));
            return;
          }
          try {
            await inquire(wanted, to, known?.find((b) => b.bank_code === wanted)?.name);
          } catch (e) {
            setBank(wanted);
            setAcct(to);
            setStep(2);
            setError(e);
          }
        }
      })
      .catch((e) => {
        setRecoveringRequest(false);
        setError(e);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 처음 한 번만 불러온다
  }, []);

  // 처리 중이면 5초마다 최대 1분까지 결과를 다시 묻는다
  const pendingId = inter?.status === "PENDING" ? inter.transfer_id : null;
  useEffect(() => {
    if (pendingId === null) return;
    let n = 0;
    const t = setInterval(() => {
      api<InterbankResult>(`/interbank-transfers/${pendingId}`)
        .then((r) => {
          if (r.status !== "PENDING") {
            setInter(r);
            clearStoredRequest();
          }
        })
        .catch(() => {});
      if (++n >= 12) clearInterval(t);
    }, 5000);
    return () => clearInterval(t);
  }, [pendingId]);

  const bankName = (code: string) => (code === "" ? OWN_BANK : (banks.find((b) => b.bank_code === code)?.name ?? code));

  async function retryBanks() {
    setBusy(true);
    try {
      const list = await api<Bank[]>("/interbank-transfers/banks");
      setBanks(list);
      setBanksUnavailable(false);
      if (bank && acct.trim()) {
        const match = list.find((b) => b.bank_code === bank);
        if (!match) {
          setError(new Error(`은행 코드 ${bank}를 찾을 수 없습니다. 은행을 직접 선택해 주세요.`));
        } else {
          await inquire(bank, acct.trim(), match.name);
          setError(null);
        }
      } else {
        setError(null);
      }
    } catch {
      setBanksUnavailable(true);
      setError(new Error("은행 목록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."));
    }
    setBusy(false);
  }

  // 예금주 조회 후 금액 입력(3단계)으로. 실패하면 던진다
  async function inquire(bank_code: string, account: string, knownBankName?: string) {
    const r =
      bank_code === ""
        ? await api<{ holder_name: string }>("/transfers/inquiry", { to_account_num: account })
        : await api<{ holder_name: string }>("/interbank-transfers/inquiry", { to_bank: bank_code, to_account: account });
    setTarget({
      bank_code,
      bank_name: knownBankName ?? bankName(bank_code),
      account,
      name: r.holder_name,
      shown: bank_code === "" ? r.holder_name : mask(r.holder_name), // 우리 은행은 서버가 이미 마스킹
    });
    setAmount(0);
    setStep(3);
  }

  async function recoverPriorRequest(userId: number): Promise<boolean> {
    setRecoveryError(null);
    setLegacyRequest(false);
    let saved: StoredTransferIntent | null = null;
    try {
      const raw = sessionStorage.getItem(TRANSFER_INTENT_KEY);
      saved = raw ? (JSON.parse(raw) as StoredTransferIntent) : null;
      if (!saved || !saved.requestId || !saved.intent || !saved.account || !saved.bank_code && saved.bank_code !== "") {
        sessionStorage.removeItem(TRANSFER_INTENT_KEY);
        requestRef.current = null;
        setRecoveringRequest(false);
        return false;
      }
    } catch {
      sessionStorage.removeItem(TRANSFER_INTENT_KEY);
      requestRef.current = null;
      setRecoveringRequest(false);
      return false;
    }

    if (saved.user_id !== userId) {
      sessionStorage.removeItem(TRANSFER_INTENT_KEY);
      requestRef.current = null;
      setRecoveringRequest(false);
      setRecoveryError(null);
      return false;
    }

    setFrom(saved.from);
    setTarget({ bank_code: saved.bank_code, bank_name: saved.bank_name, account: saved.account, name: saved.shown, shown: saved.shown });
    setAmount(saved.amount);
    setStep(3);
    if (saved.requestVersion !== 2) {
      // 이전 API는 클라이언트 request_id를 거래 ID로 사용하지 않았다. 404를 재시도 허가로 해석하면 중복 송금될 수 있다.
      requestRef.current = null;
      setLegacyRequest(true);
      setRecoveringRequest(true);
      setRecoveryError("이전 서버에서 처리된 이체일 수 있습니다. 이체를 보낸 서버의 거래내역과 잔액을 확인한 뒤 새 이체를 시작해 주세요.");
      return true;
    }
    requestRef.current = { intent: saved.intent, requestId: saved.requestId };
    setRecoveringRequest(true);
    try {
      if (saved.bank_code === "") {
        const result = await api<OwnResult>(`/transfers/requests/${saved.requestId}`);
        setOwn(result);
        sessionStorage.removeItem(TRANSFER_INTENT_KEY);
        requestRef.current = null;
      } else {
        const result = await api<InterbankResult>(`/interbank-transfers/${saved.requestId}`);
        setInter(result);
        if (result.status !== "PENDING") {
          sessionStorage.removeItem(TRANSFER_INTENT_KEY);
          requestRef.current = null;
        }
      }
      setRecoveringRequest(false);
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // 요청이 아직 기록되지 않았다면 같은 request_id로 다시 보내 안전하게 복구한다.
        setRecoveryError("이체 결과를 아직 찾지 못했습니다. 다시 이체하면 같은 요청 ID로 확인합니다.");
        setRecoveringRequest(false);
        return true;
      }
      setRecoveryError("이전 이체 결과를 확인하지 못했습니다. 결과를 다시 확인해 주세요.");
      setRecoveringRequest(true);
      return true;
    }
  }

  async function retryRecovery() {
    if (currentUserId !== null) await recoverPriorRequest(currentUserId);
  }

  function clearStoredRequest() {
    sessionStorage.removeItem(TRANSFER_INTENT_KEY);
    requestRef.current = null;
    setLegacyRequest(false);
  }

  function startAfterLegacyReview() {
    clearStoredRequest();
    setRecoveryError(null);
    setRecoveringRequest(false);
    setTarget(null);
    setAmount(0);
    setStep(1);
  }

  async function onDirect() {
    if (bank && (banksUnavailable || !banks.some((b) => b.bank_code === bank))) {
      setError(new Error(banksUnavailable ? "은행 목록을 다시 불러와 타행 계좌를 확인해 주세요." : `은행 코드 ${bank}를 은행 목록에서 확인할 수 없습니다.`));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await inquire(bank, acct.trim());
    } catch (e) {
      setError(e);
    }
    setBusy(false);
  }

  function pick(r: Recipient) {
    setTarget({ ...r, shown: r.name ?? r.account });
    setAmount(0);
    setError(null);
    setStep(3);
  }

  async function addFav(r: RecentRecipient) {
    const key = (x: Recipient) => x.bank_code + "/" + x.account;
    setRecent((l) => l.map((x) => (key(x) === key(r) ? { ...x, favorite_id: -1 } : x)));
    try {
      const f = await api<FavoriteRecipient>("/transfers/favorites", {
        bank_code: r.bank_code,
        bank_name: r.bank_name,
        account: r.account,
        name: r.name,
      });
      setRecent((l) => l.map((x) => (key(x) === key(r) ? { ...x, favorite_id: f.favorite_id } : x)));
      setFavs((l) => (l.some((x) => x.favorite_id === f.favorite_id) ? l : [f, ...l]));
    } catch {
      setRecent((l) => l.map((x) => (key(x) === key(r) ? { ...x, favorite_id: null } : x)));
    }
  }

  async function removeFav(id: number) {
    const prevFavs = favs;
    const prevRecent = recent;
    setFavs((l) => l.filter((x) => x.favorite_id !== id));
    setRecent((l) => l.map((x) => (x.favorite_id === id ? { ...x, favorite_id: null } : x)));
    try {
      await api<unknown>(`/transfers/favorites/${id}`, undefined, "DELETE");
    } catch {
      setFavs(prevFavs);
      setRecent(prevRecent);
    }
  }

  async function onPay(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!target || from === null) return;
    if (currentUserId === null) return setError(new Error("사용자 정보를 확인한 뒤 다시 시도해 주세요."));
    if (recoveringRequest || legacyRequest) return setRecoveryError("이전 이체의 거래내역과 잔액을 먼저 확인해 주세요.");
    const pw = new FormData(e.currentTarget).get("account_password");
    const intent = JSON.stringify([from, target.bank_code, target.account, amount]);
    if (requestRef.current?.intent !== intent) {
      requestRef.current = { intent, requestId: crypto.randomUUID() };
    }
    const requestId = requestRef.current.requestId;
    const stored: StoredTransferIntent = {
      requestVersion: 2, user_id: currentUserId, intent, requestId, from, bank_code: target.bank_code, bank_name: target.bank_name,
      account: target.account, shown: target.shown, amount,
    };
    sessionStorage.setItem(TRANSFER_INTENT_KEY, JSON.stringify(stored));
    setBusy(true);
    setError(null);
    try {
      if (target.bank_code === "") {
        setOwn(
          await api<OwnResult>("/transfers", {
            from_checking_account_id: from,
            to_account_num: target.account,
            amount,
            account_password: pw,
            request_id: requestId,
          }),
        );
        clearStoredRequest();
      } else {
        const result = await api<InterbankResult>("/interbank-transfers", {
            from_checking_account_id: from,
            to_bank: target.bank_code,
            to_account: target.account,
            amount,
            account_password: pw,
            request_id: requestId,
          });
        setInter(result);
        if (result.status !== "PENDING") clearStoredRequest();
      }
    } catch (err) {
      setError(err);
    }
    setBusy(false);
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

  const fromAcct = accounts?.find((a) => a.account_id === from);
  const balance = fromAcct?.balance ?? 0;
  const accountHref = from ? `/accounts/checking/${from}` : undefined;

  // 4단계: 완료
  if ((own || inter) && target) {
    const pending = inter?.status === "PENDING";
    const failed = inter?.status === "FAILED";
    const sent = own?.amount ?? inter?.amount ?? 0;
    const remain = own?.balance_after ?? inter?.balance_after ?? 0;
    return (
      <section className="daily-card mt-10 p-6 text-center">
        <span className="seal stamp size-20 text-lg">{pending ? "처리 중" : failed ? "실패" : "완료"}</span>
        <h1 className="mt-6 text-2xl font-semibold">{pending ? "이체를 처리하고 있습니다" : failed ? "이체에 실패했습니다" : "이체됐습니다!"}</h1>
        <p className="mt-3 text-3xl font-semibold tabular-nums">{won(sent)}</p>
        <p className="mt-2 text-slate tabular-nums">
          {target.shown} 님 · {target.bank_name} {target.account}
        </p>
        {pending && <p className="mt-2 text-slate">결과는 거래내역에서 확인하세요.</p>}
        {failed && <p className="mt-2 text-slate">{inter?.fail_message ?? "보낸 금액은 환불됩니다."}</p>}
        <p className="mt-1 text-slate tabular-nums">남은 잔액 {won(remain)}</p>
        <div className="mt-8 flex justify-center gap-3">
          <Link href="/accounts" className="rounded-xl bg-coral px-6 py-3 font-medium text-paper">
            내 계좌 보기
          </Link>
          {/* 같은 주소로는 화면이 새로 만들어지지 않으므로, 전체를 다시 불러 처음 상태로 되돌린다 */}
          <button type="button" onClick={() => window.location.reload()} className="rounded-xl border border-line px-6 py-3 font-medium">
            또 이체하기
          </button>
        </div>
      </section>
    );
  }

  // 2단계: 계좌번호 직접 입력
  if (step === 2) {
    return (
      <section className="daily-card mt-2 p-5 sm:p-7">
        <Back
          onClick={() => {
            setError(null);
            setStep(1);
          }}
        />
        <h1 className="mt-2 text-2xl font-semibold">누구에게 보낼까요?</h1>
        <div className="mt-6 space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm text-slate">계좌번호</span>
            <input
              autoFocus
              inputMode="numeric"
              maxLength={50}
              value={acct}
              onChange={(e) => setAcct(e.target.value.replace(/[^\d-]/g, ""))}
              className={`${inputBox} tabular-nums`}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm text-slate">은행/증권사</span>
            <select value={bank} onChange={(e) => setBank(e.target.value)} className={inputBox}>
              <option value="">SpiderBank(우리 은행)</option>
              {bank && !banks.some((b) => b.bank_code === bank) && <option value={bank}>은행 코드 {bank} (확인 필요)</option>}
              {banks.map((b) => (
                <option key={b.bank_code} value={b.bank_code}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
          {banksUnavailable && <p role="status" className="text-sm text-slate">은행 목록을 불러오지 못했습니다. 타행 계좌를 확인하려면 다시 불러와 주세요.</p>}
          {error !== null && <p role="alert" className="text-sm text-seal">{(error as Error).message}</p>}
          {(banksUnavailable || (bank !== "" && !banks.some((b) => b.bank_code === bank))) && <Button type="button" busy={busy} onClick={retryBanks}>은행 목록 다시 불러오기</Button>}
          <Button type="button" busy={busy} disabled={!acct.trim() || (bank !== "" && (banksUnavailable || !banks.some((b) => b.bank_code === bank)))} onClick={onDirect}>
            확인
          </Button>
        </div>
      </section>
    );
  }

  // 3단계: 금액
  if (step === 3 && target) {
    const over = amount > balance;
    const add = (n: number) => setAmount((a) => Math.min(MAX, a + n));
    const key = (k: string) =>
      setAmount((a) => (k === "<" ? Math.floor(a / 10) : Math.min(MAX, Number(String(a === 0 ? "" : a) + k))));
    return (
      <section className="daily-card mt-2 p-5 sm:p-7">
        <Back onClick={() => setStep(1)} />
        {recoveryError && <div role="alert" className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-coral-soft p-3 text-sm"><span>{recoveryError}</span>{legacyRequest ? <button type="button" onClick={startAfterLegacyReview} className="shrink-0 underline">내역 확인 후 새 이체</button> : <button type="button" onClick={retryRecovery} className="shrink-0 underline">결과 다시 확인</button>}</div>}
        {recoveringRequest && !legacyRequest && <p role="status" className="mt-3 text-sm text-slate">이전 이체 결과를 확인하고 있습니다…</p>}
        <div className="mt-2 text-center">
          <p className="text-xl font-semibold">{target.shown} 님</p>
          <p className="text-sm text-slate tabular-nums">
            {target.bank_name} {target.account}
          </p>
          <p className={`mt-6 text-4xl font-semibold tabular-nums ${amount === 0 ? "text-slate" : ""}`}>{won(amount)}</p>
          <p className={`mt-2 text-sm tabular-nums ${over ? "text-seal" : "text-slate"}`}>
            {over ? "출금 가능 금액을 넘었습니다. " : ""}출금가능금액 {won(balance)}
          </p>
          <div className="mt-3 flex items-center justify-center gap-2 text-sm">
            <span className="text-slate">출금할 계좌</span>
            {accounts && accounts.length > 1 ? (
              <select
                aria-label="출금 계좌"
                value={from ?? ""}
                onChange={(e) => setFrom(Number(e.target.value))}
                className="rounded-lg border border-line bg-paper px-2 py-1.5 tabular-nums outline-none focus:border-coral"
              >
                {accounts.map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    {a.nickname ?? a.account_num}
                  </option>
                ))}
              </select>
            ) : (
              <span className="font-medium tabular-nums">{accounts?.[0] ? (accounts[0].nickname ?? accounts[0].account_num) : ""}</span>
            )}
          </div>
        </div>
        <div className="mt-4 flex justify-center gap-2">
          {(
            [
              ["전액", () => setAmount(Math.min(MAX, balance))],
              ["100만", () => add(1_000_000)],
              ["10만", () => add(100_000)],
              ["5만", () => add(50_000)],
              ["1만", () => add(10_000)],
            ] as [string, () => void][]
          ).map(([l, f]) => (
            <button key={l} type="button" onClick={f} className="rounded-full border border-line px-3 py-1.5 text-sm">
              {l}
            </button>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-3 gap-1">
          {["1", "2", "3", "4", "5", "6", "7", "8", "9", "00", "0", "<"].map((k) => (
            <button
              key={k}
              type="button"
              aria-label={k === "<" ? "지우기" : k}
              onClick={() => key(k)}
              className="h-14 rounded-xl text-xl font-medium tabular-nums active:bg-coral-soft"
            >
              {k === "<" ? "⌫" : k}
            </button>
          ))}
        </div>
        <div className="mt-3">
          <Button
            type="button"
            disabled={amount === 0 || over || recoveringRequest}
            onClick={() => {
              setError(null);
              setSheet("confirm");
            }}
          >
            확인
          </Button>
        </div>

        {/* body에 직접 그린다: 화면 진입 애니메이션(transform)이 걸린 안쪽에서는 fixed가 화면이 아니라 그 영역 기준이 돼 위치가 어긋난다.
            모바일은 아래에서 올라오는 시트, PC(md 이상)는 화면 가운데 창 */}
        {sheet &&
          createPortal(
          <div className="fixed inset-0 z-50 flex items-end bg-ink/40 md:items-center md:justify-center md:p-4" role="dialog" aria-modal="true">
            <div className="mx-auto w-full max-w-md rounded-t-2xl bg-paper p-5 pb-8 md:rounded-2xl">
              <div className="flex justify-end">
                <button type="button" aria-label="닫기" onClick={() => setSheet(null)} className="-mr-2 flex size-11 items-center justify-center text-slate">
                  <svg viewBox="0 0 24 24" aria-hidden className="size-5 fill-none stroke-current stroke-2">
                    <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
                  </svg>
                </button>
              </div>
              {sheet === "confirm" ? (
                <>
                  <h2 className="text-xl font-semibold tabular-nums">
                    {target.shown} 님께 {won(amount)}을 이체합니다.
                  </h2>
                  <p className="mt-2 text-slate tabular-nums">
                    {target.bank_name} {target.account}
                  </p>
                  <p className="mt-1 text-sm text-slate">받는 분과 금액을 한 번 더 확인해 주세요</p>
                  <div className="mt-6">
                    <Button type="button" onClick={() => setSheet("password")}>
                      이체
                    </Button>
                  </div>
                </>
              ) : (
                <form onSubmit={onPay} className="space-y-4">
                  <h2 className="text-xl font-semibold">계좌 비밀번호를 입력해 주세요</h2>
                  <AccountPasswordField label="출금 계좌 비밀번호" resetHref={accountHref} autoFocus />
                  <MoneyErrorText error={error} accountHref={accountHref} />
                  <Button busy={busy} disabled={recoveringRequest}>이체</Button>
                </form>
              )}
            </div>
          </div>,
          document.body,
        )}
      </section>
    );
  }

  // 1단계: 받는 사람 고르기
  const tabs = [
    ["recent", "최근"],
    ["fav", "자주 쓰는"],
    ["mine", "내 계좌"],
  ] as const;
  const row = "flex items-center gap-1 border-b border-line";
  const pickBtn = "min-w-0 flex-1 py-3 text-left";
  const recipientRow = (r: RecentRecipient | FavoriteRecipient, fav: boolean, onStar: () => void) => (
    <li key={r.bank_code + "/" + r.account} className={row}>
      <button type="button" onClick={() => pick(r)} className={pickBtn}>
        <span className="block truncate font-medium">{r.name ?? r.account}</span>
        <span className="block truncate text-sm text-slate tabular-nums">
          {r.bank_name} {r.account}
        </span>
      </button>
      <Star on={fav} onClick={onStar} />
    </li>
  );
  const empty = (t: string) => <li className="py-10 text-center text-sm text-slate">{t}</li>;

  return (
    <section className="daily-card mt-4 p-5 sm:p-7">
      <h1 className="text-2xl font-semibold">누구에게 보낼까요?</h1>
      {error !== null && <p role="alert" className="mt-2 text-sm text-seal">{(error as Error).message}</p>}
      <button
        type="button"
        onClick={() => setStep(2)}
        className="mt-6 flex w-full items-center rounded-xl border border-line bg-paper px-3 py-3 text-left text-slate"
      >
        계좌번호
      </button>
      {banksUnavailable && <div className="mt-3 flex items-center gap-3 text-sm text-slate"><span>은행 목록을 불러오지 못했습니다.</span><button type="button" disabled={busy} onClick={retryBanks} className="underline">다시 시도</button></div>}
      <div role="tablist" className="mt-6 flex border-b border-line">
        {tabs.map(([k, l]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={`flex-1 py-2.5 text-sm font-medium ${tab === k ? "border-b-2 border-coral text-ink" : "text-slate"}`}
          >
            {l}
          </button>
        ))}
      </div>
      <ul>
        {tab === "recent" &&
          (recent.length === 0
            ? empty("최근 이체한 분이 없습니다.")
            : recent.map((r) => recipientRow(r, r.favorite_id !== null, () => (r.favorite_id === null ? addFav(r) : removeFav(r.favorite_id)))))}
        {tab === "fav" &&
          (favs.length === 0 ? empty("자주 쓰는 계좌가 없습니다. 최근 목록에서 별을 눌러 담아 보세요.") : favs.map((f) => recipientRow(f, true, () => removeFav(f.favorite_id))))}
        {tab === "mine" &&
          (accounts?.length
            ? accounts.map((a) => (
                <li key={a.account_id} className={row}>
                  <button
                    type="button"
                    onClick={() => pick({ bank_code: "", bank_name: OWN_BANK, account: a.account_num, name: myName ?? "내 계좌" })}
                    className={`${pickBtn} flex items-center justify-between gap-3`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{myName ?? "내 계좌"}</span>
                      <span className="block text-sm text-slate tabular-nums">
                        {a.nickname ? `${a.nickname} · ` : ""}
                        {a.account_num}
                      </span>
                    </span>
                    <span className="shrink-0 text-sm tabular-nums">{won(a.balance)}</span>
                  </button>
                </li>
              ))
            : empty("내 입출금 계좌가 없습니다."))}
      </ul>
    </section>
  );
}
