// FastAPI 호출 도우미. 성공은 { data }, 실패는 { error: { message, details } } 모양이다.
const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export const SESSION_KEY = "avengers_bank_session"; // storage 이벤트에서 이 키를 본다

// 로그인·갱신·비밀번호 변경이 돌려주는 토큰 묶음
export type Session = {
  access_token: string;
  token_type: "bearer";
  refresh_token: string;
  expires_in: number; // 액세스 토큰 수명(초)
  session_expires_at: string; // 갱신 토큰 만료 시각(ISO8601 UTC). 지나면 자동 로그아웃
};

// shortcut: 토큰을 localStorage에 둔다(XSS에 약함). 실서비스로 가면 httpOnly 쿠키로 바꾼다.
// 세 값을 한 키에 JSON으로 둬서 다른 탭이 반쯤 바뀐 값을 읽는 일이 없게 한다.
export const session = {
  get: (): Session | null => {
    if (typeof window === "undefined") return null;
    try {
      return JSON.parse(localStorage.getItem(SESSION_KEY) ?? "null");
    } catch {
      return null;
    }
  },
  save: (s: Session) => localStorage.setItem(SESSION_KEY, JSON.stringify(s)),
  clear: () => localStorage.removeItem(SESSION_KEY),
  // 로그인 상태 = 갱신 토큰이 있다 (액세스 토큰은 5분마다 만료되어도 갱신하면 된다)
  active: () => !!session.get()?.refresh_token,
  expiresAt: () => Date.parse(session.get()?.session_expires_at ?? "") || 0,
};

