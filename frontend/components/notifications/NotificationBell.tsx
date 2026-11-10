"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AccountNotification, api } from "@/lib/api";
import { notificationText } from "@/lib/notifications";

const UPDATED = "account-notifications-updated";
export const NOTIFICATION_ARRIVED = "account-notification-arrived";
const SHOWN_KEY = "avengers-bank-last-notification-popup";
const TOAST_KEY = "avengers-bank-last-notification-toast";
let lastToastInTab = 0;
let lastBrowserPopup = 0;

async function showBrowserPopup(latestId: number, title: string, body: string, open: () => void) {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  const showOnce = () => {
    try {
      const stored = Number(localStorage.getItem(SHOWN_KEY) ?? "0");
      if (Number.isFinite(stored)) lastBrowserPopup = Math.max(lastBrowserPopup, stored);
    } catch {}
    if (latestId <= lastBrowserPopup) return;
    lastBrowserPopup = latestId;
    try { localStorage.setItem(SHOWN_KEY, String(latestId)); } catch {}
    const popup = new Notification(title, { body, tag: "account-movement" });
    popup.onclick = () => {
      window.focus();
      open();
      popup.close();
    };
  };
  if (navigator.locks) await navigator.locks.request("account-notification-popup", showOnce);
  else showOnce();
}

export function notifyCountChanged() {
  window.dispatchEvent(new Event(UPDATED));
}

export function NotificationBell() {
  const router = useRouter();
  const [count, setCount] = useState(0);
  const [announcement, setAnnouncement] = useState<{ title: string; body: string } | null>(null);
  useEffect(() => {
    let mounted = true;
    let requestSerial = 0;
    let messageTimer: ReturnType<typeof setTimeout> | undefined;
    const load = () => {
      const serial = ++requestSerial;
      api<{ unread_count: number; latest_notification_id: number | null }>("/notifications/unread-count")
        .then(async ({ unread_count, latest_notification_id }) => {
          if (!mounted || serial !== requestSerial) return;
          setCount(unread_count);
          try {
            const stored = Number(sessionStorage.getItem(TOAST_KEY) ?? "0");
            if (Number.isFinite(stored)) lastToastInTab = Math.max(lastToastInTab, stored);
          } catch {}
          if (latest_notification_id !== null && latest_notification_id > lastToastInTab) {
            lastToastInTab = latest_notification_id;
            try { sessionStorage.setItem(TOAST_KEY, String(latest_notification_id)); } catch {}
            const rows = await api<AccountNotification[]>("/notifications?limit=1").catch(() => []);
            if (!mounted) return;
            const newest = rows[0];
            const detail = newest ? notificationText(newest) : {
              title: "새 입출금 알림", body: "알림함에서 거래 내역을 확인해 주세요.",
            };
            setAnnouncement(detail);
            window.dispatchEvent(new Event(NOTIFICATION_ARRIVED));
            void showBrowserPopup(
              latest_notification_id, detail.title, detail.body, () => router.push("/notifications"),
            ).catch(() => {});
            clearTimeout(messageTimer);
            messageTimer = setTimeout(() => setAnnouncement(null), 5000);
          }
        })
        .catch(() => {});
    };
    const onVisible = () => {
      if (document.visibilityState === "visible") load();
    };
    load();
    const interval = setInterval(load, 5_000);
    window.addEventListener("focus", load);
    window.addEventListener(UPDATED, load);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      mounted = false;
      clearInterval(interval);
      clearTimeout(messageTimer);
      window.removeEventListener("focus", load);
      window.removeEventListener(UPDATED, load);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [router]);

  return (
    <div className="relative">
      <Link href="/notifications" aria-label={`알림, 읽지 않은 알림 ${count}건`} className="relative flex size-11 items-center justify-center rounded-full hover:bg-coral-soft">
        <svg viewBox="0 0 24 24" aria-hidden className="size-6 fill-none stroke-current stroke-[1.7]">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 8-3 9h18c0-1-3-2-3-9ZM10 21h4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {count > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-5 rounded-full bg-coral px-1 text-center text-[10px] leading-5 text-paper">{count > 99 ? "99+" : count}</span>}
      </Link>
      {announcement && <div role="status" className="absolute right-0 top-12 z-20 w-72 rounded-xl border border-line bg-paper p-3 text-sm shadow-lg"><p className="font-semibold">{announcement.title}</p><p className="mt-1 text-slate">{announcement.body}</p></div>}
    </div>
  );
}
