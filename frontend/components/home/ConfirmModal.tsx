"use client";

import { useEffect, useRef } from "react";

// 브라우저 기본 <dialog>: 포커스 가두기, Esc 닫기, 배경 클릭 막기를 브라우저가 해 준다.
export function ConfirmModal({
  open,
  title,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby="confirm-title"
      onCancel={(e) => {
        e.preventDefault(); // Esc: 상태는 부모가 닫는다
        onCancel();
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-sm rounded-2xl bg-paper p-6 text-ink backdrop:bg-ink/40"
    >
      <h2 id="confirm-title" className="text-lg font-bold">
        {title}
      </h2>
      <div className="mt-6 flex gap-2">
        <button autoFocus type="button" onClick={onCancel} className="min-h-11 flex-1 rounded-xl border border-line font-medium text-slate">
          아니요
        </button>
        <button type="button" onClick={onConfirm} className="min-h-11 flex-1 rounded-xl bg-coral font-medium text-paper">
          예
        </button>
      </div>
    </dialog>
  );
}
