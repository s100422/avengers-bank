import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  // 갱신 토큰 쿠키(httpOnly, SameSite=Strict)가 자사 쿠키가 되도록 브라우저는 같은 출처의 /api로만 부르고,
  // Next 서버가 FastAPI로 넘긴다. API_ORIGIN은 서버 전용 환경변수라 브라우저 번들에 들어가지 않는다.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.API_ORIGIN ?? "http://127.0.0.1:8000"}/:path*` }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
