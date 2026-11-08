"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, ErrorText, Field, Shell } from "@/components/ui";
import { PHONE, PhoneVerify, digits } from "@/components/verify";
import { ApiError, Session, User, api, logout, logoutAll, session } from "@/lib/api";

export default function MePage() {
  return (
    <Shell>
      <Me />
    </Shell>
  );
}

function Me() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<User>("/users/me").then(setUser).catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <h1 className="mt-4 text-2xl font-semibold">내 정보</h1>
      <ErrorText message={error} />
      {user && (
        <>
          <p className="mt-1 text-slate">아이디 {user.login_id}</p>
          <ProfileForm user={user} onSaved={setUser} />
          {/* 내 정보를 못 불러왔으면 비밀번호 변경도 숨긴다 */}
          <PasswordForm />
        </>
      )}
      <button
        className="mt-10 w-full rounded-xl border border-line py-3 text-slate hover:text-ink"
        onClick={async () => {
          await logout(); // 서버 세션도 끊는다(실패해도 로그아웃은 진행)
          router.replace("/login");
        }}
      >
        로그아웃
      </button>
      <button
        className="mt-3 w-full rounded-xl py-3 text-sm text-slate underline underline-offset-4 hover:text-ink"
        onClick={async () => {
          if (!confirm("이 기기를 포함해 로그인된 모든 기기에서 로그아웃할까요?")) return;
          try {
            await logoutAll(); // 다른 기기의 세션까지 서버에서 끊는다
            router.replace("/login");
          } catch (e) {
            setError((e as Error).message);
          }
        }}
      >
        모든 기기에서 로그아웃
      </button>
    </>
  );
}

function ProfileForm({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [phone, setPhone] = useState(user.phone);
  const [token, setToken] = useState<string | null>(null); // 새 번호로 받은 CHANGE_PHONE 증표
  const [round, setRound] = useState(0); // 증표가 만료되면 올려서 인증을 처음부터
  // 하이픈만 다른 번호는 바꾼 것으로 보지 않는다
  const changed = digits(phone) !== digits(user.phone);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (changed && !token) return setMsg({ ok: false, text: "새 휴대폰 번호를 인증해 주세요." });
    setBusy(true);
    try {
      const body = { name: f.get("name"), nick_name: f.get("nick_name") || null };
      const saved = await api<User>(
        "/users/me",
        changed ? { ...body, phone: phone.trim(), phone_verification_token: token } : body,
        "PATCH",
      );
      onSaved(saved);
      setPhone(saved.phone);
      setToken(null);
      setMsg({ ok: true, text: "저장했습니다." });
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
      if (err instanceof ApiError && err.code === "INVALID_VERIFICATION_TOKEN") {
        setToken(null);
        setRound((n) => n + 1);
      }
    }
    setBusy(false);
  }

  return (
    <form onSubmit={onSubmit} className="mt-6 space-y-4">
      <Field label="이름" name="name" defaultValue={user.name} required />
      <Field label="닉네임 (선택)" name="nick_name" defaultValue={user.nick_name ?? ""} />
      <Field
        label="휴대폰 번호 (010-0000-0000 또는 01000000000)"
        name="phone"
        type="tel"
        inputMode="tel"
        value={phone}
        onChange={(e) => {
          setPhone(e.target.value);
          setToken(null);
        }}
        minLength={9}
        required
      />
      {changed && (
        <div className="space-y-2">
          <p className="text-sm text-slate">휴대폰 번호를 바꾸려면 새 번호로 인증해 주세요.</p>
          <PhoneVerify
            key={`${phone}:${round}`}
            path="/verification/phone/send-for-me"
            body={{ phone: phone.trim(), purpose: "CHANGE_PHONE" }}
            disabled={!PHONE.test(phone.trim())}
            onVerified={setToken}
          />
        </div>
      )}
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-slate" : "text-seal"}`}>{msg.text}</p>}
      <Button busy={busy} disabled={changed && !token}>
        정보 저장
      </Button>
    </form>
  );
}

function PasswordForm() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    if (f.get("new_password") !== f.get("new_password_confirm")) {
      return setMsg({ ok: false, text: "비밀번호가 일치하지 않습니다." });
    }
    setBusy(true);
    try {
      // 서버가 다른 기기의 세션을 모두 끊고 이 기기용 새 세션을 준다 → 저장된 토큰을 바꾼다
      session.save(
        await api<Session>(
          "/users/me/password",
          { current_password: f.get("current_password"), new_password: f.get("new_password") },
          "PATCH",
        ),
      );
      form.reset();
      setMsg({ ok: true, text: "비밀번호를 바꿨습니다." });
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
    setBusy(false);
  }

  return (
    <form onSubmit={onSubmit} className="mt-10 space-y-4">
      <h2 className="text-sm text-slate">비밀번호 변경</h2>
      <Field label="현재 비밀번호" name="current_password" type="password" autoComplete="current-password" required />
      <Field
        label="새 비밀번호 (8자 이상, 영문·숫자·특수문자 포함)"
        name="new_password"
        type="password"
        autoComplete="new-password"
        minLength={8}
        maxLength={128}
        required
      />
      <Field label="새 비밀번호 확인" name="new_password_confirm" type="password" autoComplete="new-password" required />
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-slate" : "text-seal"}`}>{msg.text}</p>}
      <Button busy={busy}>비밀번호 바꾸기</Button>
    </form>
  );
}
