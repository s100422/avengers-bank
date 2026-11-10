"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Shell } from "@/components/ui";
import { won } from "@/lib/api";
import { askAssistant } from "@/lib/ask-assistant";
import { money, type CategorySpend, type Summary } from "@/lib/money";
import { BackLink, Chip, baselinePeriod, Empty, LoadState, MonthNav, card, monthLabel, outlineBtn, useLoad, useMonth, withMonth } from "@/components/money/detail/common";
import { ScheduleRow } from "@/components/money/detail/ScheduleRow";
import { TxnList } from "@/components/money/detail/TxnRow";

export default function AnalysisPage() {
  return (
    <Shell>
      <Analysis />
    </Shell>
  );
}

const pct = (r: number) => `${Math.round(Math.abs(r) * 100)}%`;

function Analysis() {
  const month = useMonth();
  const { data, error, reload } = useLoad<Summary>(month, () => money.summary(month));

  // 요약 탭이 #forecast / #pace로 연결한다. 내용이 그려진 뒤에 그 위치로 내린다
  useEffect(() => {
    if (data && location.hash) document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView();
  }, [data]);

  return (
    <>
      <BackLink fallback={withMonth("/money", month)} />
      <div className="mt-2 flex items-center justify-between gap-2">
        <h1 className="text-2xl font-bold">이번 달 분석</h1>
        <MonthNav month={month} />
      </div>
      <LoadState error={error} loading={!data} onRetry={reload} />
      {data && !error && <AnalysisBody s={data} month={month} />}
    </>
  );
}

