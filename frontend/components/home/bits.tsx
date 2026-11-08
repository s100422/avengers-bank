"use client";

import { useState } from "react";
import { won } from "@/lib/api";

export const MASK = "••••••원";
export const money = (hidden: boolean, n: number) => (hidden ? MASK : won(n));

// 숨김/보기 작은 버튼. 터치 영역 44px.
export function HideToggle({ hidden, onToggle, what }: { hidden: boolean; onToggle: () => void; what: string }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={hidden ? `${what} 보기` : `${what} 숨기기`}
      aria-pressed={hidden}
      className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center rounded-full px-3 text-sm whitespace-nowrap text-slate hover:text-ink"
    >
      <span className="rounded-full border border-line bg-paper px-2.5 py-1">{hidden ? "보기" : "숨김"}</span>
    </button>
  );
}

export function Star({ filled, className = "size-5" }: { filled: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={`${className} ${filled ? "fill-coral stroke-coral" : "fill-none stroke-slate"} stroke-[1.8]`}>
      <path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" strokeLinejoin="round" />
    </svg>
  );
}

export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      aria-label={`계좌번호 ${text} 복사`}
      onClick={async (e) => {
        e.stopPropagation(); // 상세 화면 이동으로 번지지 않게
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          // 클립보드 권한이 없으면 조용히 넘어간다 (계좌번호는 화면에 보인다)
        }
      }}
      className="inline-flex min-h-11 min-w-11 items-center justify-center text-sm whitespace-nowrap text-coral"
    >
      <span aria-live="polite">{done ? "복사됨" : "복사"}</span>
    </button>
  );
}

export function Skeleton({ className }: { className: string }) {
  return <span aria-hidden className={`block animate-pulse rounded-lg bg-line/70 motion-reduce:animate-none ${className}`} />;
}
