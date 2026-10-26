import type { ChangeKind, Element, JsonLdDoc } from "./types";

export interface ElementView {
  id: string;
  type: string;
  kind: ChangeKind;
  element: Element;
  /** Set for a top-level property of the document (e.g. "@context"), not an element of its graph. */
  key?: string;
}

/**
 * The property holding the document's list of objects: the flat DDI-CDI graph,
 * or the variables of a CDIF dataset (the rest of a CDIF document is nested).
 */
export function graphKey(doc: JsonLdDoc): string {
  return "DDICDIModels" in doc ? "DDICDIModels" : "schema:variableMeasured";
}

export function elementsOf(doc: JsonLdDoc): Element[] {
  const list = doc[graphKey(doc)];
  return Array.isArray(list) ? [...(list as Element[])] : [];
}

/** A DDI-CDI element has one @type; a CDIF one a list, its most specific type last. */
function typeOf(e: Element): string {
  const t = e["@type"] as string | string[];
  return Array.isArray(t) ? t[t.length - 1] ?? "" : t;
}

/**
 * Compare two documents in document order: each top-level property as one
 * block, the graph element by element (keyed on @id).
 */
export function diffDocs(prev: JsonLdDoc | null, next: JsonLdDoc): ElementView[] {
  const prevById = new Map<string, string>();
  if (prev) for (const e of elementsOf(prev)) prevById.set(e["@id"], JSON.stringify(e));
  const graph = graphKey(next);
  const out: ElementView[] = [];
  for (const key of Object.keys(next)) {
    if (key !== graph) {
      let kind: ChangeKind = "same";
      if (prev && JSON.stringify(prev[key]) !== JSON.stringify(next[key])) kind = key in prev ? "changed" : "added";
      out.push({ id: `@${key}`, type: key, kind, element: next[key] as Element, key });
      continue;
    }
    const seen = new Set<string>();
    for (const e of elementsOf(next)) {
      const id = e["@id"];
      seen.add(id);
      let kind: ChangeKind = "same";
      if (prev) {
        const old = prevById.get(id);
        if (old === undefined) kind = "added";
        else if (old !== JSON.stringify(e)) kind = "changed";
      }
      out.push({ id, type: typeOf(e), kind, element: e });
    }
    if (prev) {
      for (const e of elementsOf(prev)) {
        if (!seen.has(e["@id"])) out.push({ id: e["@id"], type: typeOf(e), kind: "removed", element: e });
      }
    }
  }
  return out;
}

export function countByType(views: ElementView[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const v of views) if (!v.key && v.kind !== "removed") m.set(v.type, (m.get(v.type) ?? 0) + 1);
  return m;
}

/** Ids of elements that mention a variable name in their @id. */
export function idsForVariable(views: ElementView[], name: string): Set<string> {
  const out = new Set<string>();
  const needle = `-${name}`;
  for (const v of views) if (!v.key && (v.id.endsWith(needle) || v.id.includes(`${needle}-`) || v.id === `#${name}`)) out.add(v.id);
  return out;
}
