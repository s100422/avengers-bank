"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, ErrorText, Field, Shell } from "@/components/ui";
import { User, api, token } from "@/lib/api";

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
        </>
      )}
      <PasswordForm />
      <button
        className="mt-10 w-full rounded-xl border border-line py-3 text-slate hover:text-ink"
        onClick={() => {
          token.clear();
          router.replace("/login");
        }}
      >
        로그아웃
      </button>
    </>
  );
}

function ProfileForm({ user, onSaved }: { user: User; onSaved: (u: User) => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const saved = await api<User>(
        "/users/me",
        { name: f.get("name"), nick_name: f.get("nick_name") || null, phone: f.get("phone") },
        "PATCH",
      );
      onSaved(saved);
      setMsg({ ok: true, text: "저장했습니다." });
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
    setBusy(false);
  }

  return (
    <form onSubmit={onSubmit} className="mt-6 space-y-4">
      <Field label="이름" name="name" defaultValue={user.name} required />
      <Field label="닉네임 (선택)" name="nick_name" defaultValue={user.nick_name ?? ""} />
      <Field label="휴대폰 번호" name="phone" type="tel" defaultValue={user.phone} minLength={9} required />
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-slate" : "text-seal"}`}>{msg.text}</p>}
      <Button busy={busy}>정보 저장</Button>
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
    setBusy(true);
    try {
      await api(
        "/users/me/password",
        { current_password: f.get("current_password"), new_password: f.get("new_password") },
        "PATCH",
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
      <Field label="새 비밀번호 (8자 이상)" name="new_password" type="password" autoComplete="new-password" minLength={8} required />
      {msg && <p role="status" className={`text-sm ${msg.ok ? "text-slate" : "text-seal"}`}>{msg.text}</p>}
      <Button busy={busy}>비밀번호 바꾸기</Button>
    </form>
  );
}
