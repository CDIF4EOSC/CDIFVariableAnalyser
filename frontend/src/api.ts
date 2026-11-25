import type { CategoryStats, DatasetInfo, EnrichKind, EnrichResponse, FileInfo, ImageCheck, ImageCollection, ImageItem, CollectionSaveResult, ImageSuggestion, JsonLdDoc, OutputBody, OutputFormat, PreviewPage, QleverDocument, QleverFormat, QleverSaveResult, ShaclResult, Statistics, Variable } from "./types";

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

  /** The preview document, and the element IRIs of each variable: the IRIs are UUIDs,
   *  so they do not say which variable an element belongs to. */
  async output(
    id: string,
    body: OutputBody,
    format: OutputFormat = "ddicdi",
  ): Promise<{ document: JsonLdDoc; variable_ids: Record<string, string[]> }> {
    const headers = new Headers({ "Content-Type": "application/json" });
    if (apiKey) headers.set("X-API-Key", apiKey);
    const res = await fetch(`/api/files/${id}/output?format=${format}&variable_ids=true`, { method: "POST", headers, body: JSON.stringify(body) });
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? res.statusText);
    return (await res.json()) as { document: JsonLdDoc; variable_ids: Record<string, string[]> };
  },

  async download(
    id: string,
    body: OutputBody,
    format: OutputFormat = "ddicdi",
  ): Promise<{ blob: Blob; filename: string }> {
    const headers = new Headers({ "Content-Type": "application/json" });
    if (apiKey) headers.set("X-API-Key", apiKey);
    const res = await fetch(`/api/files/${id}/generate?format=${format}`, { method: "POST", headers, body: JSON.stringify(body) });
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? res.statusText);
    const cd = res.headers.get("Content-Disposition") ?? "";
    const m = /filename="?([^";]+)"?/.exec(cd);
    return { blob: await res.blob(), filename: m ? m[1] : "output" };
  },

  putInfo: (id: string, info: DatasetInfo) =>
    request<DatasetInfo>(`/api/files/${id}/info`, { method: "PUT", body: JSON.stringify(info) }),
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

  // QLever store: save the CDIF of this document; list and read back saved documents.
  saveToQlever: (id: string, body: OutputBody) =>
    request<QleverSaveResult>(`/api/files/${id}/qlever`, { method: "POST", body: JSON.stringify(body) }),
  checkCdif: (id: string, body: OutputBody) =>
    request<ShaclResult>(`/api/files/${id}/cdif/check`, { method: "POST", body: JSON.stringify(body) }),
  /** Open a saved document in the editor: a metadata-only session without data rows. */
  openQlever: (uuid: string) => request<FileInfo>(`/api/qlever/documents/${uuid}/open`, { method: "POST" }),
  qleverDocuments: () => request<QleverDocument[]>("/api/qlever/documents"),
  // Image collections: CDIF metadata for images, one Dataset per image.
  createImages: (files: File[]) => request<ImageCollection>("/api/images", { method: "POST", body: imageForm(files) }),
  addImages: (id: string, files: File[]) =>
    request<ImageCollection>(`/api/images/${id}/items`, { method: "POST", body: imageForm(files) }),
  removeImages: (id: string) => request<void>(`/api/images/${id}`, { method: "DELETE" }),
  removeImage: (id: string, imageId: string) =>
    request<ImageCollection>(`/api/images/${id}/items/${imageId}`, { method: "DELETE" }),
  saveImagesToQlever: (id: string) => request<CollectionSaveResult>(`/api/images/${id}/qlever`, { method: "POST" }),
  openImageFromQlever: (uuid: string) => request<ImageCollection>(`/api/images/from-qlever/${uuid}`, { method: "POST" }),
  putBundle: (id: string, bundle: DatasetInfo) =>
    request<ImageCollection>(`/api/images/${id}/bundle`, { method: "PUT", body: JSON.stringify(bundle) }),
  putImageInfo: (id: string, imageId: string, info: DatasetInfo) =>
    request<ImageItem>(`/api/images/${id}/items/${imageId}/info`, { method: "PUT", body: JSON.stringify(info) }),
  putImageSuggestion: (id: string, imageId: string, rest: ImageSuggestion | null) =>
    request<ImageItem>(`/api/images/${id}/items/${imageId}/suggestion`, {
      method: "PUT",
      body: JSON.stringify(rest ?? {}),
    }),
  describeImage: (id: string, imageId: string) =>
    request<ImageItem>(`/api/images/${id}/items/${imageId}/describe`, { method: "POST" }),
  imageCdif: (id: string, imageId: string) => request<JsonLdDoc>(`/api/images/${id}/items/${imageId}/cdif`),
  checkImages: (id: string) => request<ImageCheck[]>(`/api/images/${id}/check`, { method: "POST" }),
  /** A file of the API as a blob: pictures and the zip need the API key header too. */
  async blob(url: string): Promise<{ blob: Blob; filename: string }> {
    const headers = new Headers();
    if (apiKey) headers.set("X-API-Key", apiKey);
    const res = await fetch(url, { headers });
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? res.statusText);
    const m = /filename="?([^";]+)"?/.exec(res.headers.get("Content-Disposition") ?? "");
    return { blob: await res.blob(), filename: m ? m[1] : "download" };
  },

  async qleverDocument(uuid: string, format: QleverFormat = "jsonld"): Promise<{ text: string; blob: Blob; filename: string }> {
    const headers = new Headers();
    if (apiKey) headers.set("X-API-Key", apiKey);
    const res = await fetch(`/api/qlever/documents/${uuid}?format=${format}&download=true`, { headers });
    if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? res.statusText);
    const cd = res.headers.get("Content-Disposition") ?? "";
    const m = /filename="?([^";]+)"?/.exec(cd);
    const blob = await res.blob();
    return { text: await blob.text(), blob, filename: m ? m[1] : uuid };
  },
};

/** The images, with each file's last-modified day (local time) as a default date. */
function imageForm(files: File[]): FormData {
  const fd = new FormData();
  const day = (ms: number) => {
    const d = new Date(ms);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  };
  files.forEach((f) => {
    fd.append("files", f);
    fd.append("last_modified", f.lastModified ? day(f.lastModified) : "");
  });
  return fd;
}