export class ApiError extends Error {
  // code: 서버 오류 코드(TERMS_OUTDATED 등). 화면이 코드별로 다르게 처리할 때 쓴다
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

// 갱신 토큰으로 다시 받을 수 없는 요청들. 이 요청의 401은 그대로 화면에 보여 준다
const AUTH_PATHS = ["/users/login", "/users/signup", "/users/token/refresh", "/users/logout"];

function send(path: string, body: unknown, method: string | undefined, accessToken: string | undefined) {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return fetch(BASE + path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  }).catch(() => {
    throw new ApiError(0, "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
  });
}

export async function api<T>(path: string, body?: unknown, method?: "PATCH" | "POST"): Promise<T> {
  const before = session.get();
  let res = await send(path, body, method, before?.access_token);

  // 액세스 토큰(5분)이 만료됐으면 한 번만 갱신하고 다시 보낸다. 401은 서버가 처리 전에 거절한 것이라 POST도 다시 보내도 된다
  if (res.status === 401 && before?.refresh_token && !AUTH_PATHS.includes(path)) {
    if (await refreshSession(before.refresh_token)) res = await send(path, body, method, session.get()?.access_token);
    if (res.status === 401) {
      const replaced = lastRefreshFailure === "SESSION_REPLACED";
      expireSession();
      throw new ApiError(401, replaced ? REPLACED_MESSAGE : "로그인이 만료되었습니다. 다시 로그인해 주세요.", "SESSION_EXPIRED");
    }
  }

  const json = await res.json().catch(() => null);
  if (!res.ok) {
    const err = json?.error;
    // 422의 msg는 서버가 필드 이름까지 넣은 한국어 문장이다
    const message = err?.details?.[0]?.msg ?? err?.message;
    throw new ApiError(res.status, message ?? `요청이 실패했습니다 (${res.status}).`, err?.code);
  }
  return json.data as T;
}

// 갱신 토큰은 한 번 쓰면 폐기되고, 쓴 토큰을 다시 보내면 서버가 세션을 통째로 끊는다.
// 그래서 같은 탭에서는 진행 중인 갱신 하나를 같이 기다리고(single-flight),
// 여러 탭 사이에서는 Web Locks로 한 번에 한 탭만 갱신한다.
let inflight: Promise<boolean> | null = null;

// 마지막 갱신이 실패한 이유(서버 오류 코드). SESSION_REPLACED = 다른 곳에서 로그인해 이 세션이 끊김(단일 세션)
let lastRefreshFailure: string | undefined;
export const REPLACED_MESSAGE = "다른 곳에서 로그인되어 로그아웃되었습니다.";

/**
 * 세션을 갱신한다. 성공(또는 다른 탭이 이미 갱신함)이면 true, 갱신 토큰이 죽었으면 false.
 * failedWith: 401을 받은 요청에 쓰인 갱신 토큰. 저장된 값이 이와 다르면 그사이 누가 갱신한 것이니 다시 갱신하지 않는다.
 * 생략하면(연장 버튼) 무조건 갱신한다. 서버에 닿지 못하면 ApiError(0)를 던진다(세션은 그대로 둔다).
 */
export function refreshSession(failedWith?: string): Promise<boolean> {
  inflight ??= (async () => {
    try {
      const run = () => refreshOnce(failedWith);
      return await (navigator.locks ? navigator.locks.request("avengers-bank-refresh", run) : run());
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

async function refreshOnce(failedWith?: string): Promise<boolean> {
  const current = session.get()?.refresh_token; // 잠금을 얻은 뒤 저장소를 다시 읽는다
  if (!current) return false;
  if (failedWith && current !== failedWith) return true;
  try {
    session.save(await api<Session>("/users/token/refresh", { refresh_token: current }));
    lastRefreshFailure = undefined;
    return true;
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) throw e;
    lastRefreshFailure = e instanceof ApiError ? e.code : undefined;
    return false;
  }
}

/** 서버 세션을 끊고(실패해도 무시) 저장된 토큰을 지운다 */
export async function logout() {
  const refresh_token = session.get()?.refresh_token;
  session.clear();
  if (refresh_token) await api("/users/logout", { refresh_token }).catch(() => {});
}

/** 이 기기를 포함한 모든 기기의 세션을 서버에서 끊고 저장된 토큰을 지운다. 서버가 거절하면 오류를 던진다(세션 유지) */
export async function logoutAll() {
  await api("/users/logout-all", {});
  session.clear();
}

// 만료로 로그인 화면으로 가는 중. 타이머가 "다른 탭 로그아웃"으로 오해해 경로를 덮어쓰지 않게 한다
export let expiring = false;

/** 세션을 지우고 지금 화면으로 돌아올 수 있게 로그인 화면으로 보낸다. 다른 곳 로그인으로 끊겼으면 그 이유를 넘긴다 */
export function expireSession() {
  expiring = true;
  session.clear();
  if (location.pathname === "/login") return;
  const reason = lastRefreshFailure === "SESSION_REPLACED" ? "replaced" : "expired";
  location.replace(`/login?next=${encodeURIComponent(location.pathname + location.search)}&reason=${reason}`);
}

/** 로그인 뒤 돌아갈 곳. 다른 사이트로 보내지 않게 같은 사이트 경로만 받는다 */
export function safeNext(next: string | null) {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : "/accounts";
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

export type User = { user_id: number; login_id: string; name: string; nick_name: string | null; phone: string };

export type History = {
  date: string;
  amount: number;
  balance_after: number;
  type: string;
  counterpart_account: string | null;
  counterpart_name: string | null;
};

// 거래 종류: [화면 이름, 나간 돈인지]
export const HISTORY_TYPE: Record<string, [string, boolean]> = {
  TRANSFER_OUT: ["이체 보냄", true],
  TRANSFER_IN: ["입금", false],
  TO_SAVINGS: ["적금 납입", true],
  TO_DEPOSIT: ["예금 입금", true],
  CLOSE_IN: ["해지금 입금", false],
  INTEREST: ["이자", false],
  CLOSE_OUT: ["해지", true],
  CARD_PAYMENT: ["체크카드 결제", true],
  CARD_BILL_PAYMENT: ["카드대금 납부", true],
  DEV_CHARGE: ["충전(개발용)", false],
};

export type Product = { product_id: number; name: string; description: string; interest_rate: string; min_amount?: number | null };

export const won = (n: number) => n.toLocaleString("ko-KR") + "원";

export const KIND: Record<AccountSummary["account_type"], string> = {
  checking: "입출금",
  deposit: "예금",
  savings: "적금",
};

// AI 금융 비서 (/agent). 이체는 초안(draft)만 만들고, 사용자가 확인 카드에서 눌러야 실행된다.
export type TransferAction = {
  type: "TRANSFER_CONFIRMATION";
  draft_id: string;
  from_account_name: string;
  from_account_num_masked: string;
  recipient_name: string;
  to_account_num_masked: string;
  amount: number;
  expected_balance_after: number;
  expires_at: string;
};

// 비서 답변이 근거로 쓴 약관 조항. 링크는 url을 믿지 않고 id로 직접 만든다 (termsHref)
export type Citation = {
  source_id: string;
  document_version_id: number;
  title: string;
  version: string;
  section_id: string;
  section_title: string;
  url: string;
};

export type AgentReply = { conversation_id: number; answer: string; action: TransferAction | null; citations?: Citation[] };

export type AgentMessage = {
  message_id: number;
  role: "user" | "assistant";
  content: string;
  action: TransferAction | null;
  citations: Citation[];
  created_at: string;
};

export type AgentTransferResult = {
  draft_id: string;
  status: "EXECUTED";
  from_account_num_masked: string;
  to_account_num_masked: string;
  recipient_name: string;
  amount: number;
  balance_after: number;
};

export const agent = {
  chat: (message: string, conversation_id: number | null) => api<AgentReply>("/agent/chat", { message, conversation_id }),
  confirm: (draftId: string, account_password: string) =>
    api<AgentTransferResult>(`/agent/transfers/${encodeURIComponent(draftId)}/confirm`, { account_password }),
  messages: (conversationId: number) => api<AgentMessage[]>(`/agent/conversations/${conversationId}/messages`),
  cancel: (draftId: string) =>
    api<{ draft_id: string; status: "CANCELLED" }>(`/agent/transfers/${encodeURIComponent(draftId)}/cancel`, undefined, "POST"),
};

// 비서로 이체한 뒤 열려 있는 화면이 잔액을 다시 불러오게 알리는 이벤트 이름
export const ACCOUNTS_CHANGED = "accounts:changed";

// 약관. 계좌·카드의 product_id가 겹칠 수 있어 언제나 (종류, id)로 찾는다
export type TermsKind = "checking" | "deposit" | "savings" | "credit" | "debit";

export type TermsItem = {
  terms_version_id: number;
  document_key: string;
  title: string;
  version: string;
  effective_from: string;
  required: boolean;
  order: number;
};

export type TermsSet = {
  product_kind: TermsKind;
  product_id: number;
  product_code: string;
  revision_id: number;
  set_hash: string;
  items: TermsItem[];
};

export type TermsVersion = {
  terms_version_id: number;
  document_key: string;
  title: string;
  version: string;
  effective_from: string;
  status: "published" | "retired";
  demo_only: boolean;
  body: string;
  body_sha256: string;
  sections: { section_id: string; title: string }[];
};

export type TermsConsent = {
  subject_kind: TermsKind;
  subject_id: number;
  has_record: boolean;
  recorded_at: string | null;
  items: (Omit<TermsItem, "order"> & { agreed: boolean })[];
};

// 조항 id는 이 모양만 HTML id·주소 조각으로 쓴다
export const SECTION_ID = /^[a-z0-9]+(-[a-z0-9]+)*$/;

// 약관 전문 링크. 서버가 준 url 대신 id로 내부 경로만 만든다
export function termsHref(versionId: number, sectionId?: string) {
  if (!Number.isInteger(versionId) || versionId <= 0) return null;
  return `/terms/${versionId}` + (sectionId && SECTION_ID.test(sectionId) ? `#${sectionId}` : "");
}

// 약관 화면에서 "AI에게 질문하기"를 누르면 보내는 이벤트. detail은 입력창에 채울 질문
export const ASSISTANT_ASK = "assistant:ask";
