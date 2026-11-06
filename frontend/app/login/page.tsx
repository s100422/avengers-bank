"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Brand, Button, ErrorText, Field } from "@/components/ui";
import { api, token } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ access_token: string }>("/users/login", {
        login_id: f.get("login_id"),
        password: f.get("password"),
      });
      token.set(res.access_token);
      router.replace("/accounts");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center px-4">
      <Brand />
      <h1 className="mt-8 text-2xl font-semibold">로그인</h1>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <Field label="아이디" name="login_id" autoComplete="username" required />
        <Field label="비밀번호" name="password" type="password" autoComplete="current-password" required />
        <ErrorText message={error} />
        <Button busy={busy}>로그인</Button>
      </form>
      <p className="mt-6 text-sm text-slate">
        처음이신가요?{" "}
        <Link href="/signup" className="text-ink underline underline-offset-4">
          회원가입
        </Link>
      </p>
    </main>
  );
}
