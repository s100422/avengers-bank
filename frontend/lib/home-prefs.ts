// 홈 화면 설정(대표 계좌, 계좌 순서, 금액 숨김)을 사용자별로 브라우저에 저장한다.
// shortcut: 서버에 저장할 필드·API가 없어 localStorage에 둔다. 다른 기기와 공유되지 않는다. 필요해지면 사용자 설정 API로 옮긴다.
import type { AccountSummary } from "@/lib/api";

export type HomePrefs = {
  reps: string[]; // 대표 계좌 키들 (여러 개 가능, C-066). 홈 슬라이더에는 이 계좌들만 나온다
  order: string[]; // 모든 활성 계좌 키의 사용자 순서
  hideTotal: boolean; // 총자산 숨김
  hidden: string[]; // 잔액을 숨긴 계좌 키
};

// account_id는 종류마다 따로 매겨지므로 종류와 합쳐야 고유하다
export const accountKey = (a: Pick<AccountSummary, "account_type" | "account_id">) => `${a.account_type}-${a.account_id}`;

const storageKey = (userId: number) => `avengers_bank_home:${userId}`;
const EMPTY: HomePrefs = { reps: [], order: [], hideTotal: false, hidden: [] };

export function loadPrefs(userId: number): HomePrefs {
  try {
    const raw = JSON.parse(localStorage.getItem(storageKey(userId)) ?? "null");
    if (!raw || typeof raw !== "object") return EMPTY;
    const strings = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
    return {
      // 예전 저장값(대표 한 개, rep)도 읽는다
      reps: Array.isArray(raw.reps) ? strings(raw.reps) : typeof raw.rep === "string" ? [raw.rep] : [],
      order: strings(raw.order),
      hideTotal: raw.hideTotal === true,
      hidden: strings(raw.hidden),
    };
  } catch {
    return EMPTY; // 저장소를 못 쓰거나 값이 깨졌으면 기본값
  }
}

export function savePrefs(userId: number, prefs: HomePrefs) {
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(prefs));
  } catch {
    // 시크릿 창 등 저장소를 못 쓰면 이번 화면에서만 유지한다
  }
}

// 지금 있는 계좌 기준으로 정리: 사라진(해지된) 계좌 설정은 지우고, 새 계좌는 순서 끝에 붙인다
export function sanitize(prefs: HomePrefs, keys: string[]): HomePrefs {
  const valid = new Set(keys);
  const order = [...new Set(prefs.order)].filter((k) => valid.has(k));
  for (const k of keys) if (!order.includes(k)) order.push(k);
  return {
    reps: [...new Set(prefs.reps)].filter((k) => valid.has(k)),
    order,
    hideTotal: prefs.hideTotal,
    hidden: prefs.hidden.filter((k) => valid.has(k)),
  };
}

export const toggle = (list: string[], key: string) => (list.includes(key) ? list.filter((k) => k !== key) : [...list, key]);
