"use client";

import { useEffect, useRef, useState } from "react";
import { AccountSummary, KIND } from "@/lib/api";
import { accountKey } from "@/lib/home-prefs";
import { Star } from "./bits";

// 대표 계좌(별, 여러 개 가능)와 노출 순서(손잡이 끌기, 또는 손잡이에 포커스 후 ↑↓ 키)
export function AccountOrderSettings({
  accounts, // 사용자 순서대로
  reps,
  onStar,
  onReorder,
}: {
  accounts: AccountSummary[];
  reps: Set<string>;
  onStar: (key: string) => void; // 확인 모달은 부모가 띄운다
  onReorder: (order: string[]) => void;
}) {
  const keys = accounts.map(accountKey);
  const rows = useRef(new Map<string, HTMLLIElement>());
  const handles = useRef(new Map<string, HTMLButtonElement>());
  const [dragging, setDragging] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");

  const label = (k: string) => {
    const a = accounts.find((x) => accountKey(x) === k);
    return a ? (a.nickname ?? KIND[a.account_type]) : "";
  };

  function moveTo(key: string, to: number) {
    const from = keys.indexOf(key);
    if (from < 0 || to < 0 || to >= keys.length || to === from) return;
    const next = [...keys];
    next.splice(from, 1);
    next.splice(to, 0, key);
    onReorder(next);
    setAnnounce(`${label(key)}, ${to + 1}번째로 이동`);
  }

  // 순서가 바뀌면 DOM이 옮겨져 포커스가 빠질 수 있어, 키보드로 옮긴 손잡이에 다시 포커스한다
  useEffect(() => {
    if (focusKey) handles.current.get(focusKey)?.focus();
  }, [accounts, focusKey]);

  function onPointerMove(e: React.PointerEvent, key: string) {
    if (dragging !== key) return;
    // 끌고 있는 행을 뺀 나머지 중 포인터보다 위에 중심이 있는 행 수 = 새 위치
    const to = keys.filter((k) => {
      if (k === key) return false;
      const r = rows.current.get(k)?.getBoundingClientRect();
      return r ? r.top + r.height / 2 < e.clientY : false;
    }).length;
    moveTo(key, to);
  }

  return (
    <section aria-labelledby="order-title" className="rounded-3xl bg-paper p-5">
      <h2 id="order-title" className="font-semibold">
        대표 계좌 및 순서
      </h2>
      <p className="mt-1 text-sm text-slate">별을 누른 계좌가 홈의 카드로 보여요. 오른쪽 손잡이를 끌어 순서를 바꿔요.</p>
      <p aria-live="polite" className="sr-only">
        {announce}
      </p>
      <ul className="mt-3 space-y-2">
        {accounts.map((a) => {
          const key = accountKey(a);
          const isRep = reps.has(key);
          const name = a.nickname ?? `${KIND[a.account_type]} 계좌`;
          return (
            <li
              key={key}
              ref={(el) => {
                if (el) rows.current.set(key, el);
                else rows.current.delete(key);
              }}
              className={`flex items-center gap-1 rounded-2xl border px-3 py-1 transition-shadow motion-reduce:transition-none ${
                dragging === key ? "border-coral bg-coral-soft shadow-lg" : "border-line bg-paper"
              }`}
            >
              <div className="min-w-0 flex-1 py-2">
                <p className="truncate font-medium">{name}</p>
                <p className="text-sm text-slate tabular-nums">{a.account_num}</p>
              </div>
              <button
                type="button"
                onClick={() => onStar(key)}
                aria-pressed={isRep}
                aria-label={isRep ? `${name} 대표 계좌 해지` : `${name}을(를) 대표 계좌로 설정`}
                className="inline-flex size-11 shrink-0 items-center justify-center rounded-full hover:bg-porcelain"
              >
                <Star filled={isRep} className="size-6" />
              </button>
              <button
                type="button"
                ref={(el) => {
                  if (el) handles.current.set(key, el);
                  else handles.current.delete(key);
                }}
                aria-label={`${name} 순서 바꾸기. 위아래 화살표 키로 옮겨요`}
                aria-roledescription="순서 이동 손잡이"
                onPointerDown={(e) => {
                  e.preventDefault();
                  e.currentTarget.setPointerCapture(e.pointerId);
                  setDragging(key);
                  setFocusKey(null);
                }}
                onPointerMove={(e) => onPointerMove(e, key)}
                onPointerUp={() => {
                  if (dragging) setAnnounce(`${label(key)} 순서를 바꿨어요`);
                  setDragging(null);
                }}
                onPointerCancel={() => setDragging(null)}
                onKeyDown={(e) => {
                  const i = keys.indexOf(key);
                  if (e.key === "ArrowUp") moveTo(key, i - 1);
                  else if (e.key === "ArrowDown") moveTo(key, i + 1);
                  else return;
                  e.preventDefault();
                  setFocusKey(key);
                }}
                className={`inline-flex size-11 shrink-0 touch-none items-center justify-center rounded-xl text-slate ${
                  dragging === key ? "cursor-grabbing" : "cursor-grab"
                } hover:bg-porcelain focus-visible:outline-2 focus-visible:outline-coral`}
              >
                <svg viewBox="0 0 24 24" aria-hidden className="size-5 fill-none stroke-current stroke-2">
                  <path d="M5 8h14M5 12h14M5 16h14" strokeLinecap="round" />
                </svg>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
