"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Brand, Button, ErrorText, Field } from "@/components/ui";
import { CodeVerify } from "@/components/verify";
import { ApiError, LoginResult, REPLACED_MESSAGE, api, safeNext, session } from "@/lib/api";
import { useFreshOnLeave } from "@/lib/fresh";

// 다른 화면에 갔다 돌아오면 입력값·인증 증표·오류를 비우고 처음부터 시작한다
export default function LoginPage() {
  return <Login key={useFreshOnLeave()} />;
}

function Login() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const idRef = useRef(0); // 인증번호 발송 id
  const [reason, setReason] = useState<string | null>(null);
  // 새 기기 인증 중이면 서버가 준 챌린지. 상태에만 두고 저장하지 않는다(새로고침하면 처음부터)
  const [challenge, setChallenge] = useState<{ token: string; phone: string } | null>(null);

  useEffect(() => {
    // 주소의 쿼리는 브라우저에서만 읽는다 (useSearchParams는 Suspense가 필요해 이 화면에선 쓰지 않는다)
    const why = new URLSearchParams(location.search).get("reason");
    // 탈퇴한 화면은 일부러 토큰을 지우지 않고 넘어온다(서버 세션은 이미 끊김, me/page.tsx 참고). 여기서 지운다
    if (why === "withdrawn") session.clear();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReason(why);
  }, []);

  const goNext = () => router.replace(safeNext(new URLSearchParams(location.search).get("next")));

  // 챌린지가 만료·실패했으면 비밀번호 입력부터 다시 한다
  function restart(message: string) {
    setChallenge(null);
    setDemoMode(false);
    setError(message);
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    setLocked(false);
    setDemoMode(false);
    try {
      const res = await api<LoginResult>("/users/login", {
        login_id: f.get("login_id"),
        password: f.get("password"),
      });
      if (res.status === "DEVICE_VERIFICATION_REQUIRED") {
        setChallenge({ token: res.challenge_token, phone: res.phone_masked });
        setBusy(false);
        return;
      }
      session.save(res);
      goNext();
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
      {reason === "withdrawn" && (
        <p role="status" className="mt-4 rounded-xl bg-coral-soft px-3 py-2.5 text-sm">
          회원 탈퇴가 완료되었습니다. 그동안 이용해 주셔서 감사합니다.
        </p>
      )}
      {reason === "reset" && (
        <p role="status" className="mt-4 rounded-xl bg-coral-soft px-3 py-2.5 text-sm">
          비밀번호를 재설정했습니다. 새 비밀번호로 로그인해 주세요.
        </p>
      )}
      {challenge ? (
        <div className="mt-6 space-y-4">
          <h2 className="text-lg font-semibold">새 기기에서 로그인</h2>
          <p className="text-sm text-slate">처음 사용하는 기기입니다. 등록된 휴대폰 {challenge.phone}(으)로 인증번호를 보내 본인을 확인합니다.</p>
          {/* 가려진 번호(010-****-9999)라 devPhone으로 못 넘긴다. 문자함에서 번호를 직접 입력 */}
          <CodeVerify
            sentText={demoMode ? "시연 계정입니다. 담당자가 설정한 6자리 시연용 인증번호를 입력해 주세요. 실제 문자는 발송되지 않습니다." : undefined}
            send={async () => {
              try {
                const r = await api<{ verification_id: number; expires_in: number; delivery?: "demo" }>("/users/login/device/send", {
                  challenge_token: challenge.token,
                });
                idRef.current = r.verification_id;
                setDemoMode(r.delivery === "demo");
                return r.expires_in;
              } catch (e) {
                if (e instanceof ApiError && e.status === 401) restart("인증 시간이 지났습니다. 다시 로그인해 주세요.");
                throw e;
              }
            }}
            verify={async (code) => {
              // 인증번호가 틀리면 여기서 던져 같은 화면에서 다시 입력하게 한다
              const v = await api<{ verification_token: string }>("/verification/phone/verify", { verification_id: idRef.current, code });
              try {
                const res = await api<LoginResult>("/users/login/device", {
                  challenge_token: challenge.token,
                  phone_verification_token: v.verification_token,
                });
                if (res.status !== "OK") throw new Error();
                session.save(res);
                goNext();
              } catch (e) {
                restart(e instanceof ApiError && e.status !== 0 ? e.message : "로그인할 수 없습니다. 다시 로그인해 주세요.");
              }
            }}
          />
          <button type="button" onClick={() => setChallenge(null)} className="text-sm text-slate underline underline-offset-4 hover:text-ink">
            처음으로 돌아가기
          </button>
        </div>
      ) : (
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
      )}
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
