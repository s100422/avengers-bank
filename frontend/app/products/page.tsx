"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useFreshOnLeave } from "@/lib/fresh";
import { ErrorText, Shell } from "@/components/ui";
import { User, api, won } from "@/lib/api";

type Product = {
  product_id: number;
  type: "CHECKING" | "DEPOSIT" | "SAVINGS" | "CREDIT" | "DEBIT";
  name: string;
  description: string;
  interest_rate?: string;
  credit_limit?: number | null;
  min_amount?: number | null; // 예금만. null이면 최소 없음
};

// 상품 종류 → 가입 화면(/open/{kind}), 이름, 아이콘 타일 색
const TYPE = {
  CHECKING: { kind: "checking", label: "입출금", tile: "bg-[#fff1cc] text-[#c98a00]" },
  SAVINGS: { kind: "savings", label: "적금", tile: "bg-[#e3edfb] text-[#3b6fd1]" },
  DEPOSIT: { kind: "deposit", label: "정기예금", tile: "bg-[#e3f2e1] text-[#3d8b4f]" },
  CREDIT: { kind: "credit", label: "신용카드", tile: "bg-coral-soft text-coral" },
  DEBIT: { kind: "debit", label: "체크카드", tile: "bg-[#ffe6d1] text-[#d0681c]" },
} as const;

// 탭 → 보여 줄 상품 종류(칩)
const TABS = {
  recommend: { label: "추천", types: [] as Product["type"][] },
  savings: { label: "예적금", types: ["SAVINGS", "DEPOSIT"] as Product["type"][] },
  checking: { label: "입출금", types: ["CHECKING"] as Product["type"][] },
  card: { label: "카드", types: ["CREDIT", "DEBIT"] as Product["type"][] },
};
type Tab = keyof typeof TABS;
type Chip = Product["type"] | "ALL";

// 추천 탭의 테마 카드: 누르면 해당 탭과 칩으로 간다
const THEMES: { title: string; body: string; tab: Tab; chip: Chip; bg: string; icon: Product["type"] }[] = [
  { title: "돈 모으고 싶다면 적금부터 시작", body: "매달 정한 만큼 차곡차곡 쌓는 적금을 모았어요", tab: "savings", chip: "SAVINGS", bg: "bg-[#e3edfb]", icon: "SAVINGS" },
  { title: "목돈은 예금에 맡겨 두세요", body: "기간을 정해 맡기고 만기에 이자를 받아요", tab: "savings", chip: "DEPOSIT", bg: "bg-[#e3f2e1]", icon: "DEPOSIT" },
  { title: "월급 받는 통장을 바꿔 볼까요", body: "급여가 들어오면 수수료가 면제되는 통장이에요", tab: "checking", chip: "ALL", bg: "bg-[#fff1cc]", icon: "CHECKING" },
  { title: "쓰는 곳에 맞는 카드 고르기", body: "쇼핑, 교통, 해외 결제 혜택을 비교해 보세요", tab: "card", chip: "ALL", bg: "bg-coral-soft", icon: "CREDIT" },
];

// 탭마다 맨 위 배너 (그 탭에서 눈에 띄는 상품으로 연결)
const BANNERS: Partial<Record<Tab, { title: string; body: string; pick: (ps: Product[]) => Product | undefined; bg: string }>> = {
  savings: {
    title: "목돈 만들기,\n오늘부터 시작해요",
    body: "금리가 가장 높은 적금으로 바로 가입할 수 있어요",
    pick: (ps) => ps.filter((p) => p.type === "SAVINGS").sort((a, b) => Number(b.interest_rate) - Number(a.interest_rate))[0],
    bg: "bg-[#e3f2e1]",
  },
  checking: {
    title: "월급 통장 하나로\n수수료 걱정 끝",
    body: "급여가 들어오는 달은 이체·ATM 수수료가 면제돼요",
    pick: (ps) => ps.find((p) => p.name.includes("월급")) ?? ps.find((p) => p.type === "CHECKING"),
    bg: "bg-[#fff1cc]",
  },
  card: {
    title: "해외 결제도\n수수료 없이",
    body: "여행 갈 때 챙기는 트래블 카드",
    pick: (ps) => ps.find((p) => p.name.includes("트래블")) ?? ps.find((p) => p.type === "DEBIT"),
    bg: "bg-coral-soft",
  },
};

