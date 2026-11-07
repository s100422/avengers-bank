"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { token } from "@/lib/api";

export function Brand() {
  return (
    <Link href="/accounts" className="flex items-center gap-2 text-[17px] font-bold">
      <span className="seal size-7 text-[11px] tracking-tight">SP</span>
      스파이디뱅킹
    </Link>
  );
}

const icon = "size-6 fill-none stroke-current stroke-[1.6]";
const TABS = [
  {
    href: "/accounts",
    label: "홈",
    svg: <path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z" strokeLinejoin="round" />,
  },
  {
    href: "/transfer",
    label: "이체",
    svg: <path d="M4 8h14l-3.5-3.5M20 16H6l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />,
  },
  {
    href: "/products",
    label: "상품",
    svg: <path d="M4 7h16v12H4zM9 7V5h6v2M4 12h16" strokeLinejoin="round" />,
  },
  {
    href: "/me",
    label: "내 정보",
    svg: <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9a7 7 0 0 1 14 0" strokeLinecap="round" />,
  },
];

// 같은 메뉴를 폭에 따라 다르게 그린다: 휴대폰은 하단 탭, PC(md 이상)는 왼쪽 메뉴
function Nav() {
  const path = usePathname();
  // 계좌 상세(/accounts/...)는 홈 탭, 상품 가입(/open)은 상품 탭으로 본다
  const active = path.startsWith("/open") ? "/products" : path.startsWith("/cards") ? "/accounts" : TABS.find((t) => path.startsWith(t.href))?.href;
  return (
    <nav
      aria-label="주 메뉴"
      className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-paper pb-[env(safe-area-inset-bottom)] md:inset-y-0 md:right-auto md:w-60 md:border-t-0 md:border-r md:px-4 md:py-6"
    >
      <div className="mb-8 hidden px-3 md:block">
        <Brand />
      </div>
      <ul className="grid grid-cols-4 md:grid-cols-1 md:gap-1">
        {TABS.map((t) => {
          const on = t.href === active;
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                aria-current={on ? "page" : undefined}
                className={`flex flex-col items-center gap-0.5 py-2 text-xs md:flex-row md:gap-3 md:rounded-xl md:px-3 md:py-2.5 md:text-[15px] ${
                  on ? "font-semibold text-coral md:bg-coral-soft" : "text-slate hover:text-ink"
                }`}
              >
                <svg viewBox="0 0 24 24" className={icon} aria-hidden>
                  {t.svg}
                </svg>
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

// 로그인이 필요한 화면의 틀. 토큰이 없으면 로그인으로 보낸다.
// wide: 홈처럼 카드 격자를 쓰는 화면은 PC에서 넓게, 입력 화면은 읽기 좋은 폭으로 둔다.
export function Shell({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
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
    <>
      <div className="md:pl-60">
        <div className={`mx-auto w-full px-4 pb-28 md:px-10 md:pt-10 md:pb-16 ${wide ? "max-w-xl md:max-w-5xl" : "max-w-xl"}`}>
          <header className="py-5 md:hidden">
            <Brand />
          </header>
          {children}
        </div>
      </div>
      <Nav />
    </>
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
        className="w-full rounded-xl border border-line bg-paper px-3 py-2.5 outline-none focus:border-coral focus-visible:ring-2 focus-visible:ring-coral/20"
      />
    </label>
  );
}

export function Button({ busy, children, ...props }: { busy?: boolean } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      disabled={busy || props.disabled}
      className="w-full rounded-xl bg-coral px-4 py-3 font-medium text-paper disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-coral"
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
