"use client";

import { useRef, useState } from "react";
import { AccountSummary, KIND } from "@/lib/api";
import { accountKey } from "@/lib/home-prefs";
import { AccountCard, Recent } from "./AccountCard";

// 가로로 밀어 보는 계좌 카드. 터치·트랙패드는 스크롤로, 마우스는 아래 점·화살표로 넘긴다.
export function AccountCarousel({
  accounts, // 대표 계좌들, 사용자 순서대로
  hidden,
  onToggleHidden,
  recent,
}: {
  accounts: AccountSummary[];
  hidden: Set<string>;
  onToggleHidden: (key: string) => void;
  recent: Record<string, Recent>;
}) {
  const track = useRef<HTMLUListElement>(null);
  const [index, setIndex] = useState(0);

  // 카드 한 장이 차지하는 가로 폭 (카드 폭 + gap-3)
  const step = () => ((track.current?.children[0] as HTMLElement | undefined)?.offsetWidth ?? 0) + 12;

  function onScroll() {
    const el = track.current;
    if (!el || step() <= 12) return;
    // 맨 끝까지 밀면 마지막 카드로 본다 (PC에서 여러 장이 한 번에 보일 때)
    const atEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 2;
    setIndex(atEnd ? accounts.length - 1 : Math.min(accounts.length - 1, Math.round(el.scrollLeft / step())));
  }

  function go(i: number) {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    track.current?.scrollTo({ left: i * step(), behavior: reduce ? "auto" : "smooth" });
    setIndex(i); // 스크롤이 끝나기 전에도 누른 점을 바로 표시
  }

  return (
    <section aria-roledescription="carousel" aria-label="내 계좌 카드">
      <ul
        ref={track}
        onScroll={onScroll}
        className="-mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden md:mx-0 md:scroll-px-0 md:px-0"
      >
        {accounts.map((a, i) => {
          const key = accountKey(a);
          return (
            <li
              key={key}
              aria-roledescription="slide"
              aria-label={`${i + 1} / ${accounts.length}: ${a.nickname ?? KIND[a.account_type]}`}
              className={`shrink-0 snap-start md:w-full ${accounts.length === 1 ? "w-full" : "w-[86%]"}`}
            >
              <AccountCard
                account={a}
                hidden={hidden.has(key)}
                onToggleHidden={() => onToggleHidden(key)}
                recent={recent[key]}
              />
            </li>
          );
        })}
      </ul>

      {accounts.length > 1 && (
        <div className="mt-1 flex items-center justify-center">
          <button
            type="button"
            aria-label="이전 계좌"
            onClick={() => go(Math.max(0, index - 1))}
            disabled={index === 0}
            className="hidden min-h-11 min-w-11 items-center justify-center text-slate disabled:opacity-30 md:inline-flex"
          >
            ‹
          </button>
          {accounts.map((a, i) => (
            <button
              key={accountKey(a)}
              type="button"
              aria-label={`${i + 1}번째 계좌 보기`}
              aria-current={i === index}
              onClick={() => go(i)}
              className="inline-flex size-11 items-center justify-center"
            >
              <span className={`block h-2 rounded-full transition-all motion-reduce:transition-none ${i === index ? "w-5 bg-coral" : "w-2 bg-line"}`} />
            </button>
          ))}
          <button
            type="button"
            aria-label="다음 계좌"
            onClick={() => go(Math.min(accounts.length - 1, index + 1))}
            disabled={index === accounts.length - 1}
            className="hidden min-h-11 min-w-11 items-center justify-center text-slate disabled:opacity-30 md:inline-flex"
          >
            ›
          </button>
        </div>
      )}
    </section>
  );
}
