import { useEffect, useMemo, useState } from "react";
import type { Agent, DatasetInfo } from "../types";
import { IconPlus, IconX } from "./Icons";

interface Props {
  info: DatasetInfo;
  filename: string;
  onSave: (next: DatasetInfo) => Promise<void>;
}

const LICENSES: { uri: string; label: string; group: string }[] = [
  { uri: "https://creativecommons.org/licenses/by/4.0/", label: "CC BY 4.0", group: "Creative Commons" },
  { uri: "https://creativecommons.org/licenses/by-sa/4.0/", label: "CC BY-SA 4.0", group: "Creative Commons" },
  { uri: "https://creativecommons.org/licenses/by-nc/4.0/", label: "CC BY-NC 4.0", group: "Creative Commons" },
  { uri: "https://creativecommons.org/licenses/by-nc-sa/4.0/", label: "CC BY-NC-SA 4.0", group: "Creative Commons" },
  { uri: "https://creativecommons.org/licenses/by-nd/4.0/", label: "CC BY-ND 4.0", group: "Creative Commons" },
  { uri: "https://creativecommons.org/licenses/by-nc-nd/4.0/", label: "CC BY-NC-ND 4.0", group: "Creative Commons" },
  { uri: "https://creativecommons.org/licenses/by/3.0/", label: "CC BY 3.0", group: "Creative Commons" },
  { uri: "https://creativecommons.org/publicdomain/zero/1.0/", label: "CC0 1.0 (public domain)", group: "Creative Commons" },
  { uri: "https://creativecommons.org/publicdomain/mark/1.0/", label: "Public Domain Mark 1.0", group: "Creative Commons" },
  { uri: "https://opendatacommons.org/licenses/by/1-0/", label: "ODC-By 1.0", group: "Open data" },
  { uri: "https://opendatacommons.org/licenses/odbl/1-0/", label: "ODbL 1.0", group: "Open data" },
  { uri: "https://opendatacommons.org/licenses/pddl/1-0/", label: "PDDL 1.0", group: "Open data" },
  { uri: "https://spdx.org/licenses/NLOD-2.0.html", label: "NLOD 2.0 (Norway)", group: "Open data" },
  { uri: "https://spdx.org/licenses/etalab-2.0.html", label: "Etalab Open Licence 2.0 (France)", group: "Open data" },
  { uri: "https://spdx.org/licenses/OGL-UK-3.0.html", label: "OGL 3.0 (UK)", group: "Open data" },
  { uri: "https://spdx.org/licenses/DL-DE-BY-2.0.html", label: "DL-DE-BY 2.0 (Germany)", group: "Open data" },
  { uri: "https://spdx.org/licenses/MIT.html", label: "MIT", group: "Software" },
  { uri: "https://spdx.org/licenses/Apache-2.0.html", label: "Apache 2.0", group: "Software" },
  { uri: "https://spdx.org/licenses/GPL-3.0-or-later.html", label: "GPL 3.0 or later", group: "Software" },
];
const LICENSE_GROUPS = [...new Set(LICENSES.map((l) => l.group))];

const DATE_RE = /^(\d{4}(-\d{2}(-\d{2})?)?)?$/;
const ORCID_RE = /^(https:\/\/orcid\.org\/)?\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/;

const emptyAgent = (kind: Agent["kind"]): Agent => ({ name: "", kind, identifier: "", affiliation: "", affiliation_id: "", email: "" });

/** What the CDIF shapes ask of a dataset, and whether the description gives it. */
export function checklist(d: DatasetInfo) {
  return [
    { label: "Title", ok: Boolean(d.title.trim()), level: "required", note: "the file name is used otherwise" },
    { label: "Licence", ok: Boolean(d.license.trim()), level: "required", note: "written as “missing” otherwise" },
    { label: "Date modified", ok: Boolean(d.date_modified), level: "required", note: "1900-01-01 placeholder otherwise" },
    { label: "Creator", ok: d.creators.some((a) => a.name.trim()), level: "recommended" },
    { label: "Description", ok: Boolean(d.description.trim()), level: "recommended" },
    { label: "Keywords", ok: d.keywords.some((k) => k.trim()), level: "recommended" },
    { label: "Persistent identifier", ok: Boolean(d.identifier.trim()), level: "recommended", note: "a DOI is best" },
    { label: "Date published", ok: Boolean(d.date_published), level: "suggested" },
    { label: "Publisher", ok: Boolean(d.publisher?.name.trim()), level: "suggested" },
  ] as const;
}

