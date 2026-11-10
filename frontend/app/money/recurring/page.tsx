"use client";

import { useState } from "react";
import { Button, ErrorText, Field, MoneyField, Shell } from "@/components/ui";
import { ApiError, won } from "@/lib/api";
import { money, type Category, type RecurringCandidate, type RecurringItem, type RecurringUpdate } from "@/lib/money";
import { BottomSheet } from "@/components/money/detail/BottomSheet";
import { CategoryPicker } from "@/components/money/detail/CategoryPicker";
import { BackLink, Chip, Empty, LoadState, card, outlineBtn, useLoad, useMonth, withMonth } from "@/components/money/detail/common";
import { TxnList } from "@/components/money/detail/TxnRow";

export default function RecurringPage() {
  return (
    <Shell>
      <Recurring />
    </Shell>
  );
}

type Data = { candidates: RecurringCandidate[]; registered: RecurringItem[] };
const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : "저장하지 못했어요. 잠시 후 다시 시도해 주세요.");
// 건너뛰기는 항상 실제 이번 달(KST)에 건다
const currentYm = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }).slice(0, 7);
const signed = (i: { direction: "IN" | "OUT"; amount: number }) => `${i.direction === "IN" ? "+" : "-"}${won(i.amount)}`;

function Recurring() {
  const month = useMonth();
  const { data, setData, error, reload } = useLoad<Data>("recurring", () => money.recurring());
  const [tab, setTab] = useState<"candidates" | "registered">("candidates");
  const [editing, setEditing] = useState<RecurringItem | null>(null);

  const tabs = [
    { key: "candidates", label: "확인 필요", count: data?.candidates.length },
    { key: "registered", label: "등록됨", count: data?.registered.length },
  ] as const;

  return (
    <>
      <BackLink fallback={withMonth("/money", month)} />
      <h1 className="mt-2 text-2xl font-bold">정기 거래 관리</h1>

      <div role="tablist" aria-label="정기 거래" className="mt-4 grid grid-cols-2 rounded-xl bg-line/50 p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            id={`tab-${t.key}`}
            aria-selected={tab === t.key}
            aria-controls="recurring-panel"
            onClick={() => setTab(t.key)}
            className={`min-h-11 rounded-lg text-sm font-medium ${tab === t.key ? "bg-paper text-ink shadow-sm" : "text-slate"}`}
          >
            {t.label}
            {t.count !== undefined && ` ${t.count}`}
          </button>
        ))}
      </div>

      <div id="recurring-panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        <LoadState error={error} loading={!data} onRetry={reload} />
        {data && !error && tab === "candidates" && (
          <div className="mt-4 space-y-3">
            {data.candidates.length === 0 && <Empty>새로 확인할 반복 거래가 없어요.</Empty>}
            {data.candidates.map((c) => (
              <CandidateCard key={`${c.merchant_key}:${c.direction}`} c={c} onDone={reload} />
            ))}
          </div>
        )}
        {data && !error && tab === "registered" && (
          <div className="mt-4">
            {data.registered.length === 0 ? (
              <Empty>등록한 정기 거래가 없어요.</Empty>
            ) : (
              <ul className={`${card} divide-y divide-line overflow-hidden`}>
                {data.registered.map((r) => (
                  <li key={r.recurring_id}>
                    <button
                      type="button"
                      onClick={() => setEditing(r)}
                      className="flex min-h-11 w-full items-center justify-between gap-4 px-4 py-3 text-left hover:bg-porcelain"
                    >
                      <div className="min-w-0">
                        <p className="flex items-center gap-2">
                          <span className="truncate font-medium">{r.name}</span>
                          {r.status === "EXCLUDED" && <Chip>예상에서 제외</Chip>}
                          {r.status === "ACTIVE" && r.skip_month === currentYm() && <Chip>이번 달 건너뜀</Chip>}
                        </p>
                        <p className="text-sm text-slate">
                          매월 {r.day_of_month}일 · {r.category_label ?? "분류 없음"}
                        </p>
                      </div>
                      <span className={`shrink-0 font-semibold tabular-nums ${r.direction === "IN" ? "text-seal" : ""}`}>{signed(r)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <BottomSheet open={!!editing} title="정기 거래 수정" onClose={() => setEditing(null)}>
        {editing && (
          <EditRecurring
            key={editing.recurring_id}
            item={editing}
            month={month}
            onSaved={(updated) => {
              setEditing(updated);
              setData((d) => d && { ...d, registered: d.registered.map((r) => (r.recurring_id === updated.recurring_id ? updated : r)) });
            }}
          />
        )}
      </BottomSheet>
    </>
  );
}

function CandidateCard({ c, onDone }: { c: RecurringCandidate; onDone: () => void }) {
  const [busy, setBusy] = useState<"add" | "dismiss" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(kind: "add" | "dismiss") {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "add")
        await money.addRecurring({
          merchant_key: c.merchant_key, name: c.name, direction: c.direction, category: c.category, amount: c.amount, day_of_month: c.day_of_month,
        });
      else await money.dismissCandidate(c.merchant_key, c.name, c.direction);
      onDone();
    } catch (e) {
      setError(errMsg(e));
      setBusy(null);
    }
  }

  return (
    <article className={`${card} p-4`}>
      <p className="font-semibold">{c.pattern_confirmed ? "매달 반복되는 거래 같아요" : "반복 결제일 수 있어요 (아직 1번만 확인)"}</p>
      <p className="mt-1 tabular-nums">
        {c.name} · 매월 {c.day_of_month}일경 · {signed(c)}
      </p>
      {c.pattern_confirmed && (
        <p className="text-sm text-slate">
          최근 {c.months_observed}개월 동안 {c.occurrences}회 확인
        </p>
      )}
      <ErrorText message={error} />
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button type="button" disabled={!!busy} onClick={() => run("dismiss")} className={outlineBtn}>
          {busy === "dismiss" ? "처리 중…" : "반복 거래 아님"}
        </button>
        <Button type="button" busy={busy === "add"} disabled={!!busy} onClick={() => run("add")}>
          정기 거래로 등록
        </Button>
      </div>
    </article>
  );
}

function EditRecurring({ item, month, onSaved }: { item: RecurringItem; month: string; onSaved: (r: RecurringItem) => void }) {
  const [category, setCategory] = useState<Category | null>(item.category);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const ym = currentYm();
  const skipped = item.skip_month === ym;

  async function patch(what: string, body: RecurringUpdate) {
    setBusy(what);
    setError(null);
    setSaved(false);
    try {
      onSaved(await money.updateRecurring(item.recurring_id, body));
      if (what === "save") setSaved(true);
    } catch (e) {
      setError(errMsg(e));
    }
    setBusy(null);
  }

  function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    patch("save", {
      name: String(f.get("name")).trim(),
      category,
      day_of_month: Number(f.get("day")),
      amount: Number(f.get("amount")),
    });
  }

  return (
    <>
      <form onSubmit={submit} className="space-y-3">
        <Field label="이름" name="name" defaultValue={item.name} required maxLength={100} />
        <CategoryPicker value={category} onChange={setCategory} />
        <Field label="매월 며칠" name="day" type="number" inputMode="numeric" min={1} max={31} defaultValue={item.day_of_month} required />
        <MoneyField label={item.direction === "IN" ? "입금 금액" : "금액"} name="amount" defaultValue={item.amount} min={0} max={1_000_000_000} required />
        <Button busy={busy === "save"} disabled={!!busy}>
          저장
        </Button>
        {saved && (
          <p role="status" className="text-sm text-coral">
            저장했어요.
          </p>
        )}
      </form>

      <section className="mt-6">
        <h3 className="text-sm text-slate">예상 반영</h3>
        <div className="mt-2 grid grid-cols-2 gap-2" role="group" aria-label="예상 반영 여부">
          {(["ACTIVE", "EXCLUDED"] as const).map((st) => (
            <button
              key={st}
              type="button"
              aria-pressed={item.status === st}
              disabled={!!busy}
              onClick={() => item.status !== st && patch("status", { status: st })}
              className={`min-h-11 rounded-xl border px-2 text-sm font-medium disabled:opacity-50 ${
                item.status === st ? "border-coral bg-coral-soft text-coral" : "border-line"
              }`}
            >
              {st === "ACTIVE" ? "예상에 포함" : "앞으로 예상에서 제외"}
            </button>
          ))}
        </div>
        {item.status === "ACTIVE" &&
          (skipped ? (
            <p className="mt-2 flex min-h-11 items-center justify-between gap-2 rounded-xl bg-porcelain px-4 text-sm">
              <span>이번 달 건너뜀</span>
              <button
                type="button"
                disabled={!!busy}
                onClick={() => patch("skip", { clear_skip: true })}
                className="min-h-11 px-2 font-medium text-coral disabled:opacity-50"
              >
                되돌리기
              </button>
            </p>
          ) : (
            <button type="button" disabled={!!busy} onClick={() => patch("skip", { skip_month: ym })} className={`${outlineBtn} mt-2`}>
              이번 달만 건너뛰기
            </button>
          ))}
        <p className="mt-2 text-sm text-slate">
          예상에서 빼도 실제 구독이나 자동이체는 그대로예요. 여기서 바꾸는 내용은 돈 관리 분석에만 쓰여요.
        </p>
        <ErrorText message={error} />
      </section>

      <section className="mt-6">
        <h3 className="text-sm text-slate">연결된 거래</h3>
        <div className="mt-2">
          {item.transactions.length ? <TxnList items={item.transactions} month={month} /> : <Empty>아직 연결된 실제 거래가 없어요.</Empty>}
        </div>
      </section>
    </>
  );
}
