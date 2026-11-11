"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { DailyBanner } from "@/components/DailyDesign";
import { Skeleton } from "@/components/home/bits";
import { CategoryList, ForecastCard, PaceCard, RecurringEntry, ReviewBanner, UpcomingCard } from "@/components/money/summary/sections";
import { currentMonth, monthLabel, shiftMonth } from "@/components/money/summary/format";
import { Shell } from "@/components/ui";
import { askAssistant } from "@/lib/ask-assistant";
import { useFreshOnLeave } from "@/lib/fresh";
import { money, type Summary } from "@/lib/money";

export default function MoneyPage() {
  return (
    <Shell>
      {/* useSearchParams는 프리렌더 중 멈출 수 있어 Suspense로 감싼다 (cacheComponents) */}
      <Suspense fallback={null}>
        <MoneyHome />
      </Suspense>
    </Shell>
  );
}

function MoneyHome() {
  const router = useRouter();
  const now = currentMonth();
  const param = useSearchParams().get("month") ?? "";
  // 잘못된 값이나 미래 달은 이번 달로 본다
  const month = /^\d{4}-(0[1-9]|1[0-2])$/.test(param) && param <= now ? param : now;
  const [tries, setTries] = useState(0);
  const visit = useFreshOnLeave();
  const go = (m: string) => router.replace(`/money?month=${m}`, { scroll: false });

  return (
    <div className="daily-money space-y-5">
      <MonthHeader month={month} canNext={month < now} onPrev={() => go(shiftMonth(month, -1))} onNext={() => go(shiftMonth(month, 1))} />
      {/* 월·재시도·재방문마다 새로 불러온다 */}
      <SummaryView key={`${month}-${tries}-${visit}`} month={month} onRetry={() => setTries((t) => t + 1)} />
    </div>
  );
}

function MonthHeader({ month, canNext, onPrev, onNext }: { month: string; canNext: boolean; onPrev: () => void; onNext: () => void }) {
  const arrow = "flex size-11 items-center justify-center rounded-full text-ink hover:bg-coral-soft disabled:text-line disabled:hover:bg-transparent";
  return (
    <div className="flex items-center justify-between gap-2">
      <h1 className="text-2xl font-bold">돈 관리</h1>
      <div className="flex items-center">
        <button type="button" onClick={onPrev} aria-label="이전 달" className={arrow}>
          <svg viewBox="0 0 24 24" aria-hidden className="size-5 fill-none stroke-current stroke-2"><path d="m15 6-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
        <span className="min-w-24 text-center font-semibold tabular-nums" aria-live="polite">{monthLabel(month)}</span>
        <button type="button" onClick={onNext} disabled={!canNext} aria-label="다음 달" className={arrow}>
          <svg viewBox="0 0 24 24" aria-hidden className="size-5 fill-none stroke-current stroke-2"><path d="m9 6 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
      </div>
    </div>
  );
}

function SummaryView({ month, onRetry }: { month: string; onRetry: () => void }) {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    money.summary(month).then(setData).catch((e: Error) => setError(e.message || "불러오지 못했어요."));
  }, [month]);

  if (error)
    return (
      <div role="alert" className="rounded-3xl bg-paper p-6 text-center">
        <p className="font-medium">돈 관리 정보를 불러오지 못했어요</p>
        <p className="mt-1 text-sm text-slate">{error}</p>
        <button type="button" onClick={onRetry} className="mt-4 inline-flex min-h-11 items-center rounded-xl bg-coral px-5 font-medium text-paper">
          다시 시도
        </button>
      </div>
    );

  if (!data)
    return (
      <div className="space-y-4" aria-busy="true" aria-label="불러오는 중">
        <Skeleton className="h-36 w-full rounded-3xl" />
        <Skeleton className="h-60 w-full rounded-3xl" />
        <Skeleton className="h-40 w-full rounded-3xl" />
      </div>
    );

  const { forecast, pace } = data;
  const current = forecast.is_current_month;
  const empty = forecast.actual_to_date === 0 && forecast.projected_total === 0 && data.categories.length === 0;
  const label = monthLabel(month);
  const higher = pace.status === "HIGHER";
  const time = new Date(data.refreshed_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" });

  return (
    <>
      <p className="-mt-2 text-xs text-slate tabular-nums">{time} 기준</p>
      {data.review_count > 0 && <ReviewBanner count={data.review_count} />}

      {empty ? (
        <div className="rounded-3xl bg-paper p-6 text-center">
          <p className="font-medium">{label}에는 아직 소비 내역이 없어요</p>
          <p className="mt-1 text-sm text-slate">카드나 계좌로 결제하면 여기에서 분석해 드려요.</p>
        </div>
      ) : (
        <>
          <DailyBanner money />
          <div className="daily-money-overview">
            <ForecastCard month={month} forecast={forecast} />
            <PaceCard month={month} pace={pace} current={current} />
          </div>
          <button
            type="button"
            onClick={() => askAssistant(higher ? `${label} 소비가 평소보다 왜 늘었는지 알려줘` : `${label} 소비를 요약해서 알려줘`)}
            className="daily-ask flex min-h-12 w-full items-center justify-center gap-1.5 rounded-2xl border border-coral/20 bg-coral-soft/50 px-4 text-sm font-semibold text-coral hover:bg-coral-soft"
          >
            {higher ? "왜 늘었지?" : "이번 달 소비 물어보기"}
          </button>
        </>
      )}

      <div className={empty ? "" : "daily-money-details"}>
        <div className="grid min-w-0 gap-3">
          <UpcomingCard month={month} items={data.upcoming.slice(0, 3)} total={data.upcoming_total} />
          <RecurringEntry reviewCount={data.review_count} />
        </div>
        {!empty && <CategoryList month={month} items={data.categories} current={current} />}
      </div>
    </>
  );
}
