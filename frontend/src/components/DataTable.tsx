import type { PreviewPage, Variable } from "../types";
import { EditableCell } from "./EditableCell";
import { IconChevron, IconPlus, IconTrash } from "./Icons";

interface Props {
  page: PreviewPage | null;
  variables: Variable[];
  pageSize: number;
  onPageSize: (n: number) => void;
  onOffset: (n: number) => void;
  showLabels: boolean;
  onShowLabels: (b: boolean) => void;
  editedCells: Set<string>;
  editedVars: Set<string>;
  newVars: Set<string>;
  maxRowsInOutput: number | "all";
  onEditCell: (rowIndex: number, name: string, next: string, prev: string) => Promise<void>;
  onAddRow: () => Promise<void>;
  onDeleteRow: (rowIndex: number) => Promise<void>;
  loading: boolean;
}

export function DataTable(p: Props) {
  const { page, variables } = p;
  const byName = new Map(variables.map((v) => [v.name, v]));
  const total = page?.total_rows ?? 0;
  const offset = page?.offset ?? 0;
  const end = Math.min(offset + (page?.rows.length ?? 0), total);

  const isMissing = (v: Variable | undefined, cell: string): boolean => {
    if (!v || cell === "") return false;
    return v.missing.some((r) => {
      if (v.numeric) {
        const x = Number(cell);
        if (Number.isNaN(x)) return false;
        const lo = r.lo === "-inf" ? -Infinity : Number(r.lo);
        const hi = r.hi === "inf" ? Infinity : Number(r.hi);
        return x >= lo && x <= hi;
      }
      return r.lo <= cell && cell <= r.hi;
    });
  };

  return (
    <section className="panel data" aria-label="Data">
      <div className="panel-head">
        <h2>Data</h2>
        <span className="sub">
          {total.toLocaleString()} rows ·{" "}
          {p.maxRowsInOutput === "all" ? "all rows included in the output" : p.maxRowsInOutput === 0 ? "no data rows in the output" : `first ${p.maxRowsInOutput} rows included in the output`}
        </span>
        <span className="grow" />
        <label className="check">
          <input type="checkbox" checked={p.showLabels} onChange={(e) => p.onShowLabels(e.target.checked)} /> Show value labels
        </label>
        <div className="row" style={{ gap: 6 }}>
          <span style={{ color: "#374151" }}>Rows</span>
          <div className="seg" role="group" aria-label="Rows per page">
            {[5, 25, 100].map((n) => (
              <button key={n} type="button" className={p.pageSize === n ? "on" : ""} onClick={() => p.onPageSize(n)}>{n}</button>
            ))}
          </div>
          <button type="button" className="btn" disabled={offset === 0} aria-label="Previous page" onClick={() => p.onOffset(Math.max(0, offset - p.pageSize))} style={{ padding: "0 8px" }}>
            <IconChevron style={{ transform: "rotate(90deg)" }} />
          </button>
          <span className="muted mono" style={{ fontSize: 12, minWidth: 110, textAlign: "center" }}>
            {total === 0 ? "0" : `${offset + 1}–${end}`} / {total.toLocaleString()}
          </span>
          <button type="button" className="btn" disabled={end >= total} aria-label="Next page" onClick={() => p.onOffset(offset + p.pageSize)} style={{ padding: "0 8px" }}>
            <IconChevron style={{ transform: "rotate(-90deg)" }} />
          </button>
        </div>
        <button type="button" className="btn" onClick={() => void p.onAddRow()}>
          <IconPlus /> Add row
        </button>
      </div>
      <div className="panel-body" style={{ opacity: p.loading ? 0.6 : 1 }}>
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 44 }}>#</th>
              {(page?.columns ?? variables.map((v) => v.name)).map((c) => (
                <th key={c} className={`var ${p.newVars.has(c) ? "fresh" : p.editedVars.has(c) ? "edited" : ""}`} title={byName.get(c)?.label ?? c}>{c}</th>
              ))}
              <th style={{ width: 32 }} />
            </tr>
          </thead>
          <tbody>
            {(page?.rows ?? []).map((row, i) => {
              const rowIndex = offset + i;
              return (
                <tr key={rowIndex}>
                  <td className="num">{rowIndex}</td>
                  {row.map((cell, j) => {
                    const name = page!.columns[j];
                    const v = byName.get(name);
                    const sentinel = isMissing(v, cell);
                    const label = v?.value_labels[cell];
                    const key = `${rowIndex}:${name}`;
                    const edited = p.editedCells.has(key);
                    return (
                      <td key={name} style={edited ? { background: "#fffbeb" } : undefined}>
                        <EditableCell
                          mono
                          value={cell}
                          placeholder="empty"
                          suggestions={v ? Object.entries(v.value_labels).map(([code, l]) => ({ code, label: l, sentinel: isMissing(v, code) })) : undefined}
                          onCommit={(next) => p.onEditCell(rowIndex, name, next, cell)}
                          render={(val) =>
                            val === "" ? (
                              <span className="faint" style={{ fontFamily: "var(--font)", border: "1px dashed #d1d5db", borderRadius: 4, padding: "1px 6px", fontSize: 12 }}>empty</span>
                            ) : sentinel ? (
                              <span className="val-tag">{val}<small>sentinel{label ? ` · ${label}` : ""}</small></span>
                            ) : (
                              <>
                                {val}
                                {p.showLabels && label && <span className="hint-label">{label}</span>}
                              </>
                            )
                          }
                        />
                      </td>
                    );
                  })}
                  <td>
                    <button type="button" className="iconbtn" aria-label={`Delete row ${rowIndex}`} title="Delete row" onClick={() => void p.onDeleteRow(rowIndex)}>
                      <IconTrash size={13} />
                    </button>
                  </td>
                </tr>
              );
            })}
            {page && page.rows.length === 0 && (
              <tr><td colSpan={(page.columns.length || 1) + 2} className="muted" style={{ textAlign: "center", height: 80 }}>No rows.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
