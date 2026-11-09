"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Brand, Button, ErrorText, Field } from "@/components/ui";
import { CodeVerify, RECOVERY_SENT } from "@/components/verify";
import { ApiError, api } from "@/lib/api";
import { useFreshOnLeave } from "@/lib/fresh";

// 비밀번호 찾기: 아이디 + 입출금 계좌번호 + 계좌 비밀번호 → 등록된 휴대폰 인증번호 → 새 비밀번호.
// 재설정하면 로그인 잠금도 풀린다. 자동 로그인은 하지 않는다.
// 다른 화면에 갔다 돌아오면 입력값·인증 증표·오류를 비우고 처음부터 시작한다
export default function ResetPasswordPage() {
  return <ResetPassword key={useFreshOnLeave()} />;
}

function ResetPassword() {
  const router = useRouter();
  const [loginId, setLoginId] = useState("");
  const [accountNum, setAccountNum] = useState("");
  const [accountPassword, setAccountPassword] = useState(""); // 화면 상태에만 둔다(저장소에 넣지 않는다)
  const [resetToken, setResetToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const token = useRef("");
  const ready = loginId.trim() !== "" && accountNum.trim() !== "" && /^\d{4}$/.test(accountPassword);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const new_password = f.get("new_password");
    if (new_password !== f.get("new_password_confirm")) return setError("비밀번호가 일치하지 않습니다.");
    setBusy(true);
    setError(null);
    try {
      await api("/recovery/password", { reset_token: resetToken, new_password });
      router.replace("/login?reason=reset");
    } catch (err) {
      setError((err as Error).message);
      // 재설정 증표가 만료됐으면 처음부터 다시
      if (err instanceof ApiError && err.status === 400 && /TOKEN|EXPIRED/.test(err.code ?? "")) setResetToken(null);
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center px-4 py-10">
      <Brand />
      <h1 className="mt-8 text-2xl font-semibold">비밀번호 찾기</h1>
      {resetToken ? (
        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <p role="status" className="rounded-xl bg-coral-soft px-3 py-2.5 text-sm">
            본인 확인이 끝났습니다. 새 비밀번호를 정해 주세요.
          </p>
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
          <ErrorText message={error} />
          <Button busy={busy}>비밀번호 재설정</Button>
        </form>
      ) : (
        <div className="mt-6 space-y-4">
          <p className="text-sm text-slate">본인 명의 입출금 계좌로 확인한 뒤 등록된 휴대폰으로 인증번호를 보냅니다.</p>
          <ErrorText message={error} />
          <Field
            label="아이디"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            maxLength={20}
            value={loginId}
            onChange={(e) => setLoginId(e.target.value)}
          />
          <Field
            label="입출금 계좌번호"
            inputMode="numeric"
            autoComplete="off"
            maxLength={20}
            value={accountNum}
            onChange={(e) => setAccountNum(e.target.value)}
          />
          <Field
            label="계좌 비밀번호 (숫자 4자리)"
            type="password"
            inputMode="numeric"
            maxLength={4}
            autoComplete="off"
            value={accountPassword}
            onChange={(e) => setAccountPassword(e.target.value.replace(/\D/g, ""))}
          />
          <CodeVerify
            key={`${loginId}:${accountNum}:${accountPassword}`}
            disabled={!ready}
            sentText={RECOVERY_SENT}
            send={async () => {
              const r = await api<{ recovery_token: string; expires_in: number }>("/recovery/start", {
                purpose: "PASSWORD_RESET",
                login_id: loginId.trim(),
                account_num: accountNum.trim(),
                account_password: accountPassword,
              });
              token.current = r.recovery_token;
              return r.expires_in;
            }}
            verify={async (code) => {
              const r = await api<{ reset_token: string }>("/recovery/verify", { recovery_token: token.current, code });
              setAccountPassword("");
              setError(null);
              setResetToken(r.reset_token);
            }}
          />
        </div>
      )}
      <p className="mt-8 text-sm text-slate">입출금 계좌가 없으시면 고객센터로 문의해 주세요.</p>
      <p className="mt-2 text-sm text-slate">
        <Link href="/login" className="text-ink underline underline-offset-4">
          로그인
        </Link>
        <span aria-hidden> · </span>
        <Link href="/find-id" className="text-ink underline underline-offset-4">
          아이디 찾기
        </Link>
      </p>
    </main>
  );
}
