import { useEffect, useRef } from "react";

interface Props {
  title: string;
  message: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Small centred confirmation modal in the app's own look (replaces window.confirm). */
export function ConfirmDialog(p: Props) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") p.onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [p]);
  return (
    <div className="scrim center" onMouseDown={(e) => e.target === e.currentTarget && p.onCancel()}>
      <div className="modal confirm" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">{p.title}</h2>
        <p>{p.message}</p>
        <div className="confirm-actions">
          <button type="button" className="btn lg" onClick={p.onCancel} disabled={p.busy}>{p.cancelLabel ?? "Cancel"}</button>
          <button ref={confirmRef} type="button" className={`btn lg primary ${p.danger ? "danger-fill" : ""}`} onClick={p.onConfirm} disabled={p.busy}>
            {p.busy ? "Resetting…" : p.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
