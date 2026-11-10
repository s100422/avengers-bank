import { won } from "@/lib/api";
import type { PaceStatus } from "@/lib/money";

// 브라우저 기준 이번 달 "YYYY-MM"
export function currentMonth(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

// "2026-11" + (-1) → "2026-10"
export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split("-").map(Number);
  return currentMonth(new Date(y, m - 1 + delta, 1));
}

export const monthLabel = (month: string) => `${Number(month.slice(0, 4))}년 ${Number(month.slice(5, 7))}월`;

// "2026-11-15" → "11월 15일"
export const dayLabel = (date: string) => `${Number(date.slice(5, 7))}월 ${Number(date.slice(8, 10))}일`;

// 큰 금액은 만 원 단위로 반올림해 짧게: 1,482,000 → "148만 원". 만 원 미만은 그대로.
export function manwon(n: number): string {
  const abs = Math.abs(n);
  if (abs < 10_000) return won(n);
  return `${n < 0 ? "−" : ""}${Math.round(abs / 10_000).toLocaleString("ko-KR")}만 원`;
}

// 0.123 → 12
export const pct = (rate: number) => Math.round(Math.abs(rate) * 100);

export const STATUS_LABEL: Record<PaceStatus, string> = {
  HIGHER: "평소보다 많음",
  NORMAL: "평소 수준",
  LOWER: "평소보다 적음",
  UNKNOWN: "비교 데이터 부족",
};
