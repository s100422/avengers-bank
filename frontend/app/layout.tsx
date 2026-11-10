import type { Metadata } from "next";
import localFont from "next/font/local";
import { Suspense } from "react";
import { AssistantGate } from "@/components/assistant/Assistant";
import "./globals.css";

// 국내 금융 앱에서 흔히 쓰는 한글 UI 서체. 가변 폰트 하나로 모든 굵기를 쓴다.
const pretendard = localFont({
  src: "../node_modules/pretendard/dist/web/variable/woff2/PretendardVariable.woff2",
  variable: "--font-pretendard",
  weight: "45 920",
  display: "swap",
});

export const metadata: Metadata = {
  title: "스파이디뱅킹",
  description: "AvengersBank 데모",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={`${pretendard.variable} h-full antialiased`}>
      <body className="min-h-full font-sans">
        {/* 로그인한 사용자만 쓰는 화면이라 미리 그려 둘 내용이 없다. 현재 시각·주소 값(Date.now, useParams)을 쓰는 화면이 많아서
            (cacheComponents의 프리렌더 검사) 앱 전체를 Suspense 안에서 요청 시 그리게 한다 */}
        <Suspense fallback={null}>{children}</Suspense>
        {/* usePathname은 동적 경로에서 프리렌더 중 멈출 수 있어 Suspense로 감싼다 (cacheComponents) */}
        <Suspense fallback={null}>
          <AssistantGate />
        </Suspense>
      </body>
    </html>
  );
}
