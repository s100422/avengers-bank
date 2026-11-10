import Link from "next/link";
import { won } from "@/lib/api";
import type { TxnItem } from "@/lib/money";
import { Chip, timeLabel, withMonth } from "./common";

/** 거래 한 줄. 누르면 공통 거래 상세로 간다 */
export function TxnRow({ t, month }: { t: TxnItem; month: string }) {
  return (
    <li>
      <Link
        href={withMonth(`/money/transactions/${t.source}/${t.source_id}`, month)}
        className="flex min-h-11 items-center justify-between gap-4 px-4 py-3 hover:bg-porcelain"
      >
        <div className="min-w-0">
          <p className="truncate font-medium">{t.merchant ?? "이름 없는 거래"}</p>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate tabular-nums">
            <span>{timeLabel(t.occurred_at)}</span>
            <span>{t.category_label ?? "미분류"}</span>
            {t.is_one_off && <Chip>일회성</Chip>}
          </p>
        </div>
        <p className={`shrink-0 font-semibold tabular-nums ${t.direction === "IN" ? "text-seal" : ""}`}>
          {t.direction === "IN" ? "+" : "-"}
          {won(t.amount)}
        </p>
      </Link>
    </li>
  );
}

export function TxnList({ items, month }: { items: TxnItem[]; month: string }) {
  return (
    <ul className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-paper">
      {items.map((t) => (
        <TxnRow key={`${t.source}:${t.source_id}`} t={t} month={month} />
      ))}
    </ul>
  );
}
