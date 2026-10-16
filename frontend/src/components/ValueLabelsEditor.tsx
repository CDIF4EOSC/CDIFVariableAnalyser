import { useEffect, useRef, useState } from "react";
import { IconPlus, IconX } from "./Icons";

interface Props {
  labels: Record<string, string>;
  numeric: boolean;
  onSave: (labels: Record<string, string>) => void | Promise<void>;
  onClose: () => void;
}

interface Row {
  code: string;
  label: string;
}

export function ValueLabelsEditor({ labels, numeric, onSave, onClose }: Props) {
  const [rows, setRows] = useState<Row[]>(() => [...Object.entries(labels).map(([code, label]) => ({ code, label })), { code: "", label: "" }]);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose]);

  const update = (i: number, patch: Partial<Row>) => {
    setRows((rs) => {
      const next = rs.map((r, j) => (j === i ? { ...r, ...patch } : r));
      if (i === next.length - 1 && (patch.code || patch.label)) next.push({ code: "", label: "" });
      return next;
    });
  };

  const save = () => {
    const out: Record<string, string> = {};
    for (const r of rows) if (r.code.trim()) out[r.code.trim()] = r.label;
    void onSave(out);
    onClose();
  };

  const dupes = new Set(rows.map((r) => r.code.trim()).filter((c, i, a) => c && a.indexOf(c) !== i));

  return (
    <div ref={box} className="popover" style={{ top: 36, left: 0, width: 420 }} role="dialog" aria-label="Value labels">
      <div className="row">
        <h3>Value labels</h3>
        <span className="muted" style={{ fontSize: 12 }}>{numeric ? "numeric codes" : "string codes"}</span>
        <span className="grow" />
        <button type="button" className="iconbtn" aria-label="Close" onClick={onClose}><IconX /></button>
      </div>
      <div className="vl-grid" style={{ maxHeight: 300, overflow: "auto", display: "grid" }}>
        <span className="h">Code</span><span className="h">Label</span><span className="h" />
        {rows.map((r, i) => (
          <div key={i} style={{ display: "contents" }}>
            <input
              className="mono"
              value={r.code}
              placeholder="code"
              aria-label={`Code ${i + 1}`}
              style={dupes.has(r.code.trim()) ? { background: "#fef2f2" } : undefined}
              onChange={(e) => update(i, { code: e.target.value })}
            />
            <input value={r.label} placeholder="label" aria-label={`Label ${i + 1}`} onChange={(e) => update(i, { label: e.target.value })} />
            {i < rows.length - 1 ? (
              <button type="button" className="x" aria-label={`Remove ${r.code}`} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}><IconX size={12} /></button>
            ) : (
              <span className="x" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}><IconPlus size={12} /></span>
            )}
          </div>
        ))}
      </div>
      <div className="row">
        <span className="muted" style={{ fontSize: 11 }}>One Code, Category and Notation per code. Codes inside a missing range go to the sentinel code list.</span>
        <span className="grow" />
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={dupes.size > 0} onClick={save}>Save</button>
      </div>
    </div>
  );
}
