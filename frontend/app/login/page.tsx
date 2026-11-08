"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Brand, Button, ErrorText, Field } from "@/components/ui";
import { ApiError, REPLACED_MESSAGE, Session, api, safeNext, session } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    // 주소의 쿼리는 브라우저에서만 읽는다 (useSearchParams는 Suspense가 필요해 이 화면에선 쓰지 않는다)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReason(new URLSearchParams(location.search).get("reason"));
  }, []);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    setLocked(false);
    try {
      session.save(
        await api<Session>("/users/login", {
          login_id: f.get("login_id"),
          password: f.get("password"),
        }),
      );
      router.replace(safeNext(new URLSearchParams(location.search).get("next")));
    } catch (err) {
      setError((err as Error).message);
      setLocked(err instanceof ApiError && err.code === "ACCOUNT_LOCKED");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center px-4">
      <Brand />
      <h1 className="mt-8 text-2xl font-semibold">로그인</h1>
      {reason === "expired" && (
        <p role="status" className="mt-4 rounded-xl bg-coral-soft px-3 py-2.5 text-sm">
          로그인이 만료되었습니다. 다시 로그인해 주세요.
        </p>
      )}
      {reason === "replaced" && (
        <p role="status" className="mt-4 rounded-xl bg-coral-soft px-3 py-2.5 text-sm">
          {REPLACED_MESSAGE} 본인이 로그인한 것이 아니라면 다시 로그인한 뒤 비밀번호를 바꿔 주세요.
        </p>
      )}
      {reason === "reset" && (
        <p role="status" className="mt-4 rounded-xl bg-coral-soft px-3 py-2.5 text-sm">
          비밀번호를 재설정했습니다. 새 비밀번호로 로그인해 주세요.
        </p>
      )}
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <Field
          label="아이디"
          name="login_id"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          required
        />
        <Field label="비밀번호" name="password" type="password" autoComplete="current-password" required />
        <ErrorText message={error} />
        {locked && (
          <Link href="/reset-password" className="block rounded-xl border border-coral py-3 text-center font-medium text-coral">
            비밀번호 찾기
          </Link>
        )}
        <Button busy={busy}>로그인</Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate">
        <Link href="/find-id" className="hover:text-ink">
          아이디 찾기
        </Link>
        <span aria-hidden> · </span>
        <Link href="/reset-password" className="hover:text-ink">
          비밀번호 찾기
        </Link>
      </p>
      <p className="mt-6 text-sm text-slate">
        처음이신가요?{" "}
        <Link href="/signup" className="text-ink underline underline-offset-4">
          회원가입
        </Link>
      </p>
    </main>
  );
}
