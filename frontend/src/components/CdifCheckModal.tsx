import type { ShaclResult } from "../types";
import { IconX } from "./Icons";

interface Props {
  result: ShaclResult | null; // null while the check runs
  saving: boolean;
  onSave: () => void;
  onClose: () => void;
}

/** The CDIF of the document checked against the CDIF SHACL shapes, before a save. */
export function CdifCheckModal({ result, saving, onSave, onClose }: Props) {
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const missing = result?.missing_required.length ?? 0;
  const verdict = !result
    ? "Checking…"
    : [
        missing ? plural(missing, "required field") + " missing" : null,
        !result.checked
          ? `SHACL not checked: ${result.reason ?? "unavailable"}`
          : result.violation_count === 0
            ? "no SHACL violations"
            : plural(result.violation_count, "SHACL violation"),
        result.checked ? plural(result.warnings, "warning") : null,
      ].filter(Boolean).join(" · ").replace(/^./, (c) => c.toUpperCase());
  const ok = result?.checked && result.violation_count === 0 && missing === 0;
  return (
    <div className="scrim center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label="CDIF check">
        <div className="drawer-head">
          <div className="col" style={{ gap: 4, flexGrow: 1 }}>
            <span className="eyebrow">CDIF SHACL{result?.shapes ? ` · ${result.shapes}` : ""}</span>
            <h2 style={{ color: !result ? undefined : ok ? "#15803d" : "#b91c1c" }}>{verdict}</h2>
            <p>
              The CDIF that a save would store, checked against the CDIF shapes. Violations break the profile; warnings
              name recommended fields that are missing, most of them on the Dataset tab. While testing, a save goes
              ahead either way.
            </p>
          </div>
          <button type="button" className="btn" style={{ width: 32, padding: 0, justifyContent: "center" }} aria-label="Close" onClick={onClose}><IconX /></button>
        </div>
        <div className="drawer-body">
          {result && missing > 0 && (
            <section className="col" style={{ gap: 6 }}>
              <h3 style={{ fontSize: 14, margin: 0, color: "#b91c1c" }}>Required fields missing on the Dataset tab</h3>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.6 }}>
                {result.missing_required.map((m) => <li key={m}>{m}</li>)}
              </ul>
            </section>
          )}
          {result && result.violations.length > 0 && (
            <section className="col" style={{ gap: 6 }}>
              <h3 style={{ fontSize: 14, margin: 0 }}>Violations</h3>
              <pre style={{ maxHeight: 220 }}>{result.violations.join("\n")}</pre>
            </section>
          )}
          {result && result.warning_messages.length > 0 && (
            <section className="col" style={{ gap: 6 }}>
              <h3 style={{ fontSize: 14, margin: 0 }}>Warnings</h3>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.6 }}>
                {result.warning_messages.map((m) => <li key={m}>{m}</li>)}
              </ul>
            </section>
          )}
          <div className="row" style={{ gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="btn" onClick={onClose}>Close</button>
            <button type="button" className="btn primary" disabled={!result || saving} onClick={onSave}>
              {saving ? "Saving…" : "Save to QLever"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
