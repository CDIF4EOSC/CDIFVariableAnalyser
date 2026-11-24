import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { DatasetInfo, ImageCheck, ImageCollection, ImageItem, ImageSuggestion, JsonLdDoc, Vocabularies } from "../types";
import { DatasetPanel, KeywordInput, SharedFields, checklist, datesInvalid } from "./DatasetPanel";
import { IconCode, IconDownload, IconLogo, IconPlus, IconSpinner, IconX } from "./Icons";

interface Props {
  collection: ImageCollection;
  vocabularies?: Vocabularies;
  onChange: (c: ImageCollection) => void;
  onClose: () => void;
  onApiDocs: () => void;
  onToast: (text: string, kind?: "info" | "err") => void;
}

const AI_CONCURRENCY = 3;
// Fields that name one image: never inherited from the bundle (as on the server).
const OWN: (keyof DatasetInfo)[] = ["title", "description", "identifier", "url", "content_url", "record_id", "keywords"];

const filled = (v: unknown) => (Array.isArray(v) ? v.length > 0 : typeof v === "string" ? v.trim() !== "" : v != null);
const formatBytes = (n: number) =>
  n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 ** 2).toFixed(1)} MB`;

/** The description the CDIF is written from: the image's own fields, the bundle's where
 *  it has none. Mirrors ``effective_info`` on the server, without the file-name title. */
export function effectiveInfo(bundle: DatasetInfo, own: DatasetInfo): DatasetInfo {
  const out = { ...bundle } as Record<keyof DatasetInfo, unknown>;
  (Object.keys(own) as (keyof DatasetInfo)[]).forEach((k) => {
    out[k] = OWN.includes(k) || filled(own[k]) ? own[k] : bundle[k];
  });
  const seen = new Set(own.keywords.map((k) => k.trim().toLowerCase()));
  out.keywords = [...own.keywords, ...bundle.keywords.filter((k) => !seen.has(k.trim().toLowerCase()))];
  return out as unknown as DatasetInfo;
}

// Object URLs of pictures fetched with the API key header, by API path.
const pictures = new Map<string, Promise<string>>();
function picture(url: string): Promise<string> {
  let p = pictures.get(url);
  if (!p) {
    p = api.blob(url).then(({ blob }) => URL.createObjectURL(blob));
    p.catch(() => pictures.delete(url));
    pictures.set(url, p);
  }
  return p;
}
export function forgetPictures() {
  pictures.forEach((p) => void p.then((u) => URL.revokeObjectURL(u)).catch(() => undefined));
  pictures.clear();
}

function Picture({ url, alt, className }: { url: string; alt: string; className?: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    picture(url).then((u) => live && setSrc(u)).catch(() => live && setSrc(null));
    return () => { live = false; };
  }, [url]);
  return src ? <img src={src} alt={alt} className={className} /> : <div className={`${className ?? ""} pic-wait`} aria-label={alt} />;
}

type Status = "running" | "review" | "failed" | "ok" | "todo";
function statusOf(item: ImageItem, bundle: DatasetInfo): Status {
  if (item.ai_status === "running") return "running";
  if (item.suggestion) return "review";
  if (item.ai_status === "failed" && !item.info.title) return "failed";
  const required = checklist({ ...effectiveInfo(bundle, item.info) }).filter((c) => c.level === "required");
  return required.every((c) => c.ok) ? "ok" : "todo";
}
const STATUS_TEXT: Record<Status, string> = {
  running: "AI is describing this image",
  review: "AI suggestion to review",
  failed: "AI description failed",
  ok: "Required fields filled",
  todo: "Required fields missing",
};

function AddImages({ onFiles, disabled, label = "Add images" }: { onFiles: (f: File[]) => void; disabled?: boolean; label?: string }) {
  return (
    <label className={`img-add ${disabled ? "off" : ""}`}>
      <input
        type="file"
        className="sr-only"
        multiple
        disabled={disabled}
        accept=".jpg,.jpeg,.png,.webp,.tif,.tiff,image/jpeg,image/png,image/webp,image/tiff"
        onChange={(e) => { const f = [...(e.target.files ?? [])]; if (f.length) onFiles(f); e.target.value = ""; }}
      />
      <IconPlus /> {label}
    </label>
  );
}

/** The AI's staged suggestion: each part is accepted (written into the image) or rejected. */
function SuggestionBox({ s, onAccept, onReject }: {
  s: ImageSuggestion;
  onAccept: (part: Partial<ImageSuggestion>, rest: ImageSuggestion) => void;
  onReject: (rest: ImageSuggestion) => void;
}) {
  const without = (k: keyof ImageSuggestion): ImageSuggestion => ({ ...s, [k]: k === "keywords" ? [] : "" });
  return (
    <div className="ai-box" role="region" aria-label="AI suggestion">
      <div className="ai-head">
        <span className="ai-star">✦</span> <strong>AI suggestion</strong>
        <span className="muted">gpt-5.6-terra · review before it is used</span>
        <span className="grow" />
        <button type="button" className="btn sm" onClick={() => onAccept(s, { title: "", description: "", keywords: [] })}>Accept all</button>
        <button type="button" className="btn sm ghost" onClick={() => onReject({ title: "", description: "", keywords: [] })}>Reject all</button>
      </div>
      {s.title && (
        <div className="ai-part">
          <span className="ai-label">Title</span>
          <p>{s.title}</p>
          <div className="ai-acts">
            <button type="button" className="btn sm" onClick={() => onAccept({ title: s.title }, without("title"))}>Use</button>
            <button type="button" className="iconbtn" title="Reject" aria-label="Reject title" onClick={() => onReject(without("title"))}><IconX /></button>
          </div>
        </div>
      )}
      {s.description && (
        <div className="ai-part">
          <span className="ai-label">Description</span>
          <p>{s.description}</p>
          <div className="ai-acts">
            <button type="button" className="btn sm" onClick={() => onAccept({ description: s.description }, without("description"))}>Use</button>
            <button type="button" className="iconbtn" title="Reject" aria-label="Reject description" onClick={() => onReject(without("description"))}><IconX /></button>
          </div>
        </div>
      )}
      {s.keywords.length > 0 && (
        <div className="ai-part">
          <span className="ai-label">Keywords</span>
          <div className="ai-kws">
            {s.keywords.map((k) => (
              <button key={k} type="button" className="kw ai" title={`Add “${k}”`}
                onClick={() => onAccept({ keywords: [k] }, { ...s, keywords: s.keywords.filter((x) => x !== k) })}>
                + {k}
              </button>
            ))}
          </div>
          <div className="ai-acts">
            <button type="button" className="btn sm" onClick={() => onAccept({ keywords: s.keywords }, without("keywords"))}>Use all</button>
            <button type="button" className="iconbtn" title="Reject" aria-label="Reject keywords" onClick={() => onReject(without("keywords"))}><IconX /></button>
          </div>
        </div>
      )}
    </div>
  );
}

function ImageEditor({ collectionId, bundle, item, vocabularies, aiConfigured, onItem, onDescribe, onRemove, onBundle, onCdif }: {
  collectionId: string;
  bundle: DatasetInfo;
  vocabularies?: Vocabularies;
  item: ImageItem;
  aiConfigured: boolean;
  onItem: (i: ImageItem) => void;
  onDescribe: () => void;
  onRemove: () => void;
  onBundle: () => void;
  onCdif: () => void;
}) {
  const [draft, setDraft] = useState<DatasetInfo>(item.info);
  const [busy, setBusy] = useState(false);
  const saved = JSON.stringify(item.info);
  useEffect(() => setDraft(item.info), [item.id, saved]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = JSON.stringify(draft) !== saved;
  const set = <K extends keyof DatasetInfo>(k: K, v: DatasetInfo[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const effective = useMemo(() => effectiveInfo(bundle, draft), [bundle, draft]);
  const checks = useMemo(() => checklist(effective), [effective]);
  const invalid = datesInvalid(draft);
  const stem = item.filename.replace(/\.[^.]+$/, "");

  const save = async (next: DatasetInfo = draft) => {
    setBusy(true);
    try {
      onItem(await api.putImageInfo(collectionId, item.id, next));
    } finally {
      setBusy(false);
    }
  };
  const accept = async (part: Partial<ImageSuggestion>, rest: ImageSuggestion) => {
    const next = { ...draft };
    if (part.title) next.title = part.title;
    if (part.description) next.description = part.description;
    if (part.keywords?.length) {
      const have = new Set(next.keywords.map((k) => k.toLowerCase()));
      next.keywords = [...next.keywords, ...part.keywords.filter((k) => !have.has(k.toLowerCase()))];
    }
    setDraft(next);
    await save(next);
    onItem(await api.putImageSuggestion(collectionId, item.id, rest));
  };
  const reject = async (rest: ImageSuggestion) => onItem(await api.putImageSuggestion(collectionId, item.id, rest));

  return (
    <section className="img-editor" aria-label={`Image ${item.filename}`}>
      <div className="img-editor-head">
        <div className="col" style={{ gap: 2, minWidth: 0 }}>
          <strong className="ellipsis" title={item.filename}>{item.filename}</strong>
          <span className="muted">{item.mime.replace("image/", "").toUpperCase()} · {item.width}×{item.height} · {formatBytes(item.size)}</span>
        </div>
        <span className="grow" />
        <button type="button" className="btn sm" onClick={onCdif} title="Show the CDIF of this image"><IconCode /> CDIF</button>
        <button type="button" className="iconbtn" title="Remove this image" aria-label="Remove image" onClick={onRemove}><IconX /></button>
      </div>
      <div className="img-editor-body">
        <div className="img-preview"><Picture url={item.preview_url} alt={item.info.title || item.filename} /></div>

        {item.ai_status === "running" && (
          <div className="ai-box running"><IconSpinner size={16} /> Describing the image…</div>
        )}
        {item.ai_status === "failed" && (
          <div className="ai-box failed">
            <span>AI description failed: {item.ai_error || "unknown error"}</span>
            <button type="button" className="btn sm" onClick={onDescribe}>Try again</button>
          </div>
        )}
        {item.suggestion && <SuggestionBox s={item.suggestion} onAccept={(p, r) => void accept(p, r)} onReject={(r) => void reject(r)} />}
        {!aiConfigured && item.ai_status === "pending" && (
          <div className="ai-box off">AI description is not configured on this server (DDI_N8N_BEARER_KEY).</div>
        )}

        <form className="ds-form" onSubmit={(e) => { e.preventDefault(); if (dirty && !invalid) void save(); }}>
          <label className="field">
            <span>Title</span>
            <input value={draft.title} placeholder={stem} onChange={(e) => set("title", e.target.value)} />
            {!draft.title && <small>The file name “{stem}” is used until a title is given.</small>}
          </label>
          <label className="field">
            <span>Description</span>
            <textarea rows={4} value={draft.description} placeholder="What the image shows" onChange={(e) => set("description", e.target.value)} />
          </label>
          <div className="field">
            <span>Keywords{bundle.keywords.length > 0 && <span className="hint-label"> plus the bundle's: {bundle.keywords.join(", ")}</span>}</span>
            <KeywordInput keywords={draft.keywords} onChange={(k) => set("keywords", k)} />
          </div>
          <label className="field">
            <span>Download URL of the image</span>
            <input value={draft.content_url} placeholder="https://…/image.jpg" onChange={(e) => set("content_url", e.target.value)} />
            <small>Where the image itself can be fetched; CDIF writes “missing” otherwise. The output gives its size and MD5 checksum.</small>
          </label>
          <div className="grid2">
            <label className="field">
              <span>Persistent identifier</span>
              <input value={draft.identifier} placeholder="https://doi.org/10.…" onChange={(e) => set("identifier", e.target.value)} />
            </label>
            <label className="field">
              <span>Landing page</span>
              <input value={draft.url} placeholder="https://…" onChange={(e) => set("url", e.target.value)} />
            </label>
          </div>

          <div className="img-shared">
            <div className="img-shared-head">
              <h3>Shared with the bundle</h3>
              <span className="grow" />
              <button type="button" className="btn sm" onClick={onBundle}>Edit the bundle defaults</button>
            </div>
            <p className="hint-label">An empty field uses the bundle's value; fill it in to override it for this image only.</p>
          </div>
          <SharedFields draft={draft} set={set} vocabularies={vocabularies} inherit={bundle} keywords={false} />
        </form>

        <div className="ds-check img-checklist">
          <h3>CDIF checklist <span className="count">{checks.filter((c) => c.ok).length}/{checks.length}</span></h3>
          <ul>
            {checks.map((c) => (
              <li key={c.label} className={c.ok ? "ok" : c.level}>
                <span className="mark">{c.ok ? "✓" : c.level === "required" ? "!" : "·"}</span>
                <span>{c.label} <em>{c.level}</em></span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="img-editor-foot">
        {aiConfigured && item.ai_status !== "running" && (
          <button type="button" className="btn sm ghost" onClick={onDescribe} title="Ask the model again">✦ Describe again</button>
        )}
        <span className="grow" />
        {dirty && <span className="sub muted">Unsaved changes</span>}
        <button type="button" className="btn" disabled={!dirty || busy} onClick={() => setDraft(item.info)}>Discard</button>
        <button type="button" className="btn primary" disabled={!dirty || busy || invalid} onClick={() => void save()}>{busy ? "Saving…" : "Save"}</button>
      </div>
    </section>
  );
}

function CheckModal({ results, onPick, onClose }: { results: ImageCheck[] | null; onPick: (id: string) => void; onClose: () => void }) {
  const bad = results?.filter((r) => r.shacl.missing_required.length || r.shacl.violation_count || !r.shacl.checked) ?? [];
  return (
    <div className="scrim center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label="CDIF check">
        <div className="drawer-head">
          <div className="col" style={{ gap: 4, flexGrow: 1 }}>
            <span className="eyebrow">CDIF SHACL · one record per image</span>
            <h2 style={{ color: !results ? undefined : bad.length ? "#b91c1c" : "#15803d" }}>
              {!results ? "Checking…" : bad.length ? `${bad.length} of ${results.length} images need attention` : `All ${results.length} images pass`}
            </h2>
            <p>Each image's CDIF checked against the CDIF shapes, and the required fields the converter would otherwise fill with a stand-in.</p>
          </div>
          <button type="button" className="btn" style={{ width: 32, padding: 0, justifyContent: "center" }} aria-label="Close" onClick={onClose}><IconX /></button>
        </div>
        <div className="drawer-body">
          {!results ? <div className="row" style={{ gap: 8 }}><IconSpinner size={18} /> Validating…</div> : (
            <ul className="check-list">
              {results.map((r) => {
                const s = r.shacl;
                const issues = [...s.missing_required, ...(s.checked ? s.violations : [`Not checked: ${s.reason ?? "unavailable"}`])];
                return (
                  <li key={r.id}>
                    <button type="button" className="linkish" onClick={() => onPick(r.id)}>{r.filename}</button>
                    <span className={issues.length ? "bad" : "good"}>
                      {issues.length ? `${issues.length} issue${issues.length === 1 ? "" : "s"}` : "passes"}{s.checked ? ` · ${s.warnings} warning${s.warnings === 1 ? "" : "s"}` : ""}
                    </span>
                    {issues.length > 0 && <ul>{issues.map((m) => <li key={m}>{m}</li>)}</ul>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function CdifModal({ doc, filename, onClose }: { doc: JsonLdDoc | null; filename: string; onClose: () => void }) {
  return (
    <div className="scrim center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal wide" role="dialog" aria-label="CDIF of the image">
        <div className="drawer-head">
          <div className="col" style={{ gap: 4, flexGrow: 1 }}>
            <span className="eyebrow">CDIF · schema:Dataset + schema:ImageObject</span>
            <h2>{filename}</h2>
          </div>
          <button type="button" className="btn" style={{ width: 32, padding: 0, justifyContent: "center" }} aria-label="Close" onClick={onClose}><IconX /></button>
        </div>
        <div className="drawer-body">
          {doc ? <pre className="cdif-pre">{JSON.stringify(doc, null, 2)}</pre> : <IconSpinner size={18} />}
        </div>
      </div>
    </div>
  );
}

export function ImageWorkspace({ collection, vocabularies, onChange, onClose, onApiDocs, onToast }: Props) {
  const [view, setView] = useState<"images" | "bundle">("images");
  const [selected, setSelected] = useState<string | null>(collection.images[0]?.id ?? null);
  const [adding, setAdding] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [check, setCheck] = useState<ImageCheck[] | null | undefined>(undefined);
  const [cdif, setCdif] = useState<{ doc: JsonLdDoc | null; filename: string } | null>(null);
  const latest = useRef(collection);
  latest.current = collection;
  const inFlight = useRef(new Set<string>());
  const queue = useRef<string[]>([]);

  const updateItem = useCallback((item: ImageItem) => {
    const c = latest.current;
    onChange({ ...c, images: c.images.map((i) => (i.id === item.id ? item : i)) });
  }, [onChange]);

  // Ask the model about every image not yet described, a few at a time.
  const pump = useCallback(() => {
    while (inFlight.current.size < AI_CONCURRENCY && queue.current.length) {
      const id = queue.current.shift()!;
      const item = latest.current.images.find((i) => i.id === id);
      if (!item) continue;
      inFlight.current.add(id);
      updateItem({ ...item, ai_status: "running", ai_error: "" });
      api.describeImage(latest.current.id, id)
        .then(updateItem)
        .catch((e: Error) => {
          const cur = latest.current.images.find((i) => i.id === id);
          if (cur) updateItem({ ...cur, ai_status: "failed", ai_error: e.message });
        })
        .finally(() => { inFlight.current.delete(id); pump(); });
    }
  }, [updateItem]);
  const describe = useCallback((ids: string[]) => {
    ids.forEach((id) => { if (!inFlight.current.has(id) && !queue.current.includes(id)) queue.current.push(id); });
    pump();
  }, [pump]);
  useEffect(() => {
    if (!collection.ai_configured) return;
    describe(collection.images.filter((i) => i.ai_status === "pending").map((i) => i.id));
  }, [collection.images.length]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!collection.images.some((i) => i.id === selected)) setSelected(collection.images[0]?.id ?? null);
  }, [collection.images, selected]);

  const reportRejected = (c: ImageCollection) => {
    c.rejected.forEach((r) => onToast(`${r.filename}: ${r.reason}`, "err"));
  };
  const add = async (files: File[]) => {
    setAdding(true);
    try {
      const next = await api.addImages(collection.id, files);
      reportRejected(next);
      // Keep local AI state of images already shown (a describe may be in flight).
      const known = new Map(latest.current.images.map((i) => [i.id, i]));
      onChange({ ...next, images: next.images.map((i) => known.get(i.id) ?? i) });
    } catch (e) {
      onToast((e as Error).message, "err");
    } finally {
      setAdding(false);
    }
  };
  const remove = async (id: string) => {
    try {
      const next = await api.removeImage(collection.id, id);
      const known = new Map(latest.current.images.map((i) => [i.id, i]));
      onChange({ ...next, images: next.images.map((i) => known.get(i.id) ?? i) });
    } catch (e) {
      onToast((e as Error).message, "err");
    }
  };
  const saveBundle = async (bundle: DatasetInfo) => {
    const next = await api.putBundle(collection.id, bundle);
    const known = new Map(latest.current.images.map((i) => [i.id, i]));
    // The server's effective fields changed for every image; keep local AI state.
    onChange({ ...next, images: next.images.map((i) => ({ ...i, ai_status: known.get(i.id)?.ai_status ?? i.ai_status })) });
    onToast("Bundle defaults saved");
  };
  const download = async () => {
    setDownloading(true);
    try {
      const { blob, filename } = await api.blob(`/api/images/${collection.id}/cdif.zip`);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    } catch (e) {
      onToast((e as Error).message, "err");
    } finally {
      setDownloading(false);
    }
  };
  const runCheck = async () => {
    setCheck(null);
    try {
      setCheck(await api.checkImages(collection.id));
    } catch (e) {
      setCheck(undefined);
      onToast((e as Error).message, "err");
    }
  };
  const showCdif = async (item: ImageItem) => {
    setCdif({ doc: null, filename: item.filename });
    try {
      const doc = await api.imageCdif(collection.id, item.id);
      setCdif({ doc, filename: item.filename });
    } catch (e) {
      setCdif(null);
      onToast((e as Error).message, "err");
    }
  };

  const item = collection.images.find((i) => i.id === selected) ?? null;
  const toReview = collection.images.filter((i) => i.suggestion).length;
  const bundleChecks = checklist(collection.bundle).filter((c) => !["Title", "Description", "Persistent identifier", "Download URL"].includes(c.label));
  const full = collection.images.length >= collection.max_images;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "1") setView("images");
      else if (e.key === "2") setView("bundle");
      else if (view === "images" && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
        const list = latest.current.images;
        const i = list.findIndex((x) => x.id === selected);
        const next = list[Math.min(list.length - 1, Math.max(0, i + (e.key === "ArrowRight" ? 1 : -1)))];
        if (next) setSelected(next.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, selected]);

  return (
    <div className="app">
      <header className="header">
        <a className="brand" href="#" onClick={(e) => { e.preventDefault(); onClose(); }} title="Start over">
          <span className="brand-mark"><IconLogo /></span>
          <span className="brand-name">DDI-CDI Studio</span>
        </a>
        <div className="file-chip">
          <strong>Image collection</strong>
          <span>{collection.images.length} image{collection.images.length === 1 ? "" : "s"} · CDIF</span>
          <button type="button" className="iconbtn" style={{ color: "#94a3b8", width: 22, height: 22 }} aria-label="Close collection" title="Close and start over" onClick={onClose}>×</button>
        </div>
        <span className="grow" />
        <button type="button" className="hbtn" disabled={check === null} title="Check every image's CDIF against the CDIF SHACL shapes" onClick={() => void runCheck()}>Check</button>
        <button type="button" className="hbtn primary" disabled={downloading} title="Download a zip with one CDIF file per image" onClick={() => void download()}>
          <IconDownload /> {downloading ? "Preparing…" : <>Download<span className="wide-only"> CDIF zip</span></>}
        </button>
        <button type="button" className="hbtn" title="API documentation" aria-label="API documentation" onClick={onApiDocs}><IconCode /><span className="wide-only"> API</span></button>
      </header>

      <div className="workspace">
        <div className="left">
          <nav className="viewtabs" role="tablist" aria-label="Collection view">
            <button type="button" role="tab" aria-selected={view === "images"} className={view === "images" ? "on" : ""} onClick={() => setView("images")} title="Images and their own metadata (1)">
              Images <span className="count">{collection.images.length}</span>
              {toReview > 0 && <span className="badge ai" title={`${toReview} AI suggestion${toReview === 1 ? "" : "s"} to review`}>✦ {toReview}</span>}
            </button>
            <button type="button" role="tab" aria-selected={view === "bundle"} className={view === "bundle" ? "on" : ""} onClick={() => setView("bundle")} title="Licence, creators and other defaults shared by every image (2)">
              Bundle <span className="count">{bundleChecks.filter((c) => c.ok).length}/{bundleChecks.length}</span>
            </button>
            <span className="grow" />
            <span className="hint">Press 1 – 2 to switch · ← → between images</span>
          </nav>

          {view === "bundle" ? (
            <DatasetPanel
              info={collection.bundle}
              filename=""
              fileSize={null}
              fileMd5={null}
              vocabularies={vocabularies}
              onSave={saveBundle}
              mode="bundle"
            />
          ) : (
            <section className="panel img-panel">
              <div className="img-layout">
                <div className="img-grid-wrap">
                  <ul className="img-grid" aria-label="Images">
                    {collection.images.map((i) => {
                      const st = statusOf(i, collection.bundle);
                      return (
                        <li key={i.id}>
                          <button type="button" className={`img-tile ${i.id === selected ? "on" : ""}`} aria-pressed={i.id === selected} onClick={() => setSelected(i.id)}>
                            <Picture url={i.thumb_url} alt={i.filename} className="img-thumb" />
                            <span className={`img-dot ${st}`} title={STATUS_TEXT[st]} aria-label={STATUS_TEXT[st]}>
                              {st === "running" ? <IconSpinner size={10} /> : st === "review" ? "✦" : null}
                            </span>
                            <span className="img-caption ellipsis" title={i.info.title || i.filename}>{i.info.title || i.filename}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                  <div className="img-grid-foot">
                    <AddImages onFiles={(f) => void add(f)} disabled={adding || full} label={adding ? "Adding…" : "Add images"} />
                    <span className="muted">{collection.images.length}/{collection.max_images}</span>
                  </div>
                  <div className="img-legend">
                    {(["review", "running", "todo", "ok", "failed"] as Status[]).map((s) => (
                      <span key={s}><span className={`img-dot inline ${s}`} /> {STATUS_TEXT[s]}</span>
                    ))}
                  </div>
                </div>
                {item ? (
                  <ImageEditor
                    key={item.id}
                    collectionId={collection.id}
                    bundle={collection.bundle}
                    vocabularies={vocabularies}
                    item={item}
                    aiConfigured={collection.ai_configured}
                    onItem={updateItem}
                    onDescribe={() => describe([item.id])}
                    onRemove={() => void remove(item.id)}
                    onBundle={() => setView("bundle")}
                    onCdif={() => void showCdif(item)}
                  />
                ) : (
                  <div className="img-empty muted">Add images to describe them.</div>
                )}
              </div>
            </section>
          )}
        </div>
      </div>
      {check !== undefined && <CheckModal results={check} onPick={(id) => { setSelected(id); setView("images"); setCheck(undefined); }} onClose={() => setCheck(undefined)} />}
      {cdif && <CdifModal doc={cdif.doc} filename={cdif.filename} onClose={() => setCdif(null)} />}
    </div>
  );
}
