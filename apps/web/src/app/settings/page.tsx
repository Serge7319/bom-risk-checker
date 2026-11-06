"use client";

import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import {
  fetchBillingStatus,
  fetchCompliancePack,
  fetchConnectors,
  fetchPlanUsage,
} from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";
import { workspaceDisplayName } from "@/lib/display";

type Fact = { label: string; value: string };

function labelFor(key: string): string {
  return key
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function factsFrom(
  value: Record<string, unknown> | null,
  prefix = "",
  depth = 0,
): Fact[] {
  if (!value || depth > 2) return [];
  return Object.entries(value).flatMap(([key, item]) => {
    if (/(^id$|_id$|token|secret|password|raw)/i.test(key)) return [];
    const label = prefix ? `${prefix} · ${labelFor(key)}` : labelFor(key);
    if (item && typeof item === "object" && !Array.isArray(item)) {
      return factsFrom(item as Record<string, unknown>, label, depth + 1);
    }
    let display: string;
    if (typeof item === "boolean") display = item ? "Enabled" : "Disabled";
    else if (item == null || item === "") display = "Not reported";
    else if (Array.isArray(item)) {
      display = item.length && item.every((entry) => ["string", "number", "boolean"].includes(typeof entry))
        ? item.map(String).join(" · ")
        : `${item.length} item${item.length === 1 ? "" : "s"}`;
    } else display = String(item);
    return [{ label, value: display.slice(0, 180) }];
  }).slice(0, 12);
}

function FactsGrid({ facts }: { facts: Fact[] }) {
  if (!facts.length) {
    return <p className="cv-small-note">No status details were returned.</p>;
  }
  return (
    <dl className="cv-fact-grid">
      {facts.map((fact) => (
        <div className="cv-fact" key={fact.label}>
          <dt>{fact.label}</dt>
          <dd>{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function Page() {
  const session = useRequireSession();
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [usage, setUsage] = useState<Record<string, unknown> | null>(null);
  const [billing, setBilling] = useState<Record<string, unknown> | null>(null);
  const [connectors, setConnectors] = useState<Record<string, unknown> | null>(
    null,
  );
  const [compliance, setCompliance] = useState<Record<string, unknown> | null>(
    null,
  );

  useEffect(() => {
    if (!session) return;
    setBusy(true);
    Promise.all([
      fetchPlanUsage(session.access_token),
      fetchBillingStatus(session.access_token),
      fetchConnectors(session.access_token),
      fetchCompliancePack(session.access_token, "rohs"),
    ])
      .then(([u, b, c, p]) => {
        setUsage(u);
        setBilling(b);
        setConnectors(c);
        setCompliance(p);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load settings"),
      )
      .finally(() => setBusy(false));
  }, [session]);

  if (!session) return null;

  const connectorRows = ((connectors?.connectors ||
    connectors?.items ||
    []) as Array<Record<string, unknown>>) || [];
  const usageFacts = factsFrom(usage);
  const complianceFacts = factsFrom(compliance);

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.settings}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">BOM Analyzer</PrimaryLink>
            <SecondaryLink href="/">Home</SecondaryLink>
          </>
        }
      />
      <section className="cv-card pad" style={{ marginBottom: 14 }}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="workspace-name">Workspace name</label>
            <input id="workspace-name" value={workspaceDisplayName(session.workspace)} readOnly />
          </div>
          <div className="cv-field">
            <label htmlFor="plan">Plan</label>
            <input id="plan" value={session.plan} readOnly />
          </div>
          <div className="cv-field">
            <label htmlFor="email">Signed-in email</label>
            <input id="email" value={session.email} readOnly />
          </div>
        </div>
      </section>

      {busy ? <LoadingCard label="Loading plan, billing, and connector status…" /> : null}
      {error ? <div className="cv-error" role="alert">Some workspace settings could not load. {error}</div> : null}

      {billing && typeof billing.gap === "string" ? (
        <GapBanner>{String(billing.gap)}</GapBanner>
      ) : null}

      {!busy ? (
        <>
          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <h3 className="cv-card-title">Plan usage</h3>
            <p className="cv-card-subtitle">
              Limits and usage for the signed-in workspace.
            </p>
            <FactsGrid facts={usageFacts} />
          </section>

          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <h3 className="cv-card-title">Billing status</h3>
            <p className="cv-card-subtitle">
              Checkout is not live. Status below reports readiness only — no
              charges are created from this page.
            </p>
            <dl className="cv-record-meta">
              <div className="cv-record-field">
                <dt>Stripe mode</dt>
                <dd>{String(billing?.stripe_mode || "—")}</dd>
              </div>
              <div className="cv-record-field">
                <dt>Checkout enabled</dt>
                <dd>{billing?.checkout_enabled ? "Enabled" : "Disabled"}</dd>
              </div>
              <div className="cv-record-field">
                <dt>Charges created</dt>
                <dd>{billing?.charges_created ? "Yes" : "No"}</dd>
              </div>
            </dl>
          </section>

          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <h3 className="cv-card-title">Connectors</h3>
            <p className="cv-card-subtitle">
              Design-tool and PLM/ERP connectors available to this workspace.
              Blocked items need credentials after customer discovery.
            </p>
            {connectorRows.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead>
                    <tr>
                      <th>Connector</th>
                      <th>Category</th>
                      <th>Status</th>
                      <th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {connectorRows.map((row) => (
                      <tr key={String(row.id || row.display_name)}>
                        <td>
                          <strong>
                            {String(row.display_name || row.id || "")}
                          </strong>
                        </td>
                        <td>{String(row.category || "")}</td>
                        <td>{String(row.status || "")}</td>
                        <td>
                          {String(
                            row.notes || row.decision_needed || row.gap || "—",
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState icon="settings" title="No connectors configured" body="Connector options appear here when workspace integrations are added." />
            )}
          </section>

          <section className="cv-card pad">
            <h3 className="cv-card-title">Compliance pack status</h3>
            <p className="cv-card-subtitle">
              RoHS pack readiness for this workspace. Packs stay evidence-linked
              and do not claim compliance without sourced records.
            </p>
            <FactsGrid facts={complianceFacts} />
          </section>
        </>
      ) : null}
    </Shell>
  );
}

