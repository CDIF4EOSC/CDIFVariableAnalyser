import { useEffect, useMemo, useState } from "react";
import type { Agent, DatasetInfo, Grant, Vocabularies, VocabularyTerm } from "../types";
import { IconPlus, IconX } from "./Icons";

interface Props {
  info: DatasetInfo;
  filename: string;
  fileSize: number | null;
  fileMd5: string | null;
  vocabularies?: Vocabularies;
  onSave: (next: DatasetInfo) => Promise<void>;
}

const formatBytes = (n: number) =>
  n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 ** 2).toFixed(1)} MB`;

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

const emptyAgent = (kind: Agent["kind"]): Agent => ({ name: "", kind, identifier: "", affiliation: "", affiliation_id: "", email: "", role: "" });
const emptyGrant = (): Grant => ({ funder: "", funder_id: "", award: "", title: "" });

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
    { label: "Download URL", ok: Boolean(d.content_url.trim()), level: "recommended", note: "the data file's own link" },
    { label: "Date published", ok: Boolean(d.date_published), level: "suggested" },
    { label: "Contributor", ok: d.contributors.some((a) => a.name.trim()), level: "suggested" },
    { label: "Publisher", ok: Boolean(d.publisher?.name.trim()), level: "suggested" },
    { label: "Temporal coverage", ok: Boolean(d.temporal_start || d.temporal_end), level: "suggested" },
    { label: "Spatial coverage", ok: d.spatial.some((p) => p.trim()), level: "suggested" },
    // a MonetaryGrant needs at least one of funder, identifier (award) or name (title)
    { label: "Funding", ok: d.funding.some((g) => [g.funder, g.funder_id, g.award, g.title].some((v) => v.trim())), level: "suggested" },
  ] as const;
}

function AgentRow({ agent, index, count, roles, onChange, onMove, onRemove }: {
  agent: Agent;
  index: number;
  count: number;
  roles?: VocabularyTerm[]; // given for contributors: the role picker
  onChange: (a: Agent) => void;
  onMove?: (delta: number) => void; // left out for the single publisher: no number, no reordering
  onRemove: () => void;
}) {
  const person = agent.kind === "person";
  const set = (k: keyof Agent, v: string) => onChange({ ...agent, [k]: v });
  const orcidErr = person && agent.identifier.trim() && !ORCID_RE.test(agent.identifier.trim());
  return (
    <div className="agent-row">
      <div className="agent-head">
        {onMove && <span className="agent-num">{index + 1}</span>}
        <div className="seg">
          <button type="button" className={person ? "on" : ""} onClick={() => set("kind", "person")}>Person</button>
          <button type="button" className={!person ? "on" : ""} onClick={() => set("kind", "organization")}>Organisation</button>
        </div>
        {roles && (
          <select className="role-select" aria-label="Role" value={agent.role} onChange={(e) => set("role", e.target.value)}>
            <option value="">No role</option>
            {roles.map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
          </select>
        )}
        <span className="grow" />
        {onMove && (
          <>
            <button type="button" className="iconbtn" title="Move up" disabled={index === 0} onClick={() => onMove(-1)}>↑</button>
            <button type="button" className="iconbtn" title="Move down" disabled={index === count - 1} onClick={() => onMove(1)}>↓</button>
          </>
        )}
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

function KeywordInput({ keywords, onChange, placeholder = "Type a keyword and press Enter" }: { keywords: string[]; onChange: (k: string[]) => void; placeholder?: string }) {
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
        placeholder={keywords.length ? "Add another…" : placeholder}
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

export function DatasetPanel({ info, filename, fileSize, fileMd5, vocabularies, onSave }: Props) {
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
  const invalid = [draft.date_published, draft.date_modified, draft.temporal_start, draft.temporal_end]
    .some((v) => dateErr(v));
  const dateField = (label: string, value: string, onChange: (v: string) => void, placeholder = "YYYY-MM-DD") => (
    <label className="field">
      <span>{label}</span>
      <input className={dateErr(value) ? "err" : ""} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value.trim())} />
      {dateErr(value) && <small className="errmsg">{dateErr(value)}</small>}
    </label>
  );
  const checks = useMemo(() => checklist(draft), [draft]);
  const done = checks.filter((c) => c.ok).length;

  const setCreator = (i: number, a: Agent) => set("creators", draft.creators.map((c, j) => (j === i ? a : c)));
  const moveIn = (key: "creators" | "contributors", i: number, delta: number) => {
    const next = [...draft[key]];
    [next[i], next[i + delta]] = [next[i + delta], next[i]];
    set(key, next);
  };
  const setContributor = (i: number, a: Agent) => set("contributors", draft.contributors.map((c, j) => (j === i ? a : c)));
  const setGrant = (i: number, g: Grant) => set("funding", draft.funding.map((x, j) => (j === i ? g : x)));

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
                  onMove={(delta) => moveIn("creators", i, delta)}
                  onRemove={() => set("creators", draft.creators.filter((_, j) => j !== i))}
                />
              ))}
              <div className="row" style={{ gap: 8 }}>
                <button type="button" className="btn add" onClick={() => set("creators", [...draft.creators, emptyAgent("person")])}><IconPlus /> Person</button>
                <button type="button" className="btn add" onClick={() => set("creators", [...draft.creators, emptyAgent("organization")])}><IconPlus /> Organisation</button>
              </div>
            </fieldset>

            <fieldset>
              <legend>Contributors <span className="hint-label">data collectors, curators, distributors…</span></legend>
              {draft.contributors.map((a, i) => (
                <AgentRow
                  key={i}
                  agent={a}
                  index={i}
                  count={draft.contributors.length}
                  roles={vocabularies?.contributor_role ?? []}
                  onChange={(next) => setContributor(i, next)}
                  onMove={(delta) => moveIn("contributors", i, delta)}
                  onRemove={() => set("contributors", draft.contributors.filter((_, j) => j !== i))}
                />
              ))}
              <div className="row" style={{ gap: 8 }}>
                <button type="button" className="btn add" onClick={() => set("contributors", [...draft.contributors, emptyAgent("person")])}><IconPlus /> Person</button>
                <button type="button" className="btn add" onClick={() => set("contributors", [...draft.contributors, emptyAgent("organization")])}><IconPlus /> Organisation</button>
              </div>
            </fieldset>

            <fieldset>
              <legend>Publisher <span className="hint-label">who made the dataset publicly available</span></legend>
              {draft.publisher ? (
                <AgentRow
                  agent={draft.publisher}
                  index={0}
                  count={1}
                  onChange={(next) => set("publisher", next)}
                  onRemove={() => set("publisher", null)}
                />
              ) : (
                <div className="row" style={{ gap: 8 }}>
                  <button type="button" className="btn add" onClick={() => set("publisher", emptyAgent("person"))}><IconPlus /> Person</button>
                  <button type="button" className="btn add" onClick={() => set("publisher", emptyAgent("organization"))}><IconPlus /> Organisation</button>
                </div>
              )}
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
                <span>Download URL of the data file</span>
                <input value={draft.content_url} placeholder="https://…/datafile" onChange={(e) => set("content_url", e.target.value)} />
                <small>
                  Where {filename} itself can be fetched; CDIF writes “missing” otherwise.
                  {fileSize !== null && <> The output also gives its size ({formatBytes(fileSize)}){fileMd5 && <> and MD5 checksum <code>{fileMd5}</code></>}.</>}
                </small>
              </label>
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

            <fieldset>
              <legend>Coverage</legend>
              <div className="grid3">
                {dateField("Period from", draft.temporal_start, (v) => set("temporal_start", v))}
                {dateField("Period to", draft.temporal_end, (v) => set("temporal_end", v))}
              </div>
              <div className="field">
                <span>Geographic coverage</span>
                <KeywordInput keywords={draft.spatial} onChange={(k) => set("spatial", k)} placeholder="Type a country or region and press Enter" />
                <small>The period and places the data are about, not when they were collected.</small>
              </div>
            </fieldset>

            <fieldset>
              <legend>Funding</legend>
              {draft.funding.map((g, i) => (
                <div key={i} className="agent-row">
                  <div className="agent-head">
                    <span className="agent-num">{i + 1}</span>
                    <span className="grow" />
                    <button type="button" className="iconbtn" title="Remove" onClick={() => set("funding", draft.funding.filter((_, j) => j !== i))}><IconX /></button>
                  </div>
                  <div className="grid2">
                    <label className="field">
                      <span>Funder</span>
                      <input value={g.funder} placeholder="Funding organisation" onChange={(e) => setGrant(i, { ...g, funder: e.target.value })} />
                    </label>
                    <label className="field">
                      <span>Funder ROR</span>
                      <input value={g.funder_id} placeholder="https://ror.org/…" onChange={(e) => setGrant(i, { ...g, funder_id: e.target.value })} />
                    </label>
                    <label className="field">
                      <span>Award number</span>
                      <input value={g.award} onChange={(e) => setGrant(i, { ...g, award: e.target.value })} />
                    </label>
                    <label className="field">
                      <span>Grant or project name</span>
                      <input value={g.title} onChange={(e) => setGrant(i, { ...g, title: e.target.value })} />
                    </label>
                  </div>
                </div>
              ))}
              <div className="row">
                <button type="button" className="btn add" onClick={() => set("funding", [...draft.funding, emptyGrant()])}><IconPlus /> Grant</button>
              </div>
            </fieldset>
          </form>

          <aside className="ds-check">
            <h3>CDIF checklist <span className="count">{done}/{checks.length}</span></h3>
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
