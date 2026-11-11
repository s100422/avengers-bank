"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type KeyboardEvent, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { SpiderMascot } from "@/components/SpiderMascot";
import { ASSISTANT_ASK, type AssistantAction, type Citation, type FinancialReport, agent, session, termsHref } from "@/lib/api";
import type { AssistantAsk } from "@/lib/ask-assistant";
import { FinancialReportCard } from "./FinancialReportCard";
import { OpenAccountCard } from "./OpenAccountCard";
import { RichText } from "./RichText";
import { TransferCard } from "./TransferCard";

type Msg = {
  id: number;
  role: "user" | "ai";
  text: string;
  action?: AssistantAction;
  citations?: Citation[];
  reports?: FinancialReport[];
};

const SPENDING_QUESTION = "이번 달 소비 요약해줘";
const SUGGESTIONS = [SPENDING_QUESTION, "내 자산 요약해 줘", "최근 거래내역 알려줘", "다음 카드값을 낼 수 있어?", "내 예·적금 만기 알려줘"];

// 루트 레이아웃에 한 번 붙는다: 화면을 옮겨도 대화가 남는다.
// 토큰이 없거나 로그인·회원가입 화면이면 그리지 않는다(언마운트되므로 로그아웃하면 대화도 지워진다).
export function AssistantGate() {
  const path = usePathname();
  const [authed, setAuthed] = useState(false);
  useEffect(() => {
    // localStorage는 마운트 뒤에만 읽을 수 있다. 경로가 바뀔 때마다(로그인·로그아웃 뒤) 다시 본다.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAuthed(!!session.active() && !["/", "/login", "/signup"].includes(path));
  }, [path]);
  return authed ? <Assistant /> : null;
}

let nextId = 1;

// 새로고침해도 대화를 이어 보도록 이 탭에 대화 번호만 기억한다. 메시지는 서버에서 다시 불러온다
const CONVO_KEY = "avengers_bank_conversation_id";
const convo = {
  get: () => {
    try {
      return Number(sessionStorage.getItem(CONVO_KEY)) || null;
    } catch {
      return null;
    }
  },
  set: (id: number | null) => {
    try {
      if (id) sessionStorage.setItem(CONVO_KEY, String(id));
      else sessionStorage.removeItem(CONVO_KEY);
    } catch {}
  },
};

const WIDTH_KEY = "spiderbank_assistant_width";
const MIN_W = 340;
const MAX_W = 480;
const SPLIT_AT = 1120;
const MIN_PAGE_W = 760;

function subscribeToViewport(update: () => void) {
  window.addEventListener("resize", update);
  return () => window.removeEventListener("resize", update);
}

const readViewport = () => window.innerWidth;
const serverViewport = () => 0;

