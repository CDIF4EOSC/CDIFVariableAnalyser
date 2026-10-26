export interface MissingRange {
  lo: string;
  hi: string;
}

export interface Concept {
  uri: string;
  pref_label: string;
}

export interface Variable {
  name: string;
  label: string | null;
  format: string;
  type: string;
  measure: string;
  numeric: boolean;
  value_labels: Record<string, string>;
  missing: MissingRange[];
  default_role: string;
  unit_of_measure: string | null;
  concepts: Concept[];
  /** Variable functions (DDI-CDI InstanceVariable.function), e.g. ["Weight"]; empty for most substantive variables. */
  functions: string[];
}

export type EnrichKind = "unit" | "concept" | "role" | "function" | "measure";
export const ENRICH_KINDS: EnrichKind[] = ["unit", "concept", "role", "function", "measure"];

/** A pending AI suggestion for one variable; a key is absent when that kind was not requested. */
export interface Suggestion {
  unit_of_measure?: string | null;
  concepts?: Concept[];
  /** Comma-joined DDI-CDI role(s), e.g. "identifier" or "measure,attribute". */
  role?: string;
  /** Full replacement list; [] means "no function applies". */
  functions?: string[];
  /** Level of measurement: "nominal" | "ordinal" | "scale". */
  measure?: string;
}

export interface EnrichResponse {
  suggestions: { name: string; unit_of_measure?: string | null; concepts?: Concept[] | null; role?: string | null; functions?: string[] | null; measure?: string | null }[];
  errors: { name: string | null; kind: string; message: string }[];
}

export interface FileInfo {
  file_id: string;
  filename: string;
  file_format: string;
  number_rows: number;
  number_variables: number;
  encoding: string | null;
  file_label: string | null;
  delimiter: string | null;
  sentinels_in_data: boolean;
  variables: Variable[];
  preview: Record<string, string>[];
}

export interface PreviewPage {
  columns: string[];
  rows: string[][];
  offset: number;
  total_rows: number;
}

export interface Options {
  includeRows: boolean;
  maxRows: number;
  allRows: boolean;
  includeStatistics: boolean;
  /** Which statistics land in the document; a subset of ALL_STAT_NAMES. */
  statistics: string[];
  apiKey: string;
}

/** Body of POST /output and POST /generate. */
export interface OutputBody {
  max_rows: number;
  process_all_rows: boolean;
  include_statistics?: boolean;
  /** Weight variable for the emitted statistics, or "auto"; null/undefined = unweighted. */
  statistics_weight?: string | null;
  /** Which statistics to emit; omitted = all of them. */
  statistics_include?: string[];
}

export interface Element {
  "@id": string;
  "@type": string;
  [key: string]: unknown;
}

/** What the download writes: DDI-CDI JSON-LD, or the same document converted to CDIF. */
export type OutputFormat = "ddicdi" | "cdif";

export interface JsonLdDoc {
  "@context": unknown;
  DDICDIModels: Element[];
  [key: string]: unknown;
}

export type ChangeKind = "added" | "changed" | "removed" | "same";

export const ROLE_OPTIONS = [
  "measure",
  "identifier",
  "attribute",
  "measure,identifier",
  "measure,attribute",
  "identifier,attribute",
  "measure,identifier,attribute",
];

/** Vocabulary of the n8n function-enrichment workflow (DDI-CDI InstanceVariable.function). Other names are accepted by the API. */
export const FUNCTION_OPTIONS: { name: string; label: string; hint: string }[] = [
  { name: "UnitIdentifier", label: "Unit identifier", hint: "Identifies the unit (case) the data point describes: respondent id, household id, case number" },
  { name: "GeographicDimension", label: "Geographic dimension", hint: "Places the data point in a geography: country, region, NUTS code, municipality" },
  { name: "TemporalDimension", label: "Temporal dimension", hint: "Places the data point in time: reference year, survey round, wave, interview date" },
  { name: "Weight", label: "Weight", hint: "A weighting factor applied in analysis: design, post-stratification or population weight" },
  { name: "SamplingDesign", label: "Sampling design", hint: "Position of the unit in the sample design: PSU, stratum, cluster, replicate" },
];

export function functionLabel(name: string): string {
  const known = FUNCTION_OPTIONS.find((f) => f.name === name);
  return known ? known.label : name.replace(/([a-z])([A-Z])/g, "$1 $2");
}

