"use client";

import { FormEvent, useState } from "react";
import { Shell } from "@/components/Shell";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { useRequireSession } from "@/lib/session";
import { fetchAdminAccountEntitlements, updateAdminAccountEntitlements } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";

const FEATURES = [
  { key: "api_access", label: "API access", hint: "Enable developer API access for this account." },
  { key: "team_features", label: "Team features", hint: "Enable paid collaboration features." },
  { key: "datasheet_comparison", label: "Datasheet comparison", hint: "Enable datasheet comparison tools." },
  { key: "can_create_analyses", label: "Create analyses", hint: "Allow new BOM analyses even if the plan blocks them." },
] as const;

type OverrideChoice = "default" | "enabled" | "disabled";
type OverrideMap = Record<string, OverrideChoice>;

function choicesFrom(values: Record<string, boolean>): OverrideMap {
  return Object.fromEntries(FEATURES.map(({ key }) => [
    key,
    typeof values[key] === "boolean" ? (values[key] ? "enabled" : "disabled") : "default",
  ]));
}

function payloadFrom(values: OverrideMap): Record<string, boolean> {
  return Object.fromEntries(Object.entries(values)
    .filter(([, value]) => value !== "default")
    .map(([key, value]) => [key, value === "enabled"]));
}

export default function AccountEntitlementsPage() {
  const session = useRequireSession();
  const [email, setEmail] = useState("");
  const [accountEmail, setAccountEmail] = useState("");
  const [choices, setChoices] = useState<OverrideMap>(choicesFrom({}));
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    setBusy("load");
    setError("");
    setNotice("");
    try {
      const result = await fetchAdminAccountEntitlements(session.access_token, email.trim());
      setAccountEmail(result.account.email);
      setChoices(choicesFrom(result.account.feature_overrides || {}));
    } catch (err) {
      setAccountEmail("");
      setError(err instanceof Error ? err.message : "Could not load account entitlements.");
    } finally {
      setBusy("");
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !accountEmail) return;
    setBusy("save");
    setError("");
    setNotice("");
    try {
      const result = await updateAdminAccountEntitlements(
        session.access_token,
        accountEmail,
        payloadFrom(choices),
      );
      setChoices(choicesFrom(result.account.feature_overrides || {}));
      setNotice("Account feature overrides saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save account entitlements.");
    } finally {
      setBusy("");
    }
  }

  if (!session) return null;
  if (session.platform_role !== "admin") {
    return <Shell session={session}><PageHeader meta={PAGE_META.settings} /><div className="cv-error" role="alert">Platform administrator access is required.</div></Shell>;
  }

  return (
    <Shell session={session}>
      <PageHeader meta={PAGE_META.settings} actions={<SecondaryLink href="/settings">Settings</SecondaryLink>} />
      <section className="cv-card pad" style={{ maxWidth: 860, margin: "0 auto" }}>
        <h2 className="cv-card-title">Account entitlement controls</h2>
        <p className="cv-card-subtitle">Set explicit feature overrides for one account. “Use plan default” removes an override. These controls do not change the customer’s Stripe plan or price.</p>
        <form className="cv-form-grid" onSubmit={load} style={{ marginTop: 16 }}>
          <div className="cv-field">
            <label htmlFor="entitlement-email">Account email</label>
            <input id="entitlement-email" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
          </div>
          <div style={{ alignSelf: "end" }}><button className="cv-button" type="submit" disabled={busy !== ""}>{busy === "load" ? "Loading…" : "Load account"}</button></div>
        </form>
        {error ? <div className="cv-error" role="alert" style={{ marginTop: 12 }}>{error}</div> : null}
        {notice ? <div className="cv-evidence-context" role="status" style={{ marginTop: 12 }}>{notice}</div> : null}
        {accountEmail ? (
          <form onSubmit={save} style={{ marginTop: 20 }}>
            <h3 className="cv-card-title">{accountEmail}</h3>
            <div className="cv-admin-entitlement-list">
              {FEATURES.map((feature) => (
                <label className="cv-admin-entitlement-row" key={feature.key} htmlFor={`entitlement-${feature.key}`}>
                  <span><strong>{feature.label}</strong><small>{feature.hint}</small></span>
                  <select
                    id={`entitlement-${feature.key}`}
                    value={choices[feature.key] || "default"}
                    onChange={(event) => setChoices((current) => ({ ...current, [feature.key]: event.target.value as OverrideChoice }))}
                  >
                    <option value="default">Use plan default</option>
                    <option value="enabled">Enabled</option>
                    <option value="disabled">Disabled</option>
                  </select>
                </label>
              ))}
            </div>
            <button className="cv-button primary" type="submit" disabled={busy !== ""} style={{ marginTop: 16 }}>{busy === "save" ? "Saving…" : "Save overrides"}</button>
          </form>
        ) : null}
      </section>
    </Shell>
  );
}
