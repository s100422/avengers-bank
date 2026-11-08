"use client";

import Link from "next/link";
import { useState } from "react";
import { AccountOrderSettings } from "@/components/home/AccountOrderSettings";
import { Skeleton } from "@/components/home/bits";
import { ConfirmModal } from "@/components/home/ConfirmModal";
import { useHomeData } from "@/components/home/useHomeData";
import { ErrorText, Shell } from "@/components/ui";
import { toggle } from "@/lib/home-prefs";

export default function AccountSettingsPage() {
  return (
    <Shell>
      <Settings />
    </Shell>
  );
}

function Settings() {
  const { prefs, ordered, update, error } = useHomeData();
  const [confirm, setConfirm] = useState<{ key: string; unset: boolean } | null>(null);

  return (
    <>
      <Link href="/accounts" className="inline-flex min-h-11 items-center text-sm text-slate hover:text-ink">
        ← 홈
      </Link>
      <h1 className="mt-1 mb-4 text-2xl font-semibold">대표 계좌 및 순서 설정</h1>
      <ErrorText message={error} />
      {!prefs && !error && <Skeleton className="h-64 w-full rounded-3xl" />}
      {prefs && ordered.length === 0 && <p className="text-slate">설정할 계좌가 없어요.</p>}
      {prefs && ordered.length > 0 && (
        <AccountOrderSettings
          accounts={ordered}
          reps={new Set(prefs.reps)}
          onStar={(key) => setConfirm({ key, unset: prefs.reps.includes(key) })}
          onReorder={(order) => update((p) => ({ ...p, order }))}
        />
      )}
      <ConfirmModal
        open={confirm !== null}
        title={confirm?.unset ? "대표 계좌를 해지할까요?" : "대표 계좌로 설정할까요?"}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm) update((p) => ({ ...p, reps: toggle(p.reps, confirm.key) }));
          setConfirm(null);
        }}
      />
    </>
  );
}
