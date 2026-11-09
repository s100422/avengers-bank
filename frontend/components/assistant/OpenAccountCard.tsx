"use client";

import { useRouter } from "next/navigation";
import { OpenAccountAction } from "@/lib/api";
import { saveOpenDraft } from "@/lib/open-draft";

// 비서가 정리한 예·적금 가입 값. 가입은 하지 않고, 버튼이 값이 채워진 가입 화면을 연다.
// 약관 동의와 계좌 비밀번호는 그 화면에서 직접 입력한다.
export function OpenAccountCard({ action, onGo }: { action: OpenAccountAction; onGo: () => void }) {
  const router = useRouter();
  const label = action.kind === "deposit" ? "예금" : "적금";

  function go() {
    saveOpenDraft(action.kind, action.product_id, action.fields);
    onGo();
    router.push(`/open/${action.kind}/${action.product_id}`);
  }

  return (
    <div role="group" aria-label={`${label} 가입 준비`} className="rounded-2xl border border-coral/40 bg-paper p-4">
      <p className="font-semibold">{label} 가입 준비</p>
      <p className="mt-0.5 text-xs text-slate">연 {action.interest_rate}%</p>
      <dl className="mt-3 space-y-1.5 text-sm">
        {action.summary.map((r) => (
          <div key={r.label} className="flex justify-between gap-3">
            <dt className="text-slate">{r.label}</dt>
            <dd className="text-right">{r.value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-slate">약관 동의와 계좌 비밀번호는 가입 화면에서 직접 입력해요.</p>
      <button type="button" onClick={go} className="mt-4 min-h-11 w-full rounded-xl bg-coral font-medium text-paper">
        가입 화면에서 이어서 하기
      </button>
    </div>
  );
}
