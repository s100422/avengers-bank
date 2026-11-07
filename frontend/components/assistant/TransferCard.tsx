"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ACCOUNTS_CHANGED, TransferAction, agent, won } from "@/lib/api";

const at = (iso: string) =>
  new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" });

// 비서가 만든 이체 초안. 이체하기를 누르기 전에는 돈이 움직이지 않는다.
export function TransferCard({
  action,
  onDone,
  onAuthError,
}: {
  action: TransferAction;
  onDone: (text: string) => void;
  onAuthError: (e: unknown) => void;
}) {
  const router = useRouter();
  const [state, setState] = useState<"pending" | "busy" | "done" | "cancelled">("pending");
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(() => Date.parse(action.expires_at) <= Date.now());

  // 만료 시각이 되면 이체하기를 막는다
  useEffect(() => {
    if (expired) return;
    const t = setTimeout(() => setExpired(true), Math.max(0, Date.parse(action.expires_at) - Date.now()));
    return () => clearTimeout(t);
  }, [action.expires_at, expired]);

  async function run(confirm: boolean) {
    setState("busy");
    setError(null);
    try {
      if (confirm) {
        const r = await agent.confirm(action.draft_id);
        setState("done");
        onDone(`${r.recipient_name}님께 ${won(r.amount)}을 보냈어요. 최종 잔액은 ${won(r.balance_after)}입니다.`);
        window.dispatchEvent(new Event(ACCOUNTS_CHANGED));
        router.refresh();
      } else {
        await agent.cancel(action.draft_id);
        setState("cancelled");
      }
    } catch (e) {
      onAuthError(e);
      setError((e as Error).message);
      setState("pending");
    }
  }

  const rows: [string, string][] = [
    ["출금 계좌", `${action.from_account_name} ${action.from_account_num_masked}`],
    ["받는 분", action.recipient_name],
    ["받는 계좌", action.to_account_num_masked],
    ["이체 금액", won(action.amount)],
    ["이체 후 예상 잔액", won(action.expected_balance_after)],
    ["만료 시각", at(action.expires_at)],
  ];
  const closed = state === "done" || state === "cancelled";

  return (
    <div role="group" aria-label="이체 확인" className="rounded-2xl border border-coral/40 bg-paper p-4">
      <p className="font-semibold">이체 확인</p>
      <dl className="mt-3 space-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3">
            <dt className="text-slate">{k}</dt>
            <dd className={`text-right ${k === "이체 금액" ? "font-semibold" : ""}`}>{v}</dd>
          </div>
        ))}
      </dl>
      {error && (
        <p role="alert" className="mt-3 text-sm text-seal">
          {error}
        </p>
      )}
      {closed ? (
        <p className="mt-3 text-sm font-medium text-slate">{state === "done" ? "이체를 완료했어요." : "이체를 취소했어요."}</p>
      ) : (
        <>
          {expired && <p className="mt-3 text-sm text-seal">확인 시간이 지났어요. 다시 요청해 주세요.</p>}
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => run(false)}
              disabled={state === "busy"}
              aria-label="이체 취소"
              className="min-h-11 flex-1 rounded-xl border border-line font-medium text-slate disabled:opacity-50"
            >
              취소
            </button>
            <button
              type="button"
              onClick={() => run(true)}
              disabled={state === "busy" || expired}
              aria-label={`${action.recipient_name}님께 ${won(action.amount)} 이체하기`}
              className="min-h-11 flex-1 rounded-xl bg-coral font-medium text-paper disabled:opacity-50"
            >
              {state === "busy" ? "처리 중…" : "이체하기"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
