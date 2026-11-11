"use client";

import Link from "next/link";
import { useState } from "react";
import { won } from "@/lib/api";
import type { CategorySpend, Forecast, Pace, PaceStatus, ScheduledItem } from "@/lib/money";
import { PaceBars } from "./PaceChart";
import { STATUS_LABEL, dayLabel, manwon, pct } from "./format";

const card = "block rounded-3xl bg-paper p-5";
const q = (month: string) => `?month=${month}`;

export function StatusChip({ status }: { status: PaceStatus }) {
  const tone = { HIGHER: "bg-coral-soft text-coral", NORMAL: "bg-porcelain text-ink", LOWER: "bg-porcelain text-ink", UNKNOWN: "bg-porcelain text-slate" }[status];
  return <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${tone}`}>{STATUS_LABEL[status]}</span>;
}

function Chevron() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className="size-5 shrink-0 fill-none stroke-slate stroke-[1.8]">
      <path d="m9 6 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ② 이번 달 예상 지출 (지난 달이면 그 달의 실제 합계)
export function ForecastCard({ month, forecast: f }: { month: string; forecast: Forecast }) {
  const { months, monthly_avg } = f.baseline;
  const basis = months === 1 ? `지난달 ${manwon(monthly_avg ?? 0)}` : `최근 ${months}개월 월평균 ${manwon(monthly_avg ?? 0)}`;
  let compare = "비교할 지난 기록이 아직 없어요";
  if (months > 0) {
    const r = f.change_rate;
    const same = r === null || pct(r) === 0;
    compare = f.is_current_month
      ? same ? `${basis}과 비슷할 것으로 예상돼요` : `${basis}보다 약 ${pct(r)}% ${r > 0 ? "많을" : "적을"} 것으로 예상돼요`
      : same ? `${basis}과 비슷했어요` : `${basis}보다 ${pct(r)}% ${r > 0 ? "많았어요" : "적었어요"}`;
  }
  return (
    <Link href={`/money/analysis${q(month)}#forecast`} className={card}>
      <div className="flex items-center justify-between">
        <h2 className="text-sm text-slate">{f.is_current_month ? "이번 달 예상 지출" : "이 달 지출"}</h2>
        <Chevron />
      </div>
      <p className="mt-1 flex items-center gap-2 text-3xl font-bold tracking-tight tabular-nums">
        {f.is_current_month && <span className="rounded-full bg-coral-soft px-2 py-0.5 text-xs font-semibold text-coral">예상</span>}
        {f.is_current_month ? `약 ${manwon(f.projected_total)}` : won(f.actual_to_date)}
      </p>
      {f.is_current_month && (
        <p className="mt-2 text-sm text-slate tabular-nums">
          현재까지 <span className="font-semibold text-ink">{manwon(f.actual_to_date)}</span> · 남은 예상{" "}
          {manwon(f.remaining_recurring + f.remaining_variable)}
        </p>
      )}
      <p className="mt-1 text-sm">{compare}</p>
    </Link>
  );
}

// ③ 평소와 비교: 같은 일자까지의 누적 소비 비교 + 그래프
export function PaceCard({ month, pace, current }: { month: string; pace: Pace; current: boolean }) {
  const r = pace.diff_rate;
  const sentence =
    r === null
      ? "비교할 지난 기록이 아직 없어요"
      : current
        ? pct(r) === 0 ? "오늘까지 소비는 평소 같은 시점과 비슷해요" : `오늘까지 소비는 평소 같은 시점보다 ${pct(r)}% ${r > 0 ? "많아요" : "적어요"}`
        : pct(r) === 0 ? "이 달 소비는 평소와 비슷했어요" : `이 달 소비는 평소보다 ${pct(r)}% ${r > 0 ? "많았어요" : "적었어요"}`;
  return (
    <Link href={`/money/analysis${q(month)}#pace`} className={card}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm text-slate">평소와 비교</h2>
        <span className="flex items-center gap-1">
          <StatusChip status={pace.status} />
          <Chevron />
        </span>
      </div>
      <p className="mt-2 font-semibold">{sentence}</p>
      <PaceBars pace={pace} current={current} />
      {current && r !== null && (
        <p className="mt-3 text-xs text-slate">
          같은 날짜까지 쓴 돈끼리 비교해요. 주별 흐름과 월말 예상은 눌러서 볼 수 있어요.
        </p>
      )}
    </Link>
  );
}

