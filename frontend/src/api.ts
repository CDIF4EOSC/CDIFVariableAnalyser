import type { CategoryStats, EnrichKind, EnrichResponse, FileInfo, JsonLdDoc, OutputBody, PreviewPage, Statistics, Variable } from "./types";

let apiKey = "";
export function setApiKey(key: string) {
  apiKey = key;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (apiKey) headers.set("X-API-Key", apiKey);
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  const res = await fetch(url, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; version: string; qsv: string | null }>("/api/health"),
  info: () => request<Record<string, unknown>>("/api/info"),

  upload(file: File, previewRows = 5) {
    const fd = new FormData();
    fd.append("file", file);
    return request<FileInfo>(`/api/files?preview_rows=${previewRows}`, { method: "POST", body: fd });
  },
  fileInfo: (id: string) => request<FileInfo>(`/api/files/${id}`),
  preview: (id: string, rows: number, offset = 0) =>
    request<PreviewPage>(`/api/files/${id}/preview?rows=${rows}&offset=${offset}`),
  remove: (id: string) => request<void>(`/api/files/${id}`, { method: "DELETE" }),

  async output(
    id: string,
    body: OutputBody,
  ): Promise<JsonLdDoc> {
    const headers = new Headers({ "Content-Type": "application/json" });
    if (apiKey) headers.set("X-API-Key", apiKey);
    const res = await fetch(`/api/files/${id}/output`, { method: "POST", headers, body: JSON.stringify(body) });
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? res.statusText);
    return (await res.json()) as JsonLdDoc;
  },

  async download(
    id: string,
    body: OutputBody,
  ): Promise<{ blob: Blob; filename: string }> {
    const headers = new Headers({ "Content-Type": "application/json" });
    if (apiKey) headers.set("X-API-Key", apiKey);
    const res = await fetch(`/api/files/${id}/generate`, { method: "POST", headers, body: JSON.stringify(body) });
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? res.statusText);
    const cd = res.headers.get("Content-Disposition") ?? "";
    const m = /filename="?([^";]+)"?/.exec(cd);
    return { blob: await res.blob(), filename: m ? m[1] : "output" };
  },

  putRoles: (id: string, roles: Record<string, string>) =>
    request<FileInfo>(`/api/files/${id}/roles`, { method: "PUT", body: JSON.stringify({ roles }) }),
  patchVariable: (id: string, name: string, patch: Record<string, unknown>) =>
    request<Variable>(`/api/files/${id}/variables/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  addVariable: (id: string, spec: Record<string, unknown>) =>
    request<Variable>(`/api/files/${id}/variables`, { method: "POST", body: JSON.stringify(spec) }),
  deleteVariable: (id: string, name: string) =>
    request<FileInfo>(`/api/files/${id}/variables/${encodeURIComponent(name)}`, { method: "DELETE" }),
  patchRow: (id: string, index: number, values: Record<string, string | null>) =>
    request<{ index: number; row: string[]; total_rows: number }>(`/api/files/${id}/rows/${index}`, {
      method: "PATCH",
      body: JSON.stringify({ values }),
    }),
  addRow: (id: string, values: Record<string, string> = {}) =>
    request<{ index: number; total_rows: number }>(`/api/files/${id}/rows`, {
      method: "POST",
      body: JSON.stringify({ values }),
    }),
  deleteRow: (id: string, index: number) =>
    request<{ total_rows: number }>(`/api/files/${id}/rows/${index}`, { method: "DELETE" }),
  enrich: (id: string, body: { variables?: string[]; kinds: EnrichKind[] }) =>
    request<EnrichResponse>(`/api/files/${id}/enrich`, { method: "POST", body: JSON.stringify(body) }),

  statistics: (id: string, weight?: string | null, refresh = false) => {
    const q = new URLSearchParams();
    if (weight) q.set("weight", weight);
    if (refresh) q.set("refresh", "true");
    return request<Statistics>(`/api/files/${id}/statistics${q.size ? `?${q}` : ""}`);
  },
  categories: (id: string, name: string, o: { limit?: number; weight?: string | null; sort?: "count" | "code" } = {}) => {
    const q = new URLSearchParams();
    if (o.limit) q.set("limit", String(o.limit));
    if (o.weight) q.set("weight", o.weight);
    if (o.sort) q.set("sort", o.sort);
    return request<CategoryStats>(
      `/api/files/${id}/statistics/${encodeURIComponent(name)}/categories${q.size ? `?${q}` : ""}`,
    );
  },
};
