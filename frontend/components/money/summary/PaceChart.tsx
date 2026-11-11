import { won } from "@/lib/api";
import type { Pace } from "@/lib/money";
import { manwon } from "./format";

// 평소(기준) 막대 색. 이번 달은 coral. 색만으로 구분하지 않게 모든 막대에 글자 라벨을 붙인다
const USUAL = "#8c8079";

// 요약 탭: 오늘까지 쓴 돈 vs 평소 같은 시점, 가로 막대 2줄 (같은 눈금)
export function PaceBars({ pace, current }: { pace: Pace; current: boolean }) {
  const day = pace.today_day;
  const actual = pace.actual_cumulative[day - 1] ?? 0;
  const usual = pace.baseline_cumulative ? pace.baseline_cumulative[day - 1] ?? 0 : null;
  const max = Math.max(1, actual, usual ?? 0);
  const rows = [
    { label: current ? "이번 달 · 오늘까지" : "이 달", value: actual, color: "var(--coral)" },
    ...(usual === null ? [] : [{ label: current ? "평소 같은 시점" : "평소", value: usual, color: USUAL }]),
  ];
  return (
    <dl className="mt-4 space-y-3">
      {rows.map((r) => (
        <div key={r.label}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <dt className="text-slate">{r.label}</dt>
            <dd className="font-semibold tabular-nums">{won(r.value)}</dd>
          </div>
          <div aria-hidden className="mt-1 h-3 rounded-sm bg-porcelain">
            <div className="h-3 min-w-[2px] rounded-r-[4px]" style={{ width: `${(r.value / max) * 100}%`, background: r.color }} />
          </div>
        </div>
      ))}
    </dl>
  );
}

type Week = { label: string; actual: number; projected: number; usual: number | null };

// 누적 배열에서 주별(1~7일, 8~14일 …) 금액을 만든다. 오늘이 낀 주는 실제와 예상으로 나눈다
export function weeks(pace: Pace): Week[] {
  const n = pace.days_in_month;
  const full = [...pace.actual_cumulative, ...pace.projected_cumulative];
  const at = (arr: number[], d: number) => (d <= 0 ? 0 : arr[Math.min(d, arr.length) - 1] ?? 0);
  const out: Week[] = [];
  for (let start = 1; start <= n; start += 7) {
    const end = Math.min(start + 6 > 28 ? n : start + 6, n); // 29일~말일은 한 묶음
    const cut = Math.min(end, pace.today_day);
    const actual = Math.max(0, at(pace.actual_cumulative, cut) - at(pace.actual_cumulative, start - 1));
    const total = at(full, end) - at(full, start - 1);
    out.push({
      label: `${start}~${end}일`,
      actual: start > pace.today_day ? 0 : actual,
      projected: Math.max(0, total - (start > pace.today_day ? 0 : actual)),
      usual: pace.baseline_cumulative ? at(pace.baseline_cumulative, end) - at(pace.baseline_cumulative, start - 1) : null,
    });
    if (end === n) break;
  }
  return out;
}

const BAR_H = 120;

// 분석 상세: 주별로 이번 달(실제 + 예상)과 평소를 나란히. 언제부터 늘었는지 보인다
export function WeeklyBars({ pace }: { pace: Pace }) {
  const data = weeks(pace);
  const max = Math.max(1, ...data.map((w) => Math.max(w.actual + w.projected, w.usual ?? 0)));
  const h = (v: number) => Math.round((v / max) * BAR_H);
  const hasProjected = data.some((w) => w.projected > 0);
  const hasUsual = data.some((w) => w.usual !== null);
  return (
    <figure className="mt-3 rounded-2xl bg-paper p-4">
      <div className="flex items-end gap-2" aria-hidden>
        {data.map((w) => {
          const total = w.actual + w.projected;
          return (
            <div key={w.label} className="flex min-w-0 flex-1 flex-col items-center">
              <p className="mb-1 text-[11px] text-slate tabular-nums">{total > 0 ? manwon(total).replace(" 원", "") : ""}</p>
              <div className="flex items-end gap-[2px]" style={{ height: BAR_H }}>
                <div className="flex w-4 flex-col justify-end gap-[2px] sm:w-5" title={`${w.label} 이번 달: 실제 ${won(w.actual)}${w.projected ? `, 예상 약 ${won(w.projected)}` : ""}`}>
                  {w.projected > 0 && (
                    <div
                      className="rounded-t-[4px] border border-dashed border-coral bg-coral-soft"
                      style={{ height: Math.max(3, h(w.projected)) }}
                    />
                  )}
                  {w.actual > 0 && (
                    <div className={`bg-coral ${w.projected > 0 ? "" : "rounded-t-[4px]"}`} style={{ height: Math.max(2, h(w.actual)) }} />
                  )}
                </div>
                {w.usual !== null && (
                  <div
                    className="w-4 rounded-t-[4px] sm:w-5"
                    title={`${w.label} 평소: ${won(w.usual)}`}
                    style={{ height: Math.max(w.usual > 0 ? 2 : 0, h(w.usual)), background: USUAL }}
                  />
                )}
              </div>
              <p className="mt-1 w-full truncate border-t border-line pt-1 text-center text-[11px] text-slate">{w.label}</p>
            </div>
          );
        })}
      </div>
      <figcaption className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate">
        <span className="flex items-center gap-1.5"><i className="inline-block size-2.5 rounded-[2px] bg-coral" />이번 달 실제</span>
        {hasProjected && (
          <span className="flex items-center gap-1.5"><i className="inline-block size-2.5 rounded-[2px] border border-dashed border-coral bg-coral-soft" />이번 달 예상</span>
        )}
        {hasUsual && (
          <span className="flex items-center gap-1.5"><i className="inline-block size-2.5 rounded-[2px]" style={{ background: USUAL }} />평소</span>
        )}
      </figcaption>
      {/* 화면 읽기 프로그램용 표 */}
      <table className="sr-only">
        <caption>주별 소비: 이번 달과 평소</caption>
        <thead>
          <tr><th scope="col">기간</th><th scope="col">이번 달 실제</th><th scope="col">이번 달 예상</th><th scope="col">평소</th></tr>
        </thead>
        <tbody>
          {data.map((w) => (
            <tr key={w.label}>
              <th scope="row">{w.label}</th><td>{won(w.actual)}</td><td>{won(w.projected)}</td><td>{w.usual === null ? "없음" : won(w.usual)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
