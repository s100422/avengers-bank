"use client";

import { useParams } from "next/navigation";
import { Shell } from "@/components/ui";
import { won } from "@/lib/api";
import { askAssistant } from "@/lib/ask-assistant";
import { CATEGORY_LABELS, money, type Category, type CategoryDetail } from "@/lib/money";
import { BackLink, Empty, LoadState, MonthNav, baselinePeriod, card, monthLabel, outlineBtn, useLoad, useMonth, withMonth } from "@/components/money/detail/common";
import { TxnList } from "@/components/money/detail/TxnRow";

export default function CategoryPage() {
  return (
    <Shell>
      <CategoryView />
    </Shell>
  );
}

function CategoryView() {
  const month = useMonth();
  const category = useParams<{ category: string }>().category as Category;
  const known = category in CATEGORY_LABELS;
  const { data, error, reload } = useLoad<CategoryDetail>(`${category}:${month}`, () => money.category(category, month));
  const label = data?.spend.label ?? (known ? CATEGORY_LABELS[category] : "항목");

  return (
    <>
      <BackLink fallback={withMonth("/money", month)} />
      <div className="mt-2 flex items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">{label}</h1>
        <MonthNav month={month} />
      </div>
      <LoadState error={known ? error : "없는 항목이에요."} loading={!data} onRetry={reload} />
      {data && !error && known && <Body d={data} month={month} label={label} />}
    </>
  );
}

function Body({ d, month, label }: { d: CategoryDetail; month: string; label: string }) {
  const s = d.spend;
  const max = Math.max(1, ...d.monthly.map((m) => m.amount));
  // 비교 막대: 선택한 달 바로 앞 달이 하나뿐이면 "지난달"로 부른다
  const barLabel = (m: string) => (m === d.month ? `${monthLabel(m)} (선택한 달)` : d.baseline.months === 1 ? `지난달 · ${monthLabel(m)}` : monthLabel(m));

  return (
    <>
      <section className="mt-6">
        <p className="text-sm text-slate">현재까지 {label} 사용액</p>
        <p className="text-4xl font-semibold tracking-tight tabular-nums">{won(s.actual)}</p>
        {s.diff === null ? (
          <p className="mt-2 text-slate">비교할 지난 기록이 없어요.</p>
        ) : (
          <p className="mt-2">
            평소 같은 시점보다{" "}
            <strong className={s.diff > 0 ? "text-coral" : ""}>
              {won(Math.abs(s.diff))} {s.diff >= 0 ? "많아요" : "적어요"}
            </strong>
          </p>
        )}
        {s.projected !== null && <p className="mt-1 text-sm text-slate">월말 예상 {won(s.projected)}</p>}
        <p className="mt-1 text-sm text-slate">비교 기간: {baselinePeriod(d.baseline)}</p>
      </section>

      <section className="mt-8">
        <h2 className="text-sm text-slate">월별 비교</h2>
        {d.monthly.length > 1 ? (
          <ul className={`${card} mt-3 space-y-3 p-4`}>
            {d.monthly.map((m) => (
              <li key={m.month}>
                <div className="flex justify-between gap-4 text-sm tabular-nums">
                  <span className={m.month === d.month ? "font-semibold" : "text-slate"}>{barLabel(m.month)}</span>
                  <span className="font-medium">{won(m.amount)}</span>
                </div>
                <div className="mt-1 h-2.5 rounded-full bg-porcelain" aria-hidden>
                  <div
                    className={`h-full rounded-full ${m.month === d.month ? "bg-coral" : "bg-slate/40"}`}
                    style={{ width: `${(m.amount / max) * 100}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-3">
            <Empty>비교할 지난 기록이 없어요.</Empty>
          </div>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-sm text-slate">사용처별 합계</h2>
        {d.merchants.length ? (
          <ul className={`${card} mt-3 divide-y divide-line`}>
            {d.merchants.map((m) => (
              <li key={m.merchant} className="flex items-center justify-between gap-4 px-4 py-3 tabular-nums">
                <span className="min-w-0 truncate font-medium">
                  {m.merchant} <span className="text-sm font-normal text-slate">{m.count}건</span>
                </span>
                <span className="shrink-0 font-semibold">{won(m.amount)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-3">
            <Empty>이번 달 사용처가 없어요.</Empty>
          </div>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-sm text-slate">거래 내역</h2>
        <div className="mt-3">
          {d.transactions.length ? <TxnList items={d.transactions} month={month} /> : <Empty>이번 달 {label} 거래가 없어요.</Empty>}
        </div>
      </section>

      <div className="mt-8">
        <button
          type="button"
          className={outlineBtn}
          onClick={() => askAssistant(`${monthLabel(month)} ${label} 지출이 왜 늘었지? 평소와 비교해서 어디서 더 썼는지 알려줘.`)}
        >
          왜 늘었지?
        </button>
      </div>
    </>
  );
}
