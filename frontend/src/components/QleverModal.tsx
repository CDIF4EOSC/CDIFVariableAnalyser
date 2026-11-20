import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { QleverDocument, QleverFormat, QleverSaveResult } from "../types";
import { IconDownload, IconX } from "./Icons";

interface Props {
  /** The result of a save just made, shown above the list. */
  saved: QleverSaveResult | null;
  onClose: () => void;
  onToast: (text: string, kind?: "info" | "err") => void;
  /** Open a saved document in the editor (replaces the open file). */
  onOpen: (doc: QleverDocument) => Promise<void>;
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "");

function saveFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function SaveSummary({ saved }: { saved: QleverSaveResult }) {
  const { shacl } = saved;
  return (
    <section className="col" style={{ gap: 8 }}>
      <h3 style={{ fontSize: 14, margin: 0 }}>Saved</h3>
      <table>
        <tbody>
          <tr><th>Graph</th><td className="mono">{saved.graph}</td></tr>
          <tr><th>Dataset IRI</th><td className="mono">{saved.dataset_iri}</td></tr>
          <tr><th>Triples</th><td>{saved.triples.toLocaleString()}</td></tr>
          <tr>
            <th>CDIF SHACL</th>
            <td>
              {!shacl.checked
                ? `not checked: ${shacl.reason ?? "unavailable"}`
                : shacl.violation_count === 0
                  ? `no violations${shacl.warnings ? ` · ${shacl.warnings} warning${shacl.warnings === 1 ? "" : "s"}` : ""} (${shacl.shapes})`
                  : `${shacl.violation_count} violation${shacl.violation_count === 1 ? "" : "s"} · ${shacl.warnings} warnings (${shacl.shapes}). Saved anyway: SHACL only warns while testing.`}
            </td>
          </tr>
        </tbody>
      </table>
      {shacl.missing_required.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: "#b91c1c" }}>
          {shacl.missing_required.map((m) => <li key={m}>{m}</li>)}
        </ul>
      )}
      {shacl.violations.length > 0 && <pre style={{ maxHeight: 180 }}>{shacl.violations.join("\n")}</pre>}
    </section>
  );
}

/** Documents saved to QLever: list them from the catalog graph, view one as stored, download it. */
export function QleverModal({ saved, onClose, onToast, onOpen }: Props) {
  const [docs, setDocs] = useState<QleverDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<{ doc: QleverDocument; format: QleverFormat; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api.qleverDocuments().then(setDocs).catch((e) => setError(e instanceof ApiError ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);

  const open = async (doc: QleverDocument, format: QleverFormat, download: boolean) => {
    setBusy(`${doc.uuid}|${format}|${download}`);
    try {
      const r = await api.qleverDocument(doc.uuid, format);
      if (download) {
        saveFile(r.blob, r.filename);
        onToast(`Downloaded ${r.filename}`);
      } else {
        setViewing({ doc, format, text: format === "jsonld" ? JSON.stringify(JSON.parse(r.text), null, 2) : r.text });
      }
    } catch (e) {
      onToast(e instanceof ApiError ? e.message : String(e), "err");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="scrim center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label="QLever store">
        <div className="drawer-head">
          <div className="col" style={{ gap: 4, flexGrow: 1 }}>
            <span className="eyebrow">QLever store · CDIF</span>
            <h2>{viewing ? viewing.doc.title || viewing.doc.uuid : "Saved documents"}</h2>
            <p>
              {viewing
                ? <>Read back from graph <span className="mono">{viewing.doc.graph}</span>, as stored: flat JSON-LD, not the nesting of the original download.</>
                : "Each save replaces its document's graph. Open brings a document back into the editor as metadata only (no data rows, no statistics); View shows what the store holds."}
            </p>
          </div>
          <button type="button" className="btn" style={{ width: 32, padding: 0, justifyContent: "center" }} aria-label="Close" onClick={onClose}><IconX /></button>
        </div>
        <div className="drawer-body">
          {viewing ? (
            <>
              <div className="row" style={{ gap: 8 }}>
                <button type="button" className="btn" onClick={() => setViewing(null)}>← All documents</button>
                <span className="grow" />
                <button type="button" className="btn primary" disabled={busy !== null} onClick={() => { setBusy("open"); void onOpen(viewing.doc).finally(() => setBusy(null)); }}>
                  {busy === "open" ? "Opening…" : "Open in editor"}
                </button>
                {(["jsonld", "turtle"] as const).map((f) => (
                  <button key={f} type="button" className={`btn ${viewing.format === f ? "primary" : ""}`} disabled={busy !== null} onClick={() => void open(viewing.doc, f, false)}>
                    {f === "jsonld" ? "JSON-LD" : "Turtle"}
                  </button>
                ))}
                <button type="button" className="btn" disabled={busy !== null} onClick={() => void open(viewing.doc, viewing.format, true)}><IconDownload /> Download</button>
              </div>
              <pre style={{ maxHeight: "60vh" }}>{viewing.text}</pre>
            </>
          ) : (
            <>
              {saved && <SaveSummary saved={saved} />}
              {error && <p className="error" style={{ margin: 0, color: "#b91c1c" }}>{error}</p>}
              {!docs && !error && <p className="muted" style={{ margin: 0 }}>Loading…</p>}
              {docs && docs.length === 0 && <p className="muted" style={{ margin: 0 }}>Nothing saved yet.</p>}
              {docs && docs.length > 0 && (
                <table>
                  <thead><tr><th>Title</th><th>Source file</th><th>Saved</th><th>Triples</th><th /></tr></thead>
                  <tbody>
                    {docs.map((d) => (
                      <tr key={d.uuid} style={saved?.uuid === d.uuid ? { background: "var(--accent-soft)" } : undefined}>
                        <td>
                          <div>{d.title || <span className="muted">untitled</span>}</div>
                          <div className="mono muted" style={{ fontSize: 11 }} title="Dataset IRI">{d.dataset_iri}</div>
                        </td>
                        <td>{d.source_file}</td>
                        <td style={{ whiteSpace: "nowrap" }}>{when(d.saved_at)}{d.saved_by ? <div className="muted" style={{ fontSize: 11 }}>{d.saved_by}</div> : null}</td>
                        <td>{d.triples?.toLocaleString()}</td>
                        <td style={{ whiteSpace: "nowrap" }}>
                          <button type="button" className="btn primary" disabled={busy !== null} title="Open in the editor: the metadata comes back, the data rows do not" onClick={() => { setBusy(`${d.uuid}|open`); void onOpen(d).finally(() => setBusy(null)); }}>
                            {busy === `${d.uuid}|open` ? "Opening…" : "Open"}
                          </button>{" "}
                          <button type="button" className="btn" disabled={busy !== null} onClick={() => void open(d, "jsonld", false)}>View</button>{" "}
                          <button type="button" className="btn" disabled={busy !== null} title="Download CDIF JSON-LD" onClick={() => void open(d, "jsonld", true)}><IconDownload /> JSON-LD</button>{" "}
                          <button type="button" className="btn" disabled={busy !== null} title="Download Turtle" onClick={() => void open(d, "turtle", true)}><IconDownload /> Turtle</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