function AnalysisBody({ s, month }: { s: Summary; month: string }) {
  const f = s.forecast;
  const [open, setOpen] = useState(false);
  const basis =
    f.variable_basis === "BASELINE"
      ? `최근 ${f.baseline.months}개월 평균 하루 변동지출 기준`
      : f.variable_basis === "THIS_MONTH"
        ? "이번 달 지금까지의 속도 기준"
        : "남은 변동지출을 추정할 기록이 없어요";
  const higher = s.categories.filter((c) => c.status === "HIGHER");
  const lower = s.categories.filter((c) => c.status === "LOWER");

  return (
    <>
      <section id="forecast" className="mt-6 scroll-mt-4">
        <p className="flex items-center gap-2 text-sm text-slate">
          {f.is_current_month ? "이번 달 예상 지출" : `${monthLabel(month)} 지출`}
          <Chip tone="coral">{f.is_current_month ? "예상" : "실제"}</Chip>
        </p>
        <p className="text-4xl font-semibold tracking-tight tabular-nums">{won(f.projected_total)}</p>
        {f.change_rate !== null && f.baseline.monthly_avg !== null && (
          <p className="mt-1 text-sm text-slate">
            평소 월평균 {won(f.baseline.monthly_avg)}보다 {pct(f.change_rate)} {f.change_rate >= 0 ? "많아요" : "적어요"}
          </p>
        )}

        <dl className={`${card} mt-4 divide-y divide-line tabular-nums`}>
          <div className="flex items-center justify-between gap-4 px-4 py-3">
            <dt>현재까지 실제 소비</dt>
            <dd className="font-semibold">{won(f.actual_to_date)}</dd>
          </div>
          <div>
            <dt>
              <button
                type="button"
                aria-expanded={open}
                aria-controls="remaining-recurring"
                onClick={() => setOpen((o) => !o)}
                className="flex min-h-11 w-full items-center justify-between gap-4 px-4 py-3 text-left hover:bg-porcelain"
              >
                <span>
                  + 남은 정기 지출 <span className="text-sm text-slate">({s.remaining_recurring_items.length}건 {open ? "접기" : "펼치기"})</span>
                </span>
                <span className="font-semibold">{won(f.remaining_recurring)}</span>
              </button>
            </dt>
            <dd id="remaining-recurring" hidden={!open}>
              {s.remaining_recurring_items.length ? (
                <ul className="divide-y divide-line border-t border-line bg-porcelain/50">
                  {s.remaining_recurring_items.map((i) => (
                    <ScheduleRow key={i.key} s={i} />
                  ))}
                </ul>
              ) : (
                <p className="border-t border-line px-4 py-3 text-sm text-slate">이번 달 남은 정기 지출이 없어요.</p>
              )}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-4 py-3">
            <dt>+ 남은 예상 변동지출</dt>
            <dd className="font-semibold">{won(f.remaining_variable)}</dd>
          </div>
        </dl>
        <ul className="mt-3 space-y-1 text-sm text-slate">
          <li>추정 근거: {basis}</li>
          <li>비교 기간: {baselinePeriod(f.baseline)}</li>
          <li>카드대금 출금은 이미 센 카드 결제와 겹치므로 더하지 않아요.</li>
        </ul>

        <h2 className="mt-8 text-sm text-slate">평소 추정에서 제외한 일회성 지출 (이번 달 합계에는 포함)</h2>
        <div className="mt-3">
          {s.one_off_transactions.length ? (
            <TxnList items={s.one_off_transactions} month={month} />
          ) : (
            <Empty>일회성으로 표시한 지출이 없어요.</Empty>
          )}
        </div>
      </section>

      <section id="pace" className="mt-10 scroll-mt-4">
        <h2 className="text-lg font-bold">평소와 비교</h2>
        <p className="mt-1 text-slate">
          {s.pace.status === "UNKNOWN" || s.pace.diff_rate === null
            ? "비교할 지난 기록이 없어요."
            : `${s.pace.today_day}일까지 평소 같은 시점보다 ${pct(s.pace.diff_rate)} ${s.pace.diff_rate >= 0 ? "많이" : "적게"} 썼어요.`}
        </p>

        {higher.length > 0 && <CategoryLinks title="평소보다 늘어난 항목" items={higher} month={month} />}
        {lower.length > 0 && <CategoryLinks title="평소보다 줄어든 항목" items={lower} month={month} />}

        <h3 className="mt-6 text-sm text-slate">항목별 실제 vs 평소 같은 시점</h3>
        {s.categories.length ? (
          <table className={`${card} mt-3 w-full overflow-hidden text-sm tabular-nums`}>
            <thead className="text-slate">
              <tr className="border-b border-line">
                <th scope="col" className="px-4 py-2 text-left font-normal">항목</th>
                <th scope="col" className="px-2 py-2 text-right font-normal">실제</th>
                <th scope="col" className="px-4 py-2 text-right font-normal">평소</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {s.categories.map((c) => (
                <tr key={c.category}>
                  <th scope="row" className="px-4 py-2.5 text-left font-medium">
                    <Link href={withMonth(`/money/categories/${c.category}`, month)} className="underline-offset-2 hover:underline">
                      {c.label}
                    </Link>
                  </th>
                  <td className="px-2 py-2.5 text-right">{won(c.actual)}</td>
                  <td className="px-4 py-2.5 text-right text-slate">{c.baseline_to_date === null ? "—" : won(c.baseline_to_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="mt-3">
            <Empty>이번 달 소비 기록이 없어요.</Empty>
          </div>
        )}
      </section>

      <div className="mt-8">
        <button
          type="button"
          className={outlineBtn}
          onClick={() => askAssistant(`${monthLabel(month)} 예상 지출 ${won(f.projected_total)}은 어떻게 계산된 거야? 평소보다 늘어난 이유도 알려줘.`)}
        >
          이 예상에 대해 물어보기
        </button>
      </div>
    </>
  );
}

function CategoryLinks({ title, items, month }: { title: string; items: CategorySpend[]; month: string }) {
  return (
    <>
      <h3 className="mt-6 text-sm text-slate">{title}</h3>
      <ul className={`${card} mt-3 divide-y divide-line`}>
        {items.map((c) => (
          <li key={c.category}>
            <Link
              href={withMonth(`/money/categories/${c.category}`, month)}
              className="flex min-h-11 items-center justify-between gap-4 px-4 py-3 tabular-nums hover:bg-porcelain"
            >
              <span className="font-medium">{c.label}</span>
              <span className={c.status === "HIGHER" ? "font-semibold text-coral" : "font-semibold"}>
                {c.diff === null ? won(c.actual) : `${c.diff >= 0 ? "+" : "-"}${won(Math.abs(c.diff))}`} ›
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
