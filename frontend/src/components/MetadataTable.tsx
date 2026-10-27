import { useMemo, useState } from "react";
import type { EnrichKind, Suggestion, Variable } from "../types";
import { FUNCTION_OPTIONS, MEASURE_OPTIONS, TYPE_OPTIONS, functionLabel, roleLabel, typeHasDecimals } from "../types";
import { UNIT_OPTIONS, isKnownUnit, unitLabel, unitUri } from "../units";
import { ColumnHandle, useColumnWidths, type Column } from "./ColumnResize";
import { ConceptsEditor } from "./ConceptsEditor";
import { EditableCell } from "./EditableCell";
import { IconPlus, IconSearch, IconTrash, IconX } from "./Icons";
import { Chevron, Picker, type PickOption } from "./Picker";
import { ValueLabelsEditor } from "./ValueLabelsEditor";

interface Props {
  variables: Variable[];
  editedVars: Set<string>;
  newVars: Set<string>;
  focusVar: string | null;
  onFocusVar: (name: string | null) => void;
  onPatch: (name: string, patch: Record<string, unknown>, before: Record<string, unknown>) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
  onAdd: () => void;
  // AI suggestions (staged; nothing is saved until accepted)
  suggestions: Map<string, Suggestion>;
  enriching: Set<string>; // "name|kind" keys of in-flight requests
  aiAvailable: boolean;
  onEnrich: (names: string[], kinds: EnrichKind[]) => void;
  onAccept: (name: string, kind: EnrichKind) => void;
  onReject: (name: string, kind: EnrichKind) => void;
  onAcceptAll: () => void;
  onRejectAll: () => void;
}

type Filter = "all" | "edited" | "suggested";

/** The grid's columns and their default widths; every one of them is draggable.
 *  A width the user drags is remembered under this key. */
const COLUMNS: Column[] = [
  { key: "mark", label: "", width: 20 },
  { key: "name", label: "Name", width: 140 },
  { key: "type", label: "Type", width: 104 },
  { key: "width", label: "Width", width: 72 },
  { key: "decimals", label: "Decimals", width: 84 },
  { key: "label", label: "Label", width: 260 },
  { key: "values", label: "Values", width: 180 },
  { key: "missing", label: "Missing", width: 110 },
  { key: "measure", label: "Measure", width: 140 },
  { key: "role", label: "Role", width: 150 },
  { key: "function", label: "Function", width: 160 },
  { key: "unit", label: "Unit", width: 180 },
  { key: "concepts", label: "Concepts", width: 190 },
  { key: "actions", label: "", width: 44 },
];
const COLUMN_STORAGE_KEY = "ddi.metaColumns";

/** The AI button that sits in some of the headers. */
const HEAD_AI: Record<string, { kind: EnrichKind; title: string }> = {
  measure: { kind: "measure", title: "Suggest the level of measurement (nominal, ordinal, scale) for all variables" },
  role: { kind: "role", title: "Suggest roles for all variables" },
  function: { kind: "function", title: "Suggest variable functions (weight, identifier, dimension …) for all variables" },
  unit: { kind: "unit", title: "Suggest units of measure for all variables" },
  concepts: { kind: "concept", title: "Suggest ELSST concepts for all variables" },
};

function AiButton({ title, busy, disabled, onClick }: { title: string; busy: boolean; disabled: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`iconbtn ai ${busy ? "busy" : ""}`} title={disabled ? "AI enrichment is not configured (DDI_N8N_BEARER_KEY)" : title} aria-label={title} disabled={disabled || busy} onClick={onClick}>
      ✦
    </button>
  );
}

function Ghost({ text, title, onAccept, onReject }: { text: string; title: string; onAccept: () => void; onReject: () => void }) {
  return (
    <span className="suggest" title={title}>
      <span className="txt">✦ {text}</span>
      <button type="button" className="iconbtn ok" aria-label="Accept suggestion" title="Accept" onClick={onAccept}>✓</button>
      <button type="button" className="iconbtn no" aria-label="Reject suggestion" title="Reject" onClick={onReject}><IconX size={12} /></button>
    </span>
  );
}

const MEASURE_HINTS: Record<string, string> = {
  nominal: "Categories without an order",
  ordinal: "Ordered categories",
  scale: "Numbers with meaningful distances",
  unknown: "Not determined",
};
const MEASURE_PICKS: PickOption[] = MEASURE_OPTIONS.map((m) => ({ value: m, label: m, text: m, hint: MEASURE_HINTS[m] }));

