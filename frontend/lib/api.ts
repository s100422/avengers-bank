// FastAPI 호출 도우미. 성공은 { data }, 실패는 { error: { message, details } } 모양이다.
const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const TOKEN_KEY = "avengers_bank_token";

// shortcut: 토큰을 localStorage에 둔다(XSS에 약함). 실서비스로 가면 httpOnly 쿠키로 바꾼다.
export const token = {
  get: () => (typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY)),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const t = token.get();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method: body === undefined ? "GET" : "POST",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
  }

  const json = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401) token.clear();
    const err = json?.error;
    const detail = err?.details?.[0];
    const message = detail ? `${detail.loc.at(-1)}: ${detail.msg}` : err?.message;
    throw new ApiError(res.status, message ?? `요청이 실패했습니다 (${res.status}).`);
  }
  return json.data as T;
}

export type AccountSummary = {
  account_type: "checking" | "deposit" | "savings";
  account_id: number;
  account_num: string;
  balance: number;
  nickname: string | null;
  created_at: string;
  status: string | null;
};

export type User = { user_id: number; login_id: string; name: string; nick_name: string | null };

export type Product = { product_id: number; name: string; description: string; interest_rate: string };

export const won = (n: number) => n.toLocaleString("ko-KR") + "원";

export const KIND: Record<AccountSummary["account_type"], string> = {
  checking: "입출금",
  deposit: "예금",
  savings: "적금",
};
