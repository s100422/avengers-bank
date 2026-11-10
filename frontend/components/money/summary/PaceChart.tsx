import type { Pace } from "@/lib/money";
import { manwon } from "./format";

const W = 300;
const H = 120;
const PAD = { l: 4, r: 4, t: 8, b: 18 };

// 누적 소비 그래프 (차트 라이브러리 없이 직접 그린다). 실선 = 실제, 점선 = 예상, 회색 = 평소
export function PaceChart({ pace }: { pace: Pace }) {
  const { actual_cumulative: actual, projected_cumulative: projected, baseline_cumulative: baseline, days_in_month: n } = pace;
  const max = Math.max(1, ...actual, ...projected, ...(baseline ?? []));
  const x = (day: number) => PAD.l + ((day - 1) / Math.max(1, n - 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => H - PAD.b - (v / max) * (H - PAD.t - PAD.b);
  const path = (pts: [number, number][]) => pts.map(([d, v], i) => `${i ? "L" : "M"}${x(d).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  const actualPts = actual.map((v, i) => [i + 1, v] as [number, number]);
  // 예상선은 마지막 실제 점에서 이어 그린다
  const projPts: [number, number][] = [
    ...actualPts.slice(-1),
    ...projected.map((v, i) => [actual.length + i + 1, v] as [number, number]),
  ];
  const basePts = baseline?.map((v, i) => [i + 1, v] as [number, number]);

  const lastActual = actual.at(-1) ?? 0;
  const label =
    `누적 소비 그래프. ${pace.today_day}일까지 실제 ${manwon(lastActual)}` +
    (projected.length ? `, 월말 예상 ${manwon(projected.at(-1)!)}` : "") +
    (baseline ? `, 평소 같은 시점 ${manwon(baseline[Math.max(0, actual.length - 1)] ?? 0)}, 평소 월말 ${manwon(baseline.at(-1) ?? 0)}` : "");

  return (
    <figure className="mt-3">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="h-auto w-full">
        <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} className="stroke-line" strokeWidth={1} />
        {basePts && <path d={path(basePts)} fill="none" className="stroke-slate/40" strokeWidth={2} strokeLinejoin="round" />}
        {projPts.length > 1 && (
          <path d={path(projPts)} fill="none" className="stroke-coral" strokeWidth={2} strokeDasharray="4 4" strokeLinejoin="round" />
        )}
        {actualPts.length > 0 && (
          <path d={path(actualPts)} fill="none" className="stroke-coral" strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
        )}
        {actualPts.length > 0 && <circle cx={x(actual.length)} cy={y(lastActual)} r={3.5} className="fill-coral" />}
        {[1, Math.ceil(n / 2), n].map((d) => (
          <text key={d} x={x(d)} y={H - 4} textAnchor={d === 1 ? "start" : d === n ? "end" : "middle"} className="fill-slate text-[9px]">
            {d}일
          </text>
        ))}
      </svg>
      <figcaption className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate" aria-hidden>
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-coral" />실제</span>
        {projected.length > 0 && (
          <span className="flex items-center gap-1.5"><span className="w-4 border-t-2 border-dashed border-coral" />예상</span>
        )}
        {baseline && <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-slate/40" />평소</span>}
      </figcaption>
    </figure>
  );
}
