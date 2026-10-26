import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, setApiKey } from "./api";
import { diffDocs, type ElementView } from "./diff";
import { AddVariableDrawer } from "./components/AddVariableDrawer";
import { ApiDocsModal } from "./components/ApiDocsModal";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { DataTable } from "./components/DataTable";
import { IconCode, IconDownload, IconFile, IconLogo, IconRedo, IconSettings, IconUndo } from "./components/Icons";
import { JsonPreview } from "./components/JsonPreview";
import { MetadataTable } from "./components/MetadataTable";
import { OptionsPopover } from "./components/OptionsPopover";
import { StatisticsPanel } from "./components/StatisticsPanel";
import { Toasts, type Toast } from "./components/Toasts";
import { UploadScreen } from "./components/UploadScreen";
import type { Concept, EnrichKind, FileInfo, JsonLdDoc, Options, OutputFormat, PreviewPage, Statistics, Suggestion } from "./types";
import { ALL_STAT_NAMES, ENRICH_KINDS, sameFunctions } from "./types";

interface Edit {
  description: string;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
}

const DEFAULT_OPTIONS: Options = {
  includeRows: false,
  maxRows: 5,
  allRows: false,
  includeStatistics: false,
  statistics: ALL_STAT_NAMES,
  apiKey: localStorage.getItem("ddi.apiKey") ?? "",
};

const FORMAT_LABEL: Record<OutputFormat, string> = { ddicdi: "DDI-CDI", cdif: "CDIF" };

// The live preview never streams the whole file; the download does.
const PREVIEW_MAX_ROWS = 50;

type View = "meta" | "data" | "stats";

