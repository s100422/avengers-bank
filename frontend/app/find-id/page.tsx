"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { Brand, Field } from "@/components/ui";
import { CodeVerify, RECOVERY_SENT } from "@/components/verify";
import { api } from "@/lib/api";

// 아이디 찾기: 입출금 계좌번호 + 계좌 비밀번호 → 등록된 휴대폰 인증번호 → 가린 아이디
export default function FindIdPage() {
  const [accountNum, setAccountNum] = useState("");
  const [accountPassword, setAccountPassword] = useState(""); // 화면 상태에만 둔다(저장소에 넣지 않는다)
  const [masked, setMasked] = useState<string | null>(null);
  const token = useRef("");
  const ready = accountNum.trim() !== "" && /^\d{4}$/.test(accountPassword);

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center px-4 py-10">
      <Brand />
      <h1 className="mt-8 text-2xl font-semibold">아이디 찾기</h1>
      {masked ? (
        <section className="mt-6 space-y-3">
          <p role="status" className="rounded-xl bg-coral-soft px-3 py-3">
            회원님의 아이디는 <strong className="tabular-nums">{masked}</strong> 입니다.
          </p>
          <p className="text-sm text-slate">전체 아이디는 등록된 휴대폰으로 보냈습니다.</p>
          <Link href="/login" className="block rounded-xl bg-coral py-3 text-center font-medium text-paper">
            로그인하기
          </Link>
        </section>
      ) : (
        <div className="mt-6 space-y-4">
          <p className="text-sm text-slate">본인 명의 입출금 계좌로 확인한 뒤 등록된 휴대폰으로 인증번호를 보냅니다.</p>
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
            key={`${accountNum}:${accountPassword}`}
            disabled={!ready}
            sentText={RECOVERY_SENT}
            send={async () => {
              const r = await api<{ recovery_token: string; expires_in: number }>("/recovery/start", {
                purpose: "FIND_LOGIN_ID",
                account_num: accountNum.trim(),
                account_password: accountPassword,
              });
              token.current = r.recovery_token;
              return r.expires_in;
            }}
            verify={async (code) => {
              const r = await api<{ masked_login_id: string }>("/recovery/verify", { recovery_token: token.current, code });
              setAccountPassword("");
              setMasked(r.masked_login_id);
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
        <Link href="/reset-password" className="text-ink underline underline-offset-4">
          비밀번호 찾기
        </Link>
      </p>
    </main>
  );
}
