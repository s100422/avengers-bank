"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useFreshOnLeave } from "@/lib/fresh";
import { ErrorText, Shell } from "@/components/ui";
import { api, won } from "@/lib/api";
import { Heart, favoriteKey, loadFavoriteProducts, setFavoriteProduct } from "@/components/FavoriteProducts";
import { productDescription, productName } from "@/lib/product-display";

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
const THEMES: { title: string; body: string; tab: Tab; chip: Chip; tone: string; illustration: "savings" | "deposit" | "checking" }[] = [
  { title: "돈 모으고 싶다면 적금부터 시작", body: "매달 부담 없이 저축할 수 있는 적금 상품을 모아봤어요.", tab: "savings", chip: "SAVINGS", tone: "bg-[#e8f0eb]", illustration: "savings" },
  { title: "모아둔 목돈은 예금으로", body: "가입 기간과 금리를 비교해 내게 맞는 예금 상품을 찾아봐요.", tab: "savings", chip: "DEPOSIT", tone: "bg-[#ececf8]", illustration: "deposit" },
  { title: "생활비 관리는 입출금 통장으로", body: "급여 관리와 일상 결제에 편리한 입출금 상품을 살펴봐요.", tab: "checking", chip: "ALL", tone: "bg-[#f9e9e3]", illustration: "checking" },
];

// 탭마다 맨 위 배너 (그 탭에서 눈에 띄는 상품으로 연결)
type BannerSlide = { product: Product; title: string; body: string };

