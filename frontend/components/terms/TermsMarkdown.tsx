import type { ReactNode } from "react";
import { SECTION_ID } from "@/lib/api";

// 약관 본문용 작은 마크다운 렌더러. React 요소로만 그리고 HTML은 해석하지 않는다(태그는 글자 그대로 보인다).
// 지원: # ## ### 제목, "## [section-id] 제목"의 조항 id, 문단, - / 1. 목록, | 표 |, **굵게**. 나머지는 평문.

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.length > 4 && part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="font-semibold text-ink">
        {part.slice(2, -2)}
      </strong>
    ) : (
      part
    ),
  );
}

const cells = (line: string) => line.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
const isDivider = (line: string) => /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$/.test(line);

function Heading({ level, text }: { level: number; text: string }) {
  // "[section-id] 제목" → id를 붙인다. 모양이 맞지 않으면 id 없이 원문 그대로 보인다
  const m = text.match(/^\[([^\]]+)\]\s+(.+)$/);
  const id = m && SECTION_ID.test(m[1]) ? m[1] : undefined;
  const body = inline(id ? m![2] : text);
  if (level === 1) return <h2 className="mt-8 text-xl font-semibold">{body}</h2>;
  if (level === 2)
    return (
      <h2 id={id} className="mt-8 scroll-mt-6 text-lg font-semibold">
        {body}
      </h2>
    );
  return (
    <h3 id={id} className="mt-6 scroll-mt-6 font-semibold">
      {body}
    </h3>
  );
}

export function TermsMarkdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let para: string[] = [];

  const flushPara = () => {
    if (para.length) blocks.push(<p key={blocks.length}>{inline(para.join(" "))}</p>);
    para = [];
  };

  for (let i = 0; i < lines.length; ) {
    const line = lines[i].trim();

    const h = line.match(/^(#{1,3})\s+(.+)$/);
    if (h) {
      flushPara();
      blocks.push(<Heading key={blocks.length} level={h[1].length} text={h[2]} />);
      i++;
      continue;
    }

    const li = line.match(/^(-|\d+\.)\s+(.+)$/);
    if (li) {
      flushPara();
      const ordered = li[1] !== "-";
      const items: string[] = [];
      for (let m; i < lines.length && (m = lines[i].trim().match(/^(-|\d+\.)\s+(.+)$/)) && (m[1] !== "-") === ordered; i++) items.push(m[2]);
      const Tag = ordered ? "ol" : "ul";
      blocks.push(
        <Tag key={blocks.length} className={`space-y-1 pl-6 ${ordered ? "list-decimal" : "list-disc"}`}>
          {items.map((t, k) => (
            <li key={k}>{inline(t)}</li>
          ))}
        </Tag>,
      );
      continue;
    }

    // 표: 머리 줄 + 구분 줄(|---|) + 본문 줄들
    if (line.startsWith("|") && i + 1 < lines.length && isDivider(lines[i + 1].trim())) {
      flushPara();
      const head = cells(line);
      const rows: string[][] = [];
      for (i += 2; i < lines.length && lines[i].trim().startsWith("|"); i++) rows.push(cells(lines[i].trim()));
      blocks.push(
        <div key={blocks.length} className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                {head.map((c, k) => (
                  <th key={k} className="border border-line bg-porcelain px-3 py-2 text-left font-semibold">
                    {inline(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, k) => (
                <tr key={k}>
                  {r.map((c, n) => (
                    <td key={n} className="border border-line px-3 py-2 align-top">
                      {inline(c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (line) para.push(line);
    else flushPara();
    i++;
  }
  flushPara();

  return <div className="space-y-3 leading-relaxed">{blocks}</div>;
}
