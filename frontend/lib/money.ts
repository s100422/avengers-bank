// 돈 관리 API 타입. 서버 src/avengers_bank/domains/money_management/schemas.py와 1:1로 맞춘다.
import { api } from "@/lib/api";

export type Category =
  | "DINING" | "CAFE" | "MART" | "BEAUTY" | "ONLINE" | "SUBSCRIPTION" | "TRANSPORT"
  | "HOUSING" | "MEDICAL" | "LEISURE" | "TRANSFER" | "ETC" | "UNCLASSIFIED";

export const CATEGORY_LABELS: Record<Category, string> = {
  DINING: "외식", CAFE: "카페", MART: "마트·편의점", BEAUTY: "뷰티·생활", ONLINE: "온라인쇼핑",
  SUBSCRIPTION: "구독·디지털", TRANSPORT: "교통", HOUSING: "주거·통신", MEDICAL: "의료",
  LEISURE: "여가·문화", TRANSFER: "이체", ETC: "기타", UNCLASSIFIED: "미분류",
};

export type Source = "credit" | "debit" | "checking";
export type Direction = "IN" | "OUT";
export type CategorySource = "OVERRIDE" | "RULE" | "CACHE" | "LLM" | "TYPE" | "NONE";
export type PaceStatus = "HIGHER" | "NORMAL" | "LOWER" | "UNKNOWN";

// months: 0 = 비교 데이터 없음, 1 = "지난달 기준", 2~3 = "최근 N개월 평균"
export type Baseline = { months: number; period_start: string | null; period_end: string | null; monthly_avg: number | null };

export type TxnItem = {
  source: Source; source_id: number; occurred_at: string; merchant: string | null; amount: number;
  direction: Direction; category: Category | null; category_label: string | null; category_source: CategorySource;
  is_one_off: boolean; payment_label: string;
};

export type ScheduledItem = {
  key: string; kind: "CARD_BILL" | "RECURRING"; name: string; date: string; amount: number; direction: Direction;
  status: "CONFIRMED" | "ESTIMATED"; account_label: string | null; recurring_id: number | null; bill_id: number | null;
};

export type Forecast = {
  is_current_month: boolean; actual_to_date: number; remaining_recurring: number; remaining_variable: number;
  projected_total: number; variable_basis: "BASELINE" | "THIS_MONTH" | "NONE"; baseline: Baseline; change_rate: number | null;
};

// 각 리스트의 i번째 = (i+1)일까지 누적 소비. projected는 today_day+1일부터 말일까지
export type Pace = {
  status: PaceStatus; diff_rate: number | null; today_day: number; days_in_month: number;
  actual_cumulative: number[]; projected_cumulative: number[]; baseline_cumulative: number[] | null;
};

export type CategorySpend = {
  category: Category; label: string; actual: number; baseline_to_date: number | null; diff: number | null;
  projected: number | null; status: PaceStatus;
};

export type Summary = {
  month: string; refreshed_at: string; forecast: Forecast; pace: Pace; upcoming: ScheduledItem[]; upcoming_total: number;
  categories: CategorySpend[]; remaining_recurring_items: ScheduledItem[]; one_off_transactions: TxnItem[]; review_count: number;
};

export type CategoryDetail = {
  month: string; spend: CategorySpend; baseline: Baseline; monthly: { month: string; amount: number }[];
  merchants: { merchant: string; amount: number; count: number }[]; transactions: TxnItem[];
};

export type RecurringItem = {
  recurring_id: number; name: string; merchant_key: string | null; direction: Direction; category: Category | null;
  category_label: string | null; amount: number; day_of_month: number; status: "ACTIVE" | "EXCLUDED";
  skip_month: string | null; transactions: TxnItem[];
};

export type RecurringCandidate = {
  merchant_key: string; name: string; direction: Direction; category: Category | null; category_label: string | null;
  amount: number; day_of_month: number; occurrences: number; months_observed: number; pattern_confirmed: boolean;
  transactions: TxnItem[];
};

export type TxnDetail = { transaction: TxnItem; merchant_key: string | null; has_merchant_rule: boolean; recurring: RecurringItem | null };

export type RecurringCreate = {
  name: string; direction: Direction; category?: Category | null; amount: number; day_of_month: number; merchant_key?: string | null;
};
export type RecurringUpdate = Partial<Pick<RecurringItem, "name" | "category" | "amount" | "day_of_month" | "status" | "skip_month">> & { clear_skip?: boolean };

// month: "YYYY-MM"
export const money = {
  summary: (month: string) => api<Summary>(`/money/summary?month=${month}`),
  schedule: (month: string) => api<ScheduledItem[]>(`/money/schedule?month=${month}`),
  category: (category: Category, month: string) => api<CategoryDetail>(`/money/categories/${category}?month=${month}`),
  transaction: (source: Source, id: number) => api<TxnDetail>(`/money/transactions/${source}/${id}`),
  setCategory: (source: Source, id: number, category: Category, scope: "THIS" | "MERCHANT") =>
    api<TxnDetail>(`/money/transactions/${source}/${id}/category`, { category, scope }, "PUT"),
  setOneOff: (source: Source, id: number, is_one_off: boolean) =>
    api<TxnDetail>(`/money/transactions/${source}/${id}/one-off`, { is_one_off }, "PUT"),
  recurring: () => api<{ candidates: RecurringCandidate[]; registered: RecurringItem[] }>("/money/recurring"),
  addRecurring: (body: RecurringCreate) => api<RecurringItem>("/money/recurring", body, "POST"),
  updateRecurring: (id: number, body: RecurringUpdate) => api<RecurringItem>(`/money/recurring/${id}`, body, "PATCH"),
  dismissCandidate: (merchant_key: string, name: string, direction: Direction) =>
    api<null>("/money/recurring/dismiss", { merchant_key, name, direction }, "POST"),
};