const ROLE_PICKS: PickOption[] = [
  { value: "measure", label: "Measure", text: "Measure", hint: "The observed value; the default" },
  { value: "identifier", label: "Identifier", text: "Identifier", hint: "Joins the PrimaryKey; must be unique across rows" },
  { value: "attribute", label: "Attribute", text: "Attribute", hint: "Qualifies the measures, e.g. a flag or status" },
];

const FUNCTION_PICKS: PickOption[] = FUNCTION_OPTIONS.map((f) => ({
  value: f.name,
  label: f.label,
  text: f.label,
  hint: f.hint,
}));

const UNIT_PICKS: PickOption[] = [
  { value: "", label: <span className="faint">none</span>, text: "none" },
  ...UNIT_OPTIONS.map((u) => ({
    value: unitUri(u.code),
    label: <><b className="unit-sym">{u.alt}</b> {u.label}</>,
    text: `${u.alt} ${u.label} ${u.code}`,
  })),
];

function functionPicks(current: string[]): PickOption[] {
  const extra = current.filter((f) => !FUNCTION_OPTIONS.some((o) => o.name === f));
  return [...FUNCTION_PICKS, ...extra.map((f) => ({ value: f, label: functionLabel(f), text: functionLabel(f), hint: "Not in the standard vocabulary" }))];
}

function parseMissing(text: string): { lo: string; hi: string }[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((part) => {
      const m = /^(.+?)\s*(?:-|–|\.\.|to)\s*(.+)$/.exec(part);
      if (m && !/^-?\d+(\.\d+)?$/.test(part)) return { lo: m[1].trim(), hi: m[2].trim() };
      return { lo: part, hi: part };
    });
}

/** Split a native format string (SPSS F8.2 / A14 / DATE12, Stata %9.0g / %12s, SAS BEST12.) into its parts. */
interface FormatParts { prefix: string; width: number; decimals: number | null; bareDot: boolean; suffix: string }

export function splitFormat(format: string): FormatParts | null {
  const m = /^([^\d]*?)(\d+)(?:\.(\d*))?([a-zA-Z]*)$/.exec(format.trim());
  if (!m) return null;
  // SAS writes "BEST12." with a bare dot; keep it so rejoining is lossless
  const bareDot = m[3] === "";
  return { prefix: m[1], width: Number(m[2]), decimals: m[3] === undefined || bareDot ? null : Number(m[3]), bareDot, suffix: m[4] };
}

export function joinFormat(parts: FormatParts): string {
  const dec = parts.decimals === null ? (parts.bareDot ? "." : "") : `.${parts.decimals}`;
  return `${parts.prefix}${parts.width}${dec}${parts.suffix}`;
}

function missingText(v: Variable): string {
  return v.missing.map((r) => (r.lo === r.hi ? r.lo : `${r.lo} – ${r.hi}`)).join(", ");
}

