import { useEffect, useRef, useState } from "react";
import { FUNCTION_OPTIONS, functionLabel, sameFunctions } from "../types";
import { IconX } from "./Icons";

interface Props {
  functions: string[];
  onSave: (functions: string[]) => void | Promise<void>;
  onClose: () => void;
}

/** Pick zero or more variable functions (DDI-CDI InstanceVariable.function). Most variables have none. */
export function FunctionsEditor({ functions, onSave, onClose }: Props) {
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(functions));
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose]);

  const toggle = (name: string) =>
    setChosen((s) => {
      const n = new Set(s);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      return n;
    });

  // keep the vocabulary order, then any name the API returned that we do not know
  const known = FUNCTION_OPTIONS.map((f) => f.name);
  const extra = functions.filter((f) => !known.includes(f));
  const ordered = [...known.filter((f) => chosen.has(f)), ...extra.filter((f) => chosen.has(f))];
  const dirty = !sameFunctions(ordered, functions);

  const save = () => {
    void onSave(ordered);
    onClose();
  };

  return (
    <div ref={box} className="popover" style={{ top: 36, left: 0, width: 400 }} role="dialog" aria-label="Variable functions">
      <div className="row">
        <h3>Variable function</h3>
        <span className="muted" style={{ fontSize: 12 }}>what the variable is, not what it measures</span>
        <span className="grow" />
        <button type="button" className="iconbtn" aria-label="Close" onClick={onClose}><IconX /></button>
      </div>
      <div className="fn-list">
        {FUNCTION_OPTIONS.map((f) => (
          <label key={f.name} className={`fn-opt ${chosen.has(f.name) ? "on" : ""}`}>
            <input type="checkbox" checked={chosen.has(f.name)} onChange={() => toggle(f.name)} />
            <span className="col" style={{ gap: 2 }}>
              <span className="name">{f.label}</span>
              <span className="hint">{f.hint}</span>
            </span>
          </label>
        ))}
        {extra.map((f) => (
          <label key={f} className={`fn-opt ${chosen.has(f) ? "on" : ""}`}>
            <input type="checkbox" checked={chosen.has(f)} onChange={() => toggle(f)} />
            <span className="col" style={{ gap: 2 }}>
              <span className="name">{functionLabel(f)}</span>
              <span className="hint">Not in the standard vocabulary</span>
            </span>
          </label>
        ))}
      </div>
      <div className="row">
        <span className="muted" style={{ fontSize: 11 }}>Leave all unchecked for a plain measured value.</span>
        <span className="grow" />
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary" disabled={!dirty} onClick={save}>Save</button>
      </div>
    </div>
  );
}
