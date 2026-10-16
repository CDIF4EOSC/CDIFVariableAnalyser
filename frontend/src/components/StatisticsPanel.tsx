import { useCallback, useMemo, useState } from "react";
import type { CategoryStats, StatKind, Statistics, Variable, VariableStats } from "../types";
import { STAT_COLUMNS, statLabel, statValue, trimStat } from "../types";
import { IconChevron, IconSearch } from "./Icons";

type Filter = "all" | "numeric" | "categorical" | "text";
type Sort = "count" | "code";

// The overview grid is wide; render at most this many rows before asking.
const ROW_CAP = 200;

interface Props {
  stats: Statistics | null;
  variables: Variable[];
  status: "idle" | "busy" | "error";
  error: string | null;
  weight: string | null;
  onWeight: (name: string | null) => void;
  onRecompute: () => void;
  onLoadCategories: (name: string, limit: number, sort: Sort) => Promise<CategoryStats>;
  focusVar: string | null;
  onFocusVar: (name: string | null) => void;
}

const KIND_LABEL: Record<StatKind, string> = {
  numeric: "Numeric",
  categorical: "Categorical",
  text: "Text",
  empty: "Empty",
};

function num(n: number): string {
  return n.toLocaleString();
}

/** qsv is multimodal-aware and joins several modes with "|". */
function modeDisplay(raw: string | null, labels: Record<string, string>): string | null {
  if (!raw) return null;
  if (raw.startsWith("*")) return null; // *HIGH_CARDINALITY sentinel
  return raw
    .split("|")
    .map((code) => (labels[code] ? `${code} · ${labels[code]}` : code))
    .join(", ");
}

