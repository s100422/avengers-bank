"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ASSISTANT_ASK, Citation, TransferAction, agent, session, termsHref } from "@/lib/api";
import { RichText } from "./RichText";
import { TransferCard } from "./TransferCard";

type Msg = { id: number; role: "user" | "ai"; text: string; action?: TransferAction; citations?: Citation[] };

const SUGGESTIONS = ["내 자산 요약해 줘", "최근 거래내역 알려줘", "다음 카드값을 낼 수 있어?", "내 예·적금 만기 알려줘"];

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

// 넓은 화면에서 패널 폭(px). 왼쪽 가장자리를 끌거나 ←→ 키로 바꾸고, 이 브라우저에 기억한다
const WIDTH_KEY = "avengers_bank_assistant_width";
const DEFAULT_W = 340;
const MIN_W = 300;
const MAX_W = 720;
// 왼쪽 메뉴(240px)와 본문 최소 폭(320px)은 남긴다
const clampWidth = (w: number) => Math.round(Math.max(MIN_W, Math.min(w, MAX_W, window.innerWidth - 560)));

function Assistant() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState<{ text: string; error: string } | null>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);
  const [width, setWidth] = useState(DEFAULT_W);
  const [resizing, setResizing] = useState(false);
  const restored = useRef(false);

  useEffect(() => {
    try {
      const saved = Number(localStorage.getItem(WIDTH_KEY));
      // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage는 마운트 뒤에만 읽을 수 있다
      if (saved) setWidth(clampWidth(saved));
    } catch {}
  }, []);

  function resizeTo(w: number) {
    const next = clampWidth(w);
    setWidth(next);
    try {
      localStorage.setItem(WIDTH_KEY, String(next));
    } catch {}
  }

  // 다른 화면(약관 전문)이 질문을 채워 비서를 열게 한다. 보내기는 사용자가 누른다
  useEffect(() => {
    const onAsk = (e: Event) => {
      const text = (e as CustomEvent).detail;
      if (typeof text === "string") setInput(text.slice(0, 1000));
      setOpen(true);
    };
    window.addEventListener(ASSISTANT_ASK, onAsk);
    return () => window.removeEventListener(ASSISTANT_ASK, onAsk);
  }, []);

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
              ms.map((m) => ({ id: nextId++, role: m.role === "user" ? "user" : "ai", text: m.content, citations: m.citations })),
        );
      })
      .catch(() => {
        convo.set(null); // 다른 사용자 대화이거나 사라진 대화
      });
  });

  // 열면 입력창으로, 닫으면 여는 버튼으로 포커스를 옮긴다
  useEffect(() => {
    if (open) inputRef.current?.focus();
    else if (wasOpen.current) launcherRef.current?.focus();
    wasOpen.current = open;
  }, [open]);

  // 넓은 화면에서 본문을 패널 폭만큼 밀어낸다 (globals.css). 로그아웃으로 사라질 때도 지운다
  useEffect(() => {
    document.body.toggleAttribute("data-assistant-open", open);
    document.body.toggleAttribute("data-assistant-resizing", resizing);
    // 나중에 창을 줄여도 본문 자리가 남도록 CSS에서도 한 번 더 제한한다
    document.body.style.setProperty("--assistant-w", `clamp(${MIN_W}px, ${width}px, 100vw - 560px)`);
    return () => {
      document.body.removeAttribute("data-assistant-open");
      document.body.removeAttribute("data-assistant-resizing");
      document.body.style.removeProperty("--assistant-w");
    };
  }, [open, width, resizing]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, sending, failed]);

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
      add({ role: "ai", text: r.answer, action: r.action ?? undefined, citations: r.citations });
    } catch (e) {
      // 로그인 만료(401)는 api()가 세션을 지우고 로그인 화면으로 보낸다
      setFailed({ text, error: (e as Error).message });
    } finally {
      setSending(false);
    }
  }

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
          onClick={() => setOpen(true)}
          className="fixed right-4 bottom-24 z-20 flex min-h-11 items-center gap-1.5 rounded-full bg-coral px-3.5 text-sm font-semibold text-paper shadow-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-coral md:right-8 md:bottom-8"
        >
          <svg viewBox="0 0 24 24" className="size-4 fill-none stroke-current stroke-[1.8]" aria-hidden>
            <path d="M5 5h14v10H9l-4 4z" strokeLinejoin="round" />
          </svg>
          AI 금융 비서
        </button>
      )}

      {open && (
        <section
          role="dialog"
          aria-label="AI 금융 비서"
          onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
          className="fixed inset-0 z-30 flex flex-col bg-porcelain text-sm lg:left-auto lg:w-(--assistant-w) lg:border-l lg:border-line"
        >
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="AI 금융 비서 폭 조절"
            aria-valuenow={width}
            aria-valuemin={MIN_W}
            aria-valuemax={MAX_W}
            tabIndex={0}
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              setResizing(true);
            }}
            onPointerMove={(e) => resizing && setWidth(clampWidth(window.innerWidth - e.clientX))}
            onPointerUp={(e) => {
              e.currentTarget.releasePointerCapture(e.pointerId);
              setResizing(false);
              resizeTo(window.innerWidth - e.clientX);
            }}
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
          </div>
          <header className="flex items-center gap-1 border-b border-line bg-paper px-3 py-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
            <h2 className="flex-1 px-1 text-base font-bold">AI 금융 비서</h2>
            <button type="button" onClick={reset} aria-label="새 대화 시작" className="min-h-11 rounded-full px-3 text-sm text-slate hover:bg-coral-soft hover:text-ink">
              새 대화
            </button>
            <button type="button" onClick={() => setOpen(false)} aria-label="AI 금융 비서 닫기" className={iconBtn}>
              <svg viewBox="0 0 24 24" className="size-5 fill-none stroke-current stroke-2" aria-hidden>
                <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
              </svg>
            </button>
          </header>

          <div aria-live="polite" className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
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
                <p key={m.id} className="msg-in ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-coral px-3.5 py-2 whitespace-pre-wrap text-paper">
                  <span className="sr-only">나: </span>
                  {m.text}
                </p>
              ) : (
                <div key={m.id} className="msg-in max-w-[92%] space-y-2">
                  <div className="w-fit rounded-2xl rounded-bl-sm border border-line bg-paper px-3.5 py-2.5">
                    <span className="sr-only">AI 비서: </span>
                    <RichText text={m.text} />
                  </div>
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
              placeholder="무엇이든 물어보세요"
              className="max-h-32 min-h-11 flex-1 resize-none rounded-xl border border-line px-3 py-2.5 outline-none focus:border-coral focus-visible:ring-2 focus-visible:ring-coral/20"
            />
            <button
              type="submit"
              disabled={sending || !input.trim()}
              aria-label="질문 보내기"
              className="min-h-11 rounded-xl bg-coral px-4 font-medium text-paper disabled:opacity-50"
            >
              전송
            </button>
          </form>
        </section>
      )}
    </>
  );
}