function AgentRow({ agent, index, count, onChange, onMove, onRemove }: {
  agent: Agent;
  index: number;
  count: number;
  onChange: (a: Agent) => void;
  onMove: (delta: number) => void;
  onRemove: () => void;
}) {
  const person = agent.kind === "person";
  const set = (k: keyof Agent, v: string) => onChange({ ...agent, [k]: v });
  const orcidErr = person && agent.identifier.trim() && !ORCID_RE.test(agent.identifier.trim());
  return (
    <div className="agent-row">
      <div className="agent-head">
        <span className="agent-num">{index + 1}</span>
        <div className="seg">
          <button type="button" className={person ? "on" : ""} onClick={() => set("kind", "person")}>Person</button>
          <button type="button" className={!person ? "on" : ""} onClick={() => set("kind", "organization")}>Organisation</button>
        </div>
        <span className="grow" />
        <button type="button" className="iconbtn" title="Move up" disabled={index === 0} onClick={() => onMove(-1)}>↑</button>
        <button type="button" className="iconbtn" title="Move down" disabled={index === count - 1} onClick={() => onMove(1)}>↓</button>
        <button type="button" className="iconbtn" title="Remove" onClick={onRemove}><IconX /></button>
      </div>
      <div className="grid2">
        <label className="field">
          <span>Name</span>
          <input value={agent.name} placeholder={person ? "Family name, Given name" : "Organisation name"} onChange={(e) => set("name", e.target.value)} />
        </label>
        <label className="field">
          <span>{person ? "ORCID" : "ROR"}</span>
          <input
            className={orcidErr ? "err" : ""}
            value={agent.identifier}
            placeholder={person ? "0000-0002-1825-0097" : "https://ror.org/…"}
            onChange={(e) => set("identifier", e.target.value)}
          />
          {orcidErr && <small className="errmsg">An ORCID looks like 0000-0002-1825-0097</small>}
        </label>
        {person && (
          <>
            <label className="field">
              <span>Affiliation</span>
              <input value={agent.affiliation} placeholder="Organisation" onChange={(e) => set("affiliation", e.target.value)} />
            </label>
            <label className="field">
              <span>Affiliation ROR</span>
              <input value={agent.affiliation_id} placeholder="https://ror.org/…" onChange={(e) => set("affiliation_id", e.target.value)} />
            </label>
          </>
        )}
        <label className="field">
          <span>Contact e-mail <span className="hint-label">optional</span></span>
          <input type="email" value={agent.email} onChange={(e) => set("email", e.target.value)} />
        </label>
      </div>
    </div>
  );
}

function KeywordInput({ keywords, onChange }: { keywords: string[]; onChange: (k: string[]) => void }) {
  const [text, setText] = useState("");
  const add = () => {
    // One keyword per entry: CDIF rejects a comma-separated string.
    const fresh = text.split(",").map((k) => k.trim()).filter((k) => k && !keywords.includes(k));
    if (fresh.length) onChange([...keywords, ...fresh]);
    setText("");
  };
  return (
    <div className="kw-box">
      {keywords.map((k) => (
        <span key={k} className="kw">
          {k}
          <button type="button" aria-label={`Remove ${k}`} onClick={() => onChange(keywords.filter((x) => x !== k))}>×</button>
        </span>
      ))}
      <input
        value={text}
        placeholder={keywords.length ? "Add another…" : "Type a keyword and press Enter"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add();
          } else if (e.key === "Backspace" && !text && keywords.length) {
            onChange(keywords.slice(0, -1));
          }
        }}
        onBlur={add}
      />
    </div>
  );
}

