"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Brand, Button, ErrorText, Field } from "@/components/ui";
import { api, token } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const login_id = f.get("login_id");
    const password = f.get("password");
    setBusy(true);
    setError(null);
    try {
      await api("/users/signup", {
        login_id,
        password,
        name: f.get("name"),
        nick_name: f.get("nick_name") || null,
        phone: f.get("phone"),
      });
      // 가입하면 바로 로그인시킨다
      const res = await api<{ access_token: string }>("/users/login", { login_id, password });
      token.set(res.access_token);
      router.replace("/accounts");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center px-4 py-10">
      <Brand />
      <h1 className="mt-8 text-2xl font-semibold">회원가입</h1>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <Field label="아이디 (4자 이상)" name="login_id" autoComplete="username" minLength={4} required />
        <Field label="비밀번호 (8자 이상)" name="password" type="password" autoComplete="new-password" minLength={8} required />
        <Field label="이름" name="name" autoComplete="name" required />
        <Field label="닉네임 (선택)" name="nick_name" />
        <Field label="휴대폰 번호" name="phone" type="tel" placeholder="010-0000-0000" minLength={9} required />
        <ErrorText message={error} />
        <Button busy={busy}>가입하기</Button>
      </form>
      <p className="mt-6 text-sm text-slate">
        이미 계정이 있나요?{" "}
        <Link href="/login" className="text-ink underline underline-offset-4">
          로그인
        </Link>
      </p>
    </main>
  );
}
