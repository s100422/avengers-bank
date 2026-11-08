"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ErrorText, mmss } from "@/components/ui";
import { api } from "@/lib/api";

// 휴대폰 번호 형식(서버 검사와 같은 범위). 맞을 때만 인증번호 받기를 누를 수 있게 한다
export const PHONE = /^01\d-?\d{3,4}-?\d{4}$/;
// 정보가 틀려도 같은 문구. 번호당 발송 제한(15분 3번)에 걸려도 서버는 같은 응답을 주므로(정답 여부를 숨기려고) 그 안내도 함께
export const RECOVERY_SENT =
  "입력하신 정보가 맞으면 등록된 휴대폰으로 인증번호를 보냈습니다. 문자가 오지 않으면 15분 뒤에 다시 시도해 주세요.";
export const digits = (s: string) => s.replace(/\D/g, "");

const smallButton = "min-h-11 shrink-0 rounded-xl border border-line bg-paper px-3 text-sm font-medium hover:border-coral disabled:opacity-50";

/**
 * 인증번호 받기 → 6자리 입력 → 확인. 발송·확인 방법은 부모가 넘긴다(휴대폰 인증과 계정 복구가 다르다).
 * 입력값(번호·계좌 등)이 바뀌면 부모가 key를 바꿔 처음부터 다시 하게 한다.
 * 다른 폼 안에 들어가도 되도록 form을 쓰지 않는다(Enter는 직접 처리).
 */
export function CodeVerify({
  send,
  verify,
  disabled,
  sentText = "인증번호를 보냈습니다.",
  devPhone,
}: {
  send: () => Promise<number>; // 유효 시간(초)을 돌려준다
  verify: (code: string) => Promise<void>;
  disabled?: boolean;
  sentText?: string;
  devPhone?: string; // 개발용 문자함에서 볼 번호. 모르면 문자함에서 직접 입력
}) {
  const [deadline, setDeadline] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const codeId = useId();
  const left = deadline ? deadline - now : 0;

  useEffect(() => {
    if (!deadline || done) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [deadline, done]);

  async function onSend() {
    setBusy(true);
    setError(null);
    try {
      const sec = await send();
      setDeadline(Date.now() + sec * 1000);
      setNow(Date.now());
      setCode("");
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }

  async function onVerify() {
    if (!/^\d{6}$/.test(code)) return setError("인증번호 6자리를 입력해 주세요.");
    setBusy(true);
    setError(null);
    try {
      await verify(code);
      setDone(true);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  }

  if (done) {
    return (
      <p role="status" className="rounded-xl bg-coral-soft px-3 py-2.5 text-sm">
        인증되었습니다.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <button type="button" onClick={onSend} disabled={disabled || busy} className={`${smallButton} w-full`}>
        {deadline ? "인증번호 다시 받기" : "인증번호 받기"}
      </button>
      {deadline && (
        <>
          <p role="status" className="text-sm text-slate">
            {sentText}
          </p>
          <label htmlFor={codeId} className="block text-sm text-slate">
            인증번호 6자리{" "}
            <span className="tabular-nums text-coral" aria-label={`유효시간 ${mmss(left)} 남음`}>
              {left > 0 ? mmss(left) : "시간 초과"}
            </span>
          </label>
          <div className="flex gap-2">
            <input
              id={codeId}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                e.preventDefault(); // 바깥 폼(가입 등)이 제출되지 않게
                if (left > 0 && !busy) onVerify();
              }}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              className="w-full rounded-xl border border-line bg-paper px-3 py-2.5 tracking-widest tabular-nums outline-none focus:border-coral focus-visible:ring-2 focus-visible:ring-coral/20"
            />
            <button type="button" onClick={onVerify} disabled={busy || left <= 0} className={smallButton}>
              확인
            </button>
          </div>
          {left <= 0 && <p className="text-sm text-seal">유효시간이 지났습니다. 인증번호를 다시 받아 주세요.</p>}
          <DevInbox phone={devPhone} />
        </>
      )}
      <ErrorText message={error} />
    </div>
  );
}

/** 표준 휴대폰 인증: path로 보내고 /verification/phone/verify로 확인해 증표를 부모에게 넘긴다 */
export function PhoneVerify({
  path,
  body,
  devPhone,
  disabled,
  onVerified,
}: {
  path: "/verification/phone/send" | "/verification/phone/send-for-me";
  body: { purpose: string; phone?: string };
  devPhone?: string;
  disabled?: boolean;
  onVerified: (token: string) => void;
}) {
  const id = useRef(0);
  return (
    <CodeVerify
      disabled={disabled}
      devPhone={devPhone ?? body.phone}
      send={async () => {
        const r = await api<{ verification_id: number; expires_in: number }>(path, body);
        id.current = r.verification_id;
        return r.expires_in;
      }}
      verify={async (code) => {
        const r = await api<{ verification_token: string }>("/verification/phone/verify", { verification_id: id.current, code });
        onVerified(r.verification_token);
      }}
    />
  );
}

// 개발 서버에만 있는 문자함(GET /dev/sms). 한 번만 물어보고, 없으면(운영 404) 버튼을 숨긴다.
// ponytail: 실제 문자 업체가 붙으면 이 컴포넌트와 /dev/sms를 함께 지운다
let devInboxOpen: Promise<boolean> | null = null;
const hasDevInbox = () =>
  (devInboxOpen ??= api("/dev/sms?phone=010-0000-0000").then(
    () => true,
    () => false,
  ));

type Sms = { text: string; sent_at: string };

function DevInbox({ phone: given }: { phone?: string }) {
  const [enabled, setEnabled] = useState(false);
  const [typed, setTyped] = useState("");
  const phone = given ?? typed;
  const [list, setList] = useState<Sms[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    hasDevInbox().then(setEnabled);
  }, []);

  async function load() {
    setError(null);
    try {
      setList(await api<Sms[]>(`/dev/sms?phone=${encodeURIComponent(phone.trim())}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!enabled) return null;
  return (
    <div className="rounded-xl border border-dashed border-line p-3 text-sm">
      <div className="flex items-center gap-2">
        {!given && (
          <input
            aria-label="문자함 휴대폰 번호"
            placeholder="등록된 휴대폰 번호"
            type="tel"
            inputMode="tel"
            value={phone}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              e.preventDefault();
              load();
            }}
            className="min-w-0 flex-1 rounded-lg border border-line bg-paper px-2 py-1.5 outline-none focus:border-coral"
          />
        )}
        <button type="button" onClick={load} disabled={!PHONE.test(phone.trim())} className="text-slate underline underline-offset-4 hover:text-ink disabled:opacity-50">
          개발용 문자함 보기
        </button>
      </div>
      <ErrorText message={error} />
      {list && (
        <ul aria-live="polite" className="mt-2 space-y-1">
          {list.length === 0 && <li className="text-slate">받은 문자가 없습니다.</li>}
          {list.slice(0, 3).map((m, i) => (
            <li key={i} className="text-slate">
              <time className="mr-1 tabular-nums">{new Date(m.sent_at).toLocaleTimeString("ko-KR")}</time>
              {m.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
