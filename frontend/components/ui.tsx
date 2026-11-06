"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { token } from "@/lib/api";

export function Brand() {
  return (
    <Link href="/accounts" className="flex items-center gap-2 font-semibold">
      <span className="seal size-7 text-sm">어</span>
      어벤져스은행
    </Link>
  );
}

// 로그인이 필요한 화면의 틀. 토큰이 없으면 로그인으로 보낸다.
export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!token.get()) router.replace("/login");
    // localStorage는 브라우저에서만 읽을 수 있어서 마운트 뒤에 확인한다
    // eslint-disable-next-line react-hooks/set-state-in-effect
    else setReady(true);
  }, [router]);

  if (!ready) return null;
  return (
    <div className="mx-auto w-full max-w-xl px-4 pb-16">
      <header className="flex items-center justify-between py-5">
        <Brand />
        <button
          className="text-sm text-slate hover:text-ink"
          onClick={() => {
            token.clear();
            router.replace("/login");
          }}
        >
          로그아웃
        </button>
      </header>
      {children}
    </div>
  );
}

export function Field({
  label,
  ...props
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm text-slate">{label}</span>
      <input
        {...props}
        className="w-full rounded-md border border-line bg-paper px-3 py-2.5 outline-none focus:border-ink focus-visible:ring-2 focus-visible:ring-ink/20"
      />
    </label>
  );
}

export function Button({ busy, children, ...props }: { busy?: boolean } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      disabled={busy || props.disabled}
      className="w-full rounded-md bg-ink px-4 py-3 font-medium text-paper disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ink"
    >
      {busy ? "처리 중…" : children}
    </button>
  );
}

export function ErrorText({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="text-sm text-seal">
      {message}
    </p>
  );
}