export function MetadataTable({
  variables, editedVars, newVars, focusVar, onFocusVar, onPatch, onDelete, onAdd,
  suggestions, enriching, aiAvailable, onEnrich, onAccept, onReject, onAcceptAll, onRejectAll,
}: Props) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [labelsFor, setLabelsFor] = useState<string | null>(null);
  const [conceptsFor, setConceptsFor] = useState<string | null>(null);

  const cols = useColumnWidths(COLUMNS, COLUMN_STORAGE_KEY);

  const allNames = useMemo(() => variables.map((v) => v.name), [variables]);
  const busyFor = (name: string, kind: EnrichKind) => enriching.has(`${name}|${kind}`);
  const columnBusy = (kind: EnrichKind) => [...enriching].some((k) => k.endsWith(`|${kind}`));

  const nSuggestions = useMemo(() => {
    let n = 0;
    for (const s of suggestions.values()) n += (s.unit_of_measure !== undefined ? 1 : 0) + (s.concepts !== undefined ? 1 : 0) + (s.role !== undefined ? 1 : 0) + (s.functions !== undefined ? 1 : 0) + (s.measure !== undefined ? 1 : 0);
    return n;
  }, [suggestions]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return variables.filter((v) => {
      if (filter === "edited" && !editedVars.has(v.name) && !newVars.has(v.name)) return false;
      if (filter === "suggested" && !suggestions.has(v.name)) return false;
      if (!q) return true;
      return v.name.toLowerCase().includes(q) || (v.label ?? "").toLowerCase().includes(q);
    });
  }, [variables, query, filter, editedVars, newVars, suggestions]);

  const before = (v: Variable, keys: string[]): Record<string, unknown> => {
    const b: Record<string, unknown> = {};
    for (const k of keys) {
      if (k === "role") b.role = v.default_role;
      else if (k === "missing") b.missing = v.missing.map((r) => ({ lo: r.lo, hi: r.hi }));
      else if (k === "new_name") b.new_name = v.name;
      else if (k === "unit_of_measure") b.unit_of_measure = v.unit_of_measure ?? ""; // "" clears; null would mean untouched
      else if (k === "concepts") b.concepts = v.concepts.map((c) => ({ ...c }));
      else if (k === "functions") b.functions = [...v.functions];
      else b[k] = (v as unknown as Record<string, unknown>)[k];
    }
    return b;
  };

  return (
    <section className="panel meta" aria-label="Metadata">
      <div className="panel-head">
        <h2>Metadata</h2>
        <span className="sub">
          {variables.length} variables
          {editedVars.size + newVars.size > 0 && ` · ${editedVars.size + newVars.size} edited`}
        </span>
        <span className="grow" />
        <label className="search">
          <IconSearch />
          <input type="search" placeholder="Filter variables" aria-label="Filter variables" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <div className="seg" role="group" aria-label="Filter">
          {(["all", "edited", "suggested"] as Filter[]).map((f) => (
            <button key={f} type="button" className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
              {f === "all" ? "All" : f === "edited" ? "Edited" : "✦ Suggested"}
            </button>
          ))}
        </div>
        <button type="button" className="btn add" onClick={onAdd}>
          <IconPlus /> Add variable
        </button>
      </div>
      {nSuggestions > 0 && (
        <div className="suggest-bar" role="status">
          <span>✦ {nSuggestions} AI {nSuggestions === 1 ? "suggestion" : "suggestions"} for {suggestions.size} {suggestions.size === 1 ? "variable" : "variables"} · review and accept per cell, or</span>
          <button type="button" className="btn primary" onClick={onAcceptAll}>Accept all</button>
          <button type="button" className="btn" onClick={onRejectAll}>Dismiss all</button>
          <span className="grow" />
          <span className="muted">Nothing is saved until accepted · accepting all is one undo step</span>
        </div>
      )}
      <div className="panel-body">
        <table className="grid cols" style={{ minWidth: cols.total }}>
          <colgroup>
            {COLUMNS.map((c) => (
              <col key={c.key} style={{ width: cols.widths[c.key] }} />
            ))}
            <col />
          </colgroup>
          <thead>
            <tr>
              {COLUMNS.map((c) => {
                const ai = HEAD_AI[c.key];
                return (
                  <th key={c.key} className={c.key === "mark" ? "mark" : undefined}>
                    <span className="th-in">
                      {c.label}
                      {ai && (
                        <AiButton
                          title={ai.title}
                          busy={columnBusy(ai.kind)}
                          disabled={!aiAvailable}
                          onClick={() => onEnrich(allNames, [ai.kind])}
                        />
                      )}
                    </span>
                    <ColumnHandle
                      column={c}
                      active={cols.dragging === c.key}
                      onStart={cols.startResize}
                      onNudge={cols.nudge}
                      onReset={cols.reset}
                    />
                  </th>
                );
              })}
              <th />
            </tr>
          </thead>
          <tbody>
            {shown.map((v) => {
              const isNew = newVars.has(v.name);
              const isEdited = !isNew && editedVars.has(v.name);
              const nLabels = Object.keys(v.value_labels).length;
              const firstLabels = Object.entries(v.value_labels).slice(0, 2).map(([c, l]) => `${c} = ${l}`).join(", ");
              const sug = suggestions.get(v.name);
              const nConcepts = v.concepts.length;
              const firstConcepts = v.concepts.slice(0, 2).map((c) => c.pref_label || c.uri.split("/").pop()).join(", ");
              const fmt = splitFormat(v.format);
              return (
                <tr
                  key={v.name}
                  className={`${isNew ? "fresh" : isEdited ? "edited" : ""}`}
                  onClick={() => onFocusVar(focusVar === v.name ? null : v.name)}
                  style={focusVar === v.name ? { outline: "2px solid #6366f1", outlineOffset: -2 } : undefined}
                >
                  <td className="mark">
                    {isNew && <span className="dot" style={{ background: "#14b8a6" }} title="New variable" />}
                    {isEdited && <span className="dot" style={{ background: "#f59e0b" }} title="Edited" />}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="row" style={{ gap: 0, minWidth: 0 }}>
                      <EditableCell
                        mono
                        value={v.name}
                        title="Double-click to rename"
                        onCommit={(next) => onPatch(v.name, { new_name: next }, before(v, ["new_name"]))}
                        render={(val) => <strong style={{ fontWeight: 500 }}>{val}</strong>}
                      />
                      {isNew && <span className="badge-new">NEW</span>}
                    </div>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <Picker
                      title="Type"
                      ariaLabel={`Type of ${v.name}`}
                      options={(TYPE_OPTIONS.includes(v.type) ? TYPE_OPTIONS : [v.type, ...TYPE_OPTIONS]).map((t) => ({ value: t, label: t, text: t }))}
                      value={v.type}
                      width={200}
                      trigger={v.type}
                      onChange={(type) => onPatch(v.name, { type }, before(v, ["type"]))}
                    />
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {fmt ? (
                      <EditableCell
                        mono
                        value={String(fmt.width)}
                        width={44}
                        title={`Width · native format ${v.format}`}
                        onCommit={(next) => {
                          const w = Number.parseInt(next, 10);
                          if (!Number.isFinite(w) || w < 1) return Promise.resolve();
                          // SPSS rule: decimals must be smaller than the width; the server rejects it with the message shown as a toast
                          return onPatch(v.name, { format: joinFormat({ ...fmt, width: w }) }, before(v, ["format"]));
                        }}
                      />
                    ) : (
                      <EditableCell mono value={v.format} title="Native format (not parseable into width / decimals)" onCommit={(next) => onPatch(v.name, { format: next }, before(v, ["format"]))} />
                    )}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {fmt && !typeHasDecimals(v.type) ? (
                      <span className="cell mono" style={{ color: "var(--muted)", cursor: "default" }} title={`Decimals · a ${v.type} variable has none`}>0</span>
                    ) : fmt ? (
                      <EditableCell
                        mono
                        value={String(fmt.decimals ?? 0)}
                        width={44}
                        title={fmt.decimals === null ? `Decimals · format ${v.format} has none` : `Decimals · native format ${v.format}`}
                        render={(val) => <span style={fmt.decimals === null ? { color: "var(--muted)" } : undefined}>{val}</span>}
                        onCommit={(next) => {
                          const d = Number.parseInt(next, 10);
                          if (!Number.isFinite(d) || d < 0) return Promise.resolve();
                          if (fmt.decimals === null && d === 0) return Promise.resolve();
                          return onPatch(v.name, { format: joinFormat({ ...fmt, decimals: d, bareDot: false }) }, before(v, ["format"]));
                        }}
                      />
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <EditableCell
                      value={v.label ?? ""}
                      placeholder="no label"
                      title={v.label ?? "Double-click to edit"}
                      onCommit={(next) => onPatch(v.name, { label: next }, before(v, ["label"]))}
                    />
                  </td>
                  <td onClick={(e) => e.stopPropagation()} style={{ position: "relative" }}>
                    <button type="button" className={`pick-btn ${labelsFor === v.name ? "open" : ""}`} aria-label={`Value labels of ${v.name}`} title={firstLabels || "Add value labels"} onClick={() => setLabelsFor(labelsFor === v.name ? null : v.name)}>
                      <span className="pick-val">
                        {nLabels === 0 ? <span className="faint">none</span> : <>{nLabels} {nLabels === 1 ? "label" : "labels"} <span className="faint">· {firstLabels}{nLabels > 2 ? " …" : ""}</span></>}
                      </span>
                      <Chevron />
                    </button>
                    {labelsFor === v.name && (
                      <ValueLabelsEditor
                        labels={v.value_labels}
                        numeric={v.numeric}
                        onClose={() => setLabelsFor(null)}
                        onSave={(labels) => onPatch(v.name, { value_labels: labels }, before(v, ["value_labels"]))}
                      />
                    )}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <EditableCell
                      mono
                      value={missingText(v)}
                      placeholder="—"
                      title="Codes or ranges, e.g. 77, 88, 99 or 900 – 999"
                      render={(val) => <span style={{ color: val ? "#b45309" : undefined }}>{val || "—"}</span>}
                      onCommit={(next) => onPatch(v.name, { missing: parseMissing(next) }, before(v, ["missing"]))}
                    />
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="col" style={{ gap: 3, alignItems: "flex-start" }}>
                      <div className="row ai-row">
                        <Picker
                          title="Level of measurement"
                          ariaLabel={`Measure of ${v.name}`}
                          options={MEASURE_PICKS}
                          value={v.measure}
                          width={260}
                          trigger={v.measure}
                          onChange={(measure) => onPatch(v.name, { measure }, before(v, ["measure"]))}
                        />
                        <AiButton title={`Suggest the level of measurement for ${v.name}`} busy={busyFor(v.name, "measure")} disabled={!aiAvailable} onClick={() => onEnrich([v.name], ["measure"])} />
                      </div>
                      {sug && sug.measure !== undefined && (
                        <Ghost
                          text={sug.measure}
                          title={`Suggested measure: ${sug.measure} (currently ${v.measure})`}
                          onAccept={() => onAccept(v.name, "measure")}
                          onReject={() => onReject(v.name, "measure")}
                        />
                      )}
                    </div>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="col" style={{ gap: 3, alignItems: "flex-start" }}>
                      <div className="row ai-row">
                        <Picker
                          multiple
                          minSelected={1}
                          title="Role"
                          subtitle="one or more"
                          ariaLabel={`Role of ${v.name}`}
                          options={ROLE_PICKS}
                          value={v.default_role.split(",")}
                          width={300}
                          triggerTitle={roleLabel(v.default_role)}
                          trigger={roleLabel(v.default_role)}
                          onChange={(roles) => onPatch(v.name, { role: roles.join(",") }, before(v, ["role"]))}
                        />
                        <AiButton title={`Suggest a role for ${v.name}`} busy={busyFor(v.name, "role")} disabled={!aiAvailable} onClick={() => onEnrich([v.name], ["role"])} />
                      </div>
                      {sug && sug.role !== undefined && (
                        <Ghost
                          text={roleLabel(sug.role)}
                          title={`Suggested role: ${roleLabel(sug.role)} (currently ${roleLabel(v.default_role)})`}
                          onAccept={() => onAccept(v.name, "role")}
                          onReject={() => onReject(v.name, "role")}
                        />
                      )}
                    </div>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="col" style={{ gap: 3, alignItems: "flex-start" }}>
                      <div className="row ai-row">
                        <Picker
                          multiple
                          title="Variable function"
                          subtitle="what the variable is, not what it measures"
                          ariaLabel={`Functions of ${v.name}`}
                          options={functionPicks(v.functions)}
                          value={v.functions}
                          width={400}
                          footer="Leave all unticked for a plain measured value · each tick is saved at once"
                          triggerTitle={v.functions.length ? `Functions: ${v.functions.map(functionLabel).join(", ")}` : "No variable function (a plain measured value)"}
                          trigger={v.functions.length === 0 ? <span className="faint">none</span> : v.functions.map(functionLabel).join(", ")}
                          onChange={(functions) => onPatch(v.name, { functions }, before(v, ["functions"]))}
                        />
                        <AiButton title={`Suggest variable functions for ${v.name}`} busy={busyFor(v.name, "function")} disabled={!aiAvailable} onClick={() => onEnrich([v.name], ["function"])} />
                      </div>
                      {sug && sug.functions !== undefined && (
                        <Ghost
                          text={sug.functions.length ? sug.functions.map(functionLabel).join(", ") : "no function"}
                          title={sug.functions.length ? `Suggested functions (replace current): ${sug.functions.join(", ")}` : "Suggested: no variable function applies (plain measured value)"}
                          onAccept={() => onAccept(v.name, "function")}
                          onReject={() => onReject(v.name, "function")}
                        />
                      )}
                    </div>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="col" style={{ gap: 3, alignItems: "flex-start" }}>
                      <div className="row ai-row">
                        <Picker
                          title="Unit of measure"
                          subtitle="EU unit table"
                          ariaLabel={`Unit of measure of ${v.name}`}
                          options={v.unit_of_measure && !isKnownUnit(v.unit_of_measure)
                            ? [UNIT_PICKS[0], { value: v.unit_of_measure, label: unitLabel(v.unit_of_measure), text: v.unit_of_measure, hint: "Not in the table" }, ...UNIT_PICKS.slice(1)]
                            : UNIT_PICKS}
                          value={v.unit_of_measure ?? ""}
                          width={300}
                          triggerTitle={v.unit_of_measure ?? "No unit of measure"}
                          trigger={v.unit_of_measure ? unitLabel(v.unit_of_measure) : <span className="faint">none</span>}
                          onChange={(unit) => onPatch(v.name, { unit_of_measure: unit }, before(v, ["unit_of_measure"]))}
                        />
                        <AiButton title={`Suggest a unit of measure for ${v.name}`} busy={busyFor(v.name, "unit")} disabled={!aiAvailable} onClick={() => onEnrich([v.name], ["unit"])} />
                      </div>
                      {sug && sug.unit_of_measure !== undefined && (
                        <Ghost
                          text={sug.unit_of_measure ? unitLabel(sug.unit_of_measure) : "no unit"}
                          title={sug.unit_of_measure ? `Suggested: ${sug.unit_of_measure}` : "Suggested: no unit of measure applies"}
                          onAccept={() => onAccept(v.name, "unit")}
                          onReject={() => onReject(v.name, "unit")}
                        />
                      )}
                    </div>
                  </td>
                  <td onClick={(e) => e.stopPropagation()} style={{ position: "relative" }}>
                    <div className="col" style={{ gap: 3, alignItems: "flex-start" }}>
                      <div className="row ai-row">
                        <button type="button" className={`pick-btn ${conceptsFor === v.name ? "open" : ""}`} aria-label={`Concepts of ${v.name}`} title={v.concepts.map((c) => c.uri).join("\n") || "Add concepts"} onClick={() => setConceptsFor(conceptsFor === v.name ? null : v.name)}>
                          <span className="pick-val">
                            {nConcepts === 0 ? <span className="faint">none</span> : <>{nConcepts} {nConcepts === 1 ? "concept" : "concepts"} <span className="faint">· {firstConcepts}{nConcepts > 2 ? " …" : ""}</span></>}
                          </span>
                          <Chevron />
                        </button>
                        <AiButton title={`Suggest ELSST concepts for ${v.name}`} busy={busyFor(v.name, "concept")} disabled={!aiAvailable} onClick={() => onEnrich([v.name], ["concept"])} />
                      </div>
                      {sug && sug.concepts !== undefined && (
                        <Ghost
                          text={sug.concepts.length ? sug.concepts.map((c) => c.pref_label || c.uri.split("/").pop()).join(", ") : "no concepts"}
                          title={sug.concepts.length ? `Suggested (added to existing):\n${sug.concepts.map((c) => c.uri).join("\n")}` : "Suggested: no matching ELSST concept"}
                          onAccept={() => onAccept(v.name, "concept")}
                          onReject={() => onReject(v.name, "concept")}
                        />
                      )}
                    </div>
                    {conceptsFor === v.name && (
                      <ConceptsEditor
                        concepts={v.concepts}
                        onClose={() => setConceptsFor(null)}
                        onSave={(concepts) => onPatch(v.name, { concepts }, before(v, ["concepts"]))}
                      />
                    )}
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <button type="button" className="iconbtn" aria-label={`Remove variable ${v.name}`} title="Remove variable" onClick={() => void onDelete(v.name)}>
                      <IconTrash />
                    </button>
                  </td>
                  <td />
                </tr>
              );
            })}
            {shown.length === 0 && (
              <tr><td colSpan={COLUMNS.length + 1} className="muted" style={{ textAlign: "center", height: 80 }}>No variables match.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="panel-foot">
        <span>Showing {shown.length} of {variables.length}</span>
        <span className="legend"><span className="dot" style={{ background: "#f59e0b" }} /> edited</span>
        <span className="legend"><span className="dot" style={{ background: "#14b8a6" }} /> new</span>
        <span className="legend" style={{ color: "var(--accent-ink)" }}>✦ AI suggestion</span>
        <span className="grow" />
        {cols.resized && (
          <button type="button" className="linkbtn" onClick={cols.resetAll}>Reset column widths</button>
        )}
        <span>Double-click a cell to edit · Enter commits · Esc cancels · drag a column edge to widen it</span>
      </div>
    </section>
  );
}
