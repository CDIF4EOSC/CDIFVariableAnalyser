import { type ReactNode, useEffect, useMemo, useState } from "react";
import type { Agent, DatasetInfo, Grant, Vocabularies, VocabularyTerm } from "../types";
import { IconPlus, IconX } from "./Icons";

interface Props {
  info: DatasetInfo;
  filename: string;
  fileSize: number | null;
  fileMd5: string | null;
  vocabularies?: Vocabularies;
  onSave: (next: DatasetInfo) => Promise<void>;
  /** "bundle": the shared defaults of an image collection. Fields that name one image
   *  (title, description, identifiers, URLs) are left out: images never inherit them. */
  mode?: "dataset" | "bundle";
}

const formatBytes = (n: number) =>
  n < 1024 ? `${n} B` : n < 1024 ** 2 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 ** 2).toFixed(1)} MB`;

export const LICENSES: { uri: string; label: string; group: string }[] = [
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
export const LICENSE_GROUPS = [...new Set(LICENSES.map((l) => l.group))];

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

export function KeywordInput({ keywords, onChange, placeholder = "Type a keyword and press Enter" }: { keywords: string[]; onChange: (k: string[]) => void; placeholder?: string }) {
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

// Checklist items an image never inherits from the bundle, so the bundle does not list them.
const IMAGE_OWN = new Set(["Title", "Description", "Persistent identifier", "Download URL"]);

// -- dates --------------------------------------------------------------------------

const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;
/** A real calendar day as YYYY-MM-DD (no 14th month, no 31 February). */
export const isDay = (v: string) => {
  const m = DAY_RE.exec(v);
  if (!m) return false;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
};
/** "" when ``v`` is empty, a real day, or a year / year-month kept from earlier data. */
export const dateErr = (v: string) => {
  if (!v || isDay(v) || /^\d{4}$/.test(v)) return "";
  const ym = /^\d{4}-(\d{2})$/.exec(v);
  return ym && +ym[1] >= 1 && +ym[1] <= 12 ? "" : `“${v}” is not a real date; pick one from the calendar`;
};
const DATE_KEYS = ["date_published", "date_modified", "temporal_start", "temporal_end"] as const;
/** Whether any date of the description is impossible: such a description is not saved. */
export const datesInvalid = (d: DatasetInfo) => DATE_KEYS.some((k) => dateErr(d[k]));

/** A date picked from the calendar. A year or year-month from earlier data is kept and
 *  shown until a day is picked. ``inherited``: the bundle's value an empty field uses. */
export function DateInput({ label, value, onChange, inherited }: { label: string; value: string; onChange: (v: string) => void; inherited?: string }) {
  const err = dateErr(value);
  return (
    <label className="field">
      <span>{label}</span>
      <span className="date-row">
        <input type="date" className={err ? "err" : ""} value={isDay(value) ? value : ""} min="1000-01-01" max="9999-12-31" onChange={(e) => onChange(e.target.value)} />
        {value && (
          <button type="button" className="iconbtn" title={inherited !== undefined ? "Clear: use the bundle's date" : "Clear"} aria-label={`Clear ${label}`} onClick={(e) => { e.preventDefault(); onChange(""); }}>
            <IconX />
          </button>
        )}
      </span>
      {err ? <small className="errmsg">{err}</small>
        : value && !isDay(value) ? <small>Stored as “{value}” ({value.length === 4 ? "year" : "month"} only); pick a day to make it exact.</small>
        : !value && inherited ? <small>From the bundle: {inherited}</small>
        : null}
    </label>
  );
}

// -- the fields a bundle shares with its images ---------------------------------------

const agentSummary = (a: Agent) => [a.name.trim() || "(no name)", a.role && `(${a.role})`].filter(Boolean).join(" ");

/** The bundle's value, shown where the image has none, with a button to override it. */
function FromBundle({ text, onOverride }: { text: string; onOverride: () => void }) {
  return (
    <div className="from-bundle">
      <span><em>From the bundle:</em> {text}</span>
      <button type="button" className="btn sm" onClick={onOverride}>Override for this image</button>
    </div>
  );
}

/** The fieldsets of the description that are not about one file: version and language,
 *  creators, contributors, publisher, dates and licence, coverage and funding. Shared by
 *  the dataset form, the bundle defaults and each image. With ``inherit`` (the bundle),
 *  an empty field shows the bundle's value it falls back to, and can override it. */
export function SharedFields({ draft, set, vocabularies, inherit, citationTop, keywords = true, beforeDates }: {
  draft: DatasetInfo;
  set: <K extends keyof DatasetInfo>(k: K, v: DatasetInfo[K]) => void;
  vocabularies?: Vocabularies;
  inherit?: DatasetInfo;
  citationTop?: ReactNode;
  keywords?: boolean | "bundle";
  beforeDates?: ReactNode;
}) {
  const isPreset = (uri: string) => LICENSES.some((l) => l.uri === uri);
  const [otherPicked, setOtherPicked] = useState(false);
  useEffect(() => { if (!draft.license || isPreset(draft.license)) setOtherPicked(false); }, [draft.license]);
  const customLicense = otherPicked || (Boolean(draft.license) && !isPreset(draft.license));
  const licenceLabel = (uri: string) => LICENSES.find((l) => l.uri === uri)?.label ?? uri;

  const moveIn = (key: "creators" | "contributors", i: number, delta: number) => {
    const next = [...draft[key]];
    [next[i], next[i + delta]] = [next[i + delta], next[i]];
    set(key, next);
  };
  const setAt = <T,>(list: T[], i: number, v: T) => list.map((x, j) => (j === i ? v : x));
  const copy = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
  // The bundle's value an empty list falls back to, when there is one.
  const fallback = <K extends "creators" | "contributors" | "funding">(k: K) =>
    inherit && draft[k].length === 0 && inherit[k].length > 0 ? inherit[k] : null;
  const useBundle = (k: "creators" | "contributors" | "funding" | "publisher", filled: boolean) =>
    inherit && filled ? (
      <button type="button" className="btn sm ghost" onClick={() => set(k, k === "publisher" ? null : [])}>Use the bundle's instead</button>
    ) : null;
  const placeholder = (v: string | undefined, other: string) => (v ? `Bundle: ${v}` : other);

  const agents = (key: "creators" | "contributors", roles?: VocabularyTerm[]) => {
    const from = fallback(key);
    if (from) return <FromBundle text={from.map(agentSummary).join("; ")} onOverride={() => set(key, copy(from))} />;
    return (
      <>
        {draft[key].map((a, i) => (
          <AgentRow
            key={i}
            agent={a}
            index={i}
            count={draft[key].length}
            roles={roles}
            onChange={(next) => set(key, setAt(draft[key], i, next))}
            onMove={(delta) => moveIn(key, i, delta)}
            onRemove={() => set(key, draft[key].filter((_, j) => j !== i))}
          />
        ))}
        <div className="row" style={{ gap: 8 }}>
          <button type="button" className="btn add" onClick={() => set(key, [...draft[key], emptyAgent("person")])}><IconPlus /> Person</button>
          <button type="button" className="btn add" onClick={() => set(key, [...draft[key], emptyAgent("organization")])}><IconPlus /> Organisation</button>
          <span className="grow" />
          {useBundle(key, draft[key].length > 0)}
        </div>
      </>
    );
  };

  const publisherFrom = inherit && !draft.publisher && inherit.publisher ? inherit.publisher : null;
  const fundingFrom = fallback("funding");

  return (
    <>
      <fieldset>
        <legend>Citation</legend>
        {citationTop}
        <div className="grid3">
          <label className="field">
            <span>Version</span>
            <input value={draft.version} placeholder={placeholder(inherit?.version, "1.0")} onChange={(e) => set("version", e.target.value)} />
          </label>
          <label className="field">
            <span>Language</span>
            <input value={draft.language} placeholder={placeholder(inherit?.language, "en")} onChange={(e) => set("language", e.target.value)} />
          </label>
        </div>
        {keywords && (
          <div className="field">
            <span>Keywords{keywords === "bundle" && <span className="hint-label"> added after each image's own</span>}</span>
            <KeywordInput keywords={draft.keywords} onChange={(k) => set("keywords", k)} />
          </div>
        )}
      </fieldset>

      <fieldset>
        <legend>Creators <span className="hint-label">in citation order</span></legend>
        {agents("creators")}
      </fieldset>

      <fieldset>
        <legend>Contributors <span className="hint-label">data collectors, curators, distributors…</span></legend>
        {agents("contributors", vocabularies?.contributor_role ?? [])}
      </fieldset>

      <fieldset>
        <legend>Publisher <span className="hint-label">who made the {inherit ? "image" : keywords === "bundle" ? "images" : "dataset"} publicly available</span></legend>
        {publisherFrom ? (
          <FromBundle text={agentSummary(publisherFrom)} onOverride={() => set("publisher", copy(publisherFrom))} />
        ) : draft.publisher ? (
          <>
            <AgentRow agent={draft.publisher} index={0} count={1} onChange={(next) => set("publisher", next)} onRemove={() => set("publisher", null)} />
            {useBundle("publisher", true)}
          </>
        ) : (
          <div className="row" style={{ gap: 8 }}>
            <button type="button" className="btn add" onClick={() => set("publisher", emptyAgent("person"))}><IconPlus /> Person</button>
            <button type="button" className="btn add" onClick={() => set("publisher", emptyAgent("organization"))}><IconPlus /> Organisation</button>
          </div>
        )}
      </fieldset>

      {beforeDates}

      <fieldset>
        <legend>Dates and licence</legend>
        <div className="grid3">
          <DateInput label="Date published" value={draft.date_published} onChange={(v) => set("date_published", v)} inherited={inherit?.date_published} />
          <DateInput label="Date modified" value={draft.date_modified} onChange={(v) => set("date_modified", v)} inherited={inherit?.date_modified} />
          <label className="field">
            <span>Licence</span>
            <select
              value={customLicense ? "other" : draft.license}
              onChange={(e) => {
                const other = e.target.value === "other";
                setOtherPicked(other);
                set("license", other ? "" : e.target.value);
              }}
            >
              <option value="">{inherit ? (inherit.license ? `Bundle: ${licenceLabel(inherit.license)}` : "Not given (bundle has none)") : "Not given"}</option>
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
          <DateInput label="Period from" value={draft.temporal_start} onChange={(v) => set("temporal_start", v)} inherited={inherit?.temporal_start} />
          <DateInput label="Period to" value={draft.temporal_end} onChange={(v) => set("temporal_end", v)} inherited={inherit?.temporal_end} />
        </div>
        <div className="field">
          <span>Geographic coverage</span>
          <KeywordInput keywords={draft.spatial} onChange={(k) => set("spatial", k)} placeholder="Type a country or region and press Enter" />
          {inherit && draft.spatial.length === 0 && inherit.spatial.length > 0
            ? <small>From the bundle: {inherit.spatial.join(", ")}. Places added here replace them.</small>
            : <small>The period and places the data are about, not when they were collected.</small>}
        </div>
      </fieldset>

      <fieldset>
        <legend>Funding</legend>
        {fundingFrom ? (
          <FromBundle
            text={fundingFrom.map((g) => [g.funder, g.award, g.title].filter((v) => v.trim()).join(" · ") || "(empty grant)").join("; ")}
            onOverride={() => set("funding", copy(fundingFrom))}
          />
        ) : (
          <>
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
                    <input value={g.funder} placeholder="Funding organisation" onChange={(e) => set("funding", setAt(draft.funding, i, { ...g, funder: e.target.value }))} />
                  </label>
                  <label className="field">
                    <span>Funder ROR</span>
                    <input value={g.funder_id} placeholder="https://ror.org/…" onChange={(e) => set("funding", setAt(draft.funding, i, { ...g, funder_id: e.target.value }))} />
                  </label>
                  <label className="field">
                    <span>Award number</span>
                    <input value={g.award} onChange={(e) => set("funding", setAt(draft.funding, i, { ...g, award: e.target.value }))} />
                  </label>
                  <label className="field">
                    <span>Grant or project name</span>
                    <input value={g.title} onChange={(e) => set("funding", setAt(draft.funding, i, { ...g, title: e.target.value }))} />
                  </label>
                </div>
              </div>
            ))}
            <div className="row">
              <button type="button" className="btn add" onClick={() => set("funding", [...draft.funding, emptyGrant()])}><IconPlus /> Grant</button>
              <span className="grow" />
              {useBundle("funding", draft.funding.length > 0)}
            </div>
          </>
        )}
      </fieldset>
    </>
  );
}

export function DatasetPanel({ info, filename, fileSize, fileMd5, vocabularies, onSave, mode = "dataset" }: Props) {
  const bundle = mode === "bundle";
  const [draft, setDraft] = useState<DatasetInfo>(info);
  const [busy, setBusy] = useState(false);
  // A save, an undo or a redo replaces the description from outside. Keyed on the
  // content: every other edit refreshes the file info too, which must not drop a draft.
  const saved = JSON.stringify(info);
  useEffect(() => setDraft(info), [saved]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = JSON.stringify(draft) !== saved;
  const set = <K extends keyof DatasetInfo>(k: K, v: DatasetInfo[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const invalid = datesInvalid(draft);
  const checks = useMemo(() => checklist(draft).filter((c) => !bundle || !IMAGE_OWN.has(c.label)), [draft, bundle]);
  const done = checks.filter((c) => c.ok).length;

  const save = async () => {
    setBusy(true);
    try {
      await onSave(draft);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel dataset" aria-label={bundle ? "Bundle defaults" : "Dataset description"}>
      <div className="panel-head">
        <h2>{bundle ? "Bundle defaults" : "Dataset description"}</h2>
        <span className="sub">
          {bundle ? "Shared by every image of the collection · an image's own value wins" : <>Citation metadata for the CDIF output · not in {filename}</>}
        </span>
        <span className="grow" />
        {dirty && <span className="sub">Unsaved changes</span>}
        <button type="button" className="btn" disabled={!dirty || busy} onClick={() => setDraft(info)}>Discard</button>
        <button type="button" className="btn primary" disabled={!dirty || busy || invalid} onClick={() => void save()}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
      <div className="panel-body">
        <div className="ds-layout">
          <form className="ds-form" onSubmit={(e) => { e.preventDefault(); if (dirty && !invalid) void save(); }}>
            <SharedFields
              draft={draft}
              set={set}
              vocabularies={vocabularies}
              keywords={bundle ? "bundle" : true}
              citationTop={bundle ? (
                <label className="field">
                  <span>Collection name <span className="hint-label">names the collection in QLever; images keep their own titles</span></span>
                  <input value={draft.title} placeholder="e.g. Harbour fieldwork 2021" onChange={(e) => set("title", e.target.value)} />
                </label>
              ) : (
                <>
                  <label className="field">
                    <span>Title</span>
                    <input value={draft.title} placeholder={filename.replace(/\.[^.]+$/, "")} onChange={(e) => set("title", e.target.value)} />
                  </label>
                  <label className="field">
                    <span>Description</span>
                    <textarea rows={4} value={draft.description} placeholder="What the dataset contains, how and why it was collected" onChange={(e) => set("description", e.target.value)} />
                  </label>
                </>
              )}
              beforeDates={!bundle && <fieldset>
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
              </fieldset>}
            />
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
            <p>
              {bundle
                ? "Title, description, identifier and download URL are set per image on the Images tab."
                : "Variables count too: a description and an ELSST concept on each variable clear the remaining CDIF warnings."}
            </p>
          </aside>
        </div>
      </div>
    </section>
  );
}
