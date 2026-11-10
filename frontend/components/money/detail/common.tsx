"use client";

// 돈 관리 상세 화면들이 같이 쓰는 작은 조각: 선택한 월, 뒤로 가기, 불러오기 상태, 칩.
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import type { Baseline } from "@/lib/money";
import { Skeleton } from "@/components/home/bits";

const thisMonth = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }).slice(0, 7);

/** ?month=YYYY-MM (없거나 잘못되면 이번 달) */
export function useMonth(): string {
  const m = useSearchParams().get("month") ?? "";
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(m) ? m : thisMonth();
}

/** 링크마다 선택한 월을 붙여 화면을 옮겨도 월이 유지되게 한다 */
export const withMonth = (href: string, month: string) => {
  const [path, hash] = href.split("#");
  return `${path}${path.includes("?") ? "&" : "?"}month=${month}${hash ? `#${hash}` : ""}`;
};

/** "2026-11" → "2026년 11월" */
export const monthLabel = (m: string) => `${m.slice(0, 4)}년 ${Number(m.slice(5, 7))}월`;
/** "2026-11-14" → "11월 14일 (토)" */
export const dayLabel = (d: string) => {
  const date = new Date(`${d.slice(0, 10)}T00:00:00`);
  return `${date.getMonth() + 1}월 ${date.getDate()}일 (${"일월화수목금토"[date.getDay()]})`;
};
/** 거래 시각(ISO) → "11월 3일 14:05" (KST) */
export const timeLabel = (iso: string) =>
  new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });

const ymd = (d: string) => `${d.slice(0, 4)}.${Number(d.slice(5, 7))}.${Number(d.slice(8, 10))}`;
/** 비교 기간 설명: "2026.8.1 ~ 2026.10.31 (최근 3개월 평균)" / "비교 기간 없음" */
export function baselinePeriod(b: Baseline) {
  if (!b.months || !b.period_start || !b.period_end) return "비교 기간 없음";
  return `${ymd(b.period_start)} ~ ${ymd(b.period_end)} (${b.months === 1 ? "지난달 기준" : `최근 ${b.months}개월 평균`})`;
}

const shift =(m: string, n: number) => {
  const d = new Date(Number(m.slice(0, 4)), Number(m.slice(5, 7)) - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

/** 월 선택: 주소의 month만 바꾼다 (다른 쿼리·해시는 유지하지 않는다) */
export function MonthNav({ month }: { month: string }) {
  const router = useRouter();
  const path = usePathname();
  const go = (n: number) => router.replace(`${path}?month=${shift(month, n)}`, { scroll: false });
  const btn = "flex size-11 items-center justify-center rounded-full text-xl text-slate hover:bg-coral-soft hover:text-ink disabled:opacity-30";
  return (
    <div className="flex items-center gap-1">
      <button type="button" className={btn} onClick={() => go(-1)} aria-label="이전 달">‹</button>
      <span className="min-w-24 text-center font-semibold tabular-nums" aria-live="polite">{monthLabel(month)}</span>
      <button type="button" className={btn} onClick={() => go(1)} disabled={month >= thisMonth()} aria-label="다음 달">›</button>
    </div>
  );
}

/** 이전 화면으로. 바로 이 주소로 들어왔으면(기록 없음) fallback으로 간다 */
export function BackLink({ fallback, label = "돈 관리" }: { fallback: string; label?: string }) {
  const router = useRouter();
  return (
    <Link
      href={fallback}
      onClick={(e) => {
        if (window.history.length > 1) {
          e.preventDefault();
          router.back();
        }
      }}
      className="-ml-2 inline-flex min-h-11 items-center px-2 text-sm text-slate hover:text-ink"
    >
      ← {label}
    </Link>
  );
}

/** 불러오기 + 다시 시도. key가 바뀌면 다시 부른다 */
export function useLoad<T>(key: string, load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    load()
      .then((d) => {
        if (!live) return;
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (live) setError(e instanceof ApiError ? e.message : "정보를 불러오지 못했어요.");
      });
    return () => {
      live = false;
    };
  }, [key, n]); // eslint-disable-line react-hooks/exhaustive-deps -- load는 key로 결정된다
  const reload = () => {
    setError(null);
    setN((x) => x + 1);
  };
  return { data, setData, error, reload };
}

/** 오류·로딩 상태. 둘 다 아니면 null (화면이 내용을 그린다) */
export function LoadState({ error, loading, onRetry }: { error: string | null; loading: boolean; onRetry: () => void }) {
  if (error)
    return (
      <div role="alert" className="mt-6 rounded-2xl border border-line bg-paper px-5 py-8 text-center">
        <p className="text-seal">{error}</p>
        <button type="button" onClick={onRetry} className="mt-4 min-h-11 rounded-xl border border-line px-5 font-medium hover:border-coral">
          다시 시도
        </button>
      </div>
    );
  if (loading)
    return (
      <div className="mt-6 space-y-3" aria-busy="true" aria-label="불러오는 중">
        <Skeleton className="h-10 w-1/2" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  return null;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="rounded-xl border border-dashed border-line px-4 py-8 text-center text-slate">{children}</p>;
}

/** 확정/추정/예상 같은 작은 표시 */
export function Chip({ children, tone = "line" }: { children: React.ReactNode; tone?: "line" | "coral" }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${
        tone === "coral" ? "bg-coral-soft text-coral" : "border border-line text-slate"
      }`}
    >
      {children}
    </span>
  );
}

export const card = "rounded-2xl border border-line bg-paper";
export const outlineBtn = "min-h-11 w-full rounded-xl border border-line px-4 font-medium hover:border-coral disabled:opacity-50";
