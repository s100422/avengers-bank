"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorText } from "@/components/ui";
import { TermsConsent, TermsKind, api, termsHref } from "@/lib/api";

// 계좌·카드 상세의 "가입 당시 약관 보기". 누를 때 한 번 불러온다. 기록이 없으면 지어내지 않고 없다고 보여 준다.
export function ConsentRecord({ kind, subjectId }: { kind: TermsKind; subjectId: string }) {
  const [open, setOpen] = useState(false);
  const [record, setRecord] = useState<TermsConsent | null>(null);
  const [error, setError] = useState<string | null>(null);

  function toggle() {
    setOpen(!open);
    if (open || record) return;
    setError(null);
    api<TermsConsent>(`/terms/consents/${kind}/${encodeURIComponent(subjectId)}`)
      .then(setRecord)
      .catch((e) => setError(e.message));
  }

  return (
    <section className="mt-10">
      <button type="button" onClick={toggle} aria-expanded={open} className="text-sm text-slate underline underline-offset-4 hover:text-ink">
        가입 당시 약관 보기
      </button>
      {open && (
        <div className="mt-3">
          <ErrorText message={error} />
          {record && !record.has_record && (
            <p className="rounded-xl border border-dashed border-line px-4 py-6 text-center text-slate">
              가입 당시 약관 동의 기록이 없습니다 (약관 기능 도입 전 가입)
            </p>
          )}
          {record?.has_record && (
            <>
              {record.recorded_at && (
                <p className="text-sm text-slate tabular-nums">동의 일시 {new Date(record.recorded_at).toLocaleString("ko-KR")}</p>
              )}
              <ul className="mt-2 divide-y divide-line rounded-xl border border-line bg-paper">
                {record.items.map((t) => {
                  const href = termsHref(t.terms_version_id);
                  return (
                    <li key={t.terms_version_id} className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
                      <div className="min-w-0">
                        <p className="font-medium">
                          <span className="text-slate">[{t.required ? "필수" : "선택"}]</span> {t.title}
                        </p>
                        <p className="text-slate tabular-nums">
                          {t.version} · 시행일 {t.effective_from}
                          {href && (
                            <>
                              {" · "}
                              <Link href={href} className="underline underline-offset-4 hover:text-ink">
                                전문 보기
                              </Link>
                            </>
                          )}
                        </p>
                      </div>
                      <span className={`shrink-0 font-medium ${t.agreed ? "text-coral" : "text-slate"}`}>{t.agreed ? "동의" : "미동의"}</span>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}
