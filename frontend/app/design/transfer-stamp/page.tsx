"use client";

import { type CSSProperties, useState } from "react";
import { SpiderMascot } from "@/components/SpiderMascot";
import "./motion.css";

const concepts = [
  {
    id: "square",
    name: "한 줄 발사 · 사각 도장",
    description: "왼쪽에서 날아온 거미줄이 닿자마자 기울어진 사각 도장이 찍혀요.",
    impact: 290,
    launches: ["M4 98C55 113 79 42 150 67", "M12 108Q75 103 96 76"],
  },
  {
    id: "wide",
    name: "양쪽 발사 · 가로 도장",
    description: "양옆에서 날아온 두 줄이 한가운데서 만나 가로 도장을 찍어요.",
    impact: 265,
    launches: ["M3 98C51 113 80 47 150 67", "M297 36C249 21 220 87 150 67"],
  },
  {
    id: "weave",
    name: "사방 발사 · 거미줄 도장",
    description: "사방에서 날아온 줄이 엮여, 가운데 ‘완료’가 새겨진 거미줄 도장으로 찍혀요.",
    impact: 410,
    launches: ["M7 8Q70 20 150 67", "M293 8Q230 20 150 67", "M7 126Q70 114 150 67", "M293 126Q230 114 150 67"],
  },
] as const;

type Concept = (typeof concepts)[number];

// 거미줄 도장 (viewBox 0~100, 가운데 50,50). 살 8개, 고리는 살 사이에서 안쪽으로 처진 곡선(실제 거미줄처럼)
const SPOKES = 8;
const point = (r: number, i: number) => {
  const a = (i / SPOKES) * 2 * Math.PI - Math.PI / 2;
  return `${(50 + r * Math.cos(a)).toFixed(1)} ${(50 + r * Math.sin(a)).toFixed(1)}`;
};
const ring = (r: number, sag: number) =>
  `M${point(r, 0)}` +
  Array.from({ length: SPOKES }, (_, i) => `Q${point(r * sag, i + 0.5)} ${point(r, i + 1)}`).join("") +
  "Z";
const WEB_RIM = ring(47, 0.84);
const WEB_RINGS = ring(36, 0.86) + ring(26, 0.88);
const WEB_SPOKES = Array.from({ length: SPOKES }, (_, i) => `M${point(20, i)}L${point(47, i)}`).join("");

function StampMotion({ concept }: { concept: Concept }) {
  return (
    <div
      aria-hidden="true"
      className="transfer-stamp-stage"
      data-stamp={concept.id}
      style={{ "--stamp-impact": `${concept.impact}ms` } as CSSProperties}
    >
      <svg viewBox="0 0 300 134" className="transfer-stamp-scene" fill="none">
        {concept.id === "weave" && (
          <path
            className="transfer-stamp-web"
            d="M150 11Q184 28 211 31Q201 68 211 103Q180 106 150 123Q120 106 89 103Q99 68 89 31Q116 28 150 11M150 30Q174 43 190 44Q183 67 190 90Q171 92 150 104Q129 92 110 90Q117 67 110 44Q126 43 150 30M150 11v112M89 31l122 72M211 31 89 103"
          />
        )}
        {concept.launches.map((d, index) => (
          <path
            key={d}
            d={d}
            pathLength={100}
            className="transfer-stamp-launch"
            style={{ animationDelay: `${concept.id === "square" ? index * 32 : 0}ms` }}
          />
        ))}
        <path className="transfer-stamp-spark" d="M87 19l-7-6M76 46l-11-3M77 92l-11 6M94 113l-7 7M213 19l7-6M224 46l11-3M223 92l11 6M206 113l7 7" />
      </svg>
      <span className="transfer-stamp-seal">
        {concept.id === "weave" && (
          <svg className="transfer-stamp-web-outline" viewBox="0 0 100 100" fill="none">
            <path className="transfer-stamp-web-rim" d={WEB_RIM} />
            <path className="transfer-stamp-web-threads" d={WEB_SPOKES + WEB_RINGS} />
            {/* 가운데는 비워 '완료' 글자가 실에 가리지 않게 한다 */}
            <circle className="transfer-stamp-web-hub" cx="50" cy="50" r="19" />
          </svg>
        )}
        <span className="transfer-stamp-seal-label">완료</span>
      </span>
    </div>
  );
}

export default function TransferStampPreview() {
  const [replays, setReplays] = useState([0, 0, 0]);

  function replay(index?: number) {
    setReplays((previous) => previous.map((count, position) =>
      index === undefined || index === position ? count + 1 : count,
    ));
  }

  return (
    <main className="transfer-stamp-page">
      <header className="transfer-stamp-brand">
        <SpiderMascot className="size-8 text-coral" />
        <span><strong>Spider</strong>Bank</span>
      </header>
      <div className="transfer-stamp-intro">
        <div>
          <h1>이체 완료 모션</h1>
          <p>거미줄을 발사한 뒤 ‘완료’ 도장이 찍히는 세 가지 방식이에요.</p>
        </div>
        <button className="transfer-stamp-replay" type="button" onClick={() => replay()}>모두 다시 재생</button>
      </div>
      <div className="transfer-stamp-grid">
        {concepts.map((concept, index) => (
          <article className="transfer-stamp-card" key={concept.id}>
            <header className="transfer-stamp-caption">
              <h2>{index + 1}. {concept.name}</h2>
              <p>{concept.description}</p>
            </header>
            <div className="transfer-stamp-preview">
              <StampMotion key={replays[index]} concept={concept} />
              <p className="transfer-stamp-complete">이체됐습니다!</p>
              <p className="transfer-stamp-amount">50,000원</p>
              <p className="transfer-stamp-sample">미리보기 금액</p>
            </div>
            <button
              aria-label={`${concept.name} 다시 재생`}
              className="transfer-stamp-replay"
              type="button"
              onClick={() => replay(index)}
            >
              다시 재생
            </button>
          </article>
        ))}
      </div>
    </main>
  );
}
