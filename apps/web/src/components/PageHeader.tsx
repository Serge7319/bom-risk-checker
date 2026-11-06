import Link from "next/link";
import { Icon, PAGE_ICONS, type IconName } from "@/components/Icons";
import type { PageMeta } from "@/lib/routes";

function iconForMeta(meta: PageMeta): IconName {
  const key = meta.icon || "";
  return (PAGE_ICONS[key] || "spark") as IconName;
}

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
    <header className={`cv-page-header${record ? " cv-record-header" : ""}`}>
      <div className="cv-page-head-copy">
        <div className="cv-page-head-icon" aria-hidden="true">
          <Icon name={iconForMeta(meta)} />
        </div>
        <div>
          <div className="cv-eyebrow">{meta.eyebrow}</div>
          <h1>{meta.title}</h1>
          <p className="cv-page-description">{meta.description}</p>
        </div>
      </div>
      {actions ? <div className="cv-header-actions">{actions}</div> : null}
    </header>
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
    <section className="cv-card pad cv-empty-card" role="status">
      <div className="cv-empty">
        <div className="cv-empty-icon" aria-hidden="true">
          <Icon name="box" />
        </div>
        <div>
          <h3>Not available here yet</h3>
          <p>
            {capability} Use BOM Analyzer to review a report using the evidence
            available in your workspace.
          </p>
          {nextStep ? <div className="cv-empty-actions">{nextStep}</div> : null}
        </div>
      </div>
    </section>
  );
}