function Assistant() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState<{ text: string; error: string } | null>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const latestReportRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);
  const [preferredWidth, setPreferredWidth] = useState<number | null>(null);
  const [resizing, setResizing] = useState(false);
  const restored = useRef(false);
  const viewport = useSyncExternalStore(subscribeToViewport, readViewport, serverViewport);
  const split = viewport >= SPLIT_AT;
  const maxWidth = split ? Math.min(MAX_W, viewport - MIN_PAGE_W) : MAX_W;
  const clampWidth = (value: number) => Math.round(Math.max(MIN_W, Math.min(maxWidth, value)));
  const width = clampWidth(preferredWidth ?? viewport * 0.3);

  useEffect(() => {
    try {
      const saved = Number(localStorage.getItem(WIDTH_KEY));
      // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage는 마운트 뒤에만 읽을 수 있다
      if (saved >= MIN_W && saved <= MAX_W) setPreferredWidth(saved);
    } catch {}
  }, []);

  function resizeTo(w: number) {
    const next = clampWidth(w);
    setPreferredWidth(next);
    try {
      localStorage.setItem(WIDTH_KEY, String(next));
    } catch {}
  }

  // 처음 열 때 이 탭이 기억한 대화를 서버에서 불러온다 (근거 약관 포함)
  useEffect(() => {
    if (!open || restored.current) return;
    restored.current = true;
    const id = convo.get();
    if (!id) return;
    agent
      .messages(id)
      .then((ms) => {
        // 불러오는 사이 새 질문을 보냈다면 그 대화를 그대로 둔다
        setConversationId((c) => c ?? id);
        setMessages((now) =>
          now.length
            ? now
            : // shortcut: 지난 이체 확인 카드는 다시 그리지 않는다(이미 처리한 초안을 또 누르지 않게). 필요하면 초안 상태 API로 판단한다
              ms.map((m) => ({
                id: nextId++,
                role: m.role === "user" ? "user" : "ai",
                text: m.content,
                citations: m.citations,
                reports: m.reports,
                action: m.action?.type === "OPEN_ACCOUNT" ? m.action : undefined, // 가입 카드는 링크일 뿐이라 다시 그려도 안전하다
              })),
        );
      })
      .catch(() => {
        convo.set(null); // 다른 사용자 대화이거나 사라진 대화
      });
  });

  // 열면 입력창으로, 닫으면 여는 버튼으로 포커스를 옮긴다
  useEffect(() => {
    if (open) inputRef.current?.focus();
    else if (wasOpen.current) {
      const previous = returnFocusRef.current;
      (previous?.isConnected ? previous : launcherRef.current)?.focus();
    }
    wasOpen.current = open;
  }, [open]);

  useEffect(() => {
    if (open && !split && !panelRef.current?.contains(document.activeElement)) {
      inputRef.current?.focus();
    }
  }, [open, split]);

  // 좁은 창의 겹침 패널은 본문 스크롤과 키보드 탐색을 잠근다.
  useLayoutEffect(() => {
    if (!open) return;
    const page = document.getElementById("bank-page");
    document.body.toggleAttribute("data-assistant-open", split);
    document.body.toggleAttribute("data-assistant-modal", !split);
    document.body.toggleAttribute("data-assistant-resizing", split && resizing);
    document.body.style.setProperty("--assistant-w", `${width}px`);
    if (page) page.inert = !split;
    return () => {
      document.body.removeAttribute("data-assistant-open");
      document.body.removeAttribute("data-assistant-modal");
      document.body.removeAttribute("data-assistant-resizing");
      document.body.style.removeProperty("--assistant-w");
      if (page) page.inert = false;
    };
  }, [open, split, width, resizing]);

  useEffect(() => {
    if (!sending && !failed && latestReportRef.current) {
      latestReportRef.current.scrollIntoView({ block: "start" });
    } else {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [open, messages, sending, failed]);

  const add = (m: Omit<Msg, "id">) => setMessages((ms) => [...ms, { ...m, id: nextId++ }]);

  async function send(text: string, retry = false) {
    text = text.trim();
    if (!text || sending) return;
    if (!retry) {
      add({ role: "user", text });
      setInput("");
    }
    setFailed(null);
    setSending(true);
    try {
      const r = await agent.chat(text, conversationId);
      setConversationId(r.conversation_id);
      convo.set(r.conversation_id);
      add({
        role: "ai",
        text: r.answer,
        action: r.action ?? undefined,
        citations: r.citations,
        reports: r.reports,
      });
    } catch (e) {
      // 로그인 만료(401)는 api()가 세션을 지우고 로그인 화면으로 보낸다
      setFailed({ text, error: (e as Error).message });
    } finally {
      setSending(false);
    }
  }

  function showAssistant() {
    if (open) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setOpen(true);
  }

  function handlePanelKey(e: KeyboardEvent<HTMLElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
    if (e.key !== "Tab" || split) return;
    const controls = Array.from(e.currentTarget.querySelectorAll<HTMLElement>(
      'a[href], button:not(:disabled), textarea:not(:disabled), input:not(:disabled), select:not(:disabled), summary, [tabindex="0"]',
    )).filter((element) => element.getClientRects().length && element.tabIndex >= 0);
    const first = controls[0];
    const last = controls.at(-1);
    if (e.shiftKey && e.target === first) {
      e.preventDefault();
      last?.focus();
    } else if (!e.shiftKey && e.target === last) {
      e.preventDefault();
      first?.focus();
    }
  }

  // 다른 화면이 비서를 연다. 약관 전문은 문자열(입력창만 채우고 보내기는 사용자가 누른다),
  // 돈 관리는 {text}(askAssistant: 바로 보낸다. 답을 기다리는 중이면 입력창에 넣어 둔다).
  // 의존성 없이 매 렌더 다시 붙여서 최신 sending·conversationId로 보낸다
  useEffect(() => {
    const onAsk = (e: Event) => {
      const detail = (e as CustomEvent<string | AssistantAsk>).detail;
      showAssistant();
      if (typeof detail === "string") {
        setInput(detail.slice(0, 1000));
      } else if (typeof detail?.text === "string") {
        const text = detail.text.slice(0, 1000).trim();
        if (sending) setInput(text);
        else send(text);
      }
    };
    window.addEventListener(ASSISTANT_ASK, onAsk);
    return () => window.removeEventListener(ASSISTANT_ASK, onAsk);
  });

  function reset() {
    setMessages([]);
    setConversationId(null);
    convo.set(null);
    setFailed(null);
    setInput("");
    inputRef.current?.focus();
  }

  const iconBtn = "grid size-11 place-items-center rounded-full text-slate hover:bg-coral-soft hover:text-ink focus-visible:outline-2 focus-visible:outline-coral";

  return (
    <>
      {!open && (
        <button
          ref={launcherRef}
          type="button"
          aria-label="AI 금융 비서 열기"
          aria-haspopup="dialog"
          onClick={showAssistant}
          className="fixed right-4 bottom-24 z-20 flex size-12 items-center justify-center gap-1.5 rounded-full bg-coral text-sm font-semibold text-paper shadow-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-coral md:right-8 md:bottom-8 xl:h-auto xl:min-h-11 xl:w-auto xl:px-3.5"
        >
          <svg viewBox="0 0 24 24" className="size-5 fill-none stroke-current stroke-[1.8] xl:size-4" aria-hidden>
            <path d="M5 5h14v10H9l-4 4z" strokeLinejoin="round" />
          </svg>
          {/* 좁은 화면에서는 아이콘만: 글자까지 보이면 목록의 금액을 가린다. 내용 옆에 여백이 생기는 xl부터 글자를 보인다 */}
          <span className="hidden xl:inline">AI 금융 비서</span>
        </button>
      )}

      {open && !split && <div aria-hidden="true" className="fixed inset-0 z-30 hidden bg-ink/20 md:block" onClick={() => setOpen(false)} />}
      {open && (
        <section
          ref={panelRef}
          role="dialog"
          aria-modal={split ? undefined : true}
          aria-label="AI 금융 비서"
          onKeyDown={handlePanelKey}
          className="fixed inset-0 z-40 flex flex-col bg-porcelain text-sm md:left-auto md:w-(--assistant-w) md:border-l md:border-line"
        >
          {split && <div
            role="separator"
            aria-orientation="vertical"
            aria-label="AI 금융 비서 폭 조절"
            aria-valuenow={width}
            aria-valuemin={MIN_W}
            aria-valuemax={maxWidth}
            tabIndex={0}
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              setResizing(true);
            }}
            onPointerMove={(e) => {
              if (e.currentTarget.hasPointerCapture(e.pointerId)) setPreferredWidth(clampWidth(window.innerWidth - e.clientX));
            }}
            onPointerUp={(e) => {
              e.currentTarget.releasePointerCapture(e.pointerId);
              resizeTo(window.innerWidth - e.clientX);
            }}
            onLostPointerCapture={() => setResizing(false)}
            onKeyDown={(e) => {
              // 패널이 오른쪽에 붙어 있어서 ←는 넓히기, →는 좁히기
              if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                e.preventDefault();
                resizeTo(width + (e.key === "ArrowLeft" ? 24 : -24));
              }
            }}
            className={`group absolute inset-y-0 -left-1.5 z-10 hidden w-3 cursor-col-resize touch-none lg:block focus-visible:outline-none`}
          >
            <span
              aria-hidden
              className={`absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 transition-colors group-hover:bg-coral group-focus-visible:bg-coral ${resizing ? "bg-coral" : "bg-transparent"}`}
            />
          </div>}
          <header className="flex items-center gap-1 border-b border-line bg-paper px-3 py-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
            <div className="flex min-w-0 flex-1 items-center gap-2 px-1">
              <SpiderMascot className="size-7 shrink-0 text-coral" />
              <h2 className="text-base font-bold">AI 금융 비서</h2>
            </div>
            <button type="button" onClick={reset} disabled={sending} aria-label="새 대화 시작" className="min-h-11 shrink-0 rounded-full px-3 text-sm text-slate hover:bg-coral-soft hover:text-ink disabled:opacity-50">
              새 대화
            </button>
            <button type="button" onClick={() => setOpen(false)} aria-label="AI 금융 비서 닫기" className={iconBtn}>
              <svg viewBox="0 0 24 24" className="size-5 fill-none stroke-current stroke-2" aria-hidden>
                <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
              </svg>
            </button>
          </header>

          <div aria-live="polite" className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-4">
            {messages.length === 0 && (
              <div className="space-y-3">
                <p className="text-slate">계좌·카드·이체를 물어보세요. 이체는 확인 카드에서 직접 눌러야 실행됩니다.</p>
                <ul className="flex flex-wrap gap-2">
                  {SUGGESTIONS.map((q) => (
                    <li key={q}>
                      <button
                        type="button"
                        onClick={() => send(q)}
                        disabled={sending}
                        className="min-h-11 rounded-full border border-line bg-paper px-3 text-[13px] hover:border-coral disabled:opacity-50"
                      >
                        {q}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {messages.map((m) =>
              m.role === "user" ? (
                <p key={m.id} className="msg-in ml-auto w-fit max-w-[88%] rounded-2xl bg-coral-soft px-3.5 py-2.5 leading-relaxed wrap-anywhere whitespace-pre-wrap text-ink">
                  <span className="sr-only">나: </span>
                  {m.text}
                </p>
              ) : (
                <div
                  key={m.id}
                  ref={m.reports?.length && m === messages.at(-1) ? latestReportRef : undefined}
                  className={`msg-in space-y-2 ${m.reports?.length ? "w-full" : "max-w-[94%]"}`}
                >
                  <span className="sr-only">AI 비서: </span>
                  {m.reports?.length ? (
                    <>
                      <FinancialReportCard report={m.reports[0]} />
                      {m.text.trim() && (
                        <details className="rounded-2xl border border-line bg-paper px-4">
                          <summary className="cursor-pointer py-3 font-semibold text-slate focus-visible:outline-coral">AI 설명 보기</summary>
                          <div className="pb-4 wrap-anywhere"><RichText text={m.text} /></div>
                        </details>
                      )}
                      {m.reports.length > 1 && (
                        <details className="rounded-2xl border border-line bg-paper px-4">
                          <summary className="cursor-pointer py-3 font-semibold text-slate focus-visible:outline-coral">함께 조회한 리포트 {m.reports.length - 1}개 보기</summary>
                          <div className="space-y-3 pb-4">
                            {m.reports.slice(1).map((report, index) => <FinancialReportCard key={index} report={report} />)}
                          </div>
                        </details>
                      )}
                    </>
                  ) : (
                    <div className="w-fit rounded-2xl border border-line bg-paper px-3.5 py-2.5 wrap-anywhere">
                      <RichText text={m.text} />
                    </div>
                  )}
                  {!!m.citations?.length && (
                    <ul aria-label="근거 약관" className="flex flex-wrap gap-1.5">
                      {m.citations.map((c, i) => {
                        const href = termsHref(c.document_version_id, c.section_id);
                        if (!href) return null;
                        return (
                          <li key={i}>
                            <Link
                              href={href}
                              className="inline-block rounded-full border border-line bg-paper px-2.5 py-1 text-xs text-slate hover:border-coral hover:text-ink"
                            >
                              {c.title} · {c.version} · {c.section_title}
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                  {m.action?.type === "TRANSFER_CONFIRMATION" && (
                    <TransferCard action={m.action} onDone={(text) => add({ role: "ai", text })} />
                  )}
                  {m.action?.type === "OPEN_ACCOUNT" && (
                    // 좁은 화면에서는 비서가 화면을 덮으므로, 가입 화면으로 가기 전에 닫는다
                    <OpenAccountCard action={m.action} onGo={() => !split && setOpen(false)} />
                  )}
                </div>
              ),
            )}

            {sending && (
              <p className="msg-in typing flex w-fit items-center gap-1 rounded-2xl rounded-bl-sm border border-line bg-paper px-4 py-3.5">
                <span className="sr-only">답변을 만드는 중…</span>
                <span aria-hidden className="size-1.5 rounded-full bg-coral" />
                <span aria-hidden className="size-1.5 rounded-full bg-coral" />
                <span aria-hidden className="size-1.5 rounded-full bg-coral" />
              </p>
            )}

            {failed && (
              <div role="alert" className="msg-in flex items-center gap-2 rounded-2xl border border-seal/40 bg-paper px-4 py-2 text-sm text-seal">
                <span className="flex-1">{failed.error}</span>
                <button
                  type="button"
                  onClick={() => send(failed.text, true)}
                  aria-label="마지막 질문 다시 보내기"
                  className="min-h-11 shrink-0 rounded-xl border border-seal px-3 font-medium"
                >
                  다시 시도
                </button>
              </div>
            )}
            <div ref={endRef} />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="flex items-end gap-2 border-t border-line bg-paper p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
          >
            <label htmlFor="assistant-input" className="sr-only">
              질문 입력
            </label>
            <textarea
              id="assistant-input"
              ref={inputRef}
              rows={1}
              maxLength={1000}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                // 한글 조합 중 Enter는 글자 확정이라 보내지 않는다
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(input);
                }
              }}
              placeholder="돈 관리에 대해 물어보세요"
              className="max-h-32 min-h-11 min-w-0 flex-1 resize-none rounded-xl border border-line px-3 py-2.5 outline-none focus:border-coral focus-visible:ring-2 focus-visible:ring-coral/20"
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              aria-label="질문 보내기"
              className="grid size-11 shrink-0 place-items-center rounded-xl bg-coral text-paper focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-coral disabled:opacity-50"
            >
              <span aria-hidden="true" className="text-xl leading-none">↑</span>
            </button>
          </form>
        </section>
      )}
    </>
  );
}