export function sameFunctions(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

export const MEASURE_OPTIONS = ["nominal", "ordinal", "scale", "unknown"];
export const TYPE_OPTIONS = ["double", "float", "int8", "int16", "int32", "string", "datetime", "boolean", "numeric"];

/** Like SPSS: only a non-integer numeric type takes decimal places; string, date, boolean and integer types are fixed at 0. */
export function typeHasDecimals(type: string): boolean {
  return type === "double" || type === "float" || type === "numeric";
}

export function roleLabel(role: string): string {
  return role
    .split(",")
    .map((r) => r.charAt(0).toUpperCase() + r.slice(1))
    .join(", ");
}

// -- statistics (qsv stats / qsv frequency); not part of the DDI-CDI output ----------

export type StatKind = "numeric" | "categorical" | "text" | "empty";

/** One statistic, named with its DDI-CDI SummaryStatisticType term. */
export interface SummaryStat {
  name: string;
  value: string;
}

export interface VariableStats {
  name: string;
  label: string | null;
  kind: StatKind;
  /** Storage type is numeric. Independent of `kind`: a labelled 0-10 scale is both. */
  numeric: boolean;
  qsv_type: string;
  valid_n: number;
  missing_n: number;
  cardinality: number | null;
  cardinality_capped: boolean;
  has_categories: boolean;
  is_weight: boolean;
  sentinel_codes: string[];
  stats: SummaryStat[];
}

export interface Statistics {
  file_id: string;
  total_rows: number;
  weight: string | null;
  weight_candidates: string[];
  /** True when user-missing codes are already out of the data (readstat imports). */
  excludes_sentinels: boolean;
  /** True when --everything was skipped because the file is large. */
  degraded: boolean;
  elapsed_ms: number;
  variables: VariableStats[];
}

export interface Category {
  code: string;
  label: string | null;
  /** Float: weighted counts are fractional. */
  count: number;
  percent: number;
  rank: number;
  sentinel: boolean;
}

export interface CategoryStats {
  name: string;
  label: string | null;
  total_rows: number;
  valid_n: number;
  valid_n_substantive: number;
  missing_n: number;
  cardinality: number | null;
  all_unique: boolean;
  truncated: boolean;
  other_count: number;
  weight: string | null;
  categories: Category[];
}

const STAT_LABELS: Record<string, string> = {
  validCases: "Valid cases", invalidCases: "Missing cases", frequency: "Count", percentage: "Percentage",
  minimum: "Min", maximum: "Max", range: "Range", mean: "Mean", median: "Median",
  mode: "Mode", standardDeviation: "Std. dev.", variance: "Variance", sum: "Sum",
  standardErrorOfMean: "Std. error", coefficientOfVariation: "Coef. of variation",
  medianAbsoluteDeviation: "Median abs. dev.", firstQuartile: "Q1", thirdQuartile: "Q3",
  interquartileRange: "IQR", skewness: "Skewness", cardinality: "Distinct",
  negativeCount: "Negative", zeroCount: "Zero", positiveCount: "Positive",
  minimumLength: "Min length", maximumLength: "Max length", averageLength: "Avg. length",
};

export function statLabel(name: string): string {
  return STAT_LABELS[name] ?? name.replace(/([a-z])([A-Z])/g, "$1 $2");
}

/** The statistics a document can carry, grouped as the Output options box ticks them.
 *  Names are the DDI-CDI terms that land in Statistics.typeOfStatistic;
 *  the server validates them against the same vocabulary (GET /api/info -> statistics). */
export const STAT_GROUPS: { key: string; title: string; hint: string; names: string[] }[] = [
  {
    key: "counts",
    title: "Case counts",
    hint: "Per variable, next to the statistics qsv computes",
    names: ["validCases", "invalidCases"],
  },
  {
    key: "centre",
    title: "Centre and spread",
    hint: "Numeric variables",
    names: ["mean", "median", "mode", "standardDeviation", "variance", "minimum", "maximum", "range", "sum"],
  },
  {
    key: "shape",
    title: "Quartiles and shape",
    hint: "Skipped on large files, where qsv streams without them",
    names: [
      "firstQuartile", "thirdQuartile", "interquartileRange", "medianAbsoluteDeviation",
      "skewness", "coefficientOfVariation", "standardErrorOfMean",
    ],
  },
  {
    key: "tally",
    title: "Value counts",
    hint: "Distinct values, and how many are negative, zero or positive",
    names: ["cardinality", "negativeCount", "zeroCount", "positiveCount"],
  },
  {
    key: "text",
    title: "Text columns",
    hint: "String lengths, the only statistics a text variable gets",
    names: ["minimumLength", "maximumLength", "averageLength"],
  },
  {
    key: "frequencies",
    title: "Frequency distribution",
    hint: "One statistic per category of every categorical variable — the qsv frequency pass",
    names: ["frequency", "percentage"],
  },
];

export const ALL_STAT_NAMES: string[] = STAT_GROUPS.flatMap((g) => g.names);

/** Which statistics earn their own column in the overview grid. Mode, sum, the
 *  quartiles and the length statistics are detail-only: they are long, and the grid
 *  is already wide. */
export const STAT_COLUMNS = ["mean", "median", "standardDeviation", "minimum", "maximum"];

export function statValue(stats: SummaryStat[], name: string): string | null {
  return stats.find((s) => s.name === name)?.value ?? null;
}

/** qsv rounds the moments to 4 decimals but passes min/max through from the source,
 *  so a design weight arrives as "0.99586856365203". Trim it for the grid; the detail
 *  list keeps what qsv returned. */
export function trimStat(value: string, decimals = 4): string {
  const n = Number(value);
  if (!Number.isFinite(n) || !/^-?\d*\.?\d+(e[-+]?\d+)?$/i.test(value.trim())) return value;
  const rounded = Number(n.toFixed(decimals));
  return String(rounded);
}
