import type { ReactNode, SVGProps } from "react";

export type IconName =
  | "home"
  | "upload"
  | "decisions"
  | "monitor"
  | "search"
  | "report"
  | "compare"
  | "file"
  | "procure"
  | "impact"
  | "cost"
  | "risk"
  | "portfolio"
  | "insight"
  | "settings"
  | "plus"
  | "arrow"
  | "clock"
  | "shield"
  | "spark"
  | "download"
  | "check"
  | "box"
  | "bell"
  | "menu";

const glyph: Record<IconName, ReactNode> = {
  home: (
    <>
      <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z" />
    </>
  ),
  upload: (
    <>
      <path d="M12 16V4m-4 4 4-4 4 4" />
      <path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
    </>
  ),
  decisions: (
    <>
      <path d="M7 3h10l4 4v14H7z" />
      <path d="M17 3v5h4M10 13h8M10 17h6" />
    </>
  ),
  monitor: <path d="M3 12h4l3-7 4 14 3-7h4" />,
  search: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 5 5" />
    </>
  ),
  report: (
    <>
      <path d="M5 3h10l4 4v14H5z" />
      <path d="M15 3v5h4M8 12h8M8 16h8" />
    </>
  ),
  compare: (
    <>
      <path d="M4 5h7M4 12h7M4 19h7M15 5h5M15 12h5M15 19h5" />
      <path d="m13 3 2 2-2 2M11 10l2 2-2 2M13 17l2 2-2 2" />
    </>
  ),
  file: (
    <>
      <path d="M6 3h9l4 4v14H6z" />
      <path d="M15 3v5h4M9 13h7M9 17h7" />
    </>
  ),
  procure: (
    <>
      <path d="M4 7h16l-2 13H6z" />
      <path d="M9 7a3 3 0 0 1 6 0M9 11v2M15 11v2" />
    </>
  ),
  impact: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  cost: (
    <>
      <path d="M4 19V5M4 19h17" />
      <path d="m7 15 4-4 3 2 5-6" />
    </>
  ),
  risk: (
    <>
      <path d="M12 3 2.8 20h18.4z" />
      <path d="M12 9v5M12 17.5v.2" />
    </>
  ),
  portfolio: (
    <>
      <rect x="3" y="4" width="8" height="7" rx="1" />
      <rect x="13" y="4" width="8" height="7" rx="1" />
      <rect x="3" y="13" width="8" height="7" rx="1" />
      <rect x="13" y="13" width="8" height="7" rx="1" />
    </>
  ),
  insight: (
    <>
      <path d="M4 19V5M4 19h17" />
      <path d="M7 15l4-5 3 2 5-7" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.3.6.9 1 1.6 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  spark: <path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7z" />,
  download: (
    <>
      <path d="M12 4v11m-4-4 4 4 4-4" />
      <path d="M5 20h14" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  box: (
    <>
      <path d="m12 3 9 5-9 5-9-5z" />
      <path d="M3 8v9l9 5 9-5V8M12 13v9" />
    </>
  ),
  bell: (
    <>
      <path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
      <path d="M10 21h4" />
    </>
  ),
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
};

export function Icon({
  name,
  className,
  ...rest
}: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...rest}
    >
      {glyph[name] || glyph.spark}
    </svg>
  );
}

export const NAV_ICONS: Record<string, IconName> = {
  home: "home",
  bom: "upload",
  decisions: "decisions",
  monitoring: "monitor",
  replacement: "search",
  reports: "report",
  compare: "compare",
  qa: "file",
  procurement: "procure",
  design: "impact",
  cost: "cost",
  supply: "risk",
  portfolio: "portfolio",
  risk: "risk",
  ei: "insight",
  settings: "settings",
};

export const PAGE_ICONS = NAV_ICONS;
