"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { token } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(token.get() ? "/accounts" : "/login");
  }, [router]);
  return null;
}