export function DatasetPanel({ info, filename, onSave }: Props) {
  const [draft, setDraft] = useState<DatasetInfo>(info);
  const [busy, setBusy] = useState(false);
  const isPreset = (uri: string) => LICENSES.some((l) => l.uri === uri);
  const [customLicense, setCustomLicense] = useState(Boolean(info.license) && !isPreset(info.license));
  // A save, an undo or a redo replaces the description from outside. Keyed on the
  // content: every other edit refreshes the file info too, which must not drop a draft.
  const saved = JSON.stringify(info);
  useEffect(() => {
    setDraft(info);
    setCustomLicense(Boolean(info.license) && !isPreset(info.license));
  }, [saved]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = JSON.stringify(draft) !== saved;
  const set = <K extends keyof DatasetInfo>(k: K, v: DatasetInfo[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const dateErr = (v: string) => (DATE_RE.test(v) ? "" : "Use YYYY, YYYY-MM or YYYY-MM-DD");
  const invalid = Boolean(dateErr(draft.date_published) || dateErr(draft.date_modified));
  const checks = useMemo(() => checklist(draft), [draft]);
  const done = checks.filter((c) => c.ok).length;

  const setCreator = (i: number, a: Agent) => set("creators", draft.creators.map((c, j) => (j === i ? a : c)));
  const moveCreator = (i: number, delta: number) => {
    const next = [...draft.creators];
    [next[i], next[i + delta]] = [next[i + delta], next[i]];
    set("creators", next);
  };

  const save = async () => {
    setBusy(true);
    try {
      await onSave(draft);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel dataset" aria-label="Dataset description">
      <div className="panel-head">
        <h2>Dataset description</h2>
        <span className="sub">Citation metadata for the CDIF output · not in {filename}</span>
        <span className="grow" />
        {dirty && <span className="sub">Unsaved changes</span>}
        <button type="button" className="btn" disabled={!dirty || busy} onClick={() => { setDraft(info); setCustomLicense(Boolean(info.license) && !isPreset(info.license)); }}>Discard</button>
        <button type="button" className="btn primary" disabled={!dirty || busy || invalid} onClick={() => void save()}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
      <div className="panel-body">
        <div className="ds-layout">
          <form className="ds-form" onSubmit={(e) => { e.preventDefault(); if (dirty && !invalid) void save(); }}>
            <fieldset>
              <legend>Citation</legend>
              <label className="field">
                <span>Title</span>
                <input value={draft.title} placeholder={filename.replace(/\.[^.]+$/, "")} onChange={(e) => set("title", e.target.value)} />
              </label>
              <label className="field">
                <span>Description</span>
                <textarea rows={4} value={draft.description} placeholder="What the dataset contains, how and why it was collected" onChange={(e) => set("description", e.target.value)} />
              </label>
              <div className="grid3">
                <label className="field">
                  <span>Version</span>
                  <input value={draft.version} placeholder="1.0" onChange={(e) => set("version", e.target.value)} />
                </label>
                <label className="field">
                  <span>Language</span>
                  <input value={draft.language} placeholder="en" onChange={(e) => set("language", e.target.value)} />
                </label>
              </div>
              <div className="field">
                <span>Keywords</span>
                <KeywordInput keywords={draft.keywords} onChange={(k) => set("keywords", k)} />
              </div>
            </fieldset>

            <fieldset>
              <legend>Creators <span className="hint-label">in citation order</span></legend>
              {draft.creators.map((a, i) => (
                <AgentRow
                  key={i}
                  agent={a}
                  index={i}
                  count={draft.creators.length}
                  onChange={(next) => setCreator(i, next)}
                  onMove={(delta) => moveCreator(i, delta)}
                  onRemove={() => set("creators", draft.creators.filter((_, j) => j !== i))}
                />
              ))}
              <div className="row" style={{ gap: 8 }}>
                <button type="button" className="btn add" onClick={() => set("creators", [...draft.creators, emptyAgent("person")])}><IconPlus /> Person</button>
                <button type="button" className="btn add" onClick={() => set("creators", [...draft.creators, emptyAgent("organization")])}><IconPlus /> Organisation</button>
              </div>
            </fieldset>

            <fieldset>
              <legend>Publisher</legend>
              <div className="grid2">
                <label className="field">
                  <span>Name</span>
                  <input
                    value={draft.publisher?.name ?? ""}
                    placeholder="Archive or repository"
                    onChange={(e) => set("publisher", { ...(draft.publisher ?? emptyAgent("organization")), name: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span>ROR</span>
                  <input
                    value={draft.publisher?.identifier ?? ""}
                    placeholder="https://ror.org/…"
                    onChange={(e) => set("publisher", { ...(draft.publisher ?? emptyAgent("organization")), identifier: e.target.value })}
                  />
                </label>
              </div>
            </fieldset>

            <fieldset>
              <legend>Identification</legend>
              <div className="grid2">
                <label className="field">
                  <span>Persistent identifier</span>
                  <input value={draft.identifier} placeholder="https://doi.org/10.…" onChange={(e) => set("identifier", e.target.value)} />
                  <small>DOI, handle or URL of the dataset</small>
                </label>
                <label className="field">
                  <span>Landing page</span>
                  <input value={draft.url} placeholder="https://…" onChange={(e) => set("url", e.target.value)} />
                </label>
              </div>
              <label className="field">
                <span>Metadata record IRI <span className="hint-label">optional</span></span>
                <input value={draft.record_id} placeholder={`urn:ddi-cdi:${filename.replace(/\.[^.]+$/, "")}`} onChange={(e) => set("record_id", e.target.value)} />
                <small>The @id of the CDIF document, which its catalog record is about. Use the URL the record will be served from.</small>
              </label>
            </fieldset>

            <fieldset>
              <legend>Dates and licence</legend>
              <div className="grid3">
                <label className="field">
                  <span>Date published</span>
                  <input className={dateErr(draft.date_published) ? "err" : ""} value={draft.date_published} placeholder="YYYY-MM-DD" onChange={(e) => set("date_published", e.target.value.trim())} />
                  {dateErr(draft.date_published) && <small className="errmsg">{dateErr(draft.date_published)}</small>}
                </label>
                <label className="field">
                  <span>Date modified</span>
                  <input className={dateErr(draft.date_modified) ? "err" : ""} value={draft.date_modified} placeholder="YYYY-MM-DD" onChange={(e) => set("date_modified", e.target.value.trim())} />
                  {dateErr(draft.date_modified) && <small className="errmsg">{dateErr(draft.date_modified)}</small>}
                </label>
                <label className="field">
                  <span>Licence</span>
                  <select
                    value={customLicense ? "other" : draft.license}
                    onChange={(e) => {
                      const other = e.target.value === "other";
                      setCustomLicense(other);
                      if (!other) set("license", e.target.value);
                    }}
                  >
                    <option value="">Not given</option>
                    {LICENSE_GROUPS.map((g) => (
                      <optgroup key={g} label={g}>
                        {LICENSES.filter((l) => l.group === g).map((l) => <option key={l.uri} value={l.uri}>{l.label}</option>)}
                      </optgroup>
                    ))}
                    <option value="other">Other (URI)…</option>
                  </select>
                </label>
              </div>
              {customLicense && (
                <label className="field">
                  <span>Licence URI</span>
                  <input value={draft.license} placeholder="https://…" onChange={(e) => set("license", e.target.value)} />
                </label>
              )}
            </fieldset>
          </form>

          <aside className="ds-check">
            <h3>CDIF discovery <span className="count">{done}/{checks.length}</span></h3>
            <ul>
              {checks.map((c) => (
                <li key={c.label} className={c.ok ? "ok" : c.level}>
                  <span className="mark">{c.ok ? "✓" : c.level === "required" ? "!" : "·"}</span>
                  <span>
                    {c.label} <em>{c.level}</em>
                    {!c.ok && "note" in c && <small>{c.note}</small>}
                  </span>
                </li>
              ))}
            </ul>
            <p>Variables count too: a description and an ELSST concept on each variable clear the remaining CDIF warnings.</p>
          </aside>
        </div>
      </div>
    </section>
  );
}
