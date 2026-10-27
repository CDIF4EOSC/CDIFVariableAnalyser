import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { IconSearch, IconX } from "./Icons";

export interface PickOption {
  value: string;
  label: ReactNode;
  /** Plain text the search box matches against (and the accessible name). */
  text: string;
  hint?: string;
}

interface Common {
  title: string;
  subtitle?: string;
  options: PickOption[];
  /** The cell content shown on the trigger button. */
  trigger: ReactNode;
  triggerClass?: string;
  triggerTitle?: string;
  ariaLabel: string;
  /** A search box above the list; on by default for long lists. */
  searchable?: boolean;
  footer?: string;
  width?: number;
}

interface Single extends Common {
  multiple?: false;
  value: string;
  onChange: (value: string) => void | Promise<void>;
}

interface Multi extends Common {
  multiple: true;
  value: string[];
  /** At least this many must stay ticked (role: 1). */
  minSelected?: number;
  onChange: (value: string[]) => void | Promise<void>;
}

type Props = Single | Multi;

const PANEL_MAX_HEIGHT = 360;

/** The chevron every cell button ends with, pickers and the free-form editors alike. */
export const Chevron = () => (
  <svg className="pick-chev" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="m6 9 6 6 6-6" /></svg>
);

const Check = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12 5 5 9-10" /></svg>
);

/** The one picker every vocabulary cell uses (type, measure, role, function, unit).
 *  A choice applies at once: a single-choice list closes on pick, a multi-choice list stays open
 *  and saves each tick. Nothing to confirm, Esc or a click outside closes. */
export function Picker(props: Props) {
  const { title, subtitle, options, trigger, triggerClass, triggerTitle, ariaLabel, footer, width = 300 } = props;
  const searchable = props.searchable ?? options.length > 10;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [pos, setPos] = useState<{ top: number; left: number; maxHeight: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);

  // multi-choice ticks are kept locally so fast clicks build on each other, and sent in order
  const [ticked, setTicked] = useState<string[]>(props.multiple ? props.value : []);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const committed = props.multiple ? props.value.join(",") : "";
  useEffect(() => {
    if (props.multiple && !open) setTicked(props.value);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [committed, open]);

  const isOn = (v: string) => (props.multiple ? ticked.includes(v) : props.value === v);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => o.text.toLowerCase().includes(q) || o.value.toLowerCase().includes(q));
  }, [options, query]);

  const close = (refocus = true) => {
    setOpen(false);
    setPos(null);
    setQuery("");
    if (refocus) btn.current?.focus();
  };

  const place = () => {
    const r = btn.current?.getBoundingClientRect();
    if (!r) return;
    const below = window.innerHeight - r.bottom - 12;
    const above = r.top - 12;
    const up = below < 240 && above > below;
    const maxHeight = Math.min(PANEL_MAX_HEIGHT, up ? above : below);
    const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
    setPos({ top: up ? r.top - 4 - maxHeight : r.bottom + 4, left, maxHeight });
  };

  useLayoutEffect(() => {
    if (!open) return;
    place();
    const cur = options.findIndex((o) => isOn(o.value));
    setCursor(cur >= 0 ? cur : 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const placed = pos !== null;
  useEffect(() => {
    if (open && placed) (searchable ? search.current : list.current)?.focus();
  }, [open, placed, searchable]);

  useEffect(() => {
    if (!open) return;
    // on the document, so the keys work wherever the focus is while the panel is open
    const onDocKey = (e: KeyboardEvent) => keyRef.current(e);
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!box.current?.contains(t) && !btn.current?.contains(t)) close(false);
    };
    // the panel is fixed, so a scrolling grid would leave it behind
    const onScroll = (e: Event) => {
      if (!box.current?.contains(e.target as Node)) close(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onDocKey);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", place);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onDocKey);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", place);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    list.current?.querySelector(`[data-i="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const pick = (value: string) => {
    if (props.multiple) {
      const min = props.minSelected ?? 0;
      if (ticked.includes(value) && ticked.length <= min) return;
      const set = new Set(ticked.includes(value) ? ticked.filter((x) => x !== value) : [...ticked, value]);
      // keep the vocabulary order, then names we do not know
      const next = [...options.map((o) => o.value).filter((v) => set.has(v)), ...ticked.filter((v) => set.has(v) && !options.some((o) => o.value === v))];
      setTicked(next);
      const onChange = props.onChange;
      queue.current = queue.current.then(() => onChange(next)).catch(() => undefined);
    } else {
      if (value !== props.value) void props.onChange(value);
      close();
    }
  };

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(shown.length - 1, c + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if ((e.key === "Enter" || (e.key === " " && e.target !== search.current)) && !(e.target instanceof HTMLButtonElement)) {
      e.preventDefault();
      const o = shown[cursor];
      if (o) pick(o.value);
    }
  };

  const keyRef = useRef(onKey);
  keyRef.current = onKey;

  const minLeft = props.multiple ? props.minSelected ?? 0 : 0;
  const footText = footer ?? (props.multiple ? "Each tick is saved at once · Esc closes" : undefined);

  return (
    <>
      <button
        ref={btn}
        type="button"
        className={`pick-btn ${triggerClass ?? ""} ${open ? "open" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        title={triggerTitle}
        onClick={() => (open ? close() : setOpen(true))}
        onKeyDown={(e) => {
          if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span className="pick-val">{trigger}</span>
        <Chevron />
      </button>
      {open && pos && (
        <div
          ref={box}
          className="picker"
          role="dialog"
          aria-label={title}
          style={{ top: pos.top, left: pos.left, width, maxHeight: pos.maxHeight }}
        >
          <div className="picker-head">
            <h3>{title}</h3>
            {subtitle && <span className="sub">{subtitle}</span>}
            <span className="grow" />
            <button type="button" className="iconbtn" aria-label="Close" onClick={() => close()}><IconX size={12} /></button>
          </div>
          {searchable && (
            <label className="picker-search">
              <IconSearch size={12} />
              <input
                ref={search}
                value={query}
                placeholder="Search"
                aria-label={`Search ${title.toLowerCase()}`}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setCursor(0);
                }}
              />
            </label>
          )}
          <div ref={list} className="picker-list" role="listbox" aria-multiselectable={props.multiple || undefined} tabIndex={-1}>
            {shown.map((o, i) => {
              const on = isOn(o.value);
              const locked = props.multiple && on && ticked.length <= minLeft;
              return (
                <div
                  key={o.value}
                  data-i={i}
                  role="option"
                  aria-selected={on}
                  aria-disabled={locked || undefined}
                  title={locked ? "At least one must stay selected" : undefined}
                  className={`picker-opt ${on ? "on" : ""} ${i === cursor ? "cur" : ""} ${locked ? "locked" : ""}`}
                  onMouseEnter={() => setCursor(i)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => pick(o.value)}
                >
                  <span className="mark" aria-hidden>{on && <Check />}</span>
                  <span className="txt">
                    <span className="name">{o.label}</span>
                    {o.hint && <span className="hint">{o.hint}</span>}
                  </span>
                </div>
              );
            })}
            {shown.length === 0 && <div className="picker-empty">No match</div>}
          </div>
          {footText && <div className="picker-foot">{footText}</div>}
        </div>
      )}
    </>
  );
}
