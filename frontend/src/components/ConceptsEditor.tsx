import { useEffect, useRef, useState } from "react";
import type { Concept } from "../types";
import { IconPlus, IconX } from "./Icons";

interface Props {
  concepts: Concept[];
  onSave: (concepts: Concept[]) => void | Promise<void>;
  onClose: () => void;
}

const URI_RE = /^https?:\/\/\S+$/;

export function ConceptsEditor({ concepts, onSave, onClose }: Props) {
  const [rows, setRows] = useState<Concept[]>(() => [...concepts.map((c) => ({ ...c })), { uri: "", pref_label: "" }]);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const update = (i: number, patch: Partial<Concept>) => {
    setRows((rs) => {
      const next = rs.map((r, j) => (j === i ? { ...r, ...patch } : r));
      if (i === next.length - 1 && (patch.uri || patch.pref_label)) next.push({ uri: "", pref_label: "" });
      return next;
    });
  };

  const filled = rows.filter((r) => r.uri.trim());
  const invalid = new Set(filled.map((r) => r.uri.trim()).filter((u) => !URI_RE.test(u)));
  const dupes = new Set(filled.map((r) => r.uri.trim()).filter((u, i, a) => a.indexOf(u) !== i));

  const save = () => {
    void onSave(filled.map((r) => ({ uri: r.uri.trim(), pref_label: r.pref_label.trim() })));
    onClose();
  };

  return (
    <div ref={box} className="popover editor" style={{ top: 34, left: 0, width: 520 }} role="dialog" aria-label="Concepts">
      <div className="picker-head">
        <h3>Concepts</h3>
        <span className="sub">ELSST or other concept URIs</span>
        <span className="grow" />
        <button type="button" className="iconbtn" aria-label="Close" onClick={onClose}><IconX size={12} /></button>
      </div>
      <div className="editor-body vl-grid cn-grid" style={{ maxHeight: 300, overflow: "auto", display: "grid" }}>
        <span className="h">URI</span><span className="h">Label</span><span className="h" />
        {rows.map((r, i) => {
          const u = r.uri.trim();
          const bad = u && (invalid.has(u) || dupes.has(u));
          return (
            <div key={i} style={{ display: "contents" }}>
              <input
                className="mono"
                value={r.uri}
                placeholder="https://elsst.cessda.eu/id/6/…"
                aria-label={`Concept URI ${i + 1}`}
                style={bad ? { background: "#fef2f2" } : undefined}
                onChange={(e) => update(i, { uri: e.target.value })}
              />
              <input value={r.pref_label} placeholder="preferred label" aria-label={`Concept label ${i + 1}`} onChange={(e) => update(i, { pref_label: e.target.value })} />
              {i < rows.length - 1 ? (
                <button type="button" className="x" aria-label={`Remove ${r.uri}`} onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}><IconX size={12} /></button>
              ) : (
                <span className="x" style={{ display: "flex", alignItems: "center", justifyContent: "center" }}><IconPlus size={12} /></span>
              )}
            </div>
          );
        })}
      </div>
      <div className="picker-foot editor-foot">
        <span>One DDI-CDI Concept per entry, linked with uses_Concept. ELSST URIs get an int.cessda.elsst identifier.</span>
        <span className="grow" />
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={invalid.size > 0 || dupes.size > 0} onClick={save}>Save</button>
      </div>
    </div>
  );
}
