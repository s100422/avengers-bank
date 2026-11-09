// 가입 화면(/open/{kind})이 입력값을 맡겨 두는 sessionStorage 항목. 화면과 비서의 가입 카드가 같은 키·모양을 쓴다.
// 화면이 열릴 때 한 번 읽어서 입력칸을 채운다. 계좌 비밀번호는 여기 넣지 않는다(화면이 메모리에서만 다룬다).
export const openDraftKey = (kind: string) => `open-draft:${kind}`;

export function saveOpenDraft(kind: string, productId: number, fields: Record<string, string>) {
  try {
    sessionStorage.setItem(openDraftKey(kind), JSON.stringify({ productId, agreed: {}, fields }));
  } catch {}
}

// 계좌 비밀번호 임시값: 저장소가 아니라 메모리에만 둔다. 화면 이동(클라이언트 이동)에는 남고 새로고침·탭 닫기·로그아웃이면 사라진다
export const heldSecrets: Record<string, Record<string, string>> = {};

// 로그아웃·세션 만료 때 부른다: 같은 탭에서 다른 사람이 로그인했을 때 이전 사람의 가입 입력 초안이 채워지지 않게 한다
export function clearOpenDrafts() {
  for (const k of Object.keys(heldSecrets)) delete heldSecrets[k];
  try {
    for (const k of Object.keys(sessionStorage)) if (k.startsWith("open-draft:")) sessionStorage.removeItem(k);
  } catch {}
}
