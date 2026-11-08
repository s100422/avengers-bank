"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Brand, Button, ErrorText, Field } from "@/components/ui";
import { PHONE, PhoneVerify } from "@/components/verify";
import { ApiError, LoginResult, api, session } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [phone, setPhone] = useState("");
  // 지금 입력한 번호로 받은 인증 증표. 번호를 바꾸면 비운다
  const [token, setToken] = useState<string | null>(null);
  const [round, setRound] = useState(0); // 증표가 만료되면 올려서 인증 영역을 처음부터 다시 보여 준다

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const login_id = f.get("login_id");
    const password = f.get("password");
    if (password !== f.get("password_confirm")) return setError("비밀번호가 일치하지 않습니다.");
    if (!token) return setError("휴대폰 인증을 먼저 해 주세요.");
    setBusy(true);
    setError(null);
    try {
      await api("/users/signup", {
        login_id,
        password,
        name: f.get("name"),
        nick_name: f.get("nick_name") || null,
        phone: phone.trim(),
        phone_verification_token: token,
      });
      // 가입하면 바로 로그인시킨다
      const res = await api<LoginResult>("/users/login", { login_id, password });
      // 새 기기 인증이 필요하면(2단계) 가입은 끝났으니 로그인 화면에서 이어 가게 한다
      if (res.status !== "OK") return router.replace("/login");
      session.save(res);
      router.replace("/accounts");
    } catch (err) {
      setError((err as Error).message);
      if (err instanceof ApiError && err.code === "INVALID_VERIFICATION_TOKEN") {
        setToken(null);
        setRound((n) => n + 1);
      }
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center px-4 py-10">
      <Brand />
      <h1 className="mt-8 text-2xl font-semibold">회원가입</h1>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <Field
          label="아이디 (영문 소문자, 숫자, _ 4~20자)"
          name="login_id"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          minLength={4}
          maxLength={20}
          required
        />
        <Field
          label="비밀번호 (8자 이상, 영문·숫자·특수문자 포함)"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          maxLength={128}
          required
        />
        <Field label="비밀번호 확인" name="password_confirm" type="password" autoComplete="new-password" required />
        <Field label="이름" name="name" autoComplete="name" required />
        <Field label="닉네임 (선택)" name="nick_name" />
        <Field
          label="휴대폰 번호 (010-0000-0000 또는 01000000000)"
          name="phone"
          type="tel"
          inputMode="tel"
          placeholder="010-0000-0000"
          minLength={9}
          required
          value={phone}
          onChange={(e) => {
            setPhone(e.target.value);
            setToken(null);
          }}
        />
        <PhoneVerify
          key={`${phone}:${round}`}
          path="/verification/phone/send"
          body={{ phone: phone.trim(), purpose: "SIGNUP_PHONE" }}
          disabled={!PHONE.test(phone.trim())}
          onVerified={setToken}
        />
        <ErrorText message={error} />
        <Button busy={busy} disabled={!token}>
          가입하기
        </Button>
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
