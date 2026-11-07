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
        {children}
        {/* usePathname은 동적 경로에서 프리렌더 중 멈출 수 있어 Suspense로 감싼다 (cacheComponents) */}
        <Suspense fallback={null}>
          <AssistantGate />
        </Suspense>
      </body>
    </html>
  );
}
