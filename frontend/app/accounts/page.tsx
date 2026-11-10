"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AccountCarousel } from "@/components/home/AccountCarousel";
import type { Recent } from "@/components/home/AccountCard";
import { AllAccounts } from "@/components/home/AllAccounts";
import { AssetSummaryCard } from "@/components/home/AssetSummaryCard";
import { Skeleton } from "@/components/home/bits";
import { useHomeData } from "@/components/home/useHomeData";
import { ErrorText, Shell } from "@/components/ui";
import { FavoriteProductList } from "@/components/FavoriteProducts";
import { SpiderMascot } from "@/components/SpiderMascot";
import { AccountSummary, RecentRecipient, api, won } from "@/lib/api";
import { accountKey, toggle } from "@/lib/home-prefs";
import { useFreshOnLeave } from "@/lib/fresh";

type CardSummary = {
  card_type: "credit" | "debit";
  card_id: number;
  card_num: string;
  status: string;
  outstanding_amount: number | null; // 신용카드 미결제액
  accumulated_amount: number | null; // 체크카드 누적 사용액
  due_date?: string; // 신용카드: 아직 안 낸 청구서의 결제일
  due_amount?: number;
};

export default function AccountsPage() {
  return (
    <Shell>
      <Home key={useFreshOnLeave()} />
    </Shell>
  );
}

function Home() {
  const { accounts, prefs, ordered, update, error } = useHomeData();
  const [recent, setRecent] = useState<Record<string, Recent>>({});
  const [cards, setCards] = useState<CardSummary[]>([]);

  // 최근 이체 상대는 계좌를 불러온 뒤에 계좌마다 따로 (하나가 실패해도 그 카드만 표시)
  useEffect(() => {
    if (accounts) loadRecent(accounts).then(setRecent);
  }, [accounts]);

  // 카드는 따로 불러온다: 실패해도 계좌 영역은 그대로 보인다
  useEffect(() => {
    loadCards().then(setCards).catch(() => setCards([]));
  }, []);

  const total = accounts?.reduce((sum, a) => sum + a.balance, 0) ?? null;
  const hidden = new Set(prefs?.hidden);
  const reps = new Set(prefs?.reps);
  const repAccounts = ordered.filter((a) => reps.has(accountKey(a))); // 슬라이더에는 대표 계좌만 (C-066)
  const toggleHidden = (key: string) => update((p) => ({ ...p, hidden: toggle(p.hidden, key) }));
  const loading = !accounts || !prefs;

  return (
    <div className="space-y-4">
      <section className="relative isolate flex min-h-32 items-center justify-between overflow-hidden rounded-3xl border border-[#f4d9cd] bg-gradient-to-br from-paper via-paper to-coral-soft/70 px-5 py-4 shadow-[0_14px_36px_rgba(153,61,34,0.06)]">
        <div className="relative z-10 max-w-[62%]">
          <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-coral">SpiderBank · Home</p>
          <h2 className="mt-1 text-lg font-bold leading-snug tracking-tight">오늘도 가볍게,<br />금융을 한눈에</h2>
          <p className="mt-1 text-xs text-slate">필요한 금융을 편하게 확인해봐.</p>
        </div>
        <div className="absolute right-4 grid size-24 place-items-center rounded-full bg-coral-soft/60">
          <SpiderMascot className="size-[4.5rem] text-coral" />
        </div>
      </section>
      <h1 className="sr-only">홈</h1>
      <ErrorText message={error} />

      {/* 1. 내 자산 현황 */}
      <AssetSummaryCard
        total={loading ? null : total}
        count={accounts?.length ?? 0}
        hidden={prefs?.hideTotal ?? false}
        onToggle={() => update((p) => ({ ...p, hideTotal: !p.hideTotal }))}
      />

      {loading && !error && <Skeleton className="h-56 w-full rounded-3xl" />}

      {!loading && ordered.length === 0 && (
        <Link
          href="/open/checking"
          className="grid min-h-32 place-items-center rounded-3xl border-2 border-dashed border-[#f0b49a] p-5 font-medium text-coral"
        >
          첫 입출금 계좌 만들기
        </Link>
      )}

      {!loading && ordered.length > 0 && (
        <>
          {/* 2. 내 전체 계좌 보기 */}
          <AllAccounts
            accounts={ordered}
            total={total ?? 0}
            hideTotal={prefs.hideTotal}
            hidden={hidden}
            reps={reps}
            onToggleHidden={toggleHidden}
          />

          {/* 3. 대표 계좌 카드 슬라이더 (대표가 없으면 설정 안내) */}
          {repAccounts.length > 0 ? (
            <AccountCarousel accounts={repAccounts} hidden={hidden} onToggleHidden={toggleHidden} recent={recent} />
          ) : (
            <div className="rounded-3xl border-2 border-dashed border-[#f0b49a] p-6 text-center">
              <p className="font-medium">대표 계좌를 설정하면 여기에 카드로 보여요</p>
              <p className="mt-1 text-sm text-slate">자주 쓰는 계좌에 별을 눌러 보세요.</p>
              <Link
                href="/accounts/settings"
                className="mt-4 inline-flex min-h-11 items-center rounded-xl bg-coral px-5 font-medium text-paper"
              >
                대표 계좌 설정하기
              </Link>
            </div>
          )}

          {/* 4. 대표 계좌 및 순서 설정 (별도 화면) */}
          <Link
            href="/accounts/settings"
            aria-label="대표 계좌 및 순서 설정 열기"
            className="flex min-h-11 items-center justify-between rounded-2xl bg-paper px-5 py-3 font-semibold"
          >
            대표 계좌 및 순서 설정
            <svg viewBox="0 0 24 24" aria-hidden className="size-5 fill-none stroke-slate stroke-[1.8]">
              <path
                d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </Link>
          <Link href="/products" className="flex min-h-11 items-center justify-center text-sm font-medium text-coral">
            + 예금·적금·카드 가입
          </Link>
        </>
      )}

      {/* 5. 카드 목록 */}
      {cards.length > 0 && <CardList cards={cards} />}

      {/* 6. 찜한 상품 (C-117) */}
      <FavoriteProductList />
    </div>
  );
}

