import { useCallback, useEffect, useMemo, useState } from "react";

export interface Column {
  key: string;
  label: string;
  /** Default width in px; the user's drag overrides it and is remembered per browser. */
  width: number;
}

const MIN_WIDTH = 40;
const NUDGE = 16; // keyboard step

/** Column widths for a `table.grid.cols`, draggable and remembered in localStorage. */
export function useColumnWidths(columns: Column[], storageKey: string) {
  const defaults = useMemo(
    () => Object.fromEntries(columns.map((c) => [c.key, c.width])) as Record<string, number>,
    [columns],
  );

  const [widths, setWidths] = useState<Record<string, number>>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) ?? "{}") as Record<string, unknown>;
      const kept = Object.entries(saved).filter(
        ([k, v]) => k in defaults && typeof v === "number" && Number.isFinite(v) && v >= MIN_WIDTH,
      );
      return { ...defaults, ...Object.fromEntries(kept) } as Record<string, number>;
    } catch {
      return defaults; // private mode, or a stale value from an older layout
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(widths));
    } catch {
      /* storage is optional */
    }
  }, [widths, storageKey]);

  const [dragging, setDragging] = useState<string | null>(null);

  const startResize = useCallback(
    (key: string, fromX: number) => {
      const start = widths[key] ?? defaults[key];
      setDragging(key);
      document.body.classList.add("col-resizing");
      const move = (e: MouseEvent) =>
        setWidths((w) => ({ ...w, [key]: Math.max(MIN_WIDTH, Math.round(start + e.clientX - fromX)) }));
      const stop = () => {
        setDragging(null);
        document.body.classList.remove("col-resizing");
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", stop);
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", stop);
    },
    [widths, defaults],
  );

  const nudge = useCallback(
    (key: string, dx: number) =>
      setWidths((w) => ({ ...w, [key]: Math.max(MIN_WIDTH, (w[key] ?? defaults[key]) + dx) })),
    [defaults],
  );
  const reset = useCallback((key: string) => setWidths((w) => ({ ...w, [key]: defaults[key] })), [defaults]);
  const resetAll = useCallback(() => setWidths(defaults), [defaults]);

  const total = columns.reduce((n, c) => n + (widths[c.key] ?? c.width), 0);
  const resized = columns.some((c) => (widths[c.key] ?? c.width) !== c.width);

  return { widths, total, resized, dragging, startResize, nudge, reset, resetAll };
}

interface HandleProps {
  column: Column;
  active: boolean;
  onStart: (key: string, fromX: number) => void;
  onNudge: (key: string, dx: number) => void;
  onReset: (key: string) => void;
}

/** The grip on the right edge of a header cell. Drag to resize, double-click to reset. */
export function ColumnHandle({ column, active, onStart, onNudge, onReset }: HandleProps) {
  return (
    <span
      className={`col-grip ${active ? "on" : ""}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize the ${column.label || column.key} column`}
      tabIndex={0}
      onMouseDown={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onStart(column.key, e.clientX);
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        onReset(column.key);
      }}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") {
          e.preventDefault();
          onNudge(column.key, NUDGE);
        } else if (e.key === "ArrowLeft") {
          e.preventDefault();
          onNudge(column.key, -NUDGE);
        } else if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onReset(column.key);
        }
      }}
    />
  );
}
