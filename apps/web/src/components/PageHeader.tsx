import Link from "next/link";
import type { PageMeta } from "@/lib/routes";

export function PageHeader({
  meta,
  actions,
  record,
}: {
  meta: PageMeta;
  actions?: React.ReactNode;
  record?: boolean;
}) {
  return (
    <div className={`cv-page-header${record ? " cv-record-header" : ""}`}>
      <div>
        <div className="cv-eyebrow">{meta.eyebrow}</div>
        <h1>{meta.title}</h1>
        <p className="cv-page-description">{meta.description}</p>
      </div>
      {actions ? <div className="cv-header-actions">{actions}</div> : null}
    </div>
  );
}

export function PrimaryLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link className="cv-button primary" href={href}>
      {children}
    </Link>
  );
}

export function SecondaryLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <Link className="cv-button" href={href}>
      {children}
    </Link>
  );
}

export function CapabilityStub({
  capability,
  nextStep,
}: {
  capability: string;
  nextStep?: React.ReactNode;
}) {
  return (
    <section className="cv-card pad cv-empty">
      <strong style={{ display: "block", color: "#19304f", marginBottom: 6 }}>
        Not available here yet
      </strong>
      <p style={{ margin: 0 }}>
        {capability} Use BOM Analyzer to review a report using the evidence
        available in your workspace.
      </p>
      {nextStep ? <div style={{ marginTop: 14 }}>{nextStep}</div> : null}
    </section>
  );
}
