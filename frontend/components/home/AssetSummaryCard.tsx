"use client";

import { HideToggle, Skeleton, money } from "./bits";

export function AssetSummaryCard({
  total,
  count,
  hidden,
  onToggle,
}: {
  total: number | null; // null이면 불러오는 중
  count: number;
  hidden: boolean;
  onToggle: () => void;
}) {
  return (
    <section aria-labelledby="asset-title" className="daily-card daily-assets p-6 sm:p-8">
      <div className="flex items-center justify-between gap-2">
        <h2 id="asset-title" className="font-semibold">
          내 자산 현황
        </h2>
        {total !== null && <HideToggle hidden={hidden} onToggle={onToggle} what="총자산 금액" />}
      </div>
      {total === null ? (
        <div className="mt-2 space-y-2" aria-busy="true" aria-label="자산을 불러오는 중">
          <Skeleton className="h-10 w-48" />
          <Skeleton className="h-4 w-24" />
        </div>
      ) : (
        <>
          <p className="mt-1 text-[32px] leading-tight font-bold tracking-tight tabular-nums md:text-4xl">{money(hidden, total)}</p>
          <p className="mt-1 text-sm text-slate">활성 계좌 {count}개 합계</p>
        </>
      )}
    </section>
  );
}