const href = (p: Product) => `/open/${TYPE[p.type].kind}/${p.product_id}`;
const rateText = (p: Product) =>
  p.interest_rate ? `연 ${Number(p.interest_rate)}%` : p.credit_limit ? `한도 ${won(p.credit_limit)}` : "연회비 없음";

export default function ProductsPage() {
  return (
    <Shell>
      <Products key={useFreshOnLeave()} />
    </Shell>
  );
}

function Products() {
  const [products, setProducts] = useState<Product[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("recommend");
  const [chip, setChip] = useState<Chip>("ALL");
  const [favs, setFavs] = useState<string[]>([]);
  const [userId, setUserId] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([api<Product[]>("/products/accounts"), api<Product[]>("/products/cards"), api<User>("/users/me")])
      .then(([a, c, u]) => {
        setProducts([...a, ...c]);
        setUserId(u.user_id);
        setFavs(loadFavs(u.user_id));
      })
      .catch((e) => setError(e.message));
    // 다른 화면에서 /products?tab=savings 처럼 탭을 지정해 들어올 수 있다
    const t = new URLSearchParams(window.location.search).get("tab");
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 주소는 브라우저에서만 읽을 수 있어 마운트 뒤에 맞춘다
    if (t && t in TABS) setTab(t as Tab);
  }, []);

  function go(next: Tab, nextChip: Chip = "ALL") {
    setTab(next);
    setChip(nextChip);
    window.history.replaceState(null, "", next === "recommend" ? "/products" : `/products?tab=${next}`);
    window.scrollTo({ top: 0 });
  }

  function toggleFav(p: Product) {
    const key = `${p.type}-${p.product_id}`;
    const next = favs.includes(key) ? favs.filter((k) => k !== key) : [...favs, key];
    setFavs(next);
    if (userId) saveFavs(userId, next);
  }

  return (
    <>
      <h1 className="mt-2 text-2xl font-bold">금융상품</h1>
      <TabBar tab={tab} onChange={(t) => go(t)} />
      <ErrorText message={error} />

      {!products && !error && (
        <div className="mt-6 space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <span key={i} className="block h-24 animate-pulse rounded-2xl bg-line/70 motion-reduce:animate-none" />
          ))}
        </div>
      )}

      {products && (
        <div id="product-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="mt-6">
          {tab === "recommend" ? (
            <Recommend products={products} onTheme={(t, c) => go(t, c)} />
          ) : (
            <Catalog tab={tab} products={products} chip={chip} onChip={setChip} favs={favs} onFav={toggleFav} />
          )}
        </div>
      )}
    </>
  );
}