export default function App() {
  const [info, setInfo] = useState<FileInfo | null>(null);
  const [page, setPage] = useState<PreviewPage | null>(null);
  const [pageSize, setPageSize] = useState(5);
  const [offset, setOffset] = useState(0);
  const [pageLoading, setPageLoading] = useState(false);
  const [showLabels, setShowLabels] = useState(true);

  const [stats, setStats] = useState<Statistics | null>(null);
  const [statsStatus, setStatsStatus] = useState<"idle" | "busy" | "error">("idle");
  const [statsError, setStatsError] = useState<string | null>(null);
  const [statsWeight, setStatsWeight] = useState<string | null>(null);

  const [options, setOptions] = useState<Options>(DEFAULT_OPTIONS);
  const [doc, setDoc] = useState<JsonLdDoc | null>(null);
  const [views, setViews] = useState<ElementView[]>([]);
  const [outStatus, setOutStatus] = useState<"idle" | "busy" | "error">("idle");
  const [outError, setOutError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [importMs, setImportMs] = useState<number | null>(null);

  const [editedVars, setEditedVars] = useState<Set<string>>(new Set());
  const [newVars, setNewVars] = useState<Set<string>>(new Set());
  const [editedCells, setEditedCells] = useState<Set<string>>(new Set());
  const [undoStack, setUndoStack] = useState<Edit[]>([]);
  const [redoStack, setRedoStack] = useState<Edit[]>([]);
  const [focusVar, setFocusVar] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<Map<string, Suggestion>>(new Map());
  const [enriching, setEnriching] = useState<Set<string>>(new Set()); // "name|kind" keys of in-flight requests

  const [drawer, setDrawer] = useState(false);
  const [outputOpen, setOutputOpen] = useState(false);
  // What the output panel previews and the download writes.
  const [outFormat, setOutFormat] = useState<OutputFormat>("ddicdi");
  const [view, setView] = useState<View>("meta");
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [apiDocs, setApiDocs] = useState(false);
  const [apiInfo, setApiInfo] = useState<Record<string, unknown> | null>(null);
  const [health, setHealth] = useState<{ version: string; qsv: string | null } | null>(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<OutputFormat | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const docRef = useRef<JsonLdDoc | null>(null);
  const regenSeq = useRef(0);
  const fileIdRef = useRef<string | null>(null); // guards late enrichment results after a file switch
  fileIdRef.current = info?.file_id ?? null;

  /** Forget everything that belongs to the current file. Used when a file is uploaded,
   *  closed (home button) or lost on the server, so nothing from the previous file
   *  (statistics, weight variable, edits, suggestions, output) leaks into the next one. */
  const resetFileState = useCallback(() => {
    setInfo(null);
    setView("meta");
    setPage(null);
    setOffset(0);
    setImportMs(null);
    docRef.current = null;
    regenSeq.current++;
    setDoc(null);
    setViews([]);
    setOutStatus("idle");
    setOutError(null);
    setElapsed(null);
    setStats(null);
    setStatsStatus("idle");
    setStatsError(null);
    setStatsWeight(null);
    setEditedVars(new Set());
    setNewVars(new Set());
    setEditedCells(new Set());
    setUndoStack([]);
    setRedoStack([]);
    setFocusVar(null);
    setSuggestions(new Map());
    setEnriching(new Set());
    setDrawer(false);
    setOptionsOpen(false);
    setOptions((o) => ({ ...DEFAULT_OPTIONS, apiKey: o.apiKey }));
  }, []);

  const toast = useCallback((textIn: string, kind: "info" | "err" = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text: textIn, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "err" ? 6000 : 2500);
  }, []);

  // The server forgot the upload (TTL expired or the container restarted): drop the
  // dead session and send the user back to the upload screen instead of failing every
  // request against the stale file_id.
  const sessionLost = useCallback((e: unknown): boolean => {
    if (!(e instanceof ApiError && e.status === 404 && /Unknown file_id/.test(e.message))) return false;
    if (!fileIdRef.current) return true;
    resetFileState();
    setUploadError("This session has expired on the server (uploads are kept for a limited time and do not survive a restart). Upload the file again; edits from the previous session are lost.");
    return true;
  }, [resetFileState]);

  const fail = useCallback((e: unknown) => {
    if (sessionLost(e)) return;
    toast(e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e), "err");
  }, [toast, sessionLost]);

  // -- server info ----------------------------------------------------------------
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.info().then(setApiInfo).catch(() => undefined);
  }, []);
  useEffect(() => {
    setApiKey(options.apiKey);
    localStorage.setItem("ddi.apiKey", options.apiKey);
  }, [options.apiKey]);

  // -- output --------------------------------------------------------------------
  const maxRows = options.includeRows ? (options.allRows ? Math.max(options.maxRows, 1) : options.maxRows) : 0;
  const processAll = options.includeRows && options.allRows;
  const previewRows = Math.min(maxRows, PREVIEW_MAX_ROWS);
  // A stable key for the selection, so a tick regenerates the preview like any other option.
  const statsInclude = options.includeStatistics ? options.statistics.join(",") : "";

  const regenerate = useCallback(
    async (fileId: string) => {
      const seq = ++regenSeq.current;
      setOutStatus("busy");
      const t0 = performance.now();
      try {
        const body = {
          max_rows: previewRows,
          process_all_rows: false,
          include_statistics: options.includeStatistics,
          statistics_weight: statsWeight,
          statistics_include: options.includeStatistics ? options.statistics : undefined,
        };
        const next = await api.output(fileId, body, outFormat);
        if (seq !== regenSeq.current) return;
        setViews(diffDocs(docRef.current, next));
        docRef.current = next;
        setDoc(next);
        setElapsed(performance.now() - t0);
        setOutStatus("idle");
        setOutError(null);
      } catch (e) {
        if (seq !== regenSeq.current) return;
        if (sessionLost(e)) return;
        setOutStatus("error");
        setOutError(e instanceof Error ? e.message : String(e));
      }
    },
    [previewRows, options.includeStatistics, options.statistics, statsWeight, sessionLost, outFormat],
  );

  useEffect(() => {
    if (info) void regenerate(info.file_id);
  }, [info?.file_id, previewRows, options.includeStatistics, statsInclude, statsWeight]); // eslint-disable-line react-hooks/exhaustive-deps

  // Another format is another document: nothing in it is "changed" against the last one.
  useEffect(() => {
    docRef.current = null;
    setDoc(null);
    setViews([]);
    if (info) void regenerate(info.file_id);
  }, [outFormat]); // eslint-disable-line react-hooks/exhaustive-deps

  const pickFormat = (f: OutputFormat) => {
    if (f === outFormat) setOutputOpen((o) => !o);
    else {
      setOutFormat(f);
      setOutputOpen(true);
    }
  };

  // -- data page ------------------------------------------------------------------
  const loadPage = useCallback(async (fileId: string, size: number, off: number) => {
    setPageLoading(true);
    try {
      setPage(await api.preview(fileId, size, off));
    } catch (e) {
      fail(e);
    } finally {
      setPageLoading(false);
    }
  }, [fail]);

  useEffect(() => {
    if (info) void loadPage(info.file_id, pageSize, offset);
  }, [info?.file_id, pageSize, offset]); // eslint-disable-line react-hooks/exhaustive-deps

  // -- statistics -----------------------------------------------------------------
  // Computed lazily: nothing runs until the tab is opened, and `refresh()` drops the
  // result so the next visit recomputes against the edited data.csv.
  const loadStats = useCallback(async (fileId: string, weight: string | null, refreshStats = false) => {
    setStatsStatus("busy");
    setStatsError(null);
    try {
      setStats(await api.statistics(fileId, weight, refreshStats));
      setStatsStatus("idle");
    } catch (e) {
      if (sessionLost(e)) return;
      setStats(null);
      setStatsStatus("error");
      setStatsError(e instanceof Error ? e.message : String(e));
    }
  }, [sessionLost]);

  useEffect(() => {
    if (view === "stats" && info && !stats && statsStatus !== "busy" && statsStatus !== "error") {
      void loadStats(info.file_id, statsWeight);
    }
  }, [view, info?.file_id, stats, statsStatus, statsWeight]); // eslint-disable-line react-hooks/exhaustive-deps

  const changeStatsWeight = useCallback((weight: string | null) => {
    setStatsWeight(weight);
    setStats(null);
    setStatsStatus("idle");
  }, []);

  const refresh = useCallback(async () => {
    if (!info) return;
    const [i] = await Promise.all([api.fileInfo(info.file_id), loadPage(info.file_id, pageSize, offset)]);
    setInfo(i);
    setStats(null); // data may have changed; recompute on the next visit to the tab
    setStatsStatus("idle");
    await regenerate(info.file_id);
  }, [info, pageSize, offset, loadPage, regenerate]);

  // -- upload ---------------------------------------------------------------------
  const onFile = async (f: File) => {
    setUploadBusy(true);
    setUploadError(null);
    const t0 = performance.now();
    try {
      const i = await api.upload(f, 5);
      resetFileState();
      setImportMs(performance.now() - t0);
      setInfo(i);
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploadBusy(false);
    }
  };

  const [resetAsk, setResetAsk] = useState(false);
  const [resetBusy, setResetBusy] = useState(false);

  /** Home button / file chip ×: always ask, then forget the upload on the server and
   *  every piece of client state, so the next file starts completely fresh. */
  const closeFile = () => {
    if (info) setResetAsk(true);
  };

  const confirmReset = async () => {
    if (!info) return;
    setResetBusy(true);
    try {
      await api.remove(info.file_id);
    } catch {
      /* already gone */
    }
    setResetBusy(false);
    setResetAsk(false);
    resetFileState();
    setUploadError(null);
    setOutputOpen(false);
  };

  // -- edits -----------------------------------------------------------------------
  const perform = useCallback(
    async (edit: Edit) => {
      try {
        await edit.redo();
        setUndoStack((s) => [...s, edit]);
        setRedoStack([]);
        await refresh();
      } catch (e) {
        fail(e);
      }
    },
    [refresh, fail],
  );

  const undo = async () => {
    const edit = undoStack[undoStack.length - 1];
    if (!edit) return;
    try {
      await edit.undo();
      setUndoStack((s) => s.slice(0, -1));
      setRedoStack((s) => [...s, edit]);
      await refresh();
      toast(`Undid: ${edit.description}`);
    } catch (e) {
      fail(e);
    }
  };

  const redo = async () => {
    const edit = redoStack[redoStack.length - 1];
    if (!edit) return;
    try {
      await edit.redo();
      setRedoStack((s) => s.slice(0, -1));
      setUndoStack((s) => [...s, edit]);
      await refresh();
    } catch (e) {
      fail(e);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) void redo();
        else void undo();
        return;
      }
      if (!e.metaKey && !e.ctrlKey && !e.altKey) {
        if (e.key === "1") setView("meta");
        else if (e.key === "2") setView("data");
        else if (e.key === "3") setView("stats");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // re-bind each render so the closures see current stacks

  const patchVariable = async (name: string, patch: Record<string, unknown>, before: Record<string, unknown>) => {
    if (!info) return;
    const fid = info.file_id;
    const newName = typeof patch.new_name === "string" ? patch.new_name : null;
    const mark = (n: string) => setEditedVars((s) => new Set(s).add(n));
    await perform({
      description: `${Object.keys(patch).join(", ")} of ${name}`,
      redo: async () => {
        await api.patchVariable(fid, name, patch);
        mark(newName ?? name);
        if (newName) {
          setNewVars((s) => (s.has(name) ? new Set([...s].map((x) => (x === name ? newName : x))) : s));
          setSuggestions((m) => { if (!m.has(name)) return m; const n = new Map(m); const v = n.get(name)!; n.delete(name); n.set(newName, v); return n; });
        }
      },
      undo: async () => {
        await api.patchVariable(fid, newName ?? name, before);
        if (newName) setNewVars((s) => (s.has(newName) ? new Set([...s].map((x) => (x === newName ? name : x))) : s));
      },
    });
  };

  const deleteVariable = async (name: string) => {
    if (!info) return;
    if (!confirm(`Remove variable "${name}" and its column? This cannot be undone.`)) return;
    try {
      await api.deleteVariable(info.file_id, name);
      setUndoStack([]);
      setRedoStack([]);
      setNewVars((s) => { const n = new Set(s); n.delete(name); return n; });
      setEditedVars((s) => { const n = new Set(s); n.delete(name); return n; });
      setSuggestions((m) => { if (!m.has(name)) return m; const n = new Map(m); n.delete(name); return n; });
      if (focusVar === name) setFocusVar(null);
      await refresh();
      toast(`Removed ${name}`);
    } catch (e) {
      fail(e);
    }
  };

  const addVariable = async (spec: Record<string, unknown>, _keepOpen: boolean): Promise<boolean> => {
    if (!info) return false;
    const fid = info.file_id;
    const name = spec.name as string;
    try {
      await api.addVariable(fid, spec);
    } catch (e) {
      fail(e);
      return false;
    }
    setNewVars((s) => new Set(s).add(name));
    setUndoStack((s) => [
      ...s,
      {
        description: `add variable ${name}`,
        undo: async () => {
          await api.deleteVariable(fid, name);
          setNewVars((st) => { const n = new Set(st); n.delete(name); return n; });
        },
        redo: async () => {
          await api.addVariable(fid, spec);
          setNewVars((st) => new Set(st).add(name));
        },
      },
    ]);
    setRedoStack([]);
    await refresh();
    toast(`Added ${name}`);
    if (!_keepOpen) setDrawer(false);
    return true;
  };

  const editCell = async (rowIndex: number, name: string, next: string, prev: string) => {
    if (!info) return;
    const fid = info.file_id;
    await perform({
      description: `${name} in row ${rowIndex}`,
      redo: async () => {
        await api.patchRow(fid, rowIndex, { [name]: next });
        setEditedCells((s) => new Set(s).add(`${rowIndex}:${name}`));
      },
      undo: async () => {
        await api.patchRow(fid, rowIndex, { [name]: prev });
      },
    });
  };

  const addRow = async () => {
    if (!info) return;
    const fid = info.file_id;
    let index = -1;
    await perform({
      description: "add row",
      redo: async () => {
        index = (await api.addRow(fid)).index;
      },
      undo: async () => {
        await api.deleteRow(fid, index);
      },
    });
    if (index >= 0) {
      setOffset(Math.floor(index / pageSize) * pageSize);
      toast(`Row ${index} added at the end`);
    }
  };

  const deleteRow = async (rowIndex: number) => {
    if (!info) return;
    if (!confirm(`Delete row ${rowIndex}? This cannot be undone.`)) return;
    try {
      await api.deleteRow(info.file_id, rowIndex);
      setUndoStack([]);
      setRedoStack([]);
      await refresh();
    } catch (e) {
      fail(e);
    }
  };

  // -- download ---------------------------------------------------------------------
  // -- AI enrichment (suggestions are staged; accepting turns them into normal edits) ----
  const aiAvailable = Boolean(apiInfo?.ai_enrichment);

  const mergeConcepts = (existing: Concept[], added: Concept[]): Concept[] => {
    const seen = new Set(existing.map((c) => c.uri));
    return [...existing, ...added.filter((c) => !seen.has(c.uri))];
  };

  const enrichVars = async (names: string[] | null, kinds: EnrichKind[]) => {
    if (!info) return;
    const fid = info.file_id;
    const targets = names ?? info.variables.map((v) => v.name);
    const keys = targets.flatMap((t) => kinds.map((k) => `${t}|${k}`));
    setEnriching((s) => new Set([...s, ...keys]));
    try {
      const res = await api.enrich(fid, { variables: names ?? undefined, kinds });
      if (fileIdRef.current !== fid) return; // file was closed or replaced meanwhile
      const byName = new Map(info.variables.map((v) => [v.name, v]));
      let units = 0;
      let concepts = 0;
      let roles = 0;
      let functions = 0;
      let measures = 0;
      setSuggestions((m) => {
        const n = new Map(m);
        for (const s of res.suggestions) {
          const v = byName.get(s.name);
          if (!v) continue;
          const cur: Suggestion = { ...(n.get(s.name) ?? {}) };
          if (s.unit_of_measure !== undefined && (s.unit_of_measure ?? null) !== (v.unit_of_measure ?? null)) {
            cur.unit_of_measure = s.unit_of_measure ?? null;
            units++;
          }
          if (s.concepts !== undefined && s.concepts !== null) {
            const fresh = mergeConcepts(v.concepts, s.concepts).slice(v.concepts.length);
            if (fresh.length > 0) {
              cur.concepts = fresh;
              concepts++;
            }
          }
          if (s.role !== undefined && s.role !== null && s.role !== v.default_role) {
            cur.role = s.role;
            roles++;
          }
          if (s.functions !== undefined && s.functions !== null && !sameFunctions(s.functions, v.functions)) {
            cur.functions = s.functions;
            functions++;
          }
          if (s.measure !== undefined && s.measure !== null && s.measure !== v.measure) {
            cur.measure = s.measure;
            measures++;
          }
          if (Object.keys(cur).length > 0) n.set(s.name, cur);
        }
        return n;
      });
      const parts = [];
      if (kinds.includes("unit")) parts.push(`${units} unit`);
      if (kinds.includes("concept")) parts.push(`${concepts} concept`);
      if (kinds.includes("role")) parts.push(`${roles} role`);
      if (kinds.includes("function")) parts.push(`${functions} function`);
      if (kinds.includes("measure")) parts.push(`${measures} measure`);
      const total = units + concepts + roles + functions + measures;
      toast(total === 0 ? "✦ No new suggestions (current values already match)" : `✦ ${parts.join(", ")} suggestion${total === 1 ? "" : "s"} · review in the table`);
      if (res.errors.length) {
        const failed = [...new Set(res.errors.map((e) => e.name ?? e.kind))];
        toast(`Enrichment failed for ${failed.length > 6 ? `${failed.length} variables` : failed.join(", ")}: ${res.errors[0].message}`, "err");
      }
    } catch (e) {
      if (fileIdRef.current === fid) fail(e);
    } finally {
      setEnriching((s) => { const n = new Set(s); for (const k of keys) n.delete(k); return n; });
    }
  };

  const suggestionPatch = (v: FileInfo["variables"][number], sug: Suggestion, kind: EnrichKind): { patch: Record<string, unknown>; before: Record<string, unknown> } | null => {
    if (kind === "unit" && sug.unit_of_measure !== undefined) {
      return { patch: { unit_of_measure: sug.unit_of_measure ?? "" }, before: { unit_of_measure: v.unit_of_measure ?? "" } };
    }
    if (kind === "concept" && sug.concepts !== undefined) {
      return { patch: { concepts: mergeConcepts(v.concepts, sug.concepts) }, before: { concepts: v.concepts } };
    }
    if (kind === "role" && sug.role !== undefined) {
      return { patch: { role: sug.role }, before: { role: v.default_role } };
    }
    if (kind === "function" && sug.functions !== undefined) {
      return { patch: { functions: sug.functions }, before: { functions: v.functions } };
    }
    if (kind === "measure" && sug.measure !== undefined) {
      return { patch: { measure: sug.measure }, before: { measure: v.measure } };
    }
    return null;
  };

  const dropSuggestion = (name: string, kind: EnrichKind) =>
    setSuggestions((m) => {
      const cur = m.get(name);
      if (!cur) return m;
      const n = new Map(m);
      const next: Suggestion = { ...cur };
      if (kind === "unit") delete next.unit_of_measure;
      else if (kind === "concept") delete next.concepts;
      else if (kind === "function") delete next.functions;
      else if (kind === "measure") delete next.measure;
      else delete next.role;
      if (Object.keys(next).length === 0) n.delete(name);
      else n.set(name, next);
      return n;
    });

  const acceptSuggestion = async (name: string, kind: EnrichKind) => {
    if (!info) return;
    const v = info.variables.find((x) => x.name === name);
    const sug = suggestions.get(name);
    if (!v || !sug) return;
    const p = suggestionPatch(v, sug, kind);
    if (!p) return;
    dropSuggestion(name, kind);
    await patchVariable(name, p.patch, p.before);
  };

  const acceptAll = async () => {
    if (!info) return;
    const fid = info.file_id;
    const steps: { name: string; patch: Record<string, unknown>; before: Record<string, unknown> }[] = [];
    for (const [name, sug] of suggestions) {
      const v = info.variables.find((x) => x.name === name);
      if (!v) continue;
      for (const kind of ENRICH_KINDS) {
        const p = suggestionPatch(v, sug, kind);
        if (p) steps.push({ name, ...p });
      }
    }
    if (steps.length === 0) return;
    setSuggestions(new Map());
    const mark = (n: string) => setEditedVars((s) => new Set(s).add(n));
    // sequential: each PATCH rewrites meta.json, concurrent calls would lose updates
    await perform({
      description: `accept ${steps.length} AI suggestion${steps.length === 1 ? "" : "s"}`,
      redo: async () => {
        for (const s of steps) {
          await api.patchVariable(fid, s.name, s.patch);
          mark(s.name);
        }
      },
      undo: async () => {
        for (const s of [...steps].reverse()) await api.patchVariable(fid, s.name, s.before);
      },
    });
    toast(`Accepted ${steps.length} suggestion${steps.length === 1 ? "" : "s"} (one undo step)`);
  };

  const download = async (format: OutputFormat = outFormat) => {
    if (!info) return;
    setDownloading(format);
    try {
      const { blob, filename } = await api.download(info.file_id, {
        max_rows: maxRows,
        process_all_rows: processAll,
        include_statistics: options.includeStatistics,
        statistics_weight: statsWeight,
        statistics_include: options.includeStatistics ? options.statistics : undefined,
      }, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      toast(`Downloaded ${filename}`);
    } catch (e) {
      fail(e);
    } finally {
      setDownloading(null);
    }
  };

  const focusVariable = (name: string | null) => {
    setFocusVar(name);
    if (name) {
      setView("meta");
      setOutputOpen(true);
    }
  };

  /** Highlight a variable without leaving the current tab or forcing the output
   *  panel open: it only filters the preview when the user already has it open. */
  const highlightVariable = (name: string | null) => setFocusVar(name);

  const baseName = useMemo(() => (info ? info.filename.replace(/\.[^.]+$/, "") : ""), [info]);
  const editCount = undoStack.length;

  if (!info) {
    return (
      <>
        <UploadScreen
          onFile={onFile}
          busy={uploadBusy}
          error={uploadError}
          health={health}
          onApiDocs={() => setApiDocs(true)}
          supported={(apiInfo?.supported_extensions as string[] | undefined) ?? []}
          apiKeyRequired={apiInfo?.authentication === "X-API-Key header"}
          apiKey={options.apiKey}
          onApiKey={(k) => { setUploadError(null); setOptions((o) => ({ ...o, apiKey: k.trim() })); }}
        />
        {apiDocs && <ApiDocsModal apiInfo={apiInfo} onClose={() => setApiDocs(false)} />}
        <Toasts items={toasts} />
      </>
    );
  }

  return (
    <div className="app">
      <header className="header">
        <a className="brand" href="#" onClick={(e) => { e.preventDefault(); closeFile(); }} title="Start over with a new file">
          <span className="brand-mark"><IconLogo /></span>
          <span className="brand-name">DDI-CDI Studio</span>
        </a>
        <div className="file-chip">
          <IconFile style={{ color: "#a5b4fc" }} />
          <strong>{info.filename}</strong>
          <span>{info.file_format.toUpperCase()} · {info.number_rows.toLocaleString()} rows · {info.number_variables} variables</span>
          {importMs !== null && (<><span className="sep" /><span>imported in {(importMs / 1000).toFixed(2)} s</span></>)}
          <button type="button" className="iconbtn" style={{ color: "#94a3b8", width: 22, height: 22 }} aria-label="Close file" title="Close file and start over" onClick={closeFile}>×</button>
        </div>
        <span className="grow" />
        <span className={`edits-pill ${editCount === 0 ? "clean" : ""}`}>
          <span className="dot" />
          {editCount === 0 ? "No edits" : `${editCount} edit${editCount === 1 ? "" : "s"}`}
        </span>
        <div className="row" style={{ gap: 2 }}>
          <button type="button" className="hbtn icon" aria-label="Undo" title="Undo (⌘Z)" disabled={!undoStack.length} onClick={() => void undo()}><IconUndo /></button>
          <button type="button" className="hbtn icon" aria-label="Redo" title="Redo (⇧⌘Z)" disabled={!redoStack.length} onClick={() => void redo()}><IconRedo /></button>
        </div>
        <div style={{ position: "relative" }}>
          <button type="button" className="hbtn" onClick={() => setOptionsOpen((o) => !o)} aria-expanded={optionsOpen}><IconSettings /> Options</button>
          {optionsOpen && <OptionsPopover options={options} totalRows={info.number_rows} statsWeight={statsWeight} onChange={setOptions} onClose={() => setOptionsOpen(false)} />}
        </div>
        <div className="fmt-switch" role="radiogroup" aria-label="Output format">
          {(["ddicdi", "cdif"] as const).map((f) => (
            <button
              key={f}
              type="button"
              role="radio"
              aria-checked={outFormat === f}
              className={outFormat === f ? (outputOpen ? "on open" : "on") : ""}
              title={
                outFormat === f
                  ? `${outputOpen ? "Hide" : "Show"} the ${FORMAT_LABEL[f]} output panel`
                  : f === "cdif"
                    ? "Preview and download CDIF, converted from DDI-CDI (metadata only: no data rows or statistics)"
                    : "Preview and download DDI-CDI"
              }
              onClick={() => pickFormat(f)}
            >
              {outFormat === f && <span className={`out-dot ${outStatus}`} />} {FORMAT_LABEL[f]}
            </button>
          ))}
        </div>
        <button type="button" className="hbtn primary" disabled={downloading !== null} onClick={() => void download()}>
          <IconDownload /> {downloading ? "Preparing…" : `Download ${baseName}${outFormat === "cdif" ? "_CDIF.json" : "_DDICDI.jsonld"}`}
        </button>
        <button type="button" className="hbtn" title="API documentation" onClick={() => setApiDocs(true)}><IconCode /> API</button>
      </header>

      <div className={`workspace ${outputOpen ? "with-output" : ""}`}>
        <div className="left">
          <nav className="viewtabs" role="tablist" aria-label="Workspace view">
            <button type="button" role="tab" aria-selected={view === "meta"} className={view === "meta" ? "on" : ""} onClick={() => setView("meta")} title="Variables and their metadata (1)">
              Variables <span className="count">{info.number_variables}</span>
              {suggestions.size > 0 && <span className="badge ai" title={`${suggestions.size} AI suggestion${suggestions.size === 1 ? "" : "s"} to review`}>✦ {suggestions.size}</span>}
            </button>
            <button type="button" role="tab" aria-selected={view === "data"} className={view === "data" ? "on" : ""} onClick={() => setView("data")} title="Data rows (2)">
              Data <span className="count">{info.number_rows.toLocaleString()}</span>
              {editedCells.size > 0 && <span className="badge edit" title={`${editedCells.size} edited cell${editedCells.size === 1 ? "" : "s"}`}>{editedCells.size}</span>}
            </button>
            <button type="button" role="tab" aria-selected={view === "stats"} className={view === "stats" ? "on" : ""} onClick={() => setView("stats")} title="Summary statistics and frequency distributions (3)">
              Statistics
              {stats && <span className="count">{stats.variables.length}</span>}
              {statsStatus !== "idle" && <span className={`out-dot ${statsStatus}`} title={statsStatus === "busy" ? "Computing…" : "Computation failed"} />}
            </button>
            <span className="grow" />
            <span className="hint">Press 1 / 2 / 3 to switch</span>
          </nav>
          {view === "meta" ? (
            <MetadataTable
              variables={info.variables}
              editedVars={editedVars}
              newVars={newVars}
              focusVar={focusVar}
              onFocusVar={focusVariable}
              onPatch={patchVariable}
              onDelete={deleteVariable}
              onAdd={() => setDrawer(true)}
              suggestions={suggestions}
              enriching={enriching}
              aiAvailable={aiAvailable}
              onEnrich={(names, kinds) => void enrichVars(names, kinds)}
              onAccept={(name, kind) => void acceptSuggestion(name, kind)}
              onReject={dropSuggestion}
              onAcceptAll={() => void acceptAll()}
              onRejectAll={() => setSuggestions(new Map())}
            />
          ) : view === "data" ? (
            <DataTable
              page={page}
              variables={info.variables}
              pageSize={pageSize}
              onPageSize={(n) => { setPageSize(n); setOffset(0); }}
              onOffset={setOffset}
              showLabels={showLabels}
              onShowLabels={setShowLabels}
              editedCells={editedCells}
              editedVars={editedVars}
              newVars={newVars}
              maxRowsInOutput={processAll ? "all" : maxRows}
              onEditCell={editCell}
              onAddRow={addRow}
              onDeleteRow={deleteRow}
              loading={pageLoading}
            />
          ) : (
            <StatisticsPanel
              stats={stats}
              variables={info.variables}
              status={statsStatus}
              error={statsError}
              weight={statsWeight}
              onWeight={changeStatsWeight}
              onRecompute={() => void loadStats(info.file_id, statsWeight, true)}
              onLoadCategories={(name, limit, sort) =>
                api.categories(info.file_id, name, { limit, sort, weight: statsWeight })
              }
              focusVar={focusVar}
              onFocusVar={highlightVariable}
            />
          )}
        </div>
        {outputOpen && (
        <div className="right">
          <JsonPreview
            doc={doc}
            format={outFormat}
            views={views}
            status={outStatus}
            elapsedMs={elapsed}
            error={outError}
            focusVar={focusVar}
            onClearFocus={() => setFocusVar(null)}
            onToast={toast}
            onClose={() => setOutputOpen(false)}
          />
        </div>
        )}
      </div>

      <footer className="status">
        <span className={`ok ${health ? "" : "down"}`}><span className="dot" />{health ? `API connected · v${health.version}` : "API not reachable"}</span>
        {health?.qsv && <span>Engine qsv readstat {health.qsv}</span>}
        <span>
          Output rows {processAll ? `all ${info.number_rows.toLocaleString()}` : maxRows === 0 ? "none (metadata only)" : maxRows}
          {(processAll || maxRows > previewRows) && ` · preview shows ${previewRows}`}
        </span>
        <span className="grow" />
        {!info.sentinels_in_data && <span className="warn">User-missing cells arrive empty from qsv for this format (Stata: qsv issue #4627); typed codes inside a missing range are routed to the sentinel domain</span>}
      </footer>

      {drawer && <AddVariableDrawer variables={info.variables} rowsInOutput={processAll ? info.number_rows : maxRows} onClose={() => setDrawer(false)} onAdd={addVariable} />}
      {apiDocs && <ApiDocsModal apiInfo={apiInfo} onClose={() => setApiDocs(false)} />}
      {resetAsk && (
        <ConfirmDialog
          title="Start from scratch?"
          message={<>This will reset the file and everything in memory: edits, statistics, suggestions and the generated output for <strong>{info.filename}</strong> are discarded and the upload is removed from the server. You can then select a new file.</>}
          confirmLabel="Reset and choose a new file"
          cancelLabel="Keep working"
          danger
          busy={resetBusy}
          onConfirm={() => void confirmReset()}
          onCancel={() => setResetAsk(false)}
        />
      )}
      <Toasts items={toasts} />
    </div>
  );
}