function getBannerSlides(tab: Tab, products: Product[]): BannerSlide[] {
  let picks: Product[] = [];
  if (tab === "savings") {
    const byRate = (type: Product["type"]) =>
      products.filter((p) => p.type === type).sort((a, b) => Number(b.interest_rate) - Number(a.interest_rate));
    const savings = byRate("SAVINGS");
    const deposits = byRate("DEPOSIT");
    picks = [savings[0], deposits[0], savings[1] ?? deposits[1]].filter((p): p is Product => !!p);
  } else if (tab === "checking") {
    picks = products
      .filter((p) => p.type === "CHECKING")
      .sort((a, b) => Number(/급여|월급/.test(b.name)) - Number(/급여|월급/.test(a.name)))
      .slice(0, 3);
  } else if (tab === "card") {
    const debit = products.filter((p) => p.type === "DEBIT");
    const credit = products
      .filter((p) => p.type === "CREDIT")
      .sort((a, b) => Number(b.credit_limit ?? 0) - Number(a.credit_limit ?? 0));
    const travel = [...debit, ...credit].find((p) => /트래블|여행/.test(p.name));
    picks = [travel, credit[0], debit.find((p) => p.product_id !== travel?.product_id), ...credit.slice(1)]
      .filter((p): p is Product => !!p)
      .filter((p, index, all) => all.findIndex((item) => item.product_id === p.product_id && item.type === p.type) === index)
      .slice(0, 3);
  }

  return picks.map((product) => {
    const detail = productDescription(product.type, product.description);
    const rate = product.interest_rate ? ` · ${rateText(product)} (세전)` : "";
    const limit = product.credit_limit ? ` · 한도 ${won(product.credit_limit)}` : "";
    return {
      product,
      title: productName(product.type, product.name),
      body: `${detail}${rate}${limit}`,
    };
  });
}

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

  useEffect(() => {
    Promise.all([api<Product[]>("/products/accounts"), api<Product[]>("/products/cards"), loadFavoriteProducts()])
      .then(([a, c, f]) => {
        setProducts([...a, ...c]);
        setFavs(f.map((x) => favoriteKey(x.product_type, x.product_id)));
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

  async function toggleFav(p: Product) {
    const key = favoriteKey(p.type, p.product_id);
    const on = !favs.includes(key);
    setFavs((list) => (on ? [...list, key] : list.filter((k) => k !== key))); // 바로 바꾸고, 실패하면 되돌린다
    setError(null);
    try {
      await setFavoriteProduct(p.type, p.product_id, on);
    } catch (e) {
      setFavs((list) => (on ? list.filter((k) => k !== key) : [...list, key]));
      setError(e instanceof Error ? e.message : "찜을 저장하지 못했습니다.");
    }
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
  // 추천 상품은 각 유형의 실제 상품 중 금리가 높은 상품을 보여준다.
  const best = (type: Product["type"]) =>
    products.filter((p) => p.type === type).sort((a, b) => Number(b.interest_rate) - Number(a.interest_rate))[0];
  const checking = products.find((p) => p.name.includes("입출금")) ?? products.find((p) => p.type === "CHECKING");
  const picks = [checking, best("SAVINGS"), best("DEPOSIT")].filter((p): p is Product => !!p);

  return (
    <>
      <section aria-labelledby="top-title">
        <h2 id="top-title" className="text-xl font-bold">
          지금 눈여겨볼 상품
        </h2>
        <ul className="mt-3 divide-y divide-line/70">
          {picks.map((p) => (
            <li key={`${p.type}-${p.product_id}`}>
              <Link
                href={href(p)}
                className="group flex min-h-[104px] items-center gap-4 rounded-2xl px-2 py-4 transition hover:bg-paper/70 md:gap-5 md:py-5"
              >
                <PassbookTile type={p.type as "CHECKING" | "SAVINGS" | "DEPOSIT"} />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="truncate text-lg font-semibold leading-tight md:text-xl">{productName(p.type, p.name)}</span>
                    {(p.type === "SAVINGS" || p.type === "DEPOSIT") && (
                      <span className="rounded-full bg-[#edf3ff] px-2.5 py-1 text-xs font-medium text-[#4d80d8]">금리 TOP</span>
                    )}
                  </span>
                  <span className="mt-1 block text-sm leading-relaxed text-slate md:text-base">
                    {p.type === "CHECKING" ? (
                      productDescription(p.type, p.description)
                    ) : (
                      <>
                        {TYPE[p.type].label}, <span className="font-semibold text-[#4d80d8]">{rateText(p)}</span> <span>(세전)</span>
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
        <ul className="mt-3 grid gap-3">
          {THEMES.map((t) => (
            <li key={t.title}>
              <button
                type="button"
                onClick={() => onTheme(t.tab, t.chip)}
                className={`group flex min-h-[148px] w-full items-center gap-4 overflow-hidden rounded-[1.65rem] px-5 py-5 text-left transition hover:-translate-y-0.5 hover:shadow-[0_12px_28px_rgba(70,49,39,0.08)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-coral active:translate-y-0 md:px-7 md:py-6 ${t.tone}`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-base font-bold leading-snug md:text-lg">{t.title}</span>
                  <span className="mt-2 block text-sm leading-relaxed text-ink/75 md:text-base">{t.body}</span>
                </span>
                <ThemeArtwork type={t.illustration} />
              </button>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function ThemeArtwork({ type }: { type: "savings" | "deposit" | "checking" }) {
  return (
    <span aria-hidden="true" className="grid size-[76px] shrink-0 place-items-center md:size-[92px]">
      {type === "savings" && (
        <svg viewBox="0 0 96 96" className="size-full drop-shadow-[0_5px_4px_rgba(80,55,40,0.12)]">
          <circle cx="48" cy="51" r="39" fill="#d8e9ef" />
          <path d="M28 41c0-8 9-14 21-14s21 6 21 14v25c0 8-9 14-21 14S28 74 28 66V41Z" fill="#f6c98d" />
          <path d="M28 43c0-8 9-14 21-14s21 6 21 14-9 13-21 13-21-5-21-13Z" fill="#ffe0a6" />
          <path d="M45 55h8m-4-4v8" stroke="#c77e33" strokeWidth="3" strokeLinecap="round" />
          <path d="M39 26c-2-7 1-12 8-12 6 0 9 5 7 12" fill="#f1bc42" />
          <path d="M36 77h27" stroke="#d98a46" strokeWidth="4" strokeLinecap="round" />
          <circle cx="75" cy="27" r="10" fill="#dd3b24" />
          <path d="m71 27 3 3 6-7" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      {type === "deposit" && (
        <svg viewBox="0 0 96 96" className="size-full drop-shadow-[0_5px_4px_rgba(80,55,40,0.12)]">
          <circle cx="48" cy="51" r="39" fill="#dfe4f7" />
          <rect x="18" y="32" width="53" height="42" rx="8" fill="#fff" />
          <path d="m18 43 26-16 27 16" fill="#86a9dd" />
          <path d="M29 46v18m14-18v18m14-18v18M23 67h43" stroke="#607fbd" strokeWidth="4" strokeLinecap="round" />
          <circle cx="70" cy="68" r="15" fill="#f1c64e" />
          <circle cx="70" cy="68" r="9" fill="#ffe594" />
          <path d="M70 61v14m-4-10c0-2 2-3 4-3s4 1 4 3-2 3-4 3-4 1-4 3 2 3 4 3 4-1 4-3" fill="none" stroke="#b98717" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      )}
      {type === "checking" && (
        <svg viewBox="0 0 96 96" className="size-full drop-shadow-[0_5px_4px_rgba(80,55,40,0.12)]">
          <circle cx="48" cy="51" r="39" fill="#f5ded5" />
          <rect x="18" y="29" width="58" height="40" rx="9" fill="#dd3b24" />
          <path d="M18 41h58" stroke="#f7a58f" strokeWidth="4" />
          <rect x="53" y="50" width="31" height="25" rx="6" fill="#fff" />
          <path d="m61 62 5 5 10-12" fill="none" stroke="#438765" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="69" cy="32" r="3" fill="#ffe1a1" />
        </svg>
      )}
    </span>
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
  const bannerSlides = getBannerSlides(tab, inTab);
  const [bannerIndex, setBannerIndex] = useState(0);
  const [bannerPaused, setBannerPaused] = useState(false);
  const activeBanner = bannerSlides.length ? bannerSlides[bannerIndex % bannerSlides.length] : undefined;

  useEffect(() => {
    if (bannerSlides.length < 2 || bannerPaused) return;
    const timer = window.setInterval(() => {
      setBannerIndex((index) => (index + 1) % bannerSlides.length);
    }, 4500);
    return () => window.clearInterval(timer);
  }, [bannerSlides.length, bannerIndex, bannerPaused]);

  return (
    <>
      {activeBanner && (
        <section
          aria-label={`${TABS[tab].label} 상품 추천`}
          aria-roledescription="carousel"
          className={`relative overflow-hidden rounded-[1.8rem] ${bannerTone(activeBanner.product.type)}`}
          onMouseEnter={() => setBannerPaused(true)}
          onMouseLeave={() => setBannerPaused(false)}
          onFocusCapture={() => setBannerPaused(true)}
          onBlurCapture={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setBannerPaused(false);
          }}
        >
          <Link
            key={`${activeBanner.product.type}-${activeBanner.product.product_id}`}
            href={href(activeBanner.product)}
            className="grid min-h-[204px] grid-cols-[minmax(0,1fr)_92px] items-center gap-2 px-5 py-12 sm:grid-cols-[minmax(0,1fr)_116px] sm:px-7 md:min-h-[224px] md:grid-cols-[minmax(0,1fr)_136px] md:px-8"
          >
            <span className="min-w-0 self-center">
              <span className="block text-lg font-bold leading-snug md:text-xl">{activeBanner.title}</span>
              <span className="mt-2 block line-clamp-3 text-sm leading-relaxed text-ink/70 md:text-base">{activeBanner.body}</span>
              <span className="mt-3 inline-block text-sm font-semibold text-coral">상품 자세히 보기 <span aria-hidden="true">→</span></span>
            </span>
            <ProductBannerArtwork type={activeBanner.product.type} />
          </Link>
          <div className="absolute right-4 top-4 flex items-center gap-1.5 sm:right-6 sm:top-5" aria-label="배너 선택">
            {bannerSlides.map((slide, index) => (
              <button
                key={`${slide.product.type}-${slide.product.product_id}`}
                type="button"
                aria-label={`${index + 1}번째 상품 배너 보기`}
                aria-current={index === bannerIndex % bannerSlides.length ? "true" : undefined}
                onClick={() => setBannerIndex(index)}
                className={`h-2.5 rounded-full transition-all ${index === bannerIndex % bannerSlides.length ? "w-7 bg-coral" : "w-2.5 bg-ink/25 hover:bg-ink/45"}`}
              />
            ))}
            <button
              type="button"
              aria-label="다음 상품 배너"
              onClick={() => setBannerIndex((index) => (index + 1) % bannerSlides.length)}
              className="ml-1 grid size-8 place-items-center rounded-full text-xl font-bold text-ink/60 hover:bg-white/50"
            >
              <span aria-hidden="true">›</span>
            </button>
          </div>
        </section>
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

      <ul className="mt-3 grid grid-cols-1 gap-3">
        {shown.map((p) => {
          const fav = favs.includes(favoriteKey(p.type, p.product_id));
          return (
            <li key={`${p.type}-${p.product_id}`} className="relative">
              <Link href={href(p)} className="daily-card block h-full p-6 pr-16 hover:border-coral">
                <span className="block text-xl font-bold">{productName(p.type, p.name)}</span>
                <span className="mt-1 block text-slate">{productDescription(p.type, p.description)}</span>
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
                aria-label={fav ? `${productName(p.type, p.name)} 찜 해제` : `${productName(p.type, p.name)} 찜하기`}
                className="absolute top-4 right-4 inline-flex size-11 items-center justify-center rounded-full hover:bg-porcelain"
              >
                <Heart filled={fav} />
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

// 상품 종류 아이콘: 둥근 색 타일 + 단순한 선 그림
function bannerTone(type: Product["type"]) {
  return {
    CHECKING: "bg-[#fff2c8]",
    SAVINGS: "bg-[#e8eef9]",
    DEPOSIT: "bg-[#e8f0eb]",
    CREDIT: "bg-[#ececf8]",
    DEBIT: "bg-[#f8e8e1]",
  }[type];
}

function ProductBannerArtwork({ type }: { type: Product["type"] }) {
  return (
    <span aria-hidden="true" className="grid size-[88px] shrink-0 place-items-center sm:size-[104px] md:size-[124px]">
      <svg viewBox="0 0 128 128" className="size-full drop-shadow-[0_7px_6px_rgba(80,55,40,0.13)]">
        <circle cx="64" cy="68" r="52" fill="rgba(255,255,255,0.56)" />
        {type === "CHECKING" && (
          <>
            <rect x="25" y="40" width="67" height="48" rx="10" fill="#edb83f" />
            <path d="M25 50a10 10 0 0 1 10-10h47a10 10 0 0 1 10 10v8H25v-8Z" fill="#f8d15d" />
            <path d="M37 71h40" stroke="#fff2c8" strokeWidth="5" strokeLinecap="round" />
            <circle cx="93" cy="86" r="17" fill="#dd3b24" />
            <path d="m86 86 5 5 10-12" fill="none" stroke="white" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
          </>
        )}
        {type === "SAVINGS" && (
          <>
            <path d="M33 59c0-14 13-24 31-24s31 10 31 24v26c0 12-13 20-31 20S33 97 33 85V59Z" fill="#f4c986" />
            <ellipse cx="64" cy="58" rx="31" ry="14" fill="#ffe0a6" />
            <path d="M57 61h14m-7-7v14" stroke="#c77e33" strokeWidth="4" strokeLinecap="round" />
            <path d="M50 36c-3-9 1-16 10-16s13 7 10 16" fill="#f1bc42" />
            <circle cx="96" cy="36" r="15" fill="#5688df" />
            <path d="m89 36 5 5 10-12" fill="none" stroke="white" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
          </>
        )}
        {type === "DEPOSIT" && (
          <>
            <path d="m27 56 37-24 37 24v6H27v-6Z" fill="#68a84f" />
            <rect x="33" y="62" width="62" height="37" rx="5" fill="#fff" />
            <path d="M44 68v23m15-23v23m15-23v23m-43 7h61" stroke="#68a84f" strokeWidth="5" strokeLinecap="round" />
            <circle cx="91" cy="39" r="16" fill="#f1c64e" />
            <path d="M91 30v18m-5-13c0-2 2-4 5-4s5 2 5 4-2 4-5 4-5 2-5 5 2 4 5 4 5-2 5-4" fill="none" stroke="#a77b12" strokeWidth="2.5" strokeLinecap="round" />
          </>
        )}
        {type === "CREDIT" && (
          <>
            <rect x="23" y="38" width="78" height="54" rx="10" fill="#668de0" />
            <path d="M23 52h78v12H23z" fill="#8fb0f1" />
            <rect x="34" y="73" width="17" height="11" rx="3" fill="#ffe08a" />
            <path d="m83 30 4-9m10 16 9-3m-20 12 2-8" stroke="#dd3b24" strokeWidth="4" strokeLinecap="round" />
            <circle cx="91" cy="88" r="15" fill="#f1c64e" />
            <path d="m91 78 3 7 7 1-5 5 1 7-6-4-6 4 1-7-5-5 7-1 3-7Z" fill="white" />
          </>
        )}
        {type === "DEBIT" && (
          <>
            <rect x="24" y="48" width="72" height="49" rx="9" fill="#dd3b24" />
            <path d="M24 61h72v10H24z" fill="#f27b61" />
            <rect x="34" y="78" width="18" height="11" rx="3" fill="#ffe08a" />
            <path d="m77 35 22-10-6 17 15 7-24 7 5-12-12-9Z" fill="#68a84f" />
            <circle cx="40" cy="36" r="7" fill="#f1c64e" />
            <circle cx="57" cy="27" r="4" fill="#f1c64e" />
          </>
        )}
      </svg>
    </span>
  );
}

function PassbookTile({ type }: { type: "CHECKING" | "SAVINGS" | "DEPOSIT" }) {
  const color = type === "CHECKING" ? "#edb83f" : type === "SAVINGS" ? "#5688df" : "#68a84f";
  const highlight = type === "CHECKING" ? "#f8d15d" : type === "SAVINGS" ? "#7ca7f0" : "#89c76c";

  return (
    <span aria-hidden="true" className="grid size-[72px] shrink-0 place-items-center rounded-[1.35rem] bg-[#f5f5f6] md:size-[80px]">
      <svg viewBox="0 0 80 80" className="size-12 md:size-[52px]">
        <path d="M17 24h45v34a4 4 0 0 1-4 4H21a4 4 0 0 1-4-4V28a4 4 0 0 1 4-4Z" fill={color} />
        <path d="M17 28a4 4 0 0 1 4-4h41v10H17V28Z" fill={highlight} />
        {type === "CHECKING" ? (
          <path d="M24 43h29" stroke="#fff4cf" strokeWidth="3" strokeLinecap="round" />
        ) : (
          <path d="M25 47h7l4-7 5 15 5-10 3 2h6" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        )}
      </svg>
    </span>
  );
}

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
