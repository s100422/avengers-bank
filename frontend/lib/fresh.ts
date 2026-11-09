import { useLayoutEffect, useState } from "react";

/**
 * 다른 화면으로 이동했다가 돌아올 때 화면을 처음 상태로 시작하게 하는 key를 돌려준다.
 *
 * Next.js(cacheComponents)는 화면을 떠나도 지우지 않고 숨겨 두고(Activity) 상태를 보존한다. 완료·결과 화면, 열려 있던 확인 창,
 * 입력한 비밀번호·인증 증표 같은 것이 그대로 남아 있다가 돌아오면 다시 보이므로, 숨겨질 때 key를 바꿔 다음 방문은 새로 시작하게 한다.
 * 쓰는 법: 화면 컴포넌트를 `<Content key={useFreshOnLeave()} />`로 감싼다 (훅은 Content 바깥 컴포넌트에서 부른다).
 */
export function useFreshOnLeave(): number {
  const [visit, setVisit] = useState(0);
  useLayoutEffect(() => () => setVisit((v) => v + 1), []);
  return visit;
}
