"use client";

import Link from "next/link";
import { AccountSummary, KIND } from "@/lib/api";
import { CopyButton, HideToggle, money } from "./bits";

// undefined: 불러오는 중, "error": 못 불러옴, 배열: 최근 이체 상대(최신순). bank_code ""는 우리 은행, 그 밖은 타행 코드
export type Recent = { name: string; account: string; bank_code: string; bank_name: string }[] | "error" | undefined;

export function AccountCard({
  account: a,
  hidden,
  onToggleHidden,
  recent,
}: {
  account: AccountSummary;
  hidden: boolean;
  onToggleHidden: () => void;
  recent: Recent;
}) {
  const name = a.nickname ?? `${KIND[a.account_type]} 계좌`;
  return (
    <article className="daily-card flex h-full flex-col p-5 sm:p-6">
      {/* 1. 이름 (상세로 이동) */}
      <Link href={`/accounts/${a.account_type}/${a.account_id}`} className="flex min-h-11 items-center gap-1.5 font-semibold">
        <span className="truncate">{name}</span>
        <svg viewBox="0 0 24 24" aria-hidden className="ml-auto size-4 shrink-0 fill-none stroke-slate stroke-2">
          <path d="m9 6 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </Link>

      {/* 2~3. 계좌번호 + 복사 */}
      <div className="-mt-2 flex items-center gap-1 text-sm text-slate tabular-nums">
        <span className="truncate">
          {KIND[a.account_type]} {a.account_num}
        </span>
        <CopyButton text={a.account_num} />
      </div>

      {/* 4~5. 잔액 + 숨김/보기 */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[26px] font-bold tracking-tight whitespace-nowrap tabular-nums">{money(hidden, a.balance)}</span>
        <HideToggle hidden={hidden} onToggle={onToggleHidden} what={`${name} 잔액`} />
      </div>

      {/* 6. 최근 이체 상대 (넘치면 줄바꿈 대신 가로로 민다) */}
      <div className="mt-3 min-w-0">
        <p className="text-xs text-slate">최근 이체한 분</p>
        {recent === undefined ? (
          <span aria-hidden className="mt-1.5 block h-7 w-32 animate-pulse rounded-full bg-line/70 motion-reduce:animate-none" />
        ) : recent === "error" ? (
          <p className="mt-1.5 text-sm text-slate">최근 이체 내역을 불러오지 못했어요</p>
        ) : recent.length === 0 ? (
          <p className="mt-1.5 text-sm text-slate">최근 이체 내역 없음</p>
        ) : (
          <ul className="mt-1.5 flex gap-1.5 overflow-x-auto pb-1 [scrollbar-width:none]" aria-label="최근 이체한 분 목록">
            {recent.map((r) => (
              <li key={`${r.bank_code}:${r.account}`} className="shrink-0">
                {/* 누르면 이 계좌에서 그 사람(은행·계좌)에게 보내는 이체 금액 화면 (C-068, 타행 포함 C-111) */}
                <Link
                  href={`/transfer?from=${a.account_id}&bank=${encodeURIComponent(r.bank_code)}&to=${encodeURIComponent(r.account)}`}
                  aria-label={`${r.name}님께 이체`}
                  className="inline-flex min-h-11 items-center"
                >
                  <span className="rounded-full bg-porcelain px-3 py-1 text-sm whitespace-nowrap hover:bg-coral-soft hover:text-coral">
                    {r.name}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 7. 이체 (입출금만) */}
      {a.account_type === "checking" && (
        <Link
          href="/transfer"
          className="mt-4 flex min-h-11 items-center justify-center rounded-xl border border-coral/30 bg-coral-soft/40 font-semibold text-coral hover:bg-coral-soft"
        >
          이체
        </Link>
      )}
    </article>
  );
}
