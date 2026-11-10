"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { SESSION_KEY, expireSession, expiring, logout, refreshSession, session } from "@/lib/api";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { SpiderMascot } from "@/components/SpiderMascot";

export function Brand() {
  return (
    <Link href="/accounts" className="flex items-center gap-2 text-[17px] font-bold">
      <SpiderMascot className="size-8 shrink-0 text-coral" />
      <span><span className="font-bold">Spider</span><span className="font-normal">Bank</span></span>
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

// 로그인이 필요한 화면의 틀. 갱신 토큰이 없으면 로그인으로 보낸다.
// 모든 화면이 같은 폭(max-w-xl)으로 가운데에 놓인다. 화면마다 폭이 달라 UI가 흔들리던 것을 막기 위해 하나로 맞췄다.
export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!session.active()) router.replace("/login");
    // localStorage는 브라우저에서만 읽을 수 있어서 마운트 뒤에 확인한다
    // eslint-disable-next-line react-hooks/set-state-in-effect
    else setReady(true);
  }, [router]);

  if (!ready) return null;
  return (
    <>
      <div className="md:pl-60">
        <div className="mx-auto w-full max-w-xl px-4 pb-28 md:px-10 md:pt-10 md:pb-16">
          <header className="flex items-center justify-between gap-3 py-5 md:justify-end md:pt-0">
            <span className="md:hidden">
              <Brand />
            </span>
            <div className="flex items-center gap-1"><NotificationBell /><SessionTimer /></div>
          </header>
          {children}
        </div>
      </div>
      <Nav />
    </>
  );
}

const WARN_MS = 2 * 60 * 1000;
export const mmss = (ms: number) => {
  const sec = Math.max(0, Math.ceil(ms / 1000));
  return `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
};

// 세션(갱신 토큰) 만료까지 남은 시간. 만료 시각은 매번 저장소에서 읽으므로
// 자동 갱신·비밀번호 변경·다른 탭의 연장이 그대로 반영된다(다른 탭은 storage 이벤트로 바로 다시 그린다).
function SessionTimer() {
  const router = useRouter();
  const [now, setNow] = useState(Date.now);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();
  const left = session.expiresAt() - now;
  const active = session.active();

  useEffect(() => {
    const tick = () => setNow(Date.now());
    const id = setInterval(tick, 1000);
    const onStorage = (e: StorageEvent) => (e.key === SESSION_KEY || e.key === null) && tick();
    window.addEventListener("storage", onStorage);
    return () => {
      clearInterval(id);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const ending = useRef(false); // 이 탭이 직접 로그아웃 중이면 아래 "다른 탭 로그아웃" 처리를 건너뛴다
  const expired = left <= 0;

  useEffect(() => {
    if (ending.current || expiring) return;
    if (!active) router.replace("/login"); // 다른 탭에서 로그아웃했다
    else if (expired) {
      ending.current = true;
      logout().then(expireSession);
    }
  }, [active, expired, router]);

  async function extend() {
    setBusy(true);
    setError(null);
    try {
      if (!(await refreshSession())) return expireSession();
      setNow(Date.now());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    ending.current = true;
    await logout();
    router.replace("/login");
  }

  if (!active) return null;
  return (
    <>
      <p className="flex items-center gap-2 text-xs text-slate tabular-nums">
        <span>
          자동 로그아웃 <time aria-label={`${mmss(left)} 남음`}>{mmss(left)}</time>
        </span>
        <button
          type="button"
          onClick={extend}
          disabled={busy}
          className="rounded-full border border-line px-2.5 py-1 text-ink hover:border-coral disabled:opacity-50"
        >
          연장
        </button>
      </p>
      {left <= WARN_MS && (
        <div
          role="alertdialog"
          aria-labelledby={titleId}
          className="fixed inset-x-4 top-4 z-30 mx-auto max-w-sm rounded-2xl border border-coral bg-paper p-4 shadow-lg"
        >
          <p id={titleId} className="font-semibold">
            2분 후 자동으로 로그아웃됩니다.
          </p>
          <p className="mt-1 text-sm text-slate tabular-nums">남은 시간 {mmss(left)}</p>
          <ErrorText message={error} />
          <div className="mt-3 flex gap-2">
            {/* 뜨자마자 연장 버튼으로 포커스를 옮겨 Enter 한 번으로 연장할 수 있게 한다 */}
            <Button type="button" busy={busy} onClick={extend} autoFocus>
              연장
            </Button>
            <button type="button" onClick={signOut} className="w-full rounded-xl border border-line py-3 text-slate hover:text-ink">
              로그아웃
            </button>
          </div>
        </div>
      )}
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

/** 1000000 → "100만 원", 123456789 → "1억 2,345만 6,789원". 만 원 미만은 null (숫자 그대로 읽기 쉬움) */
export function koreanWon(value: number): string | null {
  if (!Number.isSafeInteger(value) || value < 10_000) return null;
  const units: [number, string][] = [[1_000_000_000_000, "조"], [100_000_000, "억"], [10_000, "만"]];
  const parts: string[] = [];
  let rest = value;
  for (const [size, unit] of units) {
    const n = Math.floor(rest / size);
    if (n) parts.push(`${n.toLocaleString("ko-KR")}${unit}`);
    rest %= size;
  }
  return rest ? `${parts.join(" ")} ${rest.toLocaleString("ko-KR")}원` : `${parts.join(" ")} 원`;
}

/** 금액 입력. 0이 많아도 헷갈리지 않게 입력칸 오른쪽에 "10만 원"처럼 읽어 준다. */
export function MoneyField({
  label,
  onInput,
  ...props
}: { label: string } & Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [value, setValue] = useState(String(props.value ?? props.defaultValue ?? ""));
  const hint = koreanWon(Number(props.value ?? value));
  const hintId = useId();
  return (
    <label className="block">
      <span className="mb-1 block text-sm text-slate">{label}</span>
      <span className="relative block">
        <input
          type="number"
          inputMode="numeric"
          step={1}
          {...props}
          aria-describedby={hint ? hintId : undefined}
          onInput={(e) => {
            setValue(e.currentTarget.value);
            onInput?.(e);
          }}
          className="w-full rounded-xl border border-line bg-paper px-3 py-2.5 pr-36 outline-none focus:border-coral focus-visible:ring-2 focus-visible:ring-coral/20"
        />
        {hint && (
          <span id={hintId} className="pointer-events-none absolute inset-y-0 right-10 flex items-center text-sm text-coral tabular-nums">
            {hint}
          </span>
        )}
      </span>
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
