import { won } from "@/lib/api";
import type { ScheduledItem } from "@/lib/money";
import { Chip, dayLabel } from "./common";

/** "-약 55,000원" — 추정 금액은 '약'을 붙인다 */
export const scheduledAmount = (s: ScheduledItem) =>
  `${s.direction === "IN" ? "+" : "-"}${s.status === "ESTIMATED" ? "약 " : ""}${won(s.amount)}`;

/** 입출금 예정 한 줄. onOpen이 있으면 눌러서 상세 패널을 연다 */
export function ScheduleRow({ s, onOpen, showDate = true }: { s: ScheduledItem; onOpen?: () => void; showDate?: boolean }) {
  const body = (
    <>
      <div className="min-w-0">
        <p className="flex items-center gap-2">
          <span className="truncate font-medium">{s.name}</span>
          <Chip tone={s.status === "CONFIRMED" ? "coral" : "line"}>{s.status === "CONFIRMED" ? "확정" : "추정"}</Chip>
        </p>
        <p className="truncate text-sm text-slate tabular-nums">
          {[showDate && dayLabel(s.date), s.account_label].filter(Boolean).join(" · ") || (s.direction === "IN" ? "입금 예정" : "출금 예정")}
        </p>
      </div>
      <p className={`shrink-0 font-semibold tabular-nums ${s.direction === "IN" ? "text-seal" : ""}`}>{scheduledAmount(s)}</p>
    </>
  );
  const cls = "flex min-h-11 w-full items-center justify-between gap-4 px-4 py-3 text-left";
  return (
    <li>
      {onOpen ? (
        <button type="button" onClick={onOpen} className={`${cls} hover:bg-porcelain`}>
          {body}
        </button>
      ) : (
        <div className={cls}>{body}</div>
      )}
    </li>
  );
}