function TabBar({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  const keys = Object.keys(TABS) as Tab[];
  return (
    <div
      role="tablist"
      aria-label="상품 종류"
      className="-mx-4 mt-4 flex gap-1 overflow-x-auto border-b border-line px-4 [scrollbar-width:none] md:mx-0 md:px-0"
      onKeyDown={(e) => {
        // ← → 로 탭 이동 (WAI-ARIA 탭 패턴)
        const i = keys.indexOf(tab);
        const next =
          e.key === "ArrowRight" ? keys[(i + 1) % keys.length] : e.key === "ArrowLeft" ? keys[(i - 1 + keys.length) % keys.length] : null;
        if (!next) return;
        e.preventDefault();
        onChange(next);
        document.getElementById(`tab-${next}`)?.focus();
      }}
    >
      {keys.map((k) => {
        const on = k === tab;
        return (
          <button
            key={k}
            id={`tab-${k}`}
            role="tab"
            type="button"
            aria-selected={on}
            aria-controls="product-panel"
            tabIndex={on ? 0 : -1}
            onClick={() => onChange(k)}
            className={`-mb-px min-h-11 shrink-0 border-b-[3px] px-3 text-lg whitespace-nowrap ${
              on ? "border-ink font-bold text-ink" : "border-transparent text-slate hover:text-ink"
            }`}
          >
            {TABS[k].label}
          </button>
        );
      })}
    </div>
  );
}

function Recommend({ products, onTheme }: { products: Product[]; onTheme: (t: Tab, c: Chip) => void }) {
  // 판매 데이터가 없어 "인기" 대신 월급통장, 금리가 가장 높은 적금·예금 하나씩을 보여 준다
  const best = (type: Product["type"]) =>
    products.filter((p) => p.type === type).sort((a, b) => Number(b.interest_rate) - Number(a.interest_rate))[0];
  const checking = products.find((p) => p.name.includes("월급")) ?? products.find((p) => p.type === "CHECKING");
  const picks = [checking, best("SAVINGS"), best("DEPOSIT")].filter((p): p is Product => !!p);

  return (
    <>
      <section aria-labelledby="top-title">
        <h2 id="top-title" className="text-xl font-bold">
          지금 눈여겨볼 상품
        </h2>
        <ul className="mt-3">
          {picks.map((p) => (
            <li key={`${p.type}-${p.product_id}`}>
              <Link href={href(p)} className="flex min-h-11 items-center gap-4 rounded-2xl py-3 hover:bg-paper/70">
                <TypeTile type={p.type} />
                <span className="min-w-0">
                  <span className="block truncate text-lg font-semibold">{p.name}</span>
                  <span className="block text-slate">
                    {p.type === "CHECKING" ? (
                      p.description
                    ) : (
                      <>
                        {TYPE[p.type].label}, <span className="font-semibold text-coral">{rateText(p)}</span>
                      </>
                    )}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="theme-title" className="mt-8">
        <h2 id="theme-title" className="text-xl font-bold">
          추천상품
        </h2>
        <ul className="mt-3 grid gap-3 md:grid-cols-2">
          {THEMES.map((t) => (
            <li key={t.title}>
              <button
                type="button"
                onClick={() => onTheme(t.tab, t.chip)}
                className={`flex h-full min-h-36 w-full items-center gap-4 rounded-3xl p-6 text-left ${t.bg}`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-lg font-bold">{t.title}</span>
                  <span className="mt-1 block text-slate">{t.body}</span>
                </span>
                <TypeTile type={t.icon} big />
              </button>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function Catalog({
  tab,
  products,
  chip,
  onChip,
  favs,
  onFav,
}: {
  tab: Exclude<Tab, "recommend">;
  products: Product[];
  chip: Chip;
  onChip: (c: Chip) => void;
  favs: string[];
  onFav: (p: Product) => void;
}) {
  const types = TABS[tab].types;
  const inTab = products.filter((p) => types.includes(p.type));
  const shown = chip === "ALL" ? inTab : inTab.filter((p) => p.type === chip);
  const banner = BANNERS[tab];
  const bannerProduct = banner?.pick(inTab);

  return (
    <>
      {banner && bannerProduct && (
        <Link href={href(bannerProduct)} className={`flex min-h-40 items-center gap-4 rounded-3xl p-6 ${banner.bg}`}>
          <span className="min-w-0 flex-1">
            <span className="block text-xl leading-snug font-bold whitespace-pre-line">{banner.title}</span>
            <span className="mt-2 block text-slate">{banner.body}</span>
            <span className="mt-3 inline-block text-sm font-semibold text-ink underline underline-offset-4">{bannerProduct.name} 보기</span>
          </span>
          <TypeTile type={bannerProduct.type} big />
        </Link>
      )}

      {types.length > 1 && (
        <div className="mt-6 flex flex-wrap gap-2" role="group" aria-label="상품 종류 거르기">
          {(["ALL", ...types] as Chip[]).map((c) => {
            const on = c === chip;
            return (
              <button
                key={c}
                type="button"
                aria-pressed={on}
                onClick={() => onChip(c)}
                className={`min-h-11 rounded-full border px-5 font-medium ${
                  on ? "border-coral bg-coral text-paper" : "border-line bg-paper text-slate hover:text-ink"
                }`}
              >
                {c === "ALL" ? "전체" : TYPE[c].label}
              </button>
            );
          })}
        </div>
      )}

      <h2 className="mt-6 text-lg font-bold">
        {chip === "ALL" ? TABS[tab].label : TYPE[chip].label} <span className="text-coral">{shown.length}</span>
      </h2>

      <ul className="mt-3 grid gap-3 md:grid-cols-2">
        {shown.map((p) => {
          const fav = favs.includes(`${p.type}-${p.product_id}`);
          return (
            <li key={`${p.type}-${p.product_id}`} className="relative">
              <Link href={href(p)} className="block h-full rounded-3xl border border-line bg-paper p-6 pr-16 hover:border-coral">
                <span className="block text-xl font-bold">{p.name}</span>
                <span className="mt-1 block text-slate">{p.description}</span>
                <span className="mt-4 block">
                  <span className="text-slate">{TYPE[p.type].label}, </span>
                  <span className="text-lg font-bold text-coral tabular-nums">{rateText(p)}</span>
                </span>
                {p.type === "DEPOSIT" && p.min_amount != null && (
                  <span className="mt-1 block text-sm text-slate tabular-nums">최소 가입 {won(p.min_amount)}</span>
                )}
              </Link>
              {/* 찜 버튼은 링크 밖에 둔다 (누르면 가입 화면으로 넘어가지 않게) */}
              <button
                type="button"
                onClick={() => onFav(p)}
                aria-pressed={fav}
                aria-label={fav ? `${p.name} 찜 해제` : `${p.name} 찜하기`}
                className="absolute top-4 right-4 inline-flex size-11 items-center justify-center rounded-full hover:bg-porcelain"
              >
                <svg viewBox="0 0 24 24" aria-hidden className={`size-7 stroke-[1.6] ${fav ? "fill-coral stroke-coral" : "fill-none stroke-slate"}`}>
                  <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z" strokeLinejoin="round" />
                </svg>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

// 상품 종류 아이콘: 둥근 색 타일 + 단순한 선 그림
function TypeTile({ type, big }: { type: Product["type"]; big?: boolean }) {
  const paths: Record<Product["type"], string> = {
    CHECKING: "M4 7h16v11H4z M4 11h16 M15 15h2", // 통장
    SAVINGS: "M7 17V9 M12 17V6 M17 17v-5 M4 20h16", // 쌓이는 막대
    DEPOSIT: "M5 10h14v9H5z M8 10V7a4 4 0 0 1 8 0v3 M12 14v2", // 금고(자물쇠)
    CREDIT: "M3 7h18v11H3z M3 11h18 M6 15h4", // 카드
    DEBIT: "M3 7h18v11H3z M3 11h18 M15 15h3", // 카드
  };
  return (
    <span aria-hidden className={`grid shrink-0 place-items-center rounded-2xl ${TYPE[type].tile} ${big ? "size-20" : "size-14"}`}>
      <svg viewBox="0 0 24 24" className={`${big ? "size-10" : "size-7"} fill-none stroke-current stroke-[1.8]`}>
        <path d={paths[type]} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

// 찜한 상품: 사용자별 브라우저 저장 (shortcut: 서버 API가 없어 localStorage. 기기 간 공유 안 됨)
const favKey = (userId: number) => `avengers_bank_fav_products:${userId}`;
function loadFavs(userId: number): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(favKey(userId)) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}
function saveFavs(userId: number, favs: string[]) {
  try {
    localStorage.setItem(favKey(userId), JSON.stringify(favs));
  } catch {
    // 저장소를 못 쓰면 이번 화면에서만 유지
  }
}
