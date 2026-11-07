"use client";

import { useEffect, useMemo, useState } from "react";
import { ACCOUNTS_CHANGED, AccountSummary, User, api } from "@/lib/api";
import { HomePrefs, accountKey, loadPrefs, sanitize, savePrefs } from "@/lib/home-prefs";

// 홈과 설정 화면이 함께 쓰는 것: 로그인 사용자, 활성 계좌(사용자 순서), 저장된 홈 설정
export function useHomeData() {
  const [user, setUser] = useState<User | null>(null);
  const [accounts, setAccounts] = useState<AccountSummary[] | null>(null);
  const [prefs, setPrefs] = useState<HomePrefs | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => Promise.all([api<User>("/users/me"), api<AccountSummary[]>("/accounts")])
      .then(([u, all]) => {
        const open = all.filter((a) => a.status !== "CLOSED");
        const clean = sanitize(loadPrefs(u.user_id), open.map(accountKey));
        savePrefs(u.user_id, clean); // 해지된 계좌 설정은 여기서 지워진다
        setUser(u);
        setAccounts(open);
        setPrefs(clean);
      })
      .catch((e) => setError(e.message));
    load();
    // AI 비서로 이체하면 잔액을 다시 불러온다
    window.addEventListener(ACCOUNTS_CHANGED, load);
    return () => window.removeEventListener(ACCOUNTS_CHANGED, load);
  }, []);

  function update(change: (p: HomePrefs) => HomePrefs) {
    if (!prefs || !user) return;
    const next = change(prefs);
    setPrefs(next);
    savePrefs(user.user_id, next);
  }

  const ordered = useMemo(() => {
    if (!accounts || !prefs) return [];
    const byKey = new Map(accounts.map((a) => [accountKey(a), a]));
    return prefs.order.flatMap((k) => byKey.get(k) ?? []);
  }, [accounts, prefs]);

  return { user, accounts, prefs, ordered, update, error };
}
