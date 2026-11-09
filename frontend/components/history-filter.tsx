"use client";

import { useState } from "react";

// 거래 내역 필터. 서버의 GET .../histories 검색 조건(C-064)으로 바꿔 쓴다.
export type Filter = {
  period: "1m" | "3m" | "6m" | "custom";
  from: string; // 직접입력일 때 YYYY-MM-DD
  to: string;
  group: keyof typeof GROUPS;
  min: string;
  max: string;
  q: string;
};

// 화면의 거래 유형 → 서버 거래 종류 코드
const GROUPS = {
  all: { label: "전체", types: [] as string[] },
  in: { label: "입금", types: ["TRANSFER_IN", "INTERBANK_IN", "INTERBANK_REFUND", "CLOSE_IN", "INTEREST", "DEV_CHARGE"] },
  out: { label: "출금", types: ["TRANSFER_OUT", "INTERBANK_OUT", "TO_SAVINGS", "TO_DEPOSIT", "CARD_PAYMENT", "CARD_BILL_PAYMENT", "CLOSE_OUT"] },
  transfer: { label: "이체", types: ["TRANSFER_OUT", "TRANSFER_IN", "INTERBANK_OUT", "INTERBANK_IN", "INTERBANK_REFUND"] },
  card: { label: "카드", types: ["CARD_PAYMENT", "CARD_BILL_PAYMENT"] },
};
const PERIODS = { "1m": "1개월", "3m": "3개월", "6m": "6개월", custom: "직접입력" } as const;

export const DEFAULT_FILTER: Filter = { period: "1m", from: "", to: "", group: "all", min: "", max: "", q: "" };

const ymd = (d: Date) => d.toLocaleDateString("sv-SE"); // YYYY-MM-DD (내 컴퓨터 날짜 기준)

export function toQuery(f: Filter): string {
  const p = new URLSearchParams({ limit: "200" });
  if (f.period === "custom") {
    if (f.from) p.set("date_from", f.from);
    if (f.to) p.set("date_to", f.to);
  } else {
    const from = new Date();
    from.setMonth(from.getMonth() - Number(f.period[0]));
    p.set("date_from", ymd(from));
  }
  GROUPS[f.group].types.forEach((t) => p.append("types", t));
  if (f.min) p.set("min_amount", f.min);
  if (f.max) p.set("max_amount", f.max);
  if (f.q.trim()) p.set("q", f.q.trim());
  return p.toString();
}

export function summary(f: Filter): string {
  const period = f.period === "custom" ? `${f.from || "처음"} ~ ${f.to || "오늘"}` : PERIODS[f.period];
  const won = (v: string) => `${Number(v).toLocaleString("ko-KR")}원`;
  const amount = f.min || f.max ? `, ${won(f.min || "0")} ~ ${f.max ? won(f.max) : ""}` : "";
  return `${period}, ${GROUPS[f.group].label}${amount}`;
}

const chip = (on: boolean) =>
  `rounded-full border px-3.5 py-1.5 text-sm whitespace-nowrap ${on ? "border-coral bg-coral-soft font-medium text-coral" : "border-line bg-paper text-slate hover:text-ink"}`;
const input = "w-full rounded-xl border border-line bg-paper px-3 py-2 outline-none focus:border-coral";

export function HistoryFilterBar({ value, onApply }: { value: Filter; onApply: (f: Filter) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const set = (patch: Partial<Filter>) => setDraft({ ...draft, ...patch });

  return (
    <div className="mt-3">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          onApply({ ...value, q: draft.q });
        }}
      >
        <input
          type="search"
          aria-label="사용처·계좌번호 검색"
          placeholder="사용처·계좌번호 검색"
          value={draft.q}
          onChange={(e) => {
            set({ q: e.target.value });
            if (e.target.value === "" && value.q) onApply({ ...value, q: "" }); // 검색어를 지우면 바로 전체로
          }}
          maxLength={100}
          className={input}
        />
        <button
          type="button"
          aria-expanded={open}
          aria-controls="history-filter"
          onClick={() => {
            setDraft({ ...value, q: draft.q }); // 적용 안 한 필터 변경은 버리고, 검색칸 글자는 그대로 둔다
            setOpen(!open);
          }}
          className="shrink-0 rounded-xl border border-line bg-paper px-3 text-sm whitespace-nowrap text-slate hover:text-ink"
        >
          필터
        </button>
      </form>
      <p className="mt-2 text-sm text-slate">{summary(value)}</p>

      {open && (
        <div id="history-filter" className="mt-3 space-y-4 rounded-2xl bg-paper p-5">
          <fieldset>
            <legend className="mb-2 text-sm text-slate">기간</legend>
            <div className="flex flex-wrap gap-2">
              {(Object.keys(PERIODS) as Filter["period"][]).map((k) => (
                <button key={k} type="button" aria-pressed={draft.period === k} onClick={() => set({ period: k })} className={chip(draft.period === k)}>
                  {PERIODS[k]}
                </button>
              ))}
            </div>
            {draft.period === "custom" && (
              <div className="mt-2 flex items-center gap-2">
                <input type="date" aria-label="시작일" value={draft.from} max={draft.to || undefined} onChange={(e) => set({ from: e.target.value })} className={input} />
                <span className="text-slate">~</span>
                <input type="date" aria-label="종료일" value={draft.to} min={draft.from || undefined} onChange={(e) => set({ to: e.target.value })} className={input} />
              </div>
            )}
          </fieldset>

          <fieldset>
            <legend className="mb-2 text-sm text-slate">거래 유형</legend>
            <div className="flex flex-wrap gap-2">
              {(Object.keys(GROUPS) as Filter["group"][]).map((k) => (
                <button key={k} type="button" aria-pressed={draft.group === k} onClick={() => set({ group: k })} className={chip(draft.group === k)}>
                  {GROUPS[k].label}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend className="mb-2 text-sm text-slate">금액 (원)</legend>
            <div className="flex items-center gap-2">
              <input type="number" inputMode="numeric" min={0} aria-label="최소 금액" placeholder="최소" value={draft.min} onChange={(e) => set({ min: e.target.value })} className={input} />
              <span className="text-slate">~</span>
              <input type="number" inputMode="numeric" min={0} aria-label="최대 금액" placeholder="최대" value={draft.max} onChange={(e) => set({ max: e.target.value })} className={input} />
            </div>
          </fieldset>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setDraft({ ...DEFAULT_FILTER, q: draft.q })}
              className="flex-1 rounded-xl border border-line py-2.5 text-slate hover:text-ink"
            >
              초기화
            </button>
            <button
              type="button"
              onClick={() => {
                onApply(draft);
                setOpen(false);
              }}
              className="flex-[2] rounded-xl bg-coral py-2.5 font-medium text-paper"
            >
              적용
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
