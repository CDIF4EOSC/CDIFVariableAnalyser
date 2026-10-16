import { useMemo, useState } from "react";
import type { Variable } from "../types";
import { MEASURE_OPTIONS, TYPE_OPTIONS, typeHasDecimals } from "../types";
import { IconPlus, IconX } from "./Icons";
import { UNIT_OPTIONS, unitUri } from "../units";

interface Props {
  variables: Variable[];
  rowsInOutput: number;
  onClose: () => void;
  onAdd: (spec: Record<string, unknown>, keepOpen: boolean) => Promise<boolean>;
}

const NUMERIC = new Set(["double", "float", "int8", "int16", "int32", "numeric"]);
const NAME_RE = /^[A-Za-z_][A-Za-z0-9_.@#$]*$/;

export function AddVariableDrawer({ variables, rowsInOutput, onClose, onAdd }: Props) {
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [width, setWidth] = useState("8");
  const [decimals, setDecimals] = useState("2");
  const [type, setType] = useState("string");
  const [measure, setMeasure] = useState("nominal");
  const [roles, setRoles] = useState<Set<string>>(new Set(["measure"]));
  const [labels, setLabels] = useState<{ code: string; label: string }[]>([{ code: "", label: "" }]);
  const [missing, setMissing] = useState("");
  const [unit, setUnit] = useState("");
  const [fill, setFill] = useState<"empty" | "constant" | "copy">("empty");
  const [fillValue, setFillValue] = useState("");
  const [busy, setBusy] = useState(false);

  const numeric = NUMERIC.has(type);
  const hasDecimals = typeHasDecimals(type);
  const w = Math.max(1, Number.parseInt(width, 10) || 8);
  const d = hasDecimals ? Math.max(0, Number.parseInt(decimals, 10) || 0) : 0;
  // composed the way the importer does for SPSS files; this string becomes the PhysicalMapping format
  const format = type === "datetime" ? `DATETIME${w}` : numeric || type === "boolean" ? `F${w}.${d}` : `A${w}`;
  const formatErr = hasDecimals && d >= w ? "The number of decimal places is too large for the field width" : "";
  const nameErr = !name ? "" : !NAME_RE.test(name) ? "Letters, digits and _ . @ # $, starting with a letter" : variables.some((v) => v.name === name) ? "A variable with this name exists" : "";
  const xsd = numeric ? (type.startsWith("int") ? "xsd:int" : "xsd:double") : type === "datetime" ? "xsd:dateTime" : type === "boolean" ? "xsd:boolean" : "xsd:string";
  const nLabels = labels.filter((l) => l.code.trim()).length;

  const willAdd = useMemo(() => {
    const out = [`+ InstanceVariable #instanceVariable-${name || "…"}`];
    for (const r of roles) out.push(`+ ${r.charAt(0).toUpperCase() + r.slice(1)}Component`);
    if (roles.has("identifier")) out.push("+ PrimaryKeyComponent");
    out.push("+ SubstantiveValueDomain" + (nLabels ? ", EnumerationDomain" : ""));
    if (missing.trim()) out.push("+ SentinelValueDomain");
    if (unit) out.push("  with describedUnitOfMeasure");
    if (nLabels) out.push(`+ CodeList with ${nLabels} Code, Category and Notation`);
    if (rowsInOutput > 0) out.push(`+ LocatorMapping, DataPoint ×${rowsInOutput}, InstanceValue ×${rowsInOutput}`);
    else out.push("+ LocatorMapping");
    return out;
  }, [name, roles, nLabels, missing, unit, rowsInOutput]);

  const toggleRole = (r: string) =>
    setRoles((s) => {
      const n = new Set(s);
      if (n.has(r)) n.delete(r);
      else n.add(r);
      if (n.size === 0) n.add("measure");
      return n;
    });

  const submit = async (keepOpen: boolean) => {
    if (!name || nameErr || formatErr) return;
    setBusy(true);
    const value_labels: Record<string, string> = {};
    for (const l of labels) if (l.code.trim()) value_labels[l.code.trim()] = l.label;
    const spec = {
      name,
      label: label || null,
      format,
      type,
      measure,
      role: [...roles].join(","),
      value_labels,
      missing: missing
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((part) => {
          const m = /^(.+?)\s*(?:-|–|\.\.|to)\s*(.+)$/.exec(part);
          return m && !/^-?\d+(\.\d+)?$/.test(part) ? { lo: m[1].trim(), hi: m[2].trim() } : { lo: part, hi: part };
        }),
      fill,
      fill_value: fillValue,
      unit_of_measure: unit || null,
    };
    const ok = await onAdd(spec, keepOpen);
    setBusy(false);
    if (ok && keepOpen) {
      setName("");
      setLabel("");
      setLabels([{ code: "", label: "" }]);
      setMissing("");
    }
  };

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-label="Add variable">
        <div className="drawer-head">
          <div className="col" style={{ gap: 4, flexGrow: 1 }}>
            <span className="eyebrow">Metadata · new variable</span>
            <h2>Add variable</h2>
            <p>Appears as a new column in the data table and as an InstanceVariable in the output.</p>
          </div>
          <button type="button" className="btn" style={{ width: 32, padding: 0, justifyContent: "center" }} aria-label="Close" onClick={onClose}><IconX /></button>
        </div>
        <div className="drawer-body">
          <div className="grid2">
            <label className="field">
              <span>Name</span>
              <input className={`mono ${nameErr ? "err" : ""}`} value={name} autoFocus onChange={(e) => setName(e.target.value.trim())} placeholder="region" />
              {nameErr ? <span className="errmsg">{nameErr}</span> : <small>{name ? `Becomes #instanceVariable-${name}` : "Unique within the dataset"}</small>}
            </label>
            <div className="row" style={{ gap: 12, alignItems: "flex-start" }}>
              <label className="field" style={{ flex: 1 }}>
                <span>Width</span>
                <input className="mono" type="number" min={1} value={width} onChange={(e) => setWidth(e.target.value)} />
              </label>
              <label className="field" style={{ flex: 1 }}>
                <span>Decimals</span>
                <input className={`mono ${formatErr ? "err" : ""}`} type="number" min={0} max={hasDecimals ? w - 1 : 0} value={hasDecimals ? decimals : "0"} disabled={!hasDecimals} onChange={(e) => setDecimals(e.target.value)} />
                {formatErr ? <span className="errmsg">{formatErr}</span> : <small>Format <span className="mono">{format}</span></small>}
              </label>
            </div>
          </div>
          <label className="field">
            <span>Label</span>
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="NUTS-2 region of interview" />
          </label>
          <div className="grid3">
            <label className="field">
              <span>Type</span>
              <select value={type} onChange={(e) => setType(e.target.value)}>
                {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="field">
              <span>Measure</span>
              <select value={measure} onChange={(e) => setMeasure(e.target.value)}>
                {MEASURE_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </label>
            <div className="field">
              <span>XSD type</span>
              <span className="mono" style={{ height: 38, display: "flex", alignItems: "center", padding: "0 10px", borderRadius: 8, border: "1px solid #e5e7eb", background: "#f9fafb", color: "#6b7280", fontSize: 12 }}>{xsd}</span>
            </div>
          </div>
          <fieldset className="field" style={{ border: "none", padding: 0, margin: 0 }}>
            <span>Role in the WideDataStructure</span>
            <div className="role-boxes">
              {["measure", "identifier", "attribute"].map((r) => (
                <label key={r} className={`role-box ${roles.has(r) ? "on" : ""}`}>
                  <input type="checkbox" checked={roles.has(r)} onChange={() => toggleRole(r)} /> {r.charAt(0).toUpperCase() + r.slice(1)}
                </label>
              ))}
            </div>
            <small>Identifiers join the PrimaryKey and must be unique across rows.</small>
          </fieldset>
          <div className="field">
            <div className="row">
              <span>Value labels</span>
              <span className="grow" />
              <button type="button" className="btn add" style={{ height: 26, fontSize: 12 }} onClick={() => setLabels((l) => [...l, { code: "", label: "" }])}><IconPlus size={12} /> Add label</button>
            </div>
            <div className="vl-grid" style={{ display: "grid" }}>
              <span className="h">Code</span><span className="h">Label</span><span className="h" />
              {labels.map((l, i) => (
                <div key={i} style={{ display: "contents" }}>
                  <input className="mono" value={l.code} placeholder="code" aria-label={`Code ${i + 1}`} onChange={(e) => setLabels((ls) => ls.map((x, j) => (j === i ? { ...x, code: e.target.value } : x)))} />
                  <input value={l.label} placeholder="label" aria-label={`Label ${i + 1}`} onChange={(e) => setLabels((ls) => ls.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
                  <button type="button" className="x" aria-label="Remove label" onClick={() => setLabels((ls) => (ls.length > 1 ? ls.filter((_, j) => j !== i) : [{ code: "", label: "" }]))}><IconX size={12} /></button>
                </div>
              ))}
            </div>
            <small>Creates a CodeList with one Code, Category and Notation per code.</small>
          </div>
          <label className="field">
            <span>Unit of measure</span>
            <select value={unit} onChange={(e) => setUnit(e.target.value)}>
              <option value="">— none —</option>
              {UNIT_OPTIONS.map((u) => <option key={u.code} value={unitUri(u.code)}>{u.alt} · {u.label}</option>)}
            </select>
            <small>EU Publications Office measurement unit, emitted as describedUnitOfMeasure. Concepts can be added in the table afterwards.</small>
          </label>
          <label className="field">
            <span>Missing values</span>
            <input className="mono" value={missing} onChange={(e) => setMissing(e.target.value)} placeholder="e.g. 77, 88, 99 or 900 – 999" />
            <small>Declared as a SentinelValueDomain; cells with these codes reference it.</small>
          </label>
          <div className="field">
            <span>Fill the new column with</span>
            <div className="seg" style={{ height: 36 }}>
              {(["empty", "constant", "copy"] as const).map((f) => (
                <button key={f} type="button" className={fill === f ? "on" : ""} style={{ flexGrow: 1 }} onClick={() => setFill(f)}>
                  {f === "empty" ? "Empty cells" : f === "constant" ? "Constant value" : "Copy of a column"}
                </button>
              ))}
            </div>
            {fill === "constant" && <input className="mono" value={fillValue} onChange={(e) => setFillValue(e.target.value)} placeholder="value written into every row" />}
            {fill === "copy" && (
              <select value={fillValue} onChange={(e) => setFillValue(e.target.value)}>
                <option value="">Choose a column…</option>
                {variables.map((v) => <option key={v.name} value={v.name}>{v.name}</option>)}
              </select>
            )}
          </div>
          <div className="will-add" style={{ marginTop: "auto" }}>
            <span className="eyebrow">Will add to the output</span>
            <div className="mono">{willAdd.map((l, i) => <div key={i}>{l}</div>)}</div>
          </div>
        </div>
        <div className="drawer-foot">
          <button type="button" className="btn lg" onClick={onClose}>Cancel</button>
          <span className="grow" />
          <button type="button" className="btn lg" disabled={busy || !name || !!nameErr || !!formatErr || (fill === "copy" && !fillValue)} onClick={() => void submit(true)}>Add and create another</button>
          <button type="button" className="btn lg primary" disabled={busy || !name || !!nameErr || !!formatErr || (fill === "copy" && !fillValue)} onClick={() => void submit(false)}>Add variable</button>
        </div>
      </aside>
    </div>
  );
}
