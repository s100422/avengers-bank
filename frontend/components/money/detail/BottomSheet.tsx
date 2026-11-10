"use client";

import { useEffect, useId, useRef } from "react";

// 바닥에서 올라오는 패널. 브라우저 기본 <dialog>가 포커스 가두기·Esc를 해 주고, 배경(dialog 자신) 클릭으로 닫는다.
export function BottomSheet({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault(); // Esc: 상태는 부모가 닫는다
        onClose();
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
      className="mx-auto mt-auto mb-0 max-h-[85dvh] w-full max-w-xl rounded-t-3xl bg-paper p-0 text-ink backdrop:bg-ink/40 md:mb-auto md:rounded-3xl"
    >
      {open && (
        <div className="p-6 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
          <div className="flex items-start justify-between gap-3">
            <h2 id={titleId} className="text-lg font-bold">
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="닫기"
              className="-mt-2 -mr-2 flex size-11 shrink-0 items-center justify-center rounded-full text-xl text-slate hover:bg-coral-soft hover:text-ink"
            >
              ×
            </button>
          </div>
          <div className="mt-4">{children}</div>
        </div>
      )}
    </dialog>
  );
}