// 최근 이체한 분 (우리 은행 + 타행). 이체 화면의 '최근' 탭과 같은 서버 목록(/transfers/recent)을 쓰고, 입출금 카드마다 같은 목록을 보인다.
// 못 불러오면 입출금 카드만 "불러오지 못함"으로 둔다.
async function loadRecent(accounts: AccountSummary[]): Promise<Record<string, Recent>> {
  let list: Recent;
  try {
    const rows = await api<RecentRecipient[]>("/transfers/recent");
    list = rows.slice(0, 10).map((r) => ({ name: r.name ?? r.account, account: r.account, bank_code: r.bank_code, bank_name: r.bank_name }));
  } catch {
    list = "error";
  }
  // 예금·적금은 이체를 보내지 않는다
  return Object.fromEntries(accounts.map((a) => [accountKey(a), a.account_type === "checking" ? list : []]));
}

async function loadCards(): Promise<CardSummary[]> {
  const cards = (await api<CardSummary[]>("/cards")).filter((x) => x.status !== "CLOSED");
  // 신용카드는 아직 안 낸 청구서 중 가장 빠른 결제일과 합계를 붙인다 (못 불러오면 이용 금액만)
  return Promise.all(
    cards.map(async (card) => {
      if (card.card_type !== "credit") return card;
      try {
        const bills = await api<{ total_amount: number; due_date: string; status: string }[]>(`/cards/credit/${card.card_id}/bills`);
        const unpaid = bills.filter((b) => b.status === "UNPAID").sort((x, y) => x.due_date.localeCompare(y.due_date));
        return unpaid.length
          ? { ...card, due_date: unpaid[0].due_date, due_amount: unpaid.reduce((s, b) => s + b.total_amount, 0) }
          : card;
      } catch {
        return card;
      }
    }),
  );
}

function CardList({ cards }: { cards: CardSummary[] }) {
  return (
    <section className="pt-4">
      <h2 className="text-sm text-slate">내 카드 {cards.length}장</h2>
      <ul className="mt-3 divide-y divide-line rounded-3xl bg-paper">
        {cards.map((c) => (
          <li key={`${c.card_type}-${c.card_id}`}>
            <Link href={`/cards/${c.card_type}/${c.card_id}`} className="flex min-h-11 items-center justify-between gap-4 px-5 py-4">
              <div className="min-w-0">
                <p className="font-semibold">
                  {c.card_type === "credit" ? "신용카드" : "체크카드"}
                  {c.status === "SUSPENDED" && <span className="ml-2 text-sm font-normal text-seal">정지됨</span>}
                </p>
                <p className="text-sm text-slate tabular-nums">•••• {c.card_num.slice(-4)}</p>
              </div>
              <div className="shrink-0 text-right tabular-nums">
                <p className="text-sm text-slate">
                  {c.card_type === "debit"
                    ? "누적 사용액"
                    : c.due_date
                      ? `${Number(c.due_date.slice(5, 7))}월 ${Number(c.due_date.slice(8, 10))}일 결제 예정`
                      : "이번 달 이용 금액"}
                </p>
                <p className="font-bold">
                  {won(c.card_type === "debit" ? (c.accumulated_amount ?? 0) : (c.due_amount ?? c.outstanding_amount ?? 0))}
                </p>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
