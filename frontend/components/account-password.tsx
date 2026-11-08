"use client";

import Link from "next/link";
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
export function AccountPasswordField({ label = "계좌 비밀번호", ...props }: { label?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
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
      {...props}
    />
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
