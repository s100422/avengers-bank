"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ErrorText, Shell } from "@/components/ui";
import { ApiError, won } from "@/lib/api";
import {
  money,
  type Category,
  type CategorySource,
  type Source,
  type TxnDetail,
} from "@/lib/money";
import { BottomSheet } from "@/components/money/detail/BottomSheet";
import { CategoryPicker } from "@/components/money/detail/CategoryPicker";
import {
  BackLink,
  Chip,
  LoadState,
  card,
  outlineBtn,
  timeLabel,
  useLoad,
  useMonth,
  withMonth,
} from "@/components/money/detail/common";

export default function TransactionPage() {
  return (
    <Shell>
      <Transaction />
    </Shell>
  );
}

const SOURCE_HINT: Record<CategorySource, string> = {
  OVERRIDE: "직접 수정함",
  RULE: "결제처 규칙",
  LLM: "자동 분류",
  TYPE: "이체",
  NONE: "미분류",
};
const SOURCES = ["credit", "debit", "checking"];
const errMsg = (e: unknown) =>
  e instanceof ApiError
    ? e.message
    : "저장하지 못했어요. 잠시 후 다시 시도해 주세요.";

function Transaction() {
  const month = useMonth();
  const p = useParams<{ source: string; id: string }>();
  const valid = SOURCES.includes(p.source) && /^\d+$/.test(p.id);
  const source = p.source as Source;
  const id = Number(p.id);
  const { data, setData, error, reload } = useLoad<TxnDetail>(
    `${p.source}/${p.id}`,
    () => money.transaction(source, id),
  );

  return (
    <>
      <BackLink fallback={withMonth("/money", month)} label="뒤로" />
      <h1 className="mt-2 text-2xl font-bold">거래 상세</h1>
      <LoadState
        error={valid ? error : "거래를 찾을 수 없어요."}
        loading={!data}
        onRetry={reload}
      />
      {data && !error && valid && (
        <Body
          d={data}
          source={source}
          id={id}
          month={month}
          onChange={setData}
        />
      )}
    </>
  );
}

function Body({
  d,
  source,
  id,
  month,
  onChange,
}: {
  d: TxnDetail;
  source: Source;
  id: number;
  month: string;
  onChange: (d: TxnDetail) => void;
}) {
  const t = d.transaction;
  const [picking, setPicking] = useState(false);
  const [choice, setChoice] = useState<Category | null>(t.category);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(what: string, call: () => Promise<TxnDetail>) {
    setBusy(what);
    setError(null);
    try {
      onChange(await call());
      return true;
    } catch (e) {
      setError(errMsg(e));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function setCategory(scope: "THIS" | "MERCHANT") {
    if (
      choice &&
      (await run(scope, () => money.setCategory(source, id, choice, scope)))
    )
      setPicking(false);
  }

  return (
    <>
      <section className="mt-6">
        <p className="text-slate">{t.merchant ?? "이름 없는 거래"}</p>
        <p
          className={`text-4xl font-semibold tracking-tight tabular-nums ${t.direction === "IN" ? "text-seal" : ""}`}
        >
          {t.direction === "IN" ? "+" : "-"}
          {won(t.amount)}
        </p>
        <dl className={`${card} mt-4 divide-y divide-line text-sm`}>
          <div className="flex justify-between gap-4 px-4 py-3">
            <dt className="text-slate">일시</dt>
            <dd className="tabular-nums">{timeLabel(t.occurred_at)}</dd>
          </div>
          <div className="flex justify-between gap-4 px-4 py-3">
            <dt className="text-slate">결제 수단</dt>
            <dd>{t.payment_label}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-4 py-2">
            <dt className="text-slate">분류</dt>
            <dd className="flex items-center gap-2">
              <span className="text-right">
                <span className="block font-medium">
                  {t.category_label ?? "미분류"}
                </span>
                <span className="block text-xs text-slate">
                  {SOURCE_HINT[t.category_source]}
                </span>
              </span>
              <button
                type="button"
                onClick={() => {
                  setChoice(t.category);
                  setError(null);
                  setPicking(true);
                }}
                className="min-h-11 rounded-full px-3 font-medium text-coral hover:bg-coral-soft"
              >
                분류 수정
              </button>
            </dd>
          </div>
        </dl>
        {d.has_merchant_rule && (
          <p className="mt-2">
            <Chip tone="coral">이 결제처 규칙 적용 중</Chip>
          </p>
        )}
      </section>

      {t.direction === "OUT" && (
        <section className={`${card} mt-6 p-4`}>
          <label className="flex min-h-11 cursor-pointer items-center justify-between gap-4">
            <span className="font-medium">일회성 지출로 표시</span>
            <input
              type="checkbox"
              role="switch"
              checked={t.is_one_off}
              disabled={!!busy}
              onChange={(e) =>
                run("oneoff", () =>
                  money.setOneOff(source, id, e.target.checked),
                )
              }
              className="size-6 accent-coral"
            />
          </label>
          <p className="mt-1 text-sm text-slate">
            이번 달 실제 소비에는 그대로 포함되고, 평소 생활비 예상에서만
            빠져요.
          </p>
          {!picking && <ErrorText message={error} />}
        </section>
      )}

      {d.recurring && (
        <section className="mt-6">
          <h2 className="text-sm text-slate">연결된 정기 거래</h2>
          <Link
            href={withMonth("/money/recurring", month)}
            className={`${card} mt-2 flex min-h-11 items-center justify-between gap-4 px-4 py-3 hover:bg-porcelain`}
          >
            <span className="min-w-0">
              <span className="block truncate font-medium">
                {d.recurring.name}
              </span>
              <span className="block text-sm text-slate">
                매월 {d.recurring.day_of_month}일 ·{" "}
                {d.recurring.status === "EXCLUDED"
                  ? "예상에서 제외"
                  : "예상에 포함"}
              </span>
            </span>
            <span className="shrink-0 font-semibold tabular-nums">
              {won(d.recurring.amount)} ›
            </span>
          </Link>
        </section>
      )}

      <p className="mt-6 text-sm text-slate">
        여기서 바꾸는 분류·표시는 돈 관리 분석에만 쓰여요. 실제 계좌·카드 거래
        기록은 바뀌지 않아요.
      </p>

      <BottomSheet
        open={picking}
        title="분류 수정"
        onClose={() => setPicking(false)}
      >
        <CategoryPicker value={choice} onChange={setChoice} />
        <ErrorText message={error} />
        <div className="mt-4 grid gap-2">
          <button
            type="button"
            disabled={!choice || !!busy}
            onClick={() => setCategory("THIS")}
            className="min-h-11 w-full rounded-xl bg-coral px-4 font-medium text-paper disabled:opacity-50"
          >
            {busy === "THIS" ? "처리 중…" : "이번 거래만 변경"}
          </button>
          <button
            type="button"
            disabled={!choice || !!busy || !d.merchant_key}
            onClick={() => setCategory("MERCHANT")}
            className={outlineBtn}
          >
            {busy === "MERCHANT" ? "처리 중…" : "이 결제처에 앞으로 적용"}
          </button>
          {!d.merchant_key && (
            <p className="text-sm text-slate">
              결제처 이름이 없는 거래는 이번 거래만 바꿀 수 있어요.
            </p>
          )}
        </div>
      </BottomSheet>
    </>
  );
}
