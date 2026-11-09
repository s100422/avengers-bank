// 가입 화면(/open/{kind})이 입력값을 맡겨 두는 sessionStorage 항목. 화면과 비서의 가입 카드가 같은 키·모양을 쓴다.
// 화면이 열릴 때 한 번 읽어서 입력칸을 채운다. 계좌 비밀번호는 여기 넣지 않는다(화면이 메모리에서만 다룬다).
export const openDraftKey = (kind: string) => `open-draft:${kind}`;

export function saveOpenDraft(kind: string, productId: number, fields: Record<string, string>) {
  try {
    sessionStorage.setItem(openDraftKey(kind), JSON.stringify({ productId, agreed: {}, fields }));
  } catch {}
}
