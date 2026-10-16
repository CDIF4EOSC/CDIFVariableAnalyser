import { useEffect, useRef, useState } from "react";

interface Props {
  value: string;
  onCommit: (next: string) => void | Promise<void>;
  mono?: boolean;
  placeholder?: string;
  title?: string;
  /** Rendered when not editing; defaults to the value. */
  render?: (value: string) => React.ReactNode;
  /** Suggestions shown while editing (e.g. value labels). */
  suggestions?: { code: string; label: string; sentinel?: boolean }[];
  width?: number;
}

/** Double-click (or Enter when focused) to edit; Enter commits, Esc cancels. */
export function EditableCell({ value, onCommit, mono, placeholder, title, render, suggestions, width }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const draftRef = useRef(value);
  draftRef.current = draft;
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      setDraft(value);
      requestAnimationFrame(() => {
        ref.current?.focus();
        ref.current?.select();
      });
    }
  }, [editing, value]);

  const commit = async (next: string) => {
    setEditing(false);
    if (next !== value) await onCommit(next);
  };

  if (!editing) {
    return (
      <div
        className={`cell ${value === "" ? "empty" : ""} ${mono ? "mono" : ""}`}
        title={title ?? "Double-click to edit"}
        tabIndex={0}
        role="button"
        onDoubleClick={() => setEditing(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === "F2") setEditing(true);
        }}
        style={width ? { width } : undefined}
      >
        {render ? render(value) : value === "" ? placeholder ?? "empty" : value}
      </div>
    );
  }

  const shown = (suggestions ?? []).filter((s) => draft === "" || s.code.startsWith(draft) || s.label.toLowerCase().includes(draft.toLowerCase())).slice(0, 8);

  return (
    <div className="cell-wrap" style={{ position: "relative" }}>
      <input
        ref={ref}
        className={`cell-input ${mono ? "mono" : ""}`}
        style={width ? { width } : undefined}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          // A blur caused by the window losing focus (alt-tab, dev tools) must not commit or cancel.
          setTimeout(() => {
            if (!document.hasFocus()) return;
            if (ref.current && document.activeElement === ref.current) return;
            void commit(draftRef.current);
          }, 0);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") void commit(draft);
          if (e.key === "Escape") setEditing(false);
        }}
      />
      {value !== draft && <span className="was">was {value === "" ? "empty" : value}</span>}
      {shown.length > 0 && (
        <div className="popover" style={{ top: 34, left: 0, minWidth: 240, padding: 6, gap: 0 }}>
          {shown.map((s) => (
            <button
              key={s.code}
              type="button"
              className="chip-btn"
              style={{ border: "none", justifyContent: "flex-start", height: 30, borderRadius: 6 }}
              onMouseDown={(e) => {
                e.preventDefault();
                void commit(s.code);
              }}
            >
              <span className="mono" style={{ width: 40, color: s.sentinel ? "#b45309" : "#6b7280" }}>{s.code}</span>
              <span style={{ color: "#374151" }}>{s.label}</span>
              {s.sentinel && <span className="pill" style={{ marginLeft: "auto", background: "#fef3c7", color: "#92400e" }}>sentinel</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
