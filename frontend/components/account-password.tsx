"use client";

import Link from "next/link";
import { useState } from "react";
import { Field } from "@/components/ui";
import { ApiError } from "@/lib/api";

export const ACCOUNT_PASSWORD_RULE = "숫자 4자리 (같은 숫자 반복·연속 숫자 불가, 예: 1111·1234·4321 불가)";

/** 새 계좌 비밀번호 규칙(서버와 같음). 맞으면 null, 아니면 안내 문장 */
export function accountPasswordProblem(pw: string, confirm: string): string | null {
  const asc = "0123456789";
  if (!/^\d{4}$/.test(pw) || new Set(pw).size === 1 || asc.includes(pw) || asc.split("").reverse().join("").includes(pw)) {
    return "계좌 비밀번호는 숫자 4자리이며, 같은 숫자나 연속된 숫자는 쓸 수 없습니다.";
  }
  return pw === confirm ? null : "계좌 비밀번호가 일치하지 않습니다.";
}

/**
 * 숫자 4자리 계좌 비밀번호 입력. 일부러 비제어 입력으로 둔다 → 상태·초안(sessionStorage)에 값이 남지 않는다.
 * 값은 제출할 때 FormData로 읽는다.
 */
export function AccountPasswordField({
  label = "계좌 비밀번호",
  resetHref,
  onReset,
  onFocus,
  ...props
}: {
  label?: string;
  resetHref?: string; // 재설정을 하는 계좌 상세 경로 (다른 화면에서 링크로 보낸다)
  onReset?: () => void; // 같은 화면에서 재설정 칸을 펼칠 때
} & React.InputHTMLAttributes<HTMLInputElement>) {
  // 입력칸을 한 번 눌러 보면 안내를 계속 보여 준다 (링크를 누르려고 입력칸을 벗어나도 사라지지 않게)
  const [touched, setTouched] = useState(false);
  const linkClass = "underline underline-offset-4 hover:text-ink";
  return (
    <div>
      <Field
        label={label}
        name="account_password"
        type="password"
        inputMode="numeric"
        pattern="\d{4}"
        minLength={4}
        maxLength={4}
        autoComplete="off"
        title="숫자 4자리"
        required
        onFocus={(e) => {
          setTouched(true);
          onFocus?.(e);
        }}
        {...props}
      />
      {touched && (resetHref || onReset) && (
        <p className="mt-1.5 text-sm text-slate">
          비밀번호를 잊으셨나요?{" "}
          {onReset ? (
            <button type="button" onClick={onReset} className={linkClass}>
              계좌 비밀번호 재설정하기
            </button>
          ) : (
            <Link href={`${resetHref}#account-password`} className={linkClass}>
              계좌 비밀번호 재설정하기
            </Link>
          )}
        </p>
      )}
    </div>
  );
}

/**
 * 돈이 나가는 요청의 오류. 계좌 비밀번호 미설정·잠김이면 그 계좌 상세(설정·재설정 영역)로 가는 링크를 붙인다.
 * accountHref: 비밀번호를 확인한 계좌의 상세 경로. 모르면 홈.
 */
export function MoneyErrorText({ error, accountHref = "/accounts" }: { error: unknown; accountHref?: string }) {
  if (!error) return null;
  const code = error instanceof ApiError ? error.code : undefined;
  const href = `${accountHref}#account-password`;
  return (
    <p role="alert" className="text-sm text-seal">
      {code === "ACCOUNT_PASSWORD_NOT_SET" ? "계좌 비밀번호를 먼저 설정해 주세요." : (error as Error).message}
      {(code === "ACCOUNT_PASSWORD_NOT_SET" || code === "ACCOUNT_PASSWORD_LOCKED") && (
        <>
          {" "}
          <Link href={href} className="font-medium underline underline-offset-4">
            {code === "ACCOUNT_PASSWORD_NOT_SET" ? "계좌 비밀번호 설정하기" : "휴대폰 인증 후 재설정하기"}
          </Link>
        </>
      )}
    </p>
  );
}
