import { useRef, useState } from "react";
import { IconCode, IconLogo, IconSpinner, IconUpload } from "./Icons";
import cdif4eoscLogo from "../assets/cdif4eosc-logo.png";

interface Props {
  onFile: (f: File) => Promise<void>;
  /** Images (JPEG, PNG, WebP, TIFF) open an image collection: CDIF per image. */
  onImages: (files: File[]) => Promise<void>;
  busy: boolean;
  error: string | null;
  health: { version: string; qsv: string | null } | null;
  onApiDocs: () => void;
  /** Set when the server has a QLever store: opens the saved documents. */
  onQlever?: () => void;
  supported: string[];
  apiKeyRequired: boolean;
  apiKey: string;
  onApiKey: (key: string) => void;
}

// Package path of each class in the DDI-CDI 1.1beta field-level documentation.
const CLASS_PATHS: Record<string, string> = {
  StructuredDataSet: "FormatDescription", TabularTextDataSet: "FormatDescription", Segment: "FormatDescription",
  SegmentPosition: "FormatDescription", LocatorMapping: "FormatDescription", TextMapping: "FormatDescription",
  PhysicalMappingPosition: "FormatDescription", DataPoint: "DataDescription", DataPointPosition: "FormatDescription",
  InstanceValue: "DataDescription", LogicalRecord: "FormatDescription",
  WideDataSet: "DataDescription/Wide", WideDataStructure: "DataDescription/Wide", InstanceVariable: "Conceptual",
  MeasureComponent: "DataDescription/Components", IdentifierComponent: "DataDescription/Components",
  AttributeComponent: "DataDescription/Components", PrimaryKey: "DataDescription/Components",
  PrimaryKeyComponent: "DataDescription/Components", ComponentPosition: "DataDescription/Components",
  SubstantiveValueDomain: "Representations", SentinelValueDomain: "Representations",
  ValueAndConceptDescription: "Representations", Concept: "Conceptual",
  CodeList: "Representations", Code: "Representations", CodePosition: "Representations", Category: "Conceptual",
  Notation: "DataDescription",
  StatisticsCollection: "FormatDescription", Statistics: "DataDescription", CategoryStatistics: "DataDescription",
};
const CLASSES = [
  "StructuredDataSet", "TabularTextDataSet", "Segment", "SegmentPosition", "LocatorMapping", "TextMapping",
  "PhysicalMappingPosition", "DataPoint", "DataPointPosition", "InstanceValue", "LogicalRecord",
  "WideDataSet", "WideDataStructure", "InstanceVariable",
  "MeasureComponent", "IdentifierComponent", "AttributeComponent", "PrimaryKey", "PrimaryKeyComponent", "ComponentPosition",
  "SubstantiveValueDomain", "SentinelValueDomain", "ValueAndConceptDescription", "Concept",
  "CodeList", "Code", "CodePosition", "Category", "Notation",
];
// Only with the "include statistics" output option.
const STATISTICS = ["StatisticsCollection", "Statistics", "CategoryStatistics"];
const DOCS = "https://ddi-cdi.github.io/m2t-ng/DDI-CDI_1-1beta/field-level-documentation/DDICDILibrary/Classes";
const classDoc = (c: string) => `${DOCS}/${CLASS_PATHS[c]}/${c}.html`;

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

const IMAGE_RE = /\.(jpe?g|png|webp|tiff?)$/i;
// The formats the page names; the file picker still accepts everything the server reads
// (.xpt5, .xpt8, .tsv, .txt ... are variants of these).
const MAIN_FORMATS: [string, string][] = [[".sav", "SPSS"], [".dta", "Stata"], [".sas7bdat", "SAS"], [".csv", "CSV"], [".parquet", "Parquet"]];
const ALSO_FORMATS = [".zsav", ".por", ".xpt"];

