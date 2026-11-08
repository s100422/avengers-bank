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
  // code: 서버 오류 코드(TERMS_OUTDATED 등). 화면이 코드별로 다르게 처리할 때 쓴다
  constructor(public status: number, message: string, public code?: string) {
    super(message);
  }
}

export async function api<T>(path: string, body?: unknown, method?: "PATCH" | "POST"): Promise<T> {
  const headers: Record<string, string> = {};
  const t = token.get();
  if (t) headers.Authorization = `Bearer ${t}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method: method ?? (body === undefined ? "GET" : "POST"),
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
    throw new ApiError(res.status, message ?? `요청이 실패했습니다 (${res.status}).`, err?.code);
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

export type Product = { product_id: number; name: string; description: string; interest_rate: string };

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
  confirm: (draftId: string) => api<AgentTransferResult>(`/agent/transfers/${encodeURIComponent(draftId)}/confirm`, undefined, "POST"),
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
