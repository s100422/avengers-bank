// 화면에서 AI 비서 패널을 열고 질문을 바로 보낸다 (돈 관리의 "왜 늘었지?" 등). Assistant.tsx가 이 이벤트를 듣는다.
// 약관 화면은 같은 이벤트에 문자열을 실어 입력창만 채운다.
import { ASSISTANT_ASK } from "@/lib/api";
export type AssistantAsk = { text: string };

export function askAssistant(text: string) {
  window.dispatchEvent(new CustomEvent<AssistantAsk>(ASSISTANT_ASK, { detail: { text } }));
}