export function UploadScreen({ onFile, onImages, busy, error, health, onApiDocs, onQlever, supported, apiKeyRequired, apiKey, onApiKey }: Props) {
  const [over, setOver] = useState(false);
  const [pending, setPending] = useState<File | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const start = (f: File) => {
    if (busy) return;
    setPending(f);
    void onFile(f).finally(() => setPending(null));
  };
  const startImages = (files: File[]) => {
    if (busy || !files.length) return;
    setPending(files[0]);
    void onImages(files).finally(() => setPending(null));
  };
  const exts = supported.length ? supported : [".sav", ".zsav", ".por", ".dta", ".sas7bdat", ".xpt", ".csv", ".parquet"];

  return (
    <div className="app">
      <header className="header">
        <a className="brand" href="#">
          <span className="brand-mark"><IconLogo /></span>
          <span className="brand-name">DDI-CDI Studio</span>
          <span className="pill" style={{ background: "#1e293b", color: "#94a3b8", letterSpacing: "0.08em", fontWeight: 600 }}>PROTOTYPE</span>
        </a>
        <span className="grow" />
        {onQlever && <button type="button" className="hbtn" onClick={onQlever}>Import from QLever</button>}
        <button type="button" className="hbtn" onClick={onApiDocs}><IconCode /> REST API docs</button>
      </header>
      <main className="upload">
        <div className="upload-inner">
          <div className="upload-main">
            <div className="col" style={{ gap: 10 }}>
              <span className="eyebrow">Convert · edit · export</span>
              <h1>Turn a statistical file into DDI-CDI, then shape it by hand.</h1>
              <p className="lead">Drop an SPSS, Stata, SAS or CSV file. Its metadata and data open in an editable workspace, and the JSON-LD on the right rewrites itself with every change you make. Images work too: each one gets its own CDIF record.</p>
            </div>
            <div
              className={`dropzone ${over ? "over" : ""} ${busy ? "busy" : ""}`}
              aria-busy={busy}
              onDragOver={(e) => { e.preventDefault(); if (!busy) setOver(true); }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setOver(false);
                const all = [...(e.dataTransfer.files ?? [])];
                if (all.length && all.every((f) => IMAGE_RE.test(f.name))) startImages(all);
                else if (all[0]) start(all[0]);
              }}
            >
              <div className={`drop-icon ${busy ? "busy" : ""}`}>{busy ? <IconSpinner /> : <IconUpload />}</div>
              <div className="col" style={{ alignItems: "center", gap: 4 }} role="status" aria-live="polite">
                <span className="drop-title">{busy ? "Importing…" : "Drop your data file or images here"}</span>
                {busy ? (
                  <span className="muted" style={{ fontSize: 13, textAlign: "center" }}>
                    {pending ? <><span className="mono">{pending.name}</span> · {fmtSize(pending.size)}<br /></> : null}
                    Reading the file with qsv readstat. Large files can take a while.
                  </span>
                ) : (
                  <span className="muted" style={{ fontSize: 14 }}>or</span>
                )}
              </div>
              {!busy && (
                <label className="file-btn">
                  <input ref={input} type="file" className="sr-only" accept={exts.join(",")} onChange={(e) => { const f = e.target.files?.[0]; if (f) start(f); e.target.value = ""; }} />
                  Choose a file
                </label>
              )}
              {!busy && (
                <div className="formats">
                  <div className="row" style={{ gap: 6, justifyContent: "center", flexWrap: "wrap" }}>
                    {MAIN_FORMATS.filter(([x]) => exts.includes(x)).map(([x, what]) => (
                      <span key={x} className="ext" title={what}>{x}</span>
                    ))}
                  </div>
                  <span className="muted also">also {ALSO_FORMATS.filter((x) => exts.includes(x)).join(" · ")}</span>
                </div>
              )}
            </div>
            <div className="img-entry">
              <div className="col" style={{ gap: 2 }}>
                <strong>Images → CDIF <span className="pill new">new</span></strong>
                <span className="muted">Photos, scans or charts: one CDIF record per image, with a title, description and keywords suggested by AI for you to review.</span>
              </div>
              <label className={`file-btn ghost ${busy ? "off" : ""}`}>
                <input
                  type="file"
                  className="sr-only"
                  multiple
                  disabled={busy}
                  accept=".jpg,.jpeg,.png,.webp,.tif,.tiff,image/jpeg,image/png,image/webp,image/tiff"
                  onChange={(e) => { const f = [...(e.target.files ?? [])]; startImages(f); e.target.value = ""; }}
                />
                Choose images
              </label>
            </div>
            {(apiKeyRequired || /X-API-Key/i.test(error ?? "")) && (
              <label className="field" style={{ maxWidth: 420 }}>
                <span>API key</span>
                <input type="password" className="mono" value={apiKey} onChange={(e) => onApiKey(e.target.value)} placeholder="the server's DDI_API_KEY" autoComplete="off" />
                <small>This server requires a key for uploads (its DDI_API_KEY). It is kept in this browser only.</small>
              </label>
            )}
            {error && <div className="err-box">{error}</div>}
          </div>
          <aside className="upload-side">
            <div className="dark-card">
              <h3>What the Studio does</h3>
              <ol>
                <li><span className="n">1</span><span><strong>Edit anything.</strong> Labels, types, value labels, missing codes, roles, cells and rows. The preview regenerates live and marks what changed.</span></li>
                <li><span className="n">2</span><span><strong>AI enrichment.</strong> Suggestions for unit of measure, ELSST concepts, variable role, function and level of measurement, reviewed by you before they are applied.</span></li>
                <li><span className="n">3</span><span><strong>Statistics.</strong> Summary statistics and frequency distributions per variable, weighted or not, and optionally written into the output.</span></li>
                <li><span className="n">4</span><span><strong>Canonical DDI-CDI 1.1beta.</strong> Code lists, value domains, sentinel values, WideDataStructure. Download as <span className="mono" style={{ color: "#a5b4fc" }}>.jsonld</span>.</span></li>
                <li><span className="n">5</span><span><strong>Images → CDIF.</strong> Photos, scans and charts get a title, description and keywords suggested by AI, one CDIF record per image.</span></li>
              </ol>
            </div>
            <div className="light-card">
              <div className="row" style={{ alignItems: "baseline" }}>
                <h3>DDI-CDI subset</h3>
                <span className="grow" />
                <span className="muted" style={{ fontSize: 12 }}>{CLASSES.length + STATISTICS.length} classes from DDI-CDI 1.1beta</span>
              </div>
              <div className="classes">
                {[...CLASSES, ...STATISTICS].map((c) => <a key={c} href={classDoc(c)} target="_blank" rel="noreferrer">{c}</a>)}
              </div>
            </div>
          </aside>
        </div>
      </main>
      <footer className="upload-foot">
        <a className="foot-project" href="https://cdif4eosc.eu/" target="_blank" rel="noreferrer" title="CDIF4EOSC project">
          <img src={cdif4eoscLogo} alt="CDIF4EOSC" />
        </a>
        <span>Developed by Sikt in the <a href="https://cdif4eosc.eu/" target="_blank" rel="noreferrer">CDIF4EOSC</a> project.</span>
        <span>Contact: <a href="mailto:benjamin.beuster@sikt.no" title="benjamin.beuster@sikt.no">Benjamin Beuster</a></span>
        <span className="grow" />
        <span className={`ok ${health ? "" : "down"}`} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: health ? "#22c55e" : "#ef4444" }} />
          {health ? `API healthy · v${health.version}${health.qsv ? ` · qsv ${health.qsv}` : ""}` : "API not reachable"}
        </span>
      </footer>
    </div>
  );
}
