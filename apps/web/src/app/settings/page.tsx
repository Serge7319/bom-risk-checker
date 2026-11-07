"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import {
  fetchBillingStatus,
  beginBillingPortal,
  beginSubscriptionCheckout,
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
  const [billingAction, setBillingAction] = useState("");
  const [billingError, setBillingError] = useState("");

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
  const planCatalog = Array.isArray(billing?.plan_catalog)
    ? billing.plan_catalog as Array<Record<string, unknown>>
    : [];
  const stripePlans = Array.isArray(billing?.plans)
    ? billing.plans as Array<Record<string, unknown>>
    : [];
  const currentPlanName = String(billing?.current_plan || usage?.plan || session.plan);
  const currentPlan = currentPlanName.toLowerCase();
  const canManageBilling = billing?.can_manage_billing === true;
  const checkoutEnabled = billing?.checkout_enabled === true;

  async function selectPlan(plan: Record<string, unknown>) {
    if (!session) return;
    const name = String(plan.name || "");
    const token = String(plan.purchase_token || "");
    setBillingAction(name);
    setBillingError("");
    try {
      const result = canManageBilling
        ? await beginBillingPortal(session.access_token)
        : await beginSubscriptionCheckout(session.access_token, token);
      const url = result.checkout?.url;
      if (!result.ok || !url) {
        throw new Error(result.detail || "Secure billing could not be opened.");
      }
      window.location.assign(url);
    } catch (err) {
      setBillingError(err instanceof Error ? err.message : "Secure billing could not be opened.");
      setBillingAction("");
    }
  }

  async function openBillingPortal() {
    if (!session) return;
    setBillingAction("portal");
    setBillingError("");
    try {
      const result = await beginBillingPortal(session.access_token);
      if (!result.ok || !result.checkout?.url) {
        throw new Error(result.detail || "Billing settings could not be opened.");
      }
      window.location.assign(result.checkout.url);
    } catch (err) {
      setBillingError(err instanceof Error ? err.message : "Billing settings could not be opened.");
      setBillingAction("");
    }
  }

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.settings}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">BOM Analyzer</PrimaryLink>
            <SecondaryLink href="/single-bom-report">One-time report</SecondaryLink>
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

      {!busy ? (
        <>
          <section className="cv-card pad cv-plan-section" style={{ marginBottom: 14 }}>
            <div className="cv-section-heading">
              <div>
                <h3 className="cv-card-title">Plans and billing</h3>
                <p className="cv-card-subtitle">
                  Your plan controls analysis limits, monitoring, and team access. Paid plans bill monthly through Stripe.
                </p>
              </div>
              {canManageBilling ? (
                <button className="cv-button" type="button" onClick={() => void openBillingPortal()} disabled={Boolean(billingAction)}>
                  {billingAction === "portal" ? "Opening billing…" : "Manage subscription"}
                </button>
              ) : null}
            </div>
            <p className="cv-current-plan" role="status">
              Current access: <strong>{currentPlanName}</strong>
              {session.trial_days_remaining != null && currentPlanName.toLowerCase() === "trial"
                ? ` · ${session.trial_days_remaining} days remaining`
                : ""}
            </p>
            <div className="cv-plan-grid">
              {planCatalog.map((plan) => {
                const name = String(plan.name || "");
                const token = String(plan.purchase_token || "");
                const current = currentPlan === name.toLowerCase();
                const providerPlan = stripePlans.find((row) => String(row.name || "") === name);
                const hasPrice = Boolean(providerPlan?.enabled);
                const paidPlan = Boolean(token);
                const enterprise = name === "Enterprise";
                const limit = (value: unknown) => value == null ? "Unlimited" : String(value);
                const bullets = [
                  `${limit(plan.monthly_bom_limit)} BOM analyses per month`,
                  `${limit(plan.max_parts_per_bom)} components per BOM`,
                  `${limit(plan.max_saved_boms)} saved BOMs`,
                  Number(plan.monitored_parts_limit) > 0 || plan.monitored_parts_limit == null
                    ? `${limit(plan.monitored_parts_limit)} monitored parts`
                    : "Monitoring not included",
                  Number(plan.ai_credits) > 0 ? `${limit(plan.ai_credits)} Ask Cadivor credits` : "Ask Cadivor not included",
                  plan.team_features ? "Team collaboration" : "Individual workspace",
                  Number(plan.included_users) > 0 ? `${limit(plan.included_users)} users included` : "",
                  plan.datasheet_comparison ? "Datasheet comparison" : "",
                  plan.api_access ? "API access" : "",
                ].filter(Boolean);
                let actionText = "Choose plan";
                if (current) actionText = "Current plan";
                else if (canManageBilling) actionText = "Change plan in billing";
                else if (!checkoutEnabled || !hasPrice) actionText = "Temporarily unavailable";
                if (enterprise) actionText = "Contact sales";
                if (name === "Student" && !current) actionText = "Student plan";
                return (
                  <article className={`cv-plan-option${current ? " current" : ""}${name === "Professional" ? " featured" : ""}`} key={name}>
                    <div className="cv-plan-option-top">
                      <h4>{name}</h4>
                      {name === "Professional" ? <span className="cv-plan-popular">Most popular</span> : null}
                    </div>
                    <div className="cv-plan-price">{String(plan.price || "Contact us")}</div>
                    <p>{String(plan.description || "")}</p>
                    <ul>{bullets.map((item) => <li key={item}>{item}</li>)}</ul>
                    {enterprise ? (
                      <a className="cv-button" href="mailto:sales@cadivor.com?subject=Cadivor%20Enterprise%20plans">{actionText}</a>
                    ) : (
                      <button
                        className={current ? "cv-button" : "cv-button primary"}
                        type="button"
                        disabled={current || !paidPlan || (!canManageBilling && (!checkoutEnabled || !hasPrice)) || Boolean(billingAction)}
                        onClick={() => void selectPlan(plan)}
                        title={paidPlan && !hasPrice ? "This Stripe price is not active or does not match the published monthly plan." : undefined}
                      >
                        {billingAction === name ? "Opening secure checkout…" : actionText}
                      </button>
                    )}
                  </article>
                );
              })}
            </div>
            {billingError ? <div className="cv-error" role="alert" style={{ marginTop: 12 }}>{billingError}</div> : null}
            {typeof billing?.gap === "string" ? <p className="cv-small-note" style={{ marginTop: 12 }}>{String(billing.gap)}</p> : null}
            <p className="cv-small-note" style={{ marginTop: 12 }}>
              Need a single paid BOM report instead of a subscription? <Link href="/single-bom-report">View the one-time report option</Link>.
            </p>
          </section>

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
              Subscription checkout status is shown below. The one-time BOM report is a separate purchase and does not start a recurring plan.
            </p>
            <dl className="cv-record-meta">
              <div className="cv-record-field">
                <dt>Subscription</dt>
                <dd>{String(billing?.subscription_status || "No active subscription").replace(/_/g, " ")}</dd>
              </div>
              <div className="cv-record-field">
                <dt>Monthly checkout</dt>
                <dd>{checkoutEnabled ? "Available" : "Unavailable"}</dd>
              </div>
            </dl>
            <div style={{ marginTop: 14 }}>
              <SecondaryLink href="/single-bom-report">View one-time BOM report and purchase history</SecondaryLink>
            </div>
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

