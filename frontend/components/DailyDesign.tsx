import Image from "next/image";
import Link from "next/link";

export function DailyBanner({ money = false }: { money?: boolean }) {
  return (
    <section className={`daily-banner ${money ? "daily-banner-money" : "daily-banner-home"}`}>
      <div className={money ? "relative z-10 max-w-[85%] sm:max-w-[70%]" : "daily-banner-copy"}>
        <p className="text-[10px] font-bold tracking-[0.16em] text-coral">SPIDERBANK · {money ? "MONEY GUIDE" : "HOME"}</p>
        <h2 className="mt-2 text-xl font-bold leading-snug tracking-tight sm:text-2xl">
          {money ? <>내 돈의 흐름을 살펴보고,<br />다음 계획도 가볍게</> : <>내 돈을 지키는<br />든든한 한 팀</>}
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-slate">{money ? "소비부터 다가오는 일정까지 함께 확인해봐." : "자산부터 소비까지, SpiderBank와 함께 살펴봐요."}</p>
      </div>
      {money ? (
        <div aria-hidden className="daily-banner-orbit" />
      ) : (
        <div className="daily-banner-art">
          <Image src="/spiderbank-shield.webp" alt="" fill unoptimized loading="eager" className="object-contain" />
        </div>
      )}
    </section>
  );
}

const shortcuts = [
  { href: "/transfer", label: "이체", tone: "rose", path: "M4 8h15l-4-4M20 16H5l4 4" },
  { href: "/products?tab=card", label: "카드", tone: "mint", path: "M4 6h16v13H4zM4 10h16M7 15h4" },
  { href: "/money/recurring", label: "반복 거래", tone: "lilac", path: "M6 8a7 7 0 0 1 12-2l2 2M20 4v4h-4M18 16A7 7 0 0 1 6 18l-2-2M4 20v-4h4" },
  { href: "/money", label: "돈 관리", tone: "gold", path: "M4 20V10h4v10M10 20V4h4v16M16 20v-7h4v7" },
];

export function DailyShortcuts() {
  return (
    <nav aria-label="금융 바로가기" className="daily-shortcuts">
      {shortcuts.map((s) => (
        <Link href={s.href} key={s.label} className={`daily-shortcut daily-tone-${s.tone}`}>
          <svg viewBox="0 0 24 24" aria-hidden className="size-7 fill-none stroke-current stroke-[1.7]"><path d={s.path} strokeLinecap="round" strokeLinejoin="round" /></svg>
          <span className="text-xs font-semibold sm:text-sm">{s.label}</span>
        </Link>
      ))}
    </nav>
  );
}
