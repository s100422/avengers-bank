"use client";

import { useState } from "react";
import { SpiderMascot } from "@/components/SpiderMascot";
import { StampMotion, concepts } from "@/components/TransferStamp";

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
