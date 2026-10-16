import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };
const base = (size: number, p: P) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  ...p,
});

export const IconPlus = ({ size = 14, ...p }: P) => (
  <svg {...base(size, p)} strokeWidth={2.4}><path d="M12 5v14M5 12h14" /></svg>
);
export const IconX = ({ size = 14, ...p }: P) => (
  <svg {...base(size, p)} strokeWidth={2.2}><path d="M18 6 6 18M6 6l12 12" /></svg>
);
export const IconSearch = ({ size = 14, ...p }: P) => (
  <svg {...base(size, p)}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
);
export const IconDownload = ({ size = 14, ...p }: P) => (
  <svg {...base(size, p)} strokeWidth={2.2}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m7 10 5 5 5-5" /><path d="M12 15V3" /></svg>
);
export const IconUpload = ({ size = 26, ...p }: P) => (
  <svg {...base(size, p)}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="m17 8-5-5-5 5" /><path d="M12 3v12" /></svg>
);
export const IconChevron = ({ size = 14, ...p }: P) => (
  <svg {...base(size, p)} strokeWidth={2.2}><path d="m6 9 6 6 6-6" /></svg>
);
export const IconUndo = ({ size = 15, ...p }: P) => (
  <svg {...base(size, p)}><path d="M9 14 4 9l5-5" /><path d="M4 9h11a5 5 0 0 1 0 10h-3" /></svg>
);
export const IconRedo = ({ size = 15, ...p }: P) => (
  <svg {...base(size, p)}><path d="m15 14 5-5-5-5" /><path d="M20 9H9a5 5 0 0 0 0 10h3" /></svg>
);
export const IconCode = ({ size = 14, ...p }: P) => (
  <svg {...base(size, p)}><path d="m16 18 6-6-6-6" /><path d="m8 6-6 6 6 6" /></svg>
);
export const IconSettings = ({ size = 14, ...p }: P) => (
  <svg {...base(size, p)}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>
);
export const IconCopy = ({ size = 14, ...p }: P) => (
  <svg {...base(size, p)}><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></svg>
);
export const IconTrash = ({ size = 14, ...p }: P) => (
  <svg {...base(size, p)}><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14" /></svg>
);
export const IconFile = ({ size = 14, ...p }: P) => (
  <svg {...base(size, p)}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6" /></svg>
);
export const IconLogo = ({ size = 16, ...p }: P) => (
  <svg {...base(size, p)} stroke="#0f172a" strokeWidth={2.4}><path d="M4 6h16M4 12h10M4 18h16" /></svg>
);
export const IconTags = ({ size = 13, ...p }: P) => (
  <svg {...base(size, p)}><path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z" /><circle cx="7" cy="7" r="1.5" /></svg>
);
export const IconSpinner = ({ size = 26, ...p }: P) => (
  <svg {...base(size, p)} className={`spin ${p.className ?? ""}`} aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.2-8.56" /></svg>
);
export const IconClose = IconX;