export function StatisticsPanel(p: Props) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [openVar, setOpenVar] = useState<string | null>(null);
  const [cats, setCats] = useState<Map<string, CategoryStats>>(new Map());
  const [catsLoading, setCatsLoading] = useState<Set<string>>(new Set());
  const [catsError, setCatsError] = useState<Map<string, string>>(new Map());
  const [sort, setSort] = useState<Sort>("count");
  const [showAllRows, setShowAllRows] = useState(false);

  const byName = useMemo(() => new Map(p.variables.map((v) => [v.name, v])), [p.variables]);

  const fetchCats = useCallback(
    async (name: string, limit: number, order: Sort) => {
      setCatsLoading((s) => new Set(s).add(name));
      setCatsError((m) => {
        const next = new Map(m);
        next.delete(name);
        return next;
      });
      try {
        const got = await p.onLoadCategories(name, limit, order);
        setCats((m) => new Map(m).set(name, got));
      } catch (e) {
        setCatsError((m) => new Map(m).set(name, e instanceof Error ? e.message : String(e)));
      } finally {
        setCatsLoading((s) => {
          const next = new Set(s);
          next.delete(name);
          return next;
        });
      }
    },
    [p],
  );

  const toggle = (v: VariableStats) => {
    if (openVar === v.name) {
      setOpenVar(null);
      return;
    }
    setOpenVar(v.name);
    p.onFocusVar(v.name);
    if (v.has_categories && !cats.has(v.name)) void fetchCats(v.name, 25, sort);
  };

  const changeSort = (order: Sort) => {
    setSort(order);
    setCats(new Map());
    if (openVar) {
      const v = p.stats?.variables.find((x) => x.name === openVar);
      if (v?.has_categories) void fetchCats(openVar, cats.get(openVar)?.truncated === false ? 10000 : 25, order);
    }
  };

  const shown = useMemo(() => {
    const list = p.stats?.variables ?? [];
    const q = query.trim().toLowerCase();
    return list.filter((v) => {
      // Filter on `kind`, not on `numeric`: a numeric-coded categorical (an age
      // group, an ESS round) is numeric in storage, so `numeric` would put it in
      // both chips. `kind` is exclusive, so the chips partition the list.
      if (filter === "numeric" && v.kind !== "numeric") return false;
      if (filter === "categorical" && v.kind !== "categorical") return false;
      if (filter === "text" && v.kind !== "text" && v.kind !== "empty") return false;
      if (!q) return true;
      return v.name.toLowerCase().includes(q) || (v.label ?? "").toLowerCase().includes(q);
    });
  }, [p.stats, query, filter]);

  const rows = showAllRows ? shown : shown.slice(0, ROW_CAP);

  // The one line of context that stops the numbers from being read wrong.
  const note = (() => {
    if (!p.stats) return null;
    if (p.stats.degraded)
      return "Large file — median, quartiles, mode and distinct counts were skipped to keep the computation streaming.";
    if (!p.stats.excludes_sentinels)
      return "This file still contains its declared missing codes, so means, sums and quartiles include them. The frequency tables mark them.";
    const withSentinels = p.stats.variables.filter((v) => v.sentinel_codes.length > 0 && v.missing_n > 0);
    if (withSentinels.length > 0)
      return `User-missing codes arrive from qsv as empty cells, so they are counted as missing and excluded from the means — they cannot be counted one by one (dathere/qsv#4625).`;
    return null;
  })();

  const nCols = 5 + STAT_COLUMNS.length + 1;

  return (
    <section className="panel stats" aria-label="Statistics">
      <div className="panel-head">
        <h2>Statistics</h2>
        <span className="sub">
          {p.stats
            ? `${p.stats.variables.length} variables · qsv stats · ${p.stats.elapsed_ms} ms`
            : p.status === "busy"
              ? "Computing…"
              : "Not computed yet"}
          {p.stats?.weight && ` · weighted by ${p.stats.weight}`}
        </span>
        <span className="grow" />
        <label className="search">
          <IconSearch />
          <input type="search" placeholder="Filter variables" aria-label="Filter variables" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <div className="seg" role="group" aria-label="Filter by kind">
          {(["all", "numeric", "categorical", "text"] as Filter[]).map((f) => (
            <button key={f} type="button" className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
              {f === "all" ? "All" : f === "text" ? "Text" : f === "numeric" ? "Numeric" : "Categorical"}
            </button>
          ))}
        </div>
        <select
          className="cell-select plain"
          aria-label="Weight variable"
          value={p.weight ?? ""}
          disabled={!p.stats || p.stats.weight_candidates.length === 0}
          title={
            p.stats && p.stats.weight_candidates.length > 0
              ? "Weighted statistics. qsv treats a missing weight as 1.0 and ignores zero or negative weights."
              : 'No weight variable — give one the "Weight" function on the Variables tab first.'
          }
          onChange={(e) => p.onWeight(e.target.value || null)}
        >
          <option value="">Unweighted</option>
          {p.stats?.weight_candidates.map((w) => (
            <option key={w} value={w}>Weighted · {w}</option>
          ))}
        </select>
        <button type="button" className="btn" onClick={p.onRecompute} disabled={p.status === "busy"}>
          {p.status === "busy" ? "Computing…" : "Recompute"}
        </button>
      </div>

      {note && <div className="stats-note" role="status">{note}</div>}

      <div className="panel-body" style={{ opacity: p.status === "busy" ? 0.6 : 1 }}>
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 20, paddingRight: 0 }} />
              <th>Name</th>
              <th>Kind</th>
              <th className="stat-num">Valid</th>
              <th className="stat-num">Missing</th>
              {STAT_COLUMNS.map((s) => (
                <th key={s} className="stat-num">{statLabel(s)}</th>
              ))}
              <th className="stat-num">Distinct</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((v) => {
              const variable = byName.get(v.name);
              const labels = variable?.value_labels ?? {};
              const open = openVar === v.name;
              return [
                <tr
                  key={v.name}
                  className={open ? "open" : ""}
                  onClick={() => toggle(v)}
                  style={p.focusVar === v.name ? { outline: "2px solid #6366f1", outlineOffset: -2 } : undefined}
                >
                  <td style={{ paddingRight: 0 }}>
                    <IconChevron size={12} style={{ transform: open ? "rotate(180deg)" : undefined, opacity: 0.5 }} />
                  </td>
                  <td>
                    <span className="mono">{v.name}</span>
                    {v.label && <span className="hint-label">{v.label}</span>}
                  </td>
                  <td>
                    <span className={`kind-pill ${v.kind}`}>{KIND_LABEL[v.kind]}</span>
                    {v.is_weight && <span className="kind-pill text" title="Weights are excluded from their own statistics">weight</span>}
                  </td>
                  <td className="stat-num">{num(v.valid_n)}</td>
                  <td className={`stat-num ${v.missing_n > 0 ? "sentinel-n" : "muted"}`}>{v.missing_n > 0 ? num(v.missing_n) : "—"}</td>
                  {STAT_COLUMNS.map((s) => {
                    const raw = v.numeric ? statValue(v.stats, s) : null;
                    return (
                      <td key={s} className={`stat-num ${raw === null ? "muted" : ""}`}>
                        {raw === null ? "—" : trimStat(raw)}
                      </td>
                    );
                  })}
                  <td className="stat-num">
                    {v.cardinality_capped ? <span title="Too many distinct values to count exactly">many</span> : v.cardinality !== null ? num(v.cardinality) : <span className="muted">—</span>}
                  </td>
                </tr>,
                open && (
                  <tr className="detail" key={`${v.name}-detail`}>
                    <td colSpan={nCols}>
                      <div className="stat-detail">
                        <div className="stat-freq">
                          {v.has_categories ? (
                            <Frequencies
                              name={v.name}
                              data={cats.get(v.name)}
                              loading={catsLoading.has(v.name)}
                              error={catsError.get(v.name)}
                              sort={sort}
                              onSort={changeSort}
                              onShowAll={() => void fetchCats(v.name, 10000, sort)}
                            />
                          ) : (
                            <p className="muted" style={{ margin: 0 }}>
                              {v.kind === "empty"
                                ? "This column is empty."
                                : v.cardinality !== null && v.cardinality >= v.valid_n
                                  ? `Every value is unique (${num(v.valid_n)} distinct) — no frequency table.`
                                  : "Too many distinct values for a frequency table."}
                            </p>
                          )}
                        </div>
                        <dl className="stat-grid">
                          {v.stats.length === 0 && <span className="muted">No statistics.</span>}
                          {v.stats.map((s) => (
                            <div key={s.name} style={{ display: "contents" }}>
                              <dt className="muted">{statLabel(s.name)}</dt>
                              <dd className="mono" title={s.value}>
                                {s.name === "mode" ? modeDisplay(trimStat(s.value, 6), labels) ?? s.value : trimStat(s.value, 6)}
                              </dd>
                            </div>
                          ))}
                          {v.sentinel_codes.length > 0 && (
                            <div style={{ display: "contents" }}>
                              <dt className="muted">Missing codes</dt>
                              <dd className="mono">{v.sentinel_codes.join(", ")}</dd>
                            </div>
                          )}
                        </dl>
                      </div>
                    </td>
                  </tr>
                ),
              ];
            })}
            {p.stats && shown.length === 0 && (
              <tr><td colSpan={nCols} className="muted" style={{ textAlign: "center", height: 80 }}>No variables match.</td></tr>
            )}
            {!p.stats && (
              <tr>
                <td colSpan={nCols} className="muted" style={{ textAlign: "center", height: 120 }}>
                  {p.status === "error" ? <span className="err-box">{p.error}</span> : "Computing statistics with qsv…"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="panel-foot">
        <span className="muted">
          {p.stats && `${num(Math.min(rows.length, shown.length))} of ${num(p.stats.variables.length)} variables`}
          {p.stats?.weight && ` · weighted by ${p.stats.weight}`}
        </span>
        {shown.length > ROW_CAP && !showAllRows && (
          <button type="button" className="btn" onClick={() => setShowAllRows(true)}>
            Show all {num(shown.length)}
          </button>
        )}
        <span className="grow" />
        <span className="muted">Statistics are not written into the DDI-CDI output.</span>
      </div>
    </section>
  );
}

function Frequencies(props: {
  name: string;
  data: CategoryStats | undefined;
  loading: boolean;
  error: string | undefined;
  sort: Sort;
  onSort: (s: Sort) => void;
  onShowAll: () => void;
}) {
  const { data } = props;
  if (props.error) return <div className="err-box">{props.error}</div>;
  if (!data) return <p className="muted" style={{ margin: 0 }}>Loading distribution…</p>;
  if (data.all_unique)
    return <p className="muted" style={{ margin: 0 }}>Every value is unique — no frequency table.</p>;

  const max = Math.max(...data.categories.map((c) => c.percent), 1);

  return (
    <div className="freq" style={{ opacity: props.loading ? 0.6 : 1 }}>
      <div className="freq-head">
        <div className="seg" role="group" aria-label="Sort categories">
          <button type="button" className={props.sort === "count" ? "on" : ""} onClick={() => props.onSort("count")}>By count</button>
          <button type="button" className={props.sort === "code" ? "on" : ""} onClick={() => props.onSort("code")}>By code</button>
        </div>
        <span className="grow" />
        <span className="muted">
          {data.cardinality !== null && `${num(data.cardinality)} distinct`}
          {data.truncated && ` · showing top ${data.categories.length}`}
          {data.missing_n > 0 && ` · ${num(data.missing_n)} missing excluded`}
          {data.valid_n_substantive !== data.valid_n && ` · ${num(data.valid_n - data.valid_n_substantive)} in missing codes`}
        </span>
      </div>
      <div className="freq-scroll">
        <table className="grid sub">
          <thead>
            <tr>
              <th style={{ width: 60 }}>Code</th>
              <th>Label</th>
              <th style={{ width: 120 }} />
              <th className="stat-num" style={{ width: 70 }}>Count</th>
              <th className="stat-num" style={{ width: 60 }}>%</th>
            </tr>
          </thead>
          <tbody>
            {data.categories.map((c) => (
              <tr key={c.code} className={c.sentinel ? "sentinel" : ""}>
                <td className="mono">{c.code}</td>
                <td>{c.label ?? <span className="muted">—</span>}{c.sentinel && <small> · missing code</small>}</td>
                <td><span className="freq-bar" style={{ width: `${(c.percent / max) * 100}%` }} /></td>
                <td className="stat-num">{num(Math.round(c.count))}</td>
                <td className="stat-num">{c.percent.toFixed(1)}</td>
              </tr>
            ))}
            {data.truncated && (
              <tr className="faint">
                <td className="mono">…</td>
                <td>Other</td>
                <td />
                <td className="stat-num">{num(Math.round(data.other_count))}</td>
                <td />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {data.truncated && (
        <button type="button" className="btn" onClick={props.onShowAll} disabled={props.loading}>
          Show all {data.cardinality !== null ? num(data.cardinality) : ""} categories
        </button>
      )}
    </div>
  );
}