// ④ 다가오는 입출금 (가까운 3건)
export function UpcomingCard({ month, items, total }: { month: string; items: ScheduledItem[]; total: number }) {
  return (
    <section className={card}>
      <h2 className="text-sm text-slate">다가오는 입출금</h2>
      {items.length === 0 ? (
        <p className="mt-3 text-sm text-slate">이번 달 남은 입출금 일정이 없어요.</p>
      ) : (
        <ul className="mt-2 divide-y divide-line">
          {items.map((s) => (
            <li key={s.key} className="flex min-h-11 items-center justify-between gap-3 py-3">
              <div className="min-w-0">
                <p className="text-xs text-slate">{dayLabel(s.date)}</p>
                <p className="truncate font-medium">{s.name}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className={`font-semibold tabular-nums ${s.direction === "IN" ? "text-coral" : ""}`}>
                  {s.status === "ESTIMATED" && "약 "}
                  {s.direction === "IN" ? "+" : "−"}
                  {won(s.amount)}
                </p>
                <p className="text-xs text-slate">{s.status === "CONFIRMED" ? "확정 청구" : "반복 거래 추정"}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-slate">카드대금은 계좌 출금 일정이에요. 이미 카드 소비에 포함돼 있어 지출에 다시 더하지 않아요.</p>
      {total > 0 && (
        <Link href={`/money/schedule${q(month)}`} className="mt-2 flex min-h-11 items-center justify-center text-sm font-medium text-coral">
          전체 일정 보기 ({total}건)
        </Link>
      )}
    </section>
  );
}

// 항목 한 줄: 이름·금액 + 막대. 막대 = 쓴 돈, 세로 눈금 = 평소 같은 시점. 모든 줄이 같은 눈금(max)을 쓴다
function CategoryRow({ c, month, max, usualLabel }: { c: CategorySpend; month: string; max: number; usualLabel: string }) {
  const higher = c.status === "HIGHER";
  const usual = c.baseline_to_date;
  const note =
    usual === null ? null
    : higher ? `${usualLabel} ${won(usual)}보다 ${won(c.actual - usual)} 많아요`
    : c.status === "LOWER" ? `${usualLabel} ${won(usual)}보다 적어요`
    : null;
  return (
    <li>
      <Link href={`/money/categories/${c.category}${q(month)}`} className="block min-h-11 px-5 py-3.5">
        <div className="flex items-baseline justify-between gap-3">
          <p className="flex min-w-0 flex-wrap items-center gap-2 font-semibold">
            {c.label}
            {higher && <StatusChip status="HIGHER" />}
          </p>
          <p className="shrink-0 font-semibold tabular-nums">{won(c.actual)}</p>
        </div>
        <div aria-hidden className="relative mt-2 h-2.5 rounded-sm bg-porcelain">
          <div
            className={`h-2.5 rounded-r-[4px] ${higher ? "bg-coral" : "bg-slate"} ${c.actual > 0 ? "min-w-[2px]" : ""}`}
            style={{ width: `${(c.actual / max) * 100}%` }}
          />
          {usual !== null && usual > 0 && (
            <span className="absolute -top-1 h-[18px] w-[2px] rounded-full bg-ink ring-2 ring-paper" style={{ left: `calc(${(usual / max) * 100}% - 1px)` }} />
          )}
        </div>
        {note && <p className="mt-1.5 text-xs text-slate tabular-nums">{note}</p>}
      </Link>
    </li>
  );
}

// ⑤ 항목별 소비: 늘어난 항목을 먼저, 나머지는 금액 큰 순. 안 쓴 항목은 접고, 미분류는 '분류하기'로 따로 뺀다
export function CategoryList({ month, items, current }: { month: string; items: CategorySpend[]; current: boolean }) {
  const [all, setAll] = useState(false);
  const usualLabel = current ? "평소 같은 시점" : "평소";
  const unclassified = items.find((c) => c.category === "UNCLASSIFIED" && c.actual > 0);
  const rest = items.filter((c) => c.category !== "UNCLASSIFIED");
  const byAmount = (a: CategorySpend, b: CategorySpend) => b.actual - a.actual;
  const higher = rest.filter((c) => c.status === "HIGHER").sort(byAmount);
  const others = rest.filter((c) => c.status !== "HIGHER" && c.actual > 0).sort(byAmount);
  const unused = rest.filter((c) => c.status !== "HIGHER" && c.actual === 0);
  const max = Math.max(1, ...rest.map((c) => Math.max(c.actual, c.baseline_to_date ?? 0)));
  const hasUsual = rest.some((c) => c.baseline_to_date !== null);
  const list = "mt-2 divide-y divide-line rounded-3xl bg-paper";
  const row = (c: CategorySpend) => <CategoryRow key={c.category} c={c} month={month} max={max} usualLabel={usualLabel} />;

  if (items.length === 0) {
    return (
      <section>
        <h2 className="text-sm text-slate">항목별 소비</h2>
        <p className="mt-3 rounded-3xl bg-paper p-5 text-sm text-slate">이 달 소비 내역이 없어요.</p>
      </section>
    );
  }
  return (
    <section>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h2 className="text-sm text-slate">항목별 소비</h2>
        {hasUsual && (
          <p className="flex items-center gap-1.5 text-xs text-slate">
            막대 = {current ? "오늘까지 쓴 돈" : "이 달 쓴 돈"} ·
            <i aria-hidden className="inline-block h-3 w-[2px] rounded-full bg-ink" /> = {usualLabel}
          </p>
        )}
      </div>

      {higher.length > 0 && (
        <>
          <h3 className="mt-3 text-sm font-semibold">평소보다 늘어난 항목</h3>
          <ul className={list}>{higher.map(row)}</ul>
        </>
      )}
      {(others.length > 0 || (all && unused.length > 0)) && (
        <>
          {higher.length > 0 && <h3 className="mt-5 text-sm font-semibold">그 밖의 항목</h3>}
          <ul className={higher.length > 0 ? list : `${list} mt-3`}>
            {others.map(row)}
            {all && unused.map(row)}
          </ul>
        </>
      )}
      {unused.length > 0 && (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-expanded={all}
          className="mt-1 flex min-h-11 w-full items-center justify-center text-sm font-medium text-coral"
        >
          {all ? "접기" : `이번 달 쓰지 않은 항목 ${unused.length}개 보기`}
        </button>
      )}

      {unclassified && (
        <Link
          href={`/money/categories/UNCLASSIFIED${q(month)}`}
          className="mt-3 flex min-h-11 items-center justify-between gap-3 rounded-2xl border border-line bg-paper px-5 py-3 text-sm"
        >
          <span>
            분류가 필요한 거래 <span className="font-semibold tabular-nums">{won(unclassified.actual)}</span>
          </span>
          <span className="shrink-0 font-semibold text-coral">분류하기</span>
        </Link>
      )}
    </section>
  );
}

// ⑥ 반복 거래 관리 진입
export function RecurringEntry({ reviewCount }: { reviewCount: number }) {
  return (
    <Link href="/money/recurring" className="flex min-h-11 items-center justify-between gap-3 rounded-2xl bg-paper px-5 py-4">
      <div>
        <p className="font-semibold">반복 거래 관리</p>
        <p className="text-sm text-slate">
          {reviewCount > 0 ? `확인이 필요한 거래 ${reviewCount}건` : "자동으로 찾은 정기 거래를 확인·수정해요"}
        </p>
      </div>
      <Chevron />
    </Link>
  );
}

export function ReviewBanner({ count }: { count: number }) {
  return (
    <Link
      href="/money/recurring"
      className="flex min-h-11 items-center justify-between gap-3 rounded-2xl border border-[#f4d9cd] bg-coral-soft/60 px-4 py-2.5 text-sm"
    >
      <span>확인이 필요한 거래가 {count}건 있어요</span>
      <span className="shrink-0 font-semibold text-coral">확인하기</span>
    </Link>
  );
}
