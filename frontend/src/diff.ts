import type { ChangeKind, Element, JsonLdDoc } from "./types";

export interface ElementView {
  id: string;
  type: string;
  kind: ChangeKind;
  element: Element;
}

export function elementsOf(doc: JsonLdDoc): Element[] {
  return [...(doc.DDICDIModels ?? [])];
}

/** Compare two documents element by element (keyed on @id). */
export function diffDocs(prev: JsonLdDoc | null, next: JsonLdDoc): ElementView[] {
  const prevById = new Map<string, string>();
  if (prev) for (const e of elementsOf(prev)) prevById.set(e["@id"], JSON.stringify(e));
  const out: ElementView[] = [];
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
    out.push({ id, type: e["@type"], kind, element: e });
  }
  if (prev) {
    for (const e of elementsOf(prev)) {
      if (!seen.has(e["@id"])) out.push({ id: e["@id"], type: e["@type"], kind: "removed", element: e });
    }
  }
  return out;
}

export function countByType(views: ElementView[]): Map<string, number> {
  const m = new Map<string, number>();
  for (const v of views) if (v.kind !== "removed") m.set(v.type, (m.get(v.type) ?? 0) + 1);
  return m;
}

/** Ids of elements that mention a variable name in their @id. */
export function idsForVariable(views: ElementView[], name: string): Set<string> {
  const out = new Set<string>();
  const needle = `-${name}`;
  for (const v of views) if (v.id.endsWith(needle) || v.id.includes(`${needle}-`) || v.id === `#${name}`) out.add(v.id);
  return out;
}
