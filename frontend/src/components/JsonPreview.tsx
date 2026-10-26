import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ElementView } from "../diff";
import { countByType, graphKey, idsForVariable } from "../diff";
import type { ChangeKind, JsonLdDoc, OutputFormat } from "../types";
import { IconCopy, IconSearch, IconX } from "./Icons";

interface Props {
  doc: JsonLdDoc | null;
  format: OutputFormat;
  views: ElementView[];
  status: "idle" | "busy" | "error";
  elapsedMs: number | null;
  error: string | null;
  focusVar: string | null;
  onClearFocus: () => void;
  onToast: (t: string) => void;
  onClose: () => void;
}

interface Line {
  text: string;
  kind: ChangeKind;
  id: string | null;
  n: number | null;
}

const TOKEN = /("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false|null)\b|([{}[\],:])/g;

function highlight(line: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  TOKEN.lastIndex = 0;
  let k = 0;
  while ((m = TOKEN.exec(line))) {
    if (m.index > last) out.push(line.slice(last, m.index));
    if (m[1] !== undefined) {
      if (m[2] !== undefined) out.push(<span key={k++} className="k">{m[1]}</span>, m[2]);
      else out.push(<span key={k++} className="s">{m[1]}</span>);
    } else if (m[3] !== undefined) out.push(<span key={k++} className="num">{m[3]}</span>);
    else if (m[4] !== undefined) out.push(<span key={k++} className="b">{m[4]}</span>);
    else out.push(<span key={k++} className="p">{m[5]}</span>);
    last = TOKEN.lastIndex;
  }
  if (last < line.length) out.push(line.slice(last));
  return out;
}

const INDENT = "        ";
const ROW = 20; // px, must match pre.code line-height
const PAD = 12; // px, pre.code vertical padding
const OVERSCAN = 20;

interface Cached {
  lines: string[]; // without the trailing comma
  lower: string; // for the search box
}

// Per element object (elements are replaced on every regeneration, so a WeakMap is enough).
const lineCache = new WeakMap<object, Cached>();
function cachedLines(v: ElementView): Cached {
  let c = lineCache.get(v.element);
  if (!c) {
    const lines = JSON.stringify(v.element, null, 4).split("\n").map((l) => INDENT + l);
    c = { lines, lower: lines.join("\n").toLowerCase() };
    lineCache.set(v.element, c);
  }
  return c;
}

/**
 * Renders only the rows inside the scroll viewport (plus an overscan), so a
 * document with tens of thousands of lines costs a few hundred DOM nodes.
 */
function VirtualCode({ count, scroller, renderRow, footer, scrollToRow }: {
  count: number;
  scroller: React.RefObject<HTMLDivElement>;
  renderRow: (i: number) => React.ReactNode;
  footer?: React.ReactNode;
  scrollToRow: number | null;
}) {
  const [range, setRange] = useState({ start: 0, end: 80 });
  const raf = useRef(0);

  const measure = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    const start = Math.max(0, Math.floor((el.scrollTop - PAD) / ROW) - OVERSCAN);
    const end = Math.min(count, Math.ceil((el.scrollTop - PAD + el.clientHeight) / ROW) + OVERSCAN);
    setRange((r) => (r.start === start && r.end === end ? r : { start, end }));
  }, [scroller, count]);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const onScroll = () => {
      cancelAnimationFrame(raf.current);
      raf.current = requestAnimationFrame(measure);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => {
      el.removeEventListener("scroll", onScroll);
      ro.disconnect();
      cancelAnimationFrame(raf.current);
    };
  }, [scroller, measure]);

  useEffect(() => {
    const el = scroller.current;
    if (!el || scrollToRow === null) return;
    el.scrollTop = Math.max(0, PAD + scrollToRow * ROW - el.clientHeight / 2);
    measure();
  }, [scroller, scrollToRow, measure]);

  const rows: React.ReactNode[] = [];
  for (let i = range.start; i < Math.min(range.end, count); i++) rows.push(renderRow(i));
  return (
    <pre className="code" style={{ boxSizing: "content-box", height: count * ROW }}>
      <div style={{ height: range.start * ROW }} />
      {rows}
      <div style={{ height: Math.max(0, count - range.end) * ROW }} />
      {footer}
    </pre>
  );
}

