import type { ReactNode } from "react";

// AI 답변의 간단한 마크다운만 그린다: **굵게**, 목록(- * • 1.), 문단.
// 글자를 React 요소로만 만들고 HTML은 해석하지 않으므로 답변에 태그가 섞여도 실행되지 않는다.
// 마스킹된 번호(120-***-**9722)의 *는 굵게 표시로 읽지 않도록 잠시 다른 글자로 바꿔 둔다
const MASK = "\u0000";
const restore = (s: string) => s.replaceAll(MASK, "*");

function inline(text: string): ReactNode[] {
  const safe = text.replace(/\d+(?:-[\d*]+)+/g, (num) => num.replaceAll("*", MASK));
  return safe.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.length > 4 && part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="font-semibold text-ink">
        {restore(part.slice(2, -2))}
      </strong>
    ) : (
      restore(part)
    ),
  );
}

type List = { ordered: boolean; items: string[] };

export function RichText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: List | null = null;
  let item = 0; // 목록 항목이 차례로 나타나게 하는 순번

  const flush = () => {
    if (!list) return;
    const { ordered, items } = list;
    const Tag = ordered ? "ol" : "ul";
    blocks.push(
      <Tag key={blocks.length} className="space-y-1.5">
        {items.map((t, i) => (
          <li
            key={i}
            className="msg-in flex gap-2.5 rounded-xl bg-porcelain px-3 py-2"
            style={{ animationDelay: `${(item++) * 70}ms` }}
          >
            {ordered ? (
              <span aria-hidden className="mt-px grid size-5 shrink-0 place-items-center rounded-full bg-coral-soft text-xs font-semibold text-coral">
                {i + 1}
              </span>
            ) : (
              <span aria-hidden className="mt-[0.45rem] size-1.5 shrink-0 rounded-full bg-coral" />
            )}
            <span className="min-w-0">{inline(t)}</span>
          </li>
        ))}
      </Tag>,
    );
    list = null;
  };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const m = line.match(/^([-*•]|\d+[.)])\s+(.+)$/);
    if (m) {
      const ordered = /\d/.test(m[1]);
      if (!list || list.ordered !== ordered) {
        flush();
        list = { ordered, items: [] };
      }
      list.items.push(m[2]);
      continue;
    }
    flush();
    if (line) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
  }
  flush();

  return <div className="space-y-2 leading-relaxed">{blocks}</div>;
}
