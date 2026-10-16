/** EU Publications Office measurement-unit authority table (same subset as the SoGreen provenance editor). */
export const BASE_UNIT_URI = "http://publications.europa.eu/resource/authority/measurement-unit/";

export interface UnitOption {
  code: string;
  label: string;
  alt: string; // symbol
}

export const UNIT_OPTIONS: UnitOption[] = [
  { code: "2N", label: "decibel", alt: "dB" },
  { code: "3C", label: "manmonth", alt: "man-month" },
  { code: "AD", label: "byte", alt: "B" },
  { code: "AMP", label: "ampere", alt: "A" },
  { code: "BAR", label: "bar", alt: "bar" },
  { code: "BIT", label: "bit", alt: "b" },
  { code: "BQL", label: "becquerel", alt: "Bq" },
  { code: "C34", label: "mole", alt: "mol" },
  { code: "C45", label: "nanometre", alt: "nm" },
  { code: "CDL", label: "candela", alt: "cd" },
  { code: "CEL", label: "degree Celsius", alt: "°C" },
  { code: "CMK", label: "square centimetre", alt: "cm²" },
  { code: "CMQ", label: "cubic centimetre", alt: "cm³" },
  { code: "CMT", label: "centimetre", alt: "cm" },
  { code: "D30", label: "terajoule", alt: "TJ" },
  { code: "E34", label: "gigabyte", alt: "GB" },
  { code: "GRM", label: "gram", alt: "g" },
  { code: "GTE", label: "gross tonnage", alt: "GT" },
  { code: "GWH", label: "gigawatt-hour", alt: "GWh" },
  { code: "H87", label: "piece", alt: "pce" },
  { code: "HAR", label: "hectare", alt: "ha" },
  { code: "HLT", label: "hectolitre", alt: "hl" },
  { code: "HTZ", label: "hertz", alt: "Hz" },
  { code: "HUR", label: "hour", alt: "h" },
  { code: "JOU", label: "joule", alt: "J" },
  { code: "KEL", label: "kelvin", alt: "K" },
  { code: "KGM", label: "kilogram", alt: "kg" },
  { code: "KMH", label: "kilometre per hour", alt: "km/h" },
  { code: "KMK", label: "square kilometre", alt: "km²" },
  { code: "KTM", label: "kilometre", alt: "km" },
  { code: "KWH", label: "kilowatt-hour", alt: "kWh" },
  { code: "KWT", label: "kilowatt", alt: "kW" },
  { code: "LH", label: "labour hour", alt: "LH" },
  { code: "LTR", label: "litre", alt: "l" },
  { code: "MAW", label: "megawatt", alt: "MW" },
  { code: "MC", label: "microgram", alt: "µg" },
  { code: "MGM", label: "milligram", alt: "mg" },
  { code: "MIN", label: "minute", alt: "min" },
  { code: "MLT", label: "millilitre", alt: "ml" },
  { code: "MMT", label: "millimetre", alt: "mm" },
  { code: "MTK", label: "square metre", alt: "m²" },
  { code: "MTR", label: "metre", alt: "m" },
  { code: "MTS", label: "metre per second", alt: "m/s" },
  { code: "NEW", label: "newton", alt: "N" },
  { code: "PAL", label: "pascal", alt: "Pa" },
  { code: "SEC", label: "second", alt: "s" },
  { code: "TKM", label: "tonne-kilometre", alt: "tkm" },
  { code: "TNE", label: "tonne", alt: "t" },
  { code: "TOE", label: "tonne of oil equivalent", alt: "toe" },
  { code: "VLT", label: "volt", alt: "V" },
  { code: "WTT", label: "watt", alt: "W" },
];

export function unitUri(code: string): string {
  return BASE_UNIT_URI + code;
}

const BY_URI = new Map(UNIT_OPTIONS.map((u) => [unitUri(u.code), u]));

/** "h · hour" for a known unit, otherwise the URI tail. */
export function unitLabel(uri: string | null | undefined): string {
  if (!uri) return "";
  const u = BY_URI.get(uri);
  return u ? `${u.alt} · ${u.label}` : uri.replace(/\/$/, "").split("/").pop() ?? uri;
}

export function isKnownUnit(uri: string | null | undefined): boolean {
  return !!uri && BY_URI.has(uri);
}
