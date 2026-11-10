import { clearOpenDrafts } from "./open-draft";
// FastAPI 호출 도우미. 성공은 { data }, 실패는 { error: { message, details } } 모양이다.
// 같은 출처의 /api로 부르면 next.config.ts의 rewrites가 FastAPI로 넘긴다(갱신 토큰 쿠키가 자사 쿠키가 되도록).
const BASE = "/api";
export const SESSION_KEY = "avengers_bank_session"; // storage 이벤트에서 이 키를 본다

// 로그인·갱신·비밀번호 변경이 돌려주는 토큰 묶음. 갱신 토큰은 httpOnly 쿠키라 JS에는 보이지 않는다
export type Session = {
  access_token: string;
  token_type: "bearer";
  expires_in: number; // 액세스 토큰 수명(초)
  session_expires_at: string; // 갱신 토큰 만료 시각(ISO8601 UTC). 지나면 자동 로그아웃
};

// 로그인 응답. 새 기기 인증(DEVICE_VERIFICATION_REQUIRED)은 2단계에서 이 타입에 더한다
export type LoginResult =
  | (Session & { status: "OK" })
  | { status: "DEVICE_VERIFICATION_REQUIRED"; challenge_token: string; phone_masked: string };

// 로그인한(등록된) 기기. current = 지금 이 브라우저
export type Device = { device_id: string; label: string; created_at: string; last_used_at: string | null; current: boolean };
export const devices = {
  list: () => api<Device[]>("/users/me/devices"),
  revoke: (id: string) => api<unknown>(`/users/me/devices/${encodeURIComponent(id)}`, undefined, "DELETE"),
};

// 액세스 토큰은 메모리에만 둔다(XSS로 훔쳐 가도 새로고침·탭 종료면 사라짐). 새로고침하면 비어 있고, 첫 401 → 쿠키로 갱신 경로가 다시 채운다.
let accessToken: string | undefined;

// localStorage에는 비밀이 아닌 만료 시각만 둔다. 다른 탭·타이머·가드가 "로그인 중인지, 언제 끝나는지" 동기적으로 읽는 표시다.
export const session = {
  save: (s: Session) => {
    accessToken = s.access_token;
    localStorage.setItem(SESSION_KEY, JSON.stringify({ session_expires_at: s.session_expires_at }));
  },
  clear: () => {
    accessToken = undefined;
    localStorage.removeItem(SESSION_KEY);
    clearOpenDrafts();
  },
  expiresAt: () => {
    if (typeof window === "undefined") return 0;
    try {
      return Date.parse(JSON.parse(localStorage.getItem(SESSION_KEY) ?? "null")?.session_expires_at ?? "") || 0;
    } catch {
      return 0;
    }
  },
  // 로그인 상태 = 만료 시각 표시가 있다 (액세스 토큰은 5분마다 만료되어도 쿠키로 갱신하면 된다)
  active: () => session.expiresAt() > 0,
};

export class ApiError extends Error {
  // code: 서버 오류 코드(TERMS_OUTDATED 등). 화면이 코드별로 다르게 처리할 때 쓴다
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

// 갱신 토큰으로 다시 받을 수 없는 요청들. 이 요청의 401은 그대로 화면에 보여 준다
const AUTH_PATHS = ["/users/login", "/users/signup", "/users/token/refresh", "/users/logout"];
const isAuthPath = (path: string) => AUTH_PATHS.includes(path) || path.startsWith("/users/login/device");

function send(path: string, body: unknown, method: string | undefined) {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return fetch(BASE + path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    headers,
    credentials: "same-origin", // 갱신 토큰 쿠키를 실어 보낸다
    body: body === undefined ? undefined : JSON.stringify(body),
  }).catch(() => {
    throw new ApiError(0, "서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.");
  });
}

