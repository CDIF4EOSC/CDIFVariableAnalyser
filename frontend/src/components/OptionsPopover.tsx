import { useEffect, useRef } from "react";
import type { Options } from "../types";
import { ALL_STAT_NAMES, STAT_GROUPS, statLabel } from "../types";

/** The two per-category statistics are the only ones that need the qsv frequency pass. */
function hasFrequencies(picked: Set<string>): boolean {
  return picked.has("frequency") || picked.has("percentage");
}

interface Props {
  options: Options;
  totalRows: number;
  statsWeight: string | null;
  onChange: (o: Options) => void;
  onClose: () => void;
}

export function OptionsPopover({ options, totalRows, statsWeight, onChange, onClose }: Props) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [onClose]);
  const set = (patch: Partial<Options>) => onChange({ ...options, ...patch });

  const picked = new Set(options.statistics);
  // Keep the stored order canonical, so the body of a request is stable.
  const setPicked = (next: Set<string>) => set({ statistics: ALL_STAT_NAMES.filter((n) => next.has(n)) });
  const toggleStat = (name: string, on: boolean) => {
    const next = new Set(picked);
    if (on) next.add(name);
    else next.delete(name);
    setPicked(next);
  };
  const toggleGroup = (names: string[], on: boolean) => {
    const next = new Set(picked);
    for (const n of names) {
      if (on) next.add(n);
      else next.delete(n);
    }
    setPicked(next);
  };

  return (
    <div ref={box} className="popover options" role="dialog" aria-label="Output options">
      <h3>Output options</h3>
      <div className="opt-body">
        <section className="opt-sec">
          <label className="check strong">
            <input type="checkbox" checked={options.includeRows} onChange={(e) => set({ includeRows: e.target.checked })} />
            Include data rows
          </label>
          <p className="opt-hint">A DataPoint and an InstanceValue per cell. Metadata only when off.</p>
          {options.includeRows && (
            <div className="opt-sub">
              <div className="grid2">
                <label className="field">
                  <span>Rows to include</span>
                  <input
                    type="number"
                    min={1}
                    max={100000}
                    value={options.maxRows}
                    disabled={options.allRows}
                    onChange={(e) => set({ maxRows: Math.max(1, Number(e.target.value) || 1) })}
                  />
                </label>
                <label className="check" style={{ alignSelf: "end", height: 38 }}>
                  <input type="checkbox" checked={options.allRows} onChange={(e) => set({ allRows: e.target.checked })} />
                  All {totalRows.toLocaleString()} rows
                </label>
              </div>
              <p className="opt-hint">
                Default 5, as in the original app. The preview shows at most 50 rows; the download streams the rest in
                chunks.
              </p>
            </div>
          )}
        </section>

        <section className="opt-sec">
          <label className="check strong">
            <input
              type="checkbox"
              checked={options.includeStatistics}
              onChange={(e) => set({ includeStatistics: e.target.checked })}
            />
            Include statistics
          </label>
          <p className="opt-hint">
            Emitted as a StatisticsCollection per variable with Statistics and CategoryStatistics, plus the Category and Notation the frequencies need. Costs a qsv pass per
            regeneration; the weight is {statsWeight ? <><b>{statsWeight}</b>, from the Statistics tab</> : "the Statistics tab's choice"}.
          </p>
          {options.includeStatistics && (
            <div className="opt-sub">
              <div className="opt-pick-head">
                <span>{picked.size} of {ALL_STAT_NAMES.length} selected</span>
                <span className="grow" />
                <button type="button" className="linkbtn" onClick={() => setPicked(new Set(ALL_STAT_NAMES))}>All</button>
                <button type="button" className="linkbtn" onClick={() => setPicked(new Set())}>None</button>
              </div>
              <div className="stat-pick">
                {STAT_GROUPS.map((g) => {
                  const on = g.names.filter((n) => picked.has(n)).length;
                  return (
                    <div className="stat-pick-group" key={g.key}>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={on === g.names.length}
                          ref={(el) => {
                            if (el) el.indeterminate = on > 0 && on < g.names.length;
                          }}
                          onChange={(e) => toggleGroup(g.names, e.target.checked)}
                        />
                        <span className="gname" title={g.hint}>{g.title}</span>
                      </label>
                      <div className="stat-pick-grid">
                        {g.names.map((n) => (
                          <label className="check sm" key={n} title={n}>
                            <input type="checkbox" checked={picked.has(n)} onChange={(e) => toggleStat(n, e.target.checked)} />
                            {statLabel(n)}
                          </label>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
              {picked.size === 0 ? (
                <p className="opt-warn">Nothing ticked — the document will carry no statistics at all.</p>
              ) : (
                !hasFrequencies(picked) && <p className="opt-hint">No per-category statistic selected, so the qsv frequency pass is skipped.</p>
              )}
            </div>
          )}
        </section>

        <section className="opt-sec">
          <label className="field">
            <span>API key</span>
            <input type="password" className="mono" value={options.apiKey} onChange={(e) => set({ apiKey: e.target.value })} placeholder="only when the server sets DDI_API_KEY" autoComplete="off" />
          </label>
        </section>
      </div>
      <div className="row opt-foot">
        <span className="grow" />
        <button type="button" className="btn primary" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}
