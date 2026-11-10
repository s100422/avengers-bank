"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { NOTIFICATION_ARRIVED, notifyCountChanged } from "@/components/notifications/NotificationBell";
import { Button, Shell } from "@/components/ui";
import { AccountNotification, HISTORY_TYPE, api } from "@/lib/api";
import { notificationText } from "@/lib/notifications";

const PAGE_SIZE = 30;

function Notifications() {
  const [items, setItems] = useState<AccountNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [browserPermission, setBrowserPermission] = useState<NotificationPermission | "unsupported">("unsupported");

  useEffect(() => {
    // Browser notifications are optional and require a user gesture to request permission.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- permission is browser state unavailable during server rendering
    setBrowserPermission(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
    let mounted = true;
    const refresh = () => {
      api<AccountNotification[]>(`/notifications?limit=${PAGE_SIZE}&offset=0`)
        .then((rows) => {
          if (!mounted) return;
          setItems(rows);
          setHasMore(rows.length === PAGE_SIZE);
        })
        .catch((err) => { if (mounted) setError((err as Error).message); })
        .finally(() => { if (mounted) setLoading(false); });
    };
    refresh();
    window.addEventListener(NOTIFICATION_ARRIVED, refresh);
    return () => { mounted = false; window.removeEventListener(NOTIFICATION_ARRIVED, refresh); };
  }, []);

  async function loadMore() {
    setBusy(true);
    setError(null);
    try {
      const rows = await api<AccountNotification[]>(`/notifications?limit=${PAGE_SIZE}&offset=${items.length}`);
      setItems((old) => [...old, ...rows]);
      setHasMore(rows.length === PAGE_SIZE);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function markRead() {
    const throughId = items[0]?.notification_id;
    if (!throughId) return;
    setBusy(true);
    setError(null);
    try {
      await api<{ unread_count: number }>("/notifications/read-all", { through_id: throughId });
      const readAt = new Date().toISOString();
      setItems((old) => old.map((item) => item.notification_id <= throughId
        ? { ...item, read_at: item.read_at ?? readAt } : item));
      notifyCountChanged();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function enableBrowserNotifications() {
    if (typeof Notification === "undefined") return;
    setBrowserPermission(await Notification.requestPermission());
  }

  return (
    <section className="mt-3">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">입출금 알림</h1>
        <button type="button" onClick={markRead} disabled={busy || items.length === 0} className="text-sm text-coral disabled:text-slate">모두 읽음</button>
      </div>
      <p className="mt-2 text-sm text-slate">계좌에 돈이 들어오거나 나간 내역을 확인하세요.</p>
      {browserPermission === "default" && <button type="button" onClick={enableBrowserNotifications} className="mt-3 rounded-xl border border-line px-3 py-2 text-sm">브라우저 팝업 알림 켜기</button>}
      {browserPermission === "granted" && <p className="mt-3 text-xs text-slate">접속 중 새 거래가 생기면 화면과 브라우저 팝업으로 알려 드립니다.</p>}
      {browserPermission === "denied" && <p className="mt-3 text-xs text-slate">브라우저 팝업 알림이 차단되어 있습니다. 브라우저 사이트 설정에서 허용할 수 있습니다.</p>}
      {error && <p role="alert" className="mt-4 text-sm text-seal">{error}</p>}
      {loading ? <p role="status" className="mt-8 text-center text-slate">알림을 불러오는 중입니다.</p> : items.length === 0 ?
        <p className="mt-10 text-center text-slate">아직 입출금 알림이 없습니다.</p> :
        <ul className="mt-6 divide-y divide-line border-t border-line">
          {items.map((item) => {
            const detail = notificationText(item);
            return (
              <li key={item.notification_id} className={`py-4 ${item.read_at === null ? "font-semibold" : ""}`}>
                <Link href={`/accounts/checking/${item.account_id}`} className="block rounded-lg hover:bg-coral-soft">
                  <span className="text-xs text-slate">{HISTORY_TYPE[item.type]?.[0] ?? item.type}</span>
                  {item.read_at === null && <span className="ml-2 rounded-full bg-coral-soft px-2 py-0.5 text-xs text-coral">새 알림</span>}
                  <p className="mt-1 tabular-nums">{detail.title}</p>
                  <p className="mt-1 text-sm font-normal text-slate tabular-nums">{detail.body}</p>
                  <time dateTime={item.date} className="mt-2 block text-xs font-normal text-slate">{new Date(item.date).toLocaleString("ko-KR")}</time>
                </Link>
              </li>
            );
          })}
        </ul>}
      {hasMore && <div className="mt-5"><Button type="button" busy={busy} onClick={loadMore}>더 보기</Button></div>}
    </section>
  );
}

export default function NotificationsPage() {
  return <Shell><Notifications /></Shell>;
}