export async function api<T>(path: string, body?: unknown, method?: "PATCH" | "POST" | "PUT" | "DELETE"): Promise<T> {
  let res = await send(path, body, method);

  // 액세스 토큰(5분)이 만료됐으면 한 번만 갱신하고 다시 보낸다. 401은 서버가 처리 전에 거절한 것이라 POST도 다시 보내도 된다
  if (res.status === 401 && session.active() && !isAuthPath(path)) {
    if (await refreshSession()) res = await send(path, body, method);
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
// 쿠키는 브라우저가 항상 최신 값을 보내므로, 다른 탭이 방금 갱신했어도 차례로 한 번 더 갱신하는 것은 무해하다(동시 갱신만 막으면 된다).
let inflight: Promise<boolean> | null = null;

// 마지막 갱신이 실패한 이유(서버 오류 코드). SESSION_REPLACED = 다른 곳에서 로그인해 이 세션이 끊김(단일 세션)
let lastRefreshFailure: string | undefined;
export const REPLACED_MESSAGE = "다른 곳에서 로그인되어 로그아웃되었습니다.";

/**
 * 세션을 갱신한다. 성공이면 true, 갱신 토큰(쿠키)이 죽었으면 false.
 * 서버에 닿지 못하면 ApiError(0)를 던진다(세션은 그대로 둔다).
 */
export function refreshSession(): Promise<boolean> {
  inflight ??= (async () => {
    try {
      return await (navigator.locks ? navigator.locks.request("avengers-bank-refresh", refreshOnce) : refreshOnce());
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

async function refreshOnce(): Promise<boolean> {
  if (!session.active()) return false; // 잠금을 얻은 뒤 저장소를 다시 읽는다(그사이 다른 탭이 로그아웃했을 수 있다)
  try {
    session.save(await api<Session>("/users/token/refresh", undefined, "POST"));
    lastRefreshFailure = undefined;
    return true;
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) throw e;
    lastRefreshFailure = e instanceof ApiError ? e.code : undefined;
    return false;
  }
}

/** 서버 세션을 끊고(실패해도 무시, 쿠키는 서버가 지운다) 저장된 토큰을 지운다 */
export async function logout() {
  const was = session.active();
  session.clear();
  if (was) await api("/users/logout", undefined, "POST").catch(() => {});
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

export type AccountNotification = History & {
  notification_id: number;
  account_id: number;
  account_num: string;
  account_nickname: string | null;
  history_id: number;
  read_at: string | null;
};

// 거래 종류: [화면 이름, 나간 돈인지]
export const HISTORY_TYPE: Record<string, [string, boolean]> = {
  TRANSFER_OUT: ["이체 보냄", true],
  TRANSFER_IN: ["입금", false],
  INTERBANK_OUT: ["타행 이체 보냄", true],
  INTERBANK_IN: ["타행 이체 받음", false],
  INTERBANK_REFUND: ["타행 이체 환불", false],
  TO_SAVINGS: ["적금 납입", true],
  TO_DEPOSIT: ["예금 입금", true],
  CLOSE_IN: ["해지금 입금", false],
  INTEREST: ["이자", false],
  CLOSE_OUT: ["해지", true],
  CARD_PAYMENT: ["체크카드 결제", true],
  CARD_BILL_PAYMENT: ["카드대금 납부", true],
  DEV_CHARGE: ["충전(개발용)", false],
};

export type InterbankResult = {
  transfer_id: string;
  status: "COMPLETED" | "PENDING" | "FAILED";
  to_bank: string;
  to_bank_name: string;
  to_account: string;
  amount: number;
  holder_name: string | null;
  balance_after: number;
  fail_message?: string | null;
};

export type Product = { product_id: number; name: string; description: string; interest_rate: string; min_amount?: number | null };

// 이체 받는 사람 (bank_code "" = 우리 은행). 최근·자주 쓰는 목록은 /transfers/recent, /transfers/favorites
export type Recipient = { bank_code: string; bank_name: string; account: string; name: string | null };
export type RecentRecipient = Recipient & { favorite_id: number | null };
export type FavoriteRecipient = Recipient & { favorite_id: number };

export const won = (n: number) => n.toLocaleString("ko-KR") + "원";

// 예·적금 이자 미리 보기 (GET /accounts/{type}/{id}/interest-preview). 적금 만기 값은 매월 납입을 계속한다고 가정한 예상이다
export type InterestPreview = {
  account_type: "deposit" | "savings";
  interest_rate: string;
  maturity_date: string;
  close_today_principal: number;
  close_today_interest: number;
  close_today_total: number;
  close_today_rate: string;
  close_today_early: boolean;
  maturity_principal: number;
  maturity_interest: number;
  maturity_total: number;
  assumed_payments: number;
  monthly_payment: number | null;
};

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

// 예·적금 가입 화면을 미리 채우는 카드. 가입은 하지 않는다 (약관 동의·계좌 비밀번호는 가입 화면에서 직접)
export type OpenAccountAction = {
  type: "OPEN_ACCOUNT";
  kind: "deposit" | "savings";
  product_id: number;
  product_name: string;
  interest_rate: string;
  summary: { label: string; value: string }[];
  fields: Record<string, string>; // 가입 화면 입력칸 이름 → 값
};

export type AssistantAction = TransferAction | OpenAccountAction;

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

export type AgentReply = { conversation_id: number; answer: string; action: AssistantAction | null; citations?: Citation[] };

export type AgentMessage = {
  message_id: number;
  role: "user" | "assistant";
  content: string;
  action: AssistantAction | null;
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
