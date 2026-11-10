"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, ErrorText, Field, MoneyField, Shell } from "@/components/ui";
import { ApiError, won } from "@/lib/api";
import { CATEGORY_LABELS, money, type Category, type Direction, type ScheduledItem } from "@/lib/money";
import { BottomSheet } from "@/components/money/detail/BottomSheet";
import { PICKABLE } from "@/components/money/detail/CategoryPicker";
import { BackLink, Empty, LoadState, MonthNav, card, dayLabel, outlineBtn, useLoad, useMonth, withMonth } from "@/components/money/detail/common";
import { ScheduleRow, scheduledAmount } from "@/components/money/detail/ScheduleRow";

export default function SchedulePage() {
  return (
    <Shell>
      <Schedule />
    </Shell>
  );
}

const FILTERS = [
  { key: "ALL", label: "전체" },
  { key: "OUT", label: "출금" },
  { key: "IN", label: "입금" },
] as const;

const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : "저장하지 못했어요. 잠시 후 다시 시도해 주세요.");

function Schedule() {
  const month = useMonth();
  const { data, error, reload } = useLoad<ScheduledItem[]>(month, () => money.schedule(month));
  const [filter, setFilter] = useState<"ALL" | Direction>("ALL");
  const [selected, setSelected] = useState<ScheduledItem | null>(null);
  const [adding, setAdding] = useState(false);

  const items = (data ?? []).filter((i) => filter === "ALL" || i.direction === filter);
  // 가까운 날짜부터 날짜별로 묶는다 (서버가 날짜순으로 준다)
  const groups = new Map<string, ScheduledItem[]>();
  for (const i of items) groups.set(i.date, [...(groups.get(i.date) ?? []), i]);

  return (
    <>
      <BackLink fallback={withMonth("/money", month)} />
      <div className="mt-2 flex items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">입출금 일정</h1>
        <MonthNav month={month} />
      </div>

      <div className="mt-4 flex gap-2" role="group" aria-label="입출금 구분">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
            className={`min-h-11 rounded-full border px-4 text-sm font-medium ${
              filter === f.key ? "border-coral bg-coral-soft text-coral" : "border-line bg-paper text-slate hover:text-ink"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <LoadState error={error} loading={!data} onRetry={reload} />
      {data && !error && (
        <div className="mt-4 space-y-5">
          {groups.size === 0 && <Empty>{filter === "ALL" ? "이번 달 남은 입출금 예정이 없어요." : "해당하는 예정 내역이 없어요."}</Empty>}
          {[...groups].map(([date, list]) => (
            <section key={date}>
              <h2 className="text-sm text-slate tabular-nums">{dayLabel(date)}</h2>
              <ul className={`${card} mt-2 divide-y divide-line overflow-hidden`}>
                {list.map((s) => (
                  <ScheduleRow key={s.key} s={s} showDate={false} onOpen={() => setSelected(s)} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      <div className="mt-8">
        <button type="button" className={outlineBtn} onClick={() => setAdding(true)}>
          + 정기 거래 추가
        </button>
      </div>

      <BottomSheet open={!!selected} title={selected?.name ?? ""} onClose={() => setSelected(null)}>
        {selected && (
          <SchedulePanel
            s={selected}
            month={month}
            onSaved={() => {
              setSelected(null);
              reload();
            }}
          />
        )}
      </BottomSheet>
      <BottomSheet open={adding} title="정기 거래 추가" onClose={() => setAdding(false)}>
        <AddRecurringForm
          onSaved={() => {
            setAdding(false);
            reload();
          }}
        />
      </BottomSheet>
    </>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <dt className="text-slate">{label}</dt>
      <dd className="text-right font-medium tabular-nums">{children}</dd>
    </div>
  );
}

const NOTE = "여기서 고치는 날짜·금액은 분석에 쓰는 예정 정보예요. 실제 자동이체·결제일·청구일은 바뀌지 않아요.";

function SchedulePanel({ s, month, onSaved }: { s: ScheduledItem; month: string; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const income = s.direction === "IN";

  if (s.kind === "CARD_BILL")
    return (
      <>
        <dl className="text-sm">
          <Row label="청구액">{won(s.amount)}</Row>
          <Row label="결제일">{dayLabel(s.date)}</Row>
          <Row label="결제 카드">{s.account_label ?? "—"}</Row>
        </dl>
        <p className="mt-2 text-sm text-slate">카드대금은 이미 센 카드 결제의 대금이라 지출 예상에 다시 더하지 않아요.</p>
        <BillLink cardId={s.card_id} />
      </>
    );

  async function save(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await money.updateRecurring(s.recurring_id!, { amount: Number(f.get("amount")), day_of_month: Number(f.get("day")) });
      onSaved();
    } catch (err) {
      setError(errMsg(err));
      setBusy(false);
    }
  }

  return (
    <>
      <dl className="text-sm">
        <Row label={income ? "예상 입금액" : "예상액"}>{scheduledAmount(s)}</Row>
        <Row label={income ? "예상 입금일" : "예상일"}>{dayLabel(s.date)}</Row>
        <Row label="추정 근거">등록한 정기 거래 · 매월 {Number(s.date.slice(8, 10))}일경</Row>
      </dl>
      <p className="mt-2 text-sm text-slate">{NOTE}</p>
      {editing ? (
        <form onSubmit={save} className="mt-4 space-y-3">
          <MoneyField label="금액" name="amount" defaultValue={s.amount} min={0} max={1_000_000_000} required autoFocus />
          <Field label="매월 며칠" name="day" type="number" inputMode="numeric" min={1} max={31} defaultValue={Number(s.date.slice(8, 10))} required />
          <ErrorText message={error} />
          <div className="flex gap-2">
            <button type="button" className={outlineBtn} onClick={() => setEditing(false)}>
              취소
            </button>
            <Button busy={busy}>저장</Button>
          </div>
        </form>
      ) : (
        <div className="mt-4 grid grid-cols-2 gap-2">
          <button type="button" className={outlineBtn} onClick={() => setEditing(true)}>
            이번 예정 수정
          </button>
          <Link href={withMonth("/money/recurring", month)} className={`${outlineBtn} flex items-center justify-center`}>
            정기 거래 관리
          </Link>
        </div>
      )}
    </>
  );
}

// 예정 항목에는 카드 id가 없어 카드 목록에서 끝 4자리("신용카드 ****1234")로 찾는다.
// shortcut: 끝 4자리가 같은 신용카드가 둘이면 첫 카드로 간다. 서버가 card_id를 주면 바로 링크하도록 바꾼다
function BillLink({ cardId }: { cardId: number | null }) {
  return (
    <Link href={cardId ? `/cards/credit/${cardId}` : "/accounts"} className={`${outlineBtn} mt-4 flex items-center justify-center`}>
      청구 내역 보기
    </Link>
  );
}

function AddRecurringForm({ onSaved }: { onSaved: () => void }) {
  const [direction, setDirection] = useState<Direction>("OUT");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await money.addRecurring({
        name: String(f.get("name")).trim(),
        direction,
        amount: Number(f.get("amount")),
        day_of_month: Number(f.get("day")),
        category: (f.get("category") as Category) || null,
      });
      onSaved();
    } catch (err) {
      setError(errMsg(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <Field label="이름" name="name" required maxLength={100} placeholder="예: 통신비, 월세, 급여" autoFocus />
      <fieldset>
        <legend className="mb-1 text-sm text-slate">구분</legend>
        <div className="grid grid-cols-2 gap-2">
          {(["OUT", "IN"] as const).map((d) => (
            <label
              key={d}
              className={`flex min-h-11 cursor-pointer items-center justify-center rounded-xl border text-sm has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-coral/40 ${
                direction === d ? "border-coral bg-coral-soft font-semibold text-coral" : "border-line"
              }`}
            >
              <input type="radio" name="direction" value={d} checked={direction === d} onChange={() => setDirection(d)} className="sr-only" />
              {d === "OUT" ? "출금" : "입금"}
            </label>
          ))}
        </div>
      </fieldset>
      <MoneyField label="금액" name="amount" min={0} max={1_000_000_000} required />
      <Field label="매월 며칠" name="day" type="number" inputMode="numeric" min={1} max={31} required />
      <label className="block">
        <span className="mb-1 block text-sm text-slate">분류 (선택)</span>
        <select name="category" defaultValue="" className="min-h-11 w-full rounded-xl border border-line bg-paper px-3 outline-none focus:border-coral">
          <option value="">선택 안 함</option>
          {PICKABLE.map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABELS[c]}
            </option>
          ))}
        </select>
      </label>
      <p className="text-sm text-slate">{NOTE}</p>
      <ErrorText message={error} />
      <Button busy={busy}>추가</Button>
    </form>
  );
}
