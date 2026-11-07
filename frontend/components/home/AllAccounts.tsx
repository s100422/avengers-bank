"use client";

import Link from "next/link";
import { useState } from "react";
import { AccountSummary, KIND } from "@/lib/api";
import { accountKey } from "@/lib/home-prefs";
import { HideToggle, Star, money } from "./bits";

// 펼친 목록의 그룹 순서는 고정: 입출금 → 적금 → 예금
const GROUP_ORDER: AccountSummary["account_type"][] = ["checking", "savings", "deposit"];

export function AllAccounts({
  accounts, // 사용자 순서대로 정렬된 활성 계좌
  total,
  hideTotal,
  hidden,
  reps,
  onToggleHidden,
}: {
  accounts: AccountSummary[];
  total: number;
  hideTotal: boolean;
  hidden: Set<string>;
  reps: Set<string>;
  onToggleHidden: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <section>
      <button
        type="button"
        aria-expanded={open}
        aria-controls="all-accounts"
        onClick={() => setOpen(!open)}
        className="flex min-h-11 w-full items-center justify-between rounded-2xl bg-paper px-5 py-3 font-semibold"
      >
        내 전체 계좌 보기
        <svg
          viewBox="0 0 24 24"
          aria-hidden
          className={`size-5 fill-none stroke-slate stroke-2 transition-transform duration-200 motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
        >
          <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {/* 높이 0 ↔ 내용 높이로 부드럽게 펼친다. 접혀 있을 땐 inert로 탭 이동·화면 읽기에서 뺀다 */}
      <div
        id="all-accounts"
        inert={!open}
        className={`grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
      >
        <div className="overflow-hidden">
          <div className="mt-2 rounded-2xl bg-paper p-5">
            <div className="flex items-baseline justify-between gap-3 border-b border-line pb-3">
              <span className="text-slate">총 잔액</span>
              <span className="text-xl font-bold whitespace-nowrap tabular-nums">{money(hideTotal, total)}</span>
            </div>
            {GROUP_ORDER.map((type) => {
              const items = accounts.filter((a) => a.account_type === type);
              if (items.length === 0) return null;
              return (
                <div key={type} className="mt-4">
                  <h3 className="text-sm text-slate">{KIND[type]}</h3>
                  <ul className="mt-1 divide-y divide-line">
                    {items.map((a) => {
                      const key = accountKey(a);
                      const isRep = reps.has(key);
                      return (
                        <li key={key} className="flex items-center gap-1">
                          <Link
                            href={`/accounts/${a.account_type}/${a.account_id}`}
                            className="flex min-h-11 min-w-0 flex-1 items-center justify-between gap-3 py-3"
                          >
                            <span className="min-w-0">
                              <span className="flex items-center gap-1 font-medium">
                                <span className="truncate">{a.nickname ?? `${KIND[type]} 계좌`}</span>
                                <span className="shrink-0 text-xs font-normal text-slate">{KIND[type]}</span>
                                {isRep && (
                                  <span className="flex shrink-0 items-center gap-0.5 text-xs font-semibold text-coral">
                                    <Star filled className="size-3.5" />
                                    대표
                                  </span>
                                )}
                              </span>
                              <span className="block text-xs whitespace-nowrap text-slate tabular-nums">{a.account_num}</span>
                            </span>
                            <span className="flex shrink-0 items-center gap-1">
                              <span className="font-semibold whitespace-nowrap tabular-nums">{money(hidden.has(key), a.balance)}</span>
                              <svg viewBox="0 0 24 24" aria-hidden className="size-4 fill-none stroke-slate stroke-2">
                                <path d="m9 6 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            </span>
                          </Link>
                          <HideToggle hidden={hidden.has(key)} onToggle={() => onToggleHidden(key)} what={`${a.nickname ?? KIND[type]} 잔액`} />
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