export function JsonPreview(p: Props) {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [cap, setCap] = useState(1500);
  const scroller = useRef<HTMLDivElement>(null);

  const counts = useMemo(() => countByType(p.views), [p.views]);
  const { changed, added, removed, objects } = useMemo(() => {
    let changed = 0, added = 0, removed = 0, objects = 0;
    for (const v of p.views) {
      if (v.kind === "changed") changed++;
      else if (v.kind === "added") added++;
      else if (v.kind === "removed") removed++;
      if (v.kind !== "removed" && !v.key) objects++;
    }
    return { changed, added, removed, objects };
  }, [p.views]);
  const varIds = useMemo(() => (p.focusVar ? idsForVariable(p.views, p.focusVar) : null), [p.views, p.focusVar]);

  const { lines, totalLines, capped, firstHighlight } = useMemo(() => {
    if (!p.doc) return { lines: [] as Line[], hidden: 0, totalLines: 0, capped: false, firstHighlight: null as number | null };
    const q = query.trim().toLowerCase();
    const out: Line[] = [];
    let n = 1;
    const push = (text: string, kind: ChangeKind = "same", id: string | null = null) => {
      out.push({ text, kind, id, n: kind === "removed" ? null : n });
      if (kind !== "removed") n += 1;
    };
    let hidden = 0;
    let shown = 0;
    let skipRun = 0;
    const flushSkip = () => {
      if (skipRun > 0) {
        out.push({ text: `⋯ ${skipRun} unchanged object${skipRun === 1 ? "" : "s"}`, kind: "same", id: "__skip", n: null });
        skipRun = 0;
      }
    };

    push("{");
    // The views are in document order: top-level properties as blocks, the graph
    // (DDICDIModels, or a CDIF dataset's variables) as one run of elements.
    const graph = graphKey(p.doc);
    const nTop = p.views.filter((v) => v.key).length + (p.views.some((v) => !v.key) ? 1 : 0);
    let topDone = 0;
    let firstHighlight: number | null = null;
    for (let idx = 0; idx < p.views.length; idx++) {
      const v = p.views[idx];
      if (v.key) {
        topDone += 1;
        const block = JSON.stringify({ [v.key]: v.element }, null, 4).split("\n").slice(1, -1);
        if (v.kind !== "same" && !varIds && firstHighlight === null) firstHighlight = out.length;
        block.forEach((l, i) => push(i === block.length - 1 && topDone < nTop ? l + "," : l, v.kind, v.id));
        continue;
      }
      // the graph: from here to the next top-level property
      let end = idx;
      while (end < p.views.length && !p.views[end].key) end++;
      const group = p.views.slice(idx, end);
      idx = end - 1;
      topDone += 1;
      push(`    ${JSON.stringify(graph)}: [`);
      group.forEach((g, gi) => {
        const matchesType = !typeFilter || g.type === typeFilter;
        const matchesVar = !varIds || varIds.has(g.id);
        const c = cachedLines(g);
        const matchesQuery = !q || c.lower.includes(q);
        const visible = matchesType && matchesVar && matchesQuery && shown < cap;
        if (!visible) {
          hidden += 1;
          skipRun += 1;
          if (g.kind !== "removed") n += c.lines.length;
          return;
        }
        flushSkip();
        shown += 1;
        const highlight = varIds ? varIds.has(g.id) : g.kind === "changed" || g.kind === "added";
        if (highlight && firstHighlight === null) firstHighlight = out.length;
        const last = gi === group.length - 1;
        c.lines.forEach((l, i) => push(!last && i === c.lines.length - 1 ? l + "," : l, g.kind, g.id));
      });
      flushSkip();
      push(topDone < nTop ? "    ]," : "    ]");
    }
    push("}");
    return { lines: out, hidden, totalLines: n - 1, capped: hidden > 0 && shown >= cap, firstHighlight };
  }, [p.doc, p.views, query, typeFilter, varIds, cap]);

  // Scroll to the first highlighted / focused line after a regeneration or focus change (not on search/cap changes).
  const [scrollTarget, setScrollTarget] = useState<number | null>(null);
  useEffect(() => {
    setScrollTarget(firstHighlight);
  }, [p.doc, varIds]); // eslint-disable-line react-hooks/exhaustive-deps

  const copy = async () => {
    await navigator.clipboard.writeText(p.doc ? JSON.stringify(p.doc, null, 4) : "");
    p.onToast("Copied to clipboard");
  };

  const q = query.trim().toLowerCase();

  return (
    <section className="out" aria-label="Output preview">
      <div className="out-head">
        <span className="out-title">{p.format === "cdif" ? "CDIF · JSON-LD" : "DDI-CDI · JSON-LD"}</span>
        <span className="grow" />
        <span className={`live ${p.status === "busy" ? "busy" : p.status === "error" ? "err" : ""}`}>
          <span className="dot" />
          {p.status === "busy" ? "Regenerating…" : p.status === "error" ? "Generation failed" : p.elapsedMs !== null ? `Live · regenerated in ${(p.elapsedMs / 1000).toFixed(2)} s` : "Live"}
        </span>
        <button type="button" className="dbtn" aria-label="Copy to clipboard" title="Copy" onClick={() => void copy()}><IconCopy /></button>
        <button type="button" className="dbtn" aria-label="Hide output panel" title="Hide output" onClick={p.onClose}><IconX /></button>
      </div>

      <div className="out-tools">
        <label className="search">
          <IconSearch size={13} />
          <input type="search" placeholder="Find in output" aria-label="Find in output" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <span style={{ fontSize: 11, color: "#64748b", flexShrink: 0 }}>Jump to</span>
        <div className="jump">
          {p.focusVar && (
            <button type="button" className="on" onClick={p.onClearFocus} title="Clear variable filter">
              {p.focusVar} ×
            </button>
          )}
          {[...counts.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([type, n]) => (
            <button key={type} type="button" className={typeFilter === type ? "on" : ""} onClick={() => setTypeFilter(typeFilter === type ? null : type)}>
              {type}<span>{n}</span>
            </button>
          ))}
        </div>
      </div>

      {p.status === "error" && <div className="out-empty" style={{ color: "#fca5a5", flexGrow: 0, padding: 12 }}>{p.error}</div>}

      <div className="code-scroll" ref={scroller}>
        {p.doc ? (
            <VirtualCode
              count={lines.length}
              scroller={scroller}
              scrollToRow={scrollTarget}
              renderRow={(i) => {
                const l = lines[i];
                if (l.id === "__skip") return <span key={i} className="skip">{l.text}</span>;
                return (
                  <span
                    key={i}
                    className={`ln ${l.kind !== "same" ? l.kind : ""} ${q && l.text.toLowerCase().includes(q) ? "hit" : ""}`}
                    data-focus={varIds && l.id && varIds.has(l.id) ? "1" : undefined}
                  >
                    <span className="n">{l.n ?? (l.kind === "removed" ? "−" : "")}</span>
                    {highlight(l.text)}
                  </span>
                );
              }}
              footer={capped ? (
                <span className="skip">
                  showing the first {cap} matching objects · <button type="button" onClick={() => setCap(cap + 1500)}>show 1500 more</button>
                </span>
              ) : undefined}
            />
          ) : (
            <div className="out-empty">{p.status === "busy" ? "Generating the document…" : `The ${p.format === "cdif" ? "CDIF" : "DDI-CDI"} document appears here as soon as a file is loaded.`}</div>
          )}
      </div>

      <div className="out-foot">
        <span><span className="sq" style={{ background: "#f59e0b" }} />{changed} changed</span>
        <span><span className="sq" style={{ background: "#14b8a6" }} />{added} added</span>
        {removed > 0 && <span><span className="sq" style={{ background: "#ef4444" }} />{removed} removed</span>}
        <span style={{ color: "#475569" }}>·</span>
        <span>{totalLines.toLocaleString()} lines · {objects.toLocaleString()} objects · {counts.size} classes</span>
      </div>
    </section>
  );
}
