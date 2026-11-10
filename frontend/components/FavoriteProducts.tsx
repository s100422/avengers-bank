"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorText } from "@/components/ui";
import { api, won } from "@/lib/api";
import { ProductKind, productDescription, productName } from "@/lib/product-display";

// 찜한 상품 (C-117): 서버(/products/favorites)에 저장해 홈·상품 화면·AI 비서가 같은 목록을 본다
export type FavoriteProduct = {
  product_type: ProductKind;
  product_id: number;
  name: string;
  description: string;
  interest_rate: string | null;
  min_amount: number | null;
  credit_limit: number | null;
};

export const favoriteKey = (type: ProductKind, id: number) => `${type}-${id}`;

export const loadFavoriteProducts = () => api<FavoriteProduct[]>("/products/favorites");

export function setFavoriteProduct(type: ProductKind, id: number, on: boolean) {
  return api<null>(`/products/favorites/${type}/${id}`, undefined, on ? "PUT" : "DELETE");
}

const KIND: Record<ProductKind, { kind: string; label: string }> = {
  CHECKING: { kind: "checking", label: "입출금" },
  SAVINGS: { kind: "savings", label: "적금" },
  DEPOSIT: { kind: "deposit", label: "정기예금" },
  CREDIT: { kind: "credit", label: "신용카드" },
  DEBIT: { kind: "debit", label: "체크카드" },
};

export function Heart({ filled }: { filled: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={`size-7 stroke-[1.6] ${filled ? "fill-coral stroke-coral" : "fill-none stroke-slate"}`}>
      <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10Z" strokeLinejoin="round" />
    </svg>
  );
}

// 홈 맨 아래: 찜한 상품 목록. 하트를 누르면 찜이 해제되고 목록에서 빠진다
export function FavoriteProductList() {
  const [items, setItems] = useState<FavoriteProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadFavoriteProducts()
      .then(setItems)
      .catch((e) => setError(e.message));
  }, []);

  async function unfavorite(p: FavoriteProduct) {
    const before = items;
    setItems((list) => list?.filter((x) => x !== p) ?? null); // 바로 빼고, 실패하면 되돌린다
    setError(null);
    try {
      await setFavoriteProduct(p.product_type, p.product_id, false);
    } catch (e) {
      setItems(before);
      setError(e instanceof Error ? e.message : "찜을 해제하지 못했습니다.");
    }
  }

  if (!items && !error) return null;

  return (
    <section aria-labelledby="fav-products-title" className="pt-4">
      <h2 id="fav-products-title" className="text-sm text-slate">
        찜한 상품 {items?.length ?? 0}개
      </h2>
      <ErrorText message={error} />
      {items && items.length === 0 && (
        <Link href="/products" className="mt-3 flex min-h-11 items-center justify-center rounded-3xl bg-paper px-5 py-4 text-sm text-slate">
          상품 화면에서 하트를 누르면 여기에 모여요
        </Link>
      )}
      {items && items.length > 0 && (
        <ul className="mt-3 divide-y divide-line rounded-3xl bg-paper">
          {items.map((p) => {
            const name = productName(p.product_type, p.name);
            const terms = p.interest_rate
              ? `연 ${Number(p.interest_rate)}%`
              : p.credit_limit
                ? `한도 ${won(p.credit_limit)}`
                : "연회비 없음";
            return (
              <li key={favoriteKey(p.product_type, p.product_id)} className="relative">
                <Link href={`/open/${KIND[p.product_type].kind}/${p.product_id}`} className="block min-h-11 px-5 py-4 pr-16">
                  <p className="font-semibold">{name}</p>
                  <p className="mt-0.5 truncate text-sm text-slate">{productDescription(p.product_type, p.description)}</p>
                  <p className="mt-1 text-sm">
                    <span className="text-slate">{KIND[p.product_type].label}, </span>
                    <span className="font-bold text-coral tabular-nums">{terms}</span>
                  </p>
                </Link>
                {/* 하트는 링크 밖에 둔다 (누르면 가입 화면으로 넘어가지 않게) */}
                <button
                  type="button"
                  onClick={() => unfavorite(p)}
                  aria-pressed
                  aria-label={`${name} 찜 해제`}
                  className="absolute top-1/2 right-3 inline-flex size-11 -translate-y-1/2 items-center justify-center rounded-full hover:bg-porcelain"
                >
                  <Heart filled />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
