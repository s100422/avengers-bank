"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Brand, ErrorText } from "@/components/ui";
import { TermsMarkdown } from "@/components/terms/TermsMarkdown";
import { ASSISTANT_ASK, SECTION_ID, TermsVersion, api, session } from "@/lib/api";

// 약관 전문. 로그인 없이 볼 수 있고, 불러올 때 AI를 부르지 않는다.
// useParams는 프리렌더 중 멈출 수 있어 Suspense로 감싼다 (cacheComponents)
export default function TermsPage() {
  return (
    <Suspense fallback={null}>
      <Terms />
    </Suspense>
  );
}

function Terms() {
  const { versionId } = useParams<{ versionId: string }>();
  const router = useRouter();
  // 가입 화면에서 왔으면 그 상품으로 돌아간다. 다른 사이트로 보내지 않게 가입 화면 경로만 받는다
  const from = useSearchParams().get("from");
  const back = from && /^\/open\/(checking|deposit|savings|credit|debit)\/\d+$/.test(from) ? from : null;
  const [doc, setDoc] = useState<TermsVersion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    // AI 비서는 로그인했을 때만 떠 있다 (AssistantGate)
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage는 마운트 뒤에만 읽을 수 있다
    setAuthed(!!session.active());
  }, []);

  useEffect(() => {
    if (!/^\d+$/.test(versionId)) return;
    api<TermsVersion>(`/terms/versions/${versionId}`).then(setDoc).catch((e) => setError(e.message));
  }, [versionId]);

  // 주소의 #조항으로 내려간다 (본문이 그려진 뒤)
  useEffect(() => {
    const id = decodeURIComponent(location.hash.slice(1));
    if (doc && SECTION_ID.test(id)) document.getElementById(id)?.scrollIntoView();
  }, [doc]);

  function ask() {
    if (!doc) return;
    window.dispatchEvent(
      new CustomEvent(ASSISTANT_ASK, { detail: `「${doc.title}」 ${doc.version} 약관에서 궁금한 점이 있어요. ` }),
    );
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-4 pt-5 pb-28 md:px-10 md:pt-10">
      <header className="mb-6">
        <Brand />
      </header>
      {!/^\d+$/.test(versionId) && <ErrorText message="없는 약관입니다." />}
      <ErrorText message={error} />
      {doc && (
        <article>
          <h1 className="text-2xl font-semibold">
            {doc.title}
            {doc.status === "retired" && (
              <span className="ml-2 align-middle rounded-full border border-line px-2 py-0.5 text-xs font-medium text-slate">이전 버전</span>
            )}
          </h1>
          <p className="mt-1 text-sm text-slate tabular-nums">
            {doc.version} · 시행일 {doc.effective_from}
          </p>
          <p role="note" className="mt-4 rounded-xl border border-seal/40 bg-paper px-4 py-3 text-sm font-medium text-seal">
            본 문서는 AvengersBank 학습용 서비스의 데모 약관입니다. 실제 금융기관 상품의 계약 문서가 아닙니다.
          </p>
          {authed && (
            <button
              type="button"
              onClick={ask}
              className="mt-4 min-h-11 rounded-full border border-line bg-paper px-4 text-sm font-medium hover:border-coral"
            >
              AI에게 이 약관 질문하기
            </button>
          )}

          {doc.sections.length > 0 && (
            <nav aria-label="목차" className="mt-6 rounded-2xl bg-paper p-5">
              <h2 className="text-sm text-slate">목차</h2>
              <ol className="mt-2 space-y-1 text-sm">
                {doc.sections
                  .filter((s) => SECTION_ID.test(s.section_id))
                  .map((s) => (
                    <li key={s.section_id}>
                      <a href={`#${s.section_id}`} className="hover:text-coral hover:underline">
                        {s.title}
                      </a>
                    </li>
                  ))}
              </ol>
            </nav>
          )}

          <div className="mt-6 rounded-2xl bg-paper p-5">
            <TermsMarkdown text={doc.body} />
          </div>
        </article>
      )}
      {back ? (
        <Link href={back} className="mt-8 inline-block text-sm text-slate hover:text-ink">
          ← 가입 화면으로
        </Link>
      ) : (
        // 이전 페이지가 있으면 거기로, 새 탭 등으로 바로 열었으면 상품 목록으로
        <button
          type="button"
          onClick={() => (history.length > 1 ? router.back() : router.push("/products"))}
          className="mt-8 inline-block text-sm text-slate hover:text-ink"
        >
          ← 이전 페이지
        </button>
      )}
    </div>
  );
}
