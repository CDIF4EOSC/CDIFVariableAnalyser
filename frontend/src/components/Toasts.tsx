export interface Toast {
  id: number;
  text: string;
  kind: "info" | "err";
}

export function Toasts({ items }: { items: Toast[] }) {
  if (!items.length) return null;
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind === "err" ? "err" : ""}`}>
          {t.text}
        </div>
      ))}
    </div>
  );
}
