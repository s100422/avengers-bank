import type { FinancialReport, ReportRow } from "@/lib/api";

const badgeTones = {
  mint: "bg-[#e5f3eb] text-[#28634e]",
  coral: "bg-coral-soft text-coral",
  neutral: "bg-[#f1edf7] text-[#5b4b75]",
};
const capturedAtFormat = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

function ReportRows({ rows, maximum }: { rows: ReportRow[]; maximum: number }) {
  return (
    <ul className="space-y-3">
      {rows.map((row, index) => (
        <li key={index}>
          <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
            <span className="min-w-0 font-medium wrap-anywhere">{row.label}</span>
            <strong className="font-semibold tabular-nums">{row.value}</strong>
          </div>
          {row.detail && <p className="mt-0.5 text-xs wrap-anywhere text-slate">{row.detail}</p>}
          {row.bar_amount !== null && maximum > 0 && (
            <div aria-hidden="true" className="mt-1.5 h-1.5 rounded-full bg-coral-soft/55">
              <div className="h-full rounded-full bg-coral/75" style={{ width: `${(row.bar_amount / maximum) * 100}%` }} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

export function FinancialReportCard({ report }: { report: FinancialReport }) {
  return (
    <section aria-label={report.title} className="daily-card assistant-report space-y-4 px-4 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
        <h3 className="text-sm font-bold wrap-anywhere">{report.title}</h3>
        <time dateTime={report.captured_at} className="text-xs text-slate">
          {capturedAtFormat.format(new Date(report.captured_at))} 조회
        </time>
      </div>
      {report.metrics.length > 0 && (
        <dl className={`assistant-report-totals ${report.metrics.length === 2 ? "assistant-report-totals-paired" : ""}`}>
          {report.metrics.map(({ label, value }) => (
            <div key={label} className="min-w-0">
              <dt className="text-xs font-medium text-slate">{label}</dt>
              <dd className="mt-1 text-[clamp(1.125rem,6cqi,1.5rem)] leading-tight font-bold wrap-anywhere tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {report.badge && (
        <p className={`w-fit rounded-full px-2.5 py-1 text-xs font-semibold ${badgeTones[report.badge_tone]}`}>{report.badge}</p>
      )}
      {report.sections.map(({ title, rows }) => {
        const maximum = Math.max(0, ...rows.map((row) => row.bar_amount ?? 0));
        return (
          <div key={title} className="space-y-3 border-t border-line pt-4">
            <h4 className="text-xs font-semibold text-slate">{title}</h4>
            <ReportRows rows={rows.slice(0, 3)} maximum={maximum} />
            {rows.length > 3 && (
              <details className="group border-t border-line pt-2">
                <summary className="cursor-pointer py-1.5 text-sm font-semibold focus-visible:outline-coral">
                  <span className="group-open:hidden">나머지 항목 {rows.length - 3}개 보기</span>
                  <span className="hidden group-open:inline">나머지 항목 접기</span>
                </summary>
                <div className="mt-2"><ReportRows rows={rows.slice(3)} maximum={maximum} /></div>
              </details>
            )}
          </div>
        );
      })}
      {report.note && <p className="text-xs text-slate">{report.note}</p>}
    </section>
  );
}
