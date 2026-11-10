"use client";

import { useState } from "react";
import { SpiderMascot } from "@/components/SpiderMascot";

const styles = new Proxy({} as Record<string, string>, {
  get: (_target, property) => String(property),
});

const concepts = [
  {
    name: "코랄 데일리",
    note: "따뜻하고 친근한 기본형",
    title: "오늘도 가볍게, 스파이더뱅킹",
    body: "필요한 금융을 한눈에 확인해봐.",
  },
  {
    name: "미드나잇 웹",
    note: "짙은 네이비와 선명한 레드",
    title: "내 금융을 촘촘하게 연결해",
    body: "거미줄처럼 이어지는 나만의 금융 허브.",
  },
  {
    name: "플레이풀 스파이더",
    note: "캐릭터를 살린 발랄한 화면",
    title: "작은 거미와 시작하는 큰 관리",
    body: "소비도 저축도 귀엽고 똑똑하게.",
  },
];

function SpiderMark({ small = false }: { small?: boolean }) {
  return <SpiderMascot className={small ? styles.spiderSmall : styles.spider} label="Red spider mascot" />;
}

export default function SpiderDesignPreview() {
  const [active, setActive] = useState(0);
  const concept = concepts[active];

  return (
    <main className={`spiderPreviewPage theme${active + 1}`}>
      <header className={styles.topbar}>
        <a className={styles.brand} href="#top" aria-label="SpiderBank logo">
          <SpiderMark small />
          <span><span className="font-bold">Spider</span><span className={styles.brandLight}>Bank</span></span>
        </a>
        <span className={styles.previewTag}>DESIGN CONCEPTS · 01</span>
      </header>

      <section className={styles.intro} id="top">
        <p className={styles.eyebrow}>SpiderBank · Home</p>
        <h1>어떤 거미가<br />우리 은행의 얼굴일까?</h1>
        <p className={styles.lead}>세 가지 분위기의 홈 화면을 비교해보고, 마음에 드는 방향을 골라줘.</p>
      </section>

      <nav className={styles.choices} aria-label="Design concepts">
        {concepts.map((item, index) => (
          <button
            aria-pressed={active === index}
            className={`${styles.choice} ${active === index ? styles.choiceActive : ""}`}
            key={item.name}
            onClick={() => setActive(index)}
            type="button"
          >
            <span className={styles.choiceIndex}>0{index + 1}</span>
            <span className={styles.choiceText}><strong>{item.name}</strong><small>{item.note}</small></span>
            <span className={styles.choiceArrow} aria-hidden="true">↗</span>
          </button>
        ))}
      </nav>

      <section className={styles.showcase} aria-live="polite">
        <div className={styles.copy}>
          <p className={styles.eyebrow}>OPTION 0{active + 1}</p>
          <h2>{concept.title}</h2>
          <p>{concept.body}</p>
          <div className={styles.palette}>
            <span className={styles.swatchRed} />
            <span className={styles.swatchBase} />
            <span className={styles.swatchAccent} />
            <span className={styles.paletteLabel}>{["코랄 · 크림 · 잉크", "미드나잇 · 체리 · 실버", "크림 · 토마토 · 라일락"][active]}</span>
          </div>
          <p className={styles.hint}>위 카드에서 다른 시안을 눌러 비교해봐</p>
        </div>

        <div className={styles.phoneStage}>
          <div className={styles.phone}>
            <div className={styles.phoneTop}><span>9:41</span><span>● ● ▰</span></div>
            <div className={styles.appHeader}>
              <div className={styles.appBrand}><SpiderMark small /><strong><span className="font-bold">Spider</span><span className={styles.brandLight}>Bank</span></strong></div>
              <button className={styles.bell} type="button" aria-label="Notifications">♧</button>
            </div>
            <div className={styles.greeting}><span>안녕, 쑤진님</span><span className={styles.wave}>✦</span><small>오늘의 금융을 확인해봐</small></div>
            <article className={styles.balanceCard}>
              <div className={styles.balanceTop}><span>내 자산</span><span>•••</span></div>
              <strong>₩ 2,480,000</strong>
              <div className={styles.balanceBottom}><span>이번 달 <b>+₩ 120,000</b></span><span className={styles.balanceLink}>자세히 →</span></div>
              {active === 1 && <div className={styles.webLines} aria-hidden="true" />}
              {active === 2 && <div className={styles.miniSpider}><SpiderMark small /></div>}
            </article>
            <div className={styles.sectionTitle}><strong>빠른 메뉴</strong><span>편집</span></div>
            <div className={styles.actions}>
              {[["↗", "송금"], ["▤", "계좌"], ["▣", "카드"], ["＋", "더보기"]].map(([icon, label]) => (
                <div className={styles.action} key={label}><span>{icon}</span><small>{label}</small></div>
              ))}
            </div>
            <article className={styles.insight}>
              <div className={styles.insightIcon}><SpiderMark small /></div>
              <div><small>이번 주 한마디</small><strong>커피값을 잘 아꼈어!</strong></div>
              <span className={styles.insightArrow}>›</span>
            </article>
            <div className={styles.tabbar}><span className={styles.tabActive}>⌂<small>홈</small></span><span>▤<small>자산</small></span><span>◎<small>혜택</small></span><span>☻<small>MY</small></span></div>
          </div>
          <div className={styles.stageNote}><span>●</span> 인터랙티브 시안 <b>·</b> 옵션 0{active + 1}</div>
        </div>
      </section>
      <footer className={styles.footer}><span>SpiderBank</span><span>다음 단계: 선택한 톤으로 실제 홈 화면에 적용</span></footer>
    </main>
  );
}
