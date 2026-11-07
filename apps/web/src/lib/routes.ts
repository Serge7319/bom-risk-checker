export type NavItem = {
  href: string;
  label: string;
  id: string;
};

export type NavGroup = {
  label: string;
  items: NavItem[];
};

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { id: "home", href: "/", label: "Home" },
      { id: "bom", href: "/bom-analyzer", label: "BOM Analyzer" },
      { id: "decisions", href: "/engineering-decisions", label: "Engineering Decisions" },
      { id: "monitoring", href: "/monitoring", label: "Monitoring" },
      { id: "replacement", href: "/find-replacement", label: "Find a replacement" },
      { id: "reports", href: "/reports", label: "Reports" },
    ],
  },
  {
    label: "Decision tools",
    items: [
      { id: "compare", href: "/compare-parts", label: "Compare Parts" },
      { id: "qa", href: "/datasheet-qa", label: "Datasheet Q&A" },
      { id: "procurement", href: "/procurement", label: "Procurement Advisor" },
      { id: "design", href: "/design-impact", label: "Design Impact Analyzer" },
      { id: "cost", href: "/cost-optimization", label: "Cost Optimization" },
      { id: "supply", href: "/supply-risk", label: "Supply Risk Scenario" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { id: "portfolio", href: "/portfolio-intelligence", label: "Portfolio Intelligence" },
      { id: "risk", href: "/detailed-risk-report", label: "Detailed Risk Report" },
      { id: "ei", href: "/engineering-intelligence", label: "Engineering Intelligence" },
    ],
  },
  {
    label: "Workspace admin",
    items: [
      { id: "reports", href: "/single-bom-report", label: "One-time BOM report" },
      { id: "settings", href: "/settings", label: "Settings" },
    ],
  },
];

export type PageMeta = {
  title: string;
  eyebrow: string;
  description: string;
  icon?: string;
};

export const PAGE_META: Record<string, PageMeta> = {
  home: {
    icon: "home",
    title: "Home",
    eyebrow: "Portfolio overview",
    description:
      "A clear view of engineering priorities across your saved BOMs.",
  },
  bom: {
    icon: "bom",
    title: "BOM Analyzer",
    eyebrow: "Analysis workspace",
    description:
      "Upload a BOM, review evidence quality, and open a traceable engineering report.",
  },
  decisions: {
    icon: "decisions",
    title: "Engineering Decisions",
    eyebrow: "Decision queue",
    description:
      "Review the highest-impact component decisions and the evidence behind each one.",
  },
  monitoring: {
    icon: "monitoring",
    title: "Monitoring",
    eyebrow: "Alerts & monitoring",
    description:
      "Review lifecycle, inventory, pricing, and supplier changes across monitored components.",
  },
  replacement: {
    icon: "replacement",
    title: "Find a replacement",
    eyebrow: "Replacement search",
    description:
      "Find candidate parts and see which fit requirements are supported by evidence.",
  },
  reports: {
    icon: "reports",
    title: "Reports",
    eyebrow: "Saved reports",
    description:
      "Open saved BOM analyses, review component evidence, and download a CSV report.",
  },
  compare: {
    icon: "compare",
    title: "Compare Parts",
    eyebrow: "Side-by-side comparison",
    description:
      "Compare two parts using saved analysis fields and clearly labeled offline catalog evidence.",
  },
  qa: {
    icon: "qa",
    title: "Datasheet Q&A",
    eyebrow: "Datasheet workspace",
    description:
      "Ask focused questions and inspect the page citations behind each answer.",
  },
  procurement: {
    icon: "procurement",
    title: "Procurement Advisor",
    eyebrow: "Sourcing workspace",
    description:
      "Review supplier coverage, availability, pricing, and sourcing next steps.",
  },
  design: {
    icon: "design",
    title: "Design Impact Analyzer",
    eyebrow: "Design impact",
    description:
      "Trace a component change through saved BOMs, projects, and affected decisions.",
  },
  cost: {
    icon: "cost",
    title: "Cost Optimization",
    eyebrow: "Price harmonization",
    description:
      "Review saved sample prices and model volume opportunities; supplier prices are not live quotes.",
  },
  supply: {
    icon: "supply",
    title: "Supply Risk Scenario",
    eyebrow: "Supply scenario",
    description:
      "Model a supplier or inventory disruption against recorded portfolio evidence.",
  },
  portfolio: {
    icon: "portfolio",
    title: "Portfolio Intelligence",
    eyebrow: "Portfolio intelligence",
    description:
      "Understand lifecycle exposure, evidence coverage, and decision readiness across BOMs.",
  },
  risk: {
    icon: "risk",
    title: "Detailed Risk Report",
    eyebrow: "Detailed risk report",
    description:
      "A component-level view of risk signals, source quality, and recommended review.",
  },
  ei: {
    icon: "ei",
    title: "Engineering Intelligence",
    eyebrow: "Engineering report",
    description:
      "Review the saved analysis, component signals, and source-backed exceptions.",
  },
  settings: {
    icon: "settings",
    title: "Settings",
    eyebrow: "Workspace settings",
    description:
      "Review account, plan usage, and integration readiness.",
  },
  single_bom_report: {
    icon: "reports",
    title: "One-time BOM report",
    eyebrow: "Single report purchase",
    description:
      "Purchase one complete BOM analysis without starting a recurring subscription.",
  },
  record: {
    title: "Engineering decision record",
    eyebrow: "Decision record",
    description:
      "A durable record of the evidence, reviewer decision, rationale, and release impact.",
  },
};
