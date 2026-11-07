"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import {
  beginBillingPortal,
  beginSubscriptionCheckout,
  cancelWorkspaceInvitation,
  changePassword,
  createWorkspace,
  createWorkspaceInvitation,
  fetchBillingStatus,
  fetchCompliancePack,
  fetchConnectors,
  fetchPlanUsage,
  fetchServiceReadiness,
  type ServiceReadiness,
  fetchPreferences,
  fetchProfile,
  fetchSecurityStatus,
  fetchWorkspaceSettings,
  listWorkspaceActivity,
  listWorkspaceInvitations,
  listWorkspaceMembers,
  listWorkspaces,
  requestPasswordReset,
  resendWorkspaceInvitation,
  revokeOtherSessions,
  switchWorkspace,
  updatePreferences,
  updateProfile,
  updateWorkspaceSettings,
} from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";
import { workspaceDisplayName } from "@/lib/display";

type TabId = "profile" | "preferences" | "workspace" | "security" | "billing";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "profile", label: "Profile" },
  { id: "preferences", label: "Preferences" },
  { id: "workspace", label: "Workspace" },
  { id: "security", label: "Security" },
  { id: "billing", label: "Billing" },
];

const NOTIFICATION_LABELS: Array<{ key: string; label: string; hint: string }> = [
  { key: "project_activity", label: "Project activity", hint: "BOM uploads and analysis updates" },
  { key: "simulation_results", label: "Simulation results", hint: "Scenario and risk simulations" },
  { key: "team_activity", label: "Team activity", hint: "Member joins, role changes, invites" },
  { key: "product_updates", label: "Product updates", hint: "Cadivor product announcements" },
  { key: "marketing_emails", label: "Marketing emails", hint: "Occasional product education" },
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asRows(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

function settingsErrorMessage(err: unknown, fallback: string): string {
  const raw = err instanceof Error ? err.message : "";
  if (!raw || /failed to fetch/i.test(raw) || raw === "NetworkError when attempting to fetch resource.") {
    return "Could not reach Cadivor. Check your connection and try again.";
  }
  return raw || fallback;
}

async function settledValue<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch {
    return null;
  }
}

function Toggle({
  id,
  checked,
  onChange,
  label,
  hint,
}: {
  id: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <label className="cv-settings-toggle" htmlFor={id}>
      <span>
        <strong>{label}</strong>
        {hint ? <small>{hint}</small> : null}
      </span>
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}

export default function Page() {
  const session = useRequireSession();
  const [tab, setTab] = useState<TabId>("profile");
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [profile, setProfile] = useState<Record<string, unknown>>({});
  const [preferences, setPreferences] = useState<Record<string, unknown>>({});
  const [security, setSecurity] = useState<Record<string, unknown>>({});
  const [workspace, setWorkspace] = useState<Record<string, unknown>>({});
  const [workspaces, setWorkspaces] = useState<Array<Record<string, unknown>>>([]);
  const [members, setMembers] = useState<Array<Record<string, unknown>>>([]);
  const [invites, setInvites] = useState<Array<Record<string, unknown>>>([]);
  const [activity, setActivity] = useState<Array<Record<string, unknown>>>([]);
  const [usage, setUsage] = useState<Record<string, unknown> | null>(null);
  const [billing, setBilling] = useState<Record<string, unknown> | null>(null);
  const [connectors, setConnectors] = useState<Record<string, unknown> | null>(null);
  const [readiness, setReadiness] = useState<ServiceReadiness | null>(null);
  const [readinessUnknown, setReadinessUnknown] = useState(false);
  const [compliance, setCompliance] = useState<Record<string, unknown> | null>(null);
  const [billingAction, setBillingAction] = useState("");
  const [billingError, setBillingError] = useState("");

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("engineer");
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const notificationPrefs = useMemo(
    () => asRecord(preferences.notification_preferences),
    [preferences],
  );

  async function reload(active = session) {
    if (!active) return;
    setBusy(true);
    setError("");
    const token = active.access_token;
    const coreErrors: string[] = [];

    // Core account data must succeed independently of workspace/billing extras.
    const [profileRes, prefsRes, securityRes] = await Promise.all([
      settledValue(fetchProfile(token)),
      settledValue(fetchPreferences(token)),
      settledValue(fetchSecurityStatus(token)),
    ]);
    if (profileRes) {
      setProfile(asRecord(profileRes.profile || profileRes));
    } else {
      coreErrors.push("profile");
    }
    if (prefsRes) {
      setPreferences(asRecord(prefsRes.preferences || prefsRes));
    } else {
      coreErrors.push("preferences");
    }
    if (securityRes) {
      setSecurity(securityRes);
    } else {
      coreErrors.push("security");
    }

    const [workspaceRes, workspacesRes, membersRes, activityRes, invitesRes] =
      await Promise.all([
        settledValue(fetchWorkspaceSettings(token)),
        settledValue(listWorkspaces(token)),
        settledValue(listWorkspaceMembers(token)),
        settledValue(listWorkspaceActivity(token)),
        settledValue(listWorkspaceInvitations(token)),
      ]);
    if (workspaceRes) {
      setWorkspace(asRecord(workspaceRes.workspace || workspaceRes));
    }
    if (workspacesRes) {
      setWorkspaces(asRows(workspacesRes.workspaces || workspacesRes.items));
    }
    if (membersRes) {
      setMembers(asRows(membersRes.members));
    }
    if (activityRes) {
      setActivity(asRows(activityRes.activity || activityRes.items));
    }
    setInvites(asRows(invitesRes?.invitations));

    const [usageRes, billingRes, connectorsRes, complianceRes, readinessRes] =
      await Promise.all([
        settledValue(fetchPlanUsage(token)),
        settledValue(fetchBillingStatus(token)),
        settledValue(fetchConnectors(token)),
        settledValue(fetchCompliancePack(token, "rohs")),
        settledValue(fetchServiceReadiness(token)),
      ]);
    if (usageRes) setUsage(usageRes);
    if (billingRes) setBilling(billingRes);
    if (connectorsRes) setConnectors(connectorsRes);
    if (complianceRes) setCompliance(complianceRes);
    if (readinessRes && readinessRes.ok !== false) {
      setReadiness(readinessRes);
      setReadinessUnknown(false);
      if (readinessRes.connectors) {
        setConnectors({
          ...(connectorsRes || {}),
          ...readinessRes.connectors,
          connectors:
            readinessRes.connectors.connectors ||
            asRows(
              (connectorsRes as Record<string, unknown> | null)?.connectors ||
                (connectorsRes as Record<string, unknown> | null)?.items,
            ),
        });
      }
    } else {
      setReadiness(null);
      setReadinessUnknown(true);
    }

    if (coreErrors.length === 3) {
      setError("Could not reach Cadivor. Check your connection and try again.");
    } else if (coreErrors.includes("profile")) {
      setError("Profile could not be loaded. You can still try saving again.");
    }
    setBusy(false);
  }

  useEffect(() => {
    if (!session) return;
    void reload(session);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  if (!session) return null;

  const planCatalog = Array.isArray(billing?.plan_catalog)
    ? (billing.plan_catalog as Array<Record<string, unknown>>)
    : [];
  const stripePlans = Array.isArray(billing?.plans)
    ? (billing.plans as Array<Record<string, unknown>>)
    : [];
  const currentPlanName = String(billing?.current_plan || usage?.plan || session.plan);
  const currentPlan = currentPlanName.toLowerCase();
  const canManageBilling = billing?.can_manage_billing === true;
  const checkoutEnabled = billing?.checkout_enabled === true;
  const connectorRows = asRows(
    readiness?.connectors?.connectors || connectors?.connectors || connectors?.items,
  );
  function readinessLabel(
    status: string | undefined,
    readyText = "Ready",
    notReadyText = "Not connected",
  ): string {
    if (readinessUnknown || !status || status === "unknown") return "Unknown";
    if (status === "ready") return readyText;
    if (status === "partial") return "Partial";
    return notReadyText;
  }
  const password = asRecord(security.password);
  const twoFactor = asRecord(security.two_factor);
  const sessions = asRecord(security.sessions);
  const canAdminister = workspace.can_administer === true;

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setSaving("profile");
    setNotice("");
    setError("");
    try {
      const saved = await updateProfile(session.access_token, {
        full_name: profile.full_name,
        company_name: profile.company_name,
        job_title: profile.job_title,
        country: profile.country,
        language: profile.language,
        timezone: profile.timezone,
      });
      setProfile(asRecord(saved.profile || saved));
      setNotice("Profile saved.");
    } catch (err) {
      setError(settingsErrorMessage(err, "Profile could not be saved"));
    } finally {
      setSaving("");
    }
  }

  async function savePreferences(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setSaving("preferences");
    setNotice("");
    setError("");
    try {
      const saved = await updatePreferences(session.access_token, {
        appearance: preferences.appearance,
        density: preferences.density,
        default_units: preferences.default_units,
        default_currency: preferences.default_currency,
        monitoring_notifications: preferences.monitoring_notifications,
        timezone: preferences.timezone || profile.timezone,
        notification_preferences: notificationPrefs,
      });
      setPreferences(asRecord(saved.preferences || saved));
      setNotice("Preferences saved.");
    } catch (err) {
      setError(settingsErrorMessage(err, "Preferences could not be saved"));
    } finally {
      setSaving("");
    }
  }

  async function saveWorkspace(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setSaving("workspace");
    setNotice("");
    setError("");
    try {
      const saved = await updateWorkspaceSettings(session.access_token, {
        name: workspace.name,
        timezone: workspace.timezone,
        unit_system: workspace.unit_system,
      });
      setWorkspace(asRecord(saved.workspace || saved));
      setNotice("Workspace settings saved.");
    } catch (err) {
      setError(settingsErrorMessage(err, "Workspace settings could not be saved"));
    } finally {
      setSaving("");
    }
  }

  async function onInvite(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setSaving("invite");
    setError("");
    setNotice("");
    try {
      const created = await createWorkspaceInvitation(session.access_token, {
        email: inviteEmail,
        role: inviteRole,
      });
      setInviteEmail("");
      setNotice("Invitation created and queued for delivery.");
      const invitesRes = await settledValue(
        listWorkspaceInvitations(session.access_token),
      );
      if (invitesRes) {
        setInvites(asRows(invitesRes.invitations));
      } else if (created && typeof created === "object") {
        const invitation = asRecord(
          (created as Record<string, unknown>).invitation || created,
        );
        if (invitation.id) {
          setInvites((prev) => [invitation, ...prev]);
        }
      }
    } catch (err) {
      setError(settingsErrorMessage(err, "Invitation could not be sent"));
    } finally {
      setSaving("");
    }
  }

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

      <div className="cv-settings-shell">
        <aside className="cv-settings-nav" aria-label="Settings sections">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? "active" : undefined}
              onClick={() => {
                setTab(item.id);
                setNotice("");
                setError("");
              }}
            >
              {item.label}
            </button>
          ))}
        </aside>

        <div className="cv-settings-main">
          {busy ? <LoadingCard label="Loading account and workspace settings…" /> : null}
          {error ? <div className="cv-error" role="alert">{error}</div> : null}
          {notice ? (
            <div className="cv-card pad" role="status" style={{ marginBottom: 14, padding: 12 }}>
              {notice}
            </div>
          ) : null}

          {!busy && tab === "profile" ? (
            <form className="cv-card pad" onSubmit={saveProfile}>
              <h3 className="cv-card-title">Profile</h3>
              <p className="cv-card-subtitle">
                Name and organization details for this Cadivor account. Email is managed by sign-in.
              </p>
              <div className="cv-form-grid" style={{ marginTop: 14 }}>
                <div className="cv-field">
                  <label htmlFor="full-name">Full name</label>
                  <input
                    id="full-name"
                    value={String(profile.full_name || "")}
                    onChange={(e) => setProfile({ ...profile, full_name: e.target.value })}
                  />
                </div>
                <div className="cv-field">
                  <label htmlFor="profile-email">Email</label>
                  <input id="profile-email" value={String(profile.email || session.email)} readOnly />
                </div>
                <div className="cv-field">
                  <label htmlFor="organization">Organization</label>
                  <input
                    id="organization"
                    value={String(profile.company_name || "")}
                    onChange={(e) => setProfile({ ...profile, company_name: e.target.value })}
                  />
                </div>
                <div className="cv-field">
                  <label htmlFor="job-title">Role / job title</label>
                  <input
                    id="job-title"
                    value={String(profile.job_title || "")}
                    onChange={(e) => setProfile({ ...profile, job_title: e.target.value })}
                  />
                </div>
                <div className="cv-field">
                  <label htmlFor="country">Location / country</label>
                  <input
                    id="country"
                    value={String(profile.country || "")}
                    onChange={(e) => setProfile({ ...profile, country: e.target.value })}
                  />
                </div>
                <div className="cv-field">
                  <label htmlFor="language">Language</label>
                  <input
                    id="language"
                    value={String(profile.language || "en")}
                    onChange={(e) => setProfile({ ...profile, language: e.target.value })}
                  />
                </div>
                <div className="cv-field">
                  <label htmlFor="timezone">Timezone</label>
                  <input
                    id="timezone"
                    value={String(profile.timezone || "UTC")}
                    onChange={(e) => setProfile({ ...profile, timezone: e.target.value })}
                    placeholder="America/New_York"
                  />
                </div>
              </div>
              <div style={{ marginTop: 14 }}>
                <button className="cv-button primary" type="submit" disabled={saving === "profile"}>
                  {saving === "profile" ? "Saving…" : "Save profile"}
                </button>
              </div>
            </form>
          ) : null}

          {!busy && tab === "preferences" ? (
            <form className="cv-card pad" onSubmit={savePreferences}>
              <h3 className="cv-card-title">Preferences</h3>
              <p className="cv-card-subtitle">
                Appearance, units, and notification choices for this account.
              </p>
              <div className="cv-form-grid" style={{ marginTop: 14 }}>
                <div className="cv-field">
                  <label htmlFor="appearance">Appearance</label>
                  <select
                    id="appearance"
                    value={String(preferences.appearance || "system")}
                    onChange={(e) => setPreferences({ ...preferences, appearance: e.target.value })}
                  >
                    <option value="system">System</option>
                    <option value="light">Light</option>
                    <option value="dark">Dark</option>
                  </select>
                </div>
                <div className="cv-field">
                  <label htmlFor="density">Density</label>
                  <select
                    id="density"
                    value={String(preferences.density || "comfortable")}
                    onChange={(e) => setPreferences({ ...preferences, density: e.target.value })}
                  >
                    <option value="comfortable">Comfortable</option>
                    <option value="compact">Compact</option>
                  </select>
                </div>
                <div className="cv-field">
                  <label htmlFor="units">Units</label>
                  <select
                    id="units"
                    value={String(preferences.default_units || "metric")}
                    onChange={(e) => setPreferences({ ...preferences, default_units: e.target.value })}
                  >
                    <option value="metric">Metric</option>
                    <option value="imperial">Imperial</option>
                  </select>
                </div>
                <div className="cv-field">
                  <label htmlFor="currency">Currency</label>
                  <select
                    id="currency"
                    value={String(preferences.default_currency || "USD")}
                    onChange={(e) =>
                      setPreferences({ ...preferences, default_currency: e.target.value })
                    }
                  >
                    {["USD", "EUR", "GBP", "CAD"].map((code) => (
                      <option key={code} value={code}>
                        {code}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="cv-field">
                  <label htmlFor="pref-timezone">Timezone</label>
                  <input
                    id="pref-timezone"
                    value={String(preferences.timezone || profile.timezone || "UTC")}
                    onChange={(e) => setPreferences({ ...preferences, timezone: e.target.value })}
                  />
                </div>
              </div>
              <div className="cv-settings-toggles" style={{ marginTop: 16 }}>
                {NOTIFICATION_LABELS.map((item) => (
                  <Toggle
                    key={item.key}
                    id={`pref-${item.key}`}
                    label={item.label}
                    hint={item.hint}
                    checked={Boolean(notificationPrefs[item.key])}
                    onChange={(next) =>
                      setPreferences({
                        ...preferences,
                        notification_preferences: { ...notificationPrefs, [item.key]: next },
                      })
                    }
                  />
                ))}
                <Toggle
                  id="pref-monitoring"
                  label="Monitoring / lifecycle alerts"
                  hint="Part lifecycle and monitoring notifications"
                  checked={Boolean(preferences.monitoring_notifications)}
                  onChange={(next) =>
                    setPreferences({ ...preferences, monitoring_notifications: next })
                  }
                />
              </div>
              <div style={{ marginTop: 14 }}>
                <button
                  className="cv-button primary"
                  type="submit"
                  disabled={saving === "preferences"}
                >
                  {saving === "preferences" ? "Saving…" : "Save preferences"}
                </button>
              </div>
            </form>
          ) : null}

          {!busy && tab === "workspace" ? (
            <>
              <section className="cv-card pad" style={{ marginBottom: 14 }}>
                <h3 className="cv-card-title">Active workspace</h3>
                <p className="cv-card-subtitle">
                  Switch between workspaces you belong to, or create another when your plan allows it.
                </p>
                <div className="cv-form-grid" style={{ marginTop: 14 }}>
                  <div className="cv-field">
                    <label htmlFor="active-workspace">Workspace</label>
                    <select
                      id="active-workspace"
                      value={String(workspace.workspace_id || session.workspace_id || "")}
                      onChange={(e) => {
                        void (async () => {
                          if (!session) return;
                          setSaving("switch");
                          try {
                            await switchWorkspace(session.access_token, e.target.value);
                            window.location.reload();
                          } catch (err) {
                            setError(
                              err instanceof Error ? err.message : "Could not switch workspace",
                            );
                            setSaving("");
                          }
                        })();
                      }}
                    >
                      {workspaces.map((row) => (
                        <option
                          key={String(row.workspace_id)}
                          value={String(row.workspace_id)}
                        >
                          {String(row.name || row.workspace_name || row.workspace_id)}
                          {row.role ? ` · ${String(row.role)}` : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="cv-field">
                    <label htmlFor="create-workspace">Create another workspace</label>
                    <div style={{ display: "flex", gap: 8 }}>
                      <input
                        id="create-workspace"
                        value={newWorkspaceName}
                        onChange={(e) => setNewWorkspaceName(e.target.value)}
                        placeholder="Workspace name"
                      />
                      <button
                        className="cv-button"
                        type="button"
                        disabled={saving === "create-ws" || !newWorkspaceName.trim()}
                        onClick={() => {
                          void (async () => {
                            if (!session) return;
                            setSaving("create-ws");
                            setError("");
                            try {
                              await createWorkspace(session.access_token, newWorkspaceName.trim());
                              setNewWorkspaceName("");
                              window.location.reload();
                            } catch (err) {
                              setError(
                                err instanceof Error
                                  ? err.message
                                  : "Could not create workspace",
                              );
                              setSaving("");
                            }
                          })();
                        }}
                      >
                        Create
                      </button>
                    </div>
                  </div>
                </div>
              </section>

              <form className="cv-card pad" style={{ marginBottom: 14 }} onSubmit={saveWorkspace}>
                <h3 className="cv-card-title">Workspace settings</h3>
                <p className="cv-card-subtitle">
                  Name, timezone, and units for{" "}
                  {String(workspace.name || workspaceDisplayName(session.workspace))}.
                </p>
                <div className="cv-form-grid" style={{ marginTop: 14 }}>
                  <div className="cv-field">
                    <label htmlFor="ws-name">Workspace name</label>
                    <input
                      id="ws-name"
                      value={String(workspace.name || "")}
                      onChange={(e) => setWorkspace({ ...workspace, name: e.target.value })}
                      disabled={!canAdminister}
                      required
                    />
                  </div>
                  <div className="cv-field">
                    <label htmlFor="ws-timezone">Timezone</label>
                    <input
                      id="ws-timezone"
                      value={String(workspace.timezone || "UTC")}
                      onChange={(e) => setWorkspace({ ...workspace, timezone: e.target.value })}
                      disabled={!canAdminister}
                    />
                  </div>
                  <div className="cv-field">
                    <label htmlFor="ws-units">Units</label>
                    <select
                      id="ws-units"
                      value={String(workspace.unit_system || "metric")}
                      onChange={(e) => setWorkspace({ ...workspace, unit_system: e.target.value })}
                      disabled={!canAdminister}
                    >
                      <option value="metric">Metric</option>
                      <option value="imperial">Imperial</option>
                    </select>
                  </div>
                </div>
                {canAdminister ? (
                  <div style={{ marginTop: 14 }}>
                    <button
                      className="cv-button primary"
                      type="submit"
                      disabled={saving === "workspace"}
                    >
                      {saving === "workspace" ? "Saving…" : "Save workspace"}
                    </button>
                  </div>
                ) : (
                  <p className="cv-small-note" style={{ marginTop: 12 }}>
                    Only owners and admins can edit workspace settings.
                  </p>
                )}
              </form>

              <section className="cv-card pad" style={{ marginBottom: 14 }}>
                <h3 className="cv-card-title">Members</h3>
                {members.length ? (
                  <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                    <table className="cv-table">
                      <thead>
                        <tr>
                          <th>Member</th>
                          <th>Role</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {members.map((row) => (
                          <tr key={String(row.user_id || row.email)}>
                            <td>
                              <strong>{String(row.display_name || row.email || "")}</strong>
                              <div className="cv-small-note">{String(row.email || "")}</div>
                            </td>
                            <td>{String(row.role || "")}</td>
                            <td>{String(row.status || "active")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState icon="settings" title="No members listed" body="Member directory appears here for this workspace." />
                )}
              </section>

              {canAdminister ? (
                <section className="cv-card pad" style={{ marginBottom: 14 }}>
                  <h3 className="cv-card-title">Invitations</h3>
                  <form className="cv-form-grid" onSubmit={onInvite} style={{ marginTop: 12 }}>
                    <div className="cv-field">
                      <label htmlFor="invite-email">Email</label>
                      <input
                        id="invite-email"
                        type="email"
                        value={inviteEmail}
                        onChange={(e) => setInviteEmail(e.target.value)}
                        required
                      />
                    </div>
                    <div className="cv-field">
                      <label htmlFor="invite-role">Role</label>
                      <select
                        id="invite-role"
                        value={inviteRole}
                        onChange={(e) => setInviteRole(e.target.value)}
                      >
                        <option value="admin">Admin</option>
                        <option value="engineer">Engineer</option>
                        <option value="viewer">Viewer</option>
                      </select>
                    </div>
                    <div style={{ gridColumn: "1 / -1" }}>
                      <button className="cv-button primary" type="submit" disabled={saving === "invite"}>
                        {saving === "invite" ? "Sending…" : "Send invitation"}
                      </button>
                    </div>
                  </form>
                  {invites.length ? (
                    <div className="cv-table-wrap" style={{ marginTop: 14 }}>
                      <table className="cv-table cv-table-actions">
                        <thead>
                          <tr>
                            <th>Email</th>
                            <th>Role</th>
                            <th>Status</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {invites.map((row) => (
                            <tr key={String(row.id)}>
                              <td>{String(row.email || "")}</td>
                              <td>{String(row.role || "")}</td>
                              <td>{String(row.status || "")}</td>
                              <td className="cv-table-action">
                                {String(row.status) === "pending" ? (
                                  <>
                                    <button
                                      className="cv-button"
                                      type="button"
                                      onClick={() => {
                                        void (async () => {
                                          if (!session) return;
                                          try {
                                            await resendWorkspaceInvitation(
                                              session.access_token,
                                              String(row.id),
                                            );
                                            setNotice("Invitation resent.");
                                            await reload(session);
                                          } catch (err) {
                                            setError(
                                              err instanceof Error
                                                ? err.message
                                                : "Could not resend invitation",
                                            );
                                          }
                                        })();
                                      }}
                                    >
                                      Resend
                                    </button>{" "}
                                    <button
                                      className="cv-button"
                                      type="button"
                                      onClick={() => {
                                        void (async () => {
                                          if (!session) return;
                                          try {
                                            await cancelWorkspaceInvitation(
                                              session.access_token,
                                              String(row.id),
                                            );
                                            setNotice("Invitation cancelled.");
                                            await reload(session);
                                          } catch (err) {
                                            setError(
                                              err instanceof Error
                                                ? err.message
                                                : "Could not cancel invitation",
                                            );
                                          }
                                        })();
                                      }}
                                    >
                                      Cancel
                                    </button>
                                  </>
                                ) : (
                                  "—"
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="cv-small-note" style={{ marginTop: 12 }}>
                      No invitations yet.
                    </p>
                  )}
                </section>
              ) : null}

              <section className="cv-card pad">
                <h3 className="cv-card-title">Activity</h3>
                {activity.length ? (
                  <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                    <table className="cv-table">
                      <thead>
                        <tr>
                          <th>When</th>
                          <th>Event</th>
                          <th>Detail</th>
                        </tr>
                      </thead>
                      <tbody>
                        {activity.map((row) => (
                          <tr key={String(row.id || `${row.created_at}-${row.event}`)}>
                            <td>{String(row.created_at || "").replace("T", " ").slice(0, 19)}</td>
                            <td>{String(row.event || "")}</td>
                            <td>{String(row.message || "")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="cv-small-note" style={{ marginTop: 12 }}>
                    Workspace activity appears here as members join and settings change.
                  </p>
                )}
              </section>
            </>
          ) : null}

          {!busy && tab === "security" ? (
            <section className="cv-card pad">
              <h3 className="cv-card-title">Security</h3>
              <p className="cv-card-subtitle">
                Password and session controls use Supabase Auth when production authentication is enabled.
              </p>
              <dl className="cv-fact-grid" style={{ marginTop: 14 }}>
                <div className="cv-fact">
                  <dt>Password management</dt>
                  <dd>{String(password.managed_by || "Not reported")}</dd>
                </div>
                <div className="cv-fact">
                  <dt>Two-factor authentication</dt>
                  <dd>{String(twoFactor.label || twoFactor.status || "Planned")}</dd>
                </div>
                <div className="cv-fact">
                  <dt>Active sessions</dt>
                  <dd>
                    {sessions.revoke_others_available
                      ? "You can revoke other signed-in devices."
                      : String(sessions.status || "Unavailable in this environment")}
                  </dd>
                </div>
              </dl>

              {password.reset_available ? (
                <div style={{ marginTop: 16 }}>
                  <button
                    className="cv-button"
                    type="button"
                    disabled={saving === "reset"}
                    onClick={() => {
                      void (async () => {
                        setSaving("reset");
                        setError("");
                        try {
                          await requestPasswordReset(session.email);
                          setNotice(
                            "If this account uses email sign-in, a password reset link will arrive by email.",
                          );
                        } catch (err) {
                          setError(
                            err instanceof Error ? err.message : "Password reset could not start",
                          );
                        } finally {
                          setSaving("");
                        }
                      })();
                    }}
                  >
                    {saving === "reset" ? "Sending…" : "Send password reset email"}
                  </button>
                </div>
              ) : (
                <p className="cv-small-note" style={{ marginTop: 12 }}>
                  Password reset is available when Supabase Auth manages this account.
                </p>
              )}

              {password.change_available ? (
                <form
                  className="cv-form-grid"
                  style={{ marginTop: 18 }}
                  onSubmit={(event) => {
                    event.preventDefault();
                    void (async () => {
                      setSaving("password");
                      setError("");
                      try {
                        await changePassword(session.access_token, {
                          current_password: currentPassword,
                          new_password: newPassword,
                        });
                        setCurrentPassword("");
                        setNewPassword("");
                        setNotice("Password updated.");
                      } catch (err) {
                        setError(
                          err instanceof Error ? err.message : "Password could not be changed",
                        );
                      } finally {
                        setSaving("");
                      }
                    })();
                  }}
                >
                  <div className="cv-field">
                    <label htmlFor="current-password">Current password</label>
                    <input
                      id="current-password"
                      type="password"
                      value={currentPassword}
                      onChange={(e) => setCurrentPassword(e.target.value)}
                      required
                    />
                  </div>
                  <div className="cv-field">
                    <label htmlFor="new-password">New password</label>
                    <input
                      id="new-password"
                      type="password"
                      minLength={12}
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      required
                    />
                  </div>
                  <div style={{ gridColumn: "1 / -1" }}>
                    <button className="cv-button primary" type="submit" disabled={saving === "password"}>
                      {saving === "password" ? "Updating…" : "Change password"}
                    </button>
                  </div>
                </form>
              ) : null}

              {sessions.revoke_others_available ? (
                <div style={{ marginTop: 16 }}>
                  <button
                    className="cv-button"
                    type="button"
                    disabled={saving === "sessions"}
                    onClick={() => {
                      void (async () => {
                        setSaving("sessions");
                        setError("");
                        try {
                          await revokeOtherSessions(session.access_token);
                          setNotice("Other sessions were signed out.");
                        } catch (err) {
                          setError(
                            err instanceof Error ? err.message : "Could not revoke sessions",
                          );
                        } finally {
                          setSaving("");
                        }
                      })();
                    }}
                  >
                    {saving === "sessions" ? "Signing out…" : "Sign out other devices"}
                  </button>
                </div>
              ) : null}

              <p className="cv-small-note" style={{ marginTop: 16 }}>
                Connected accounts: email and password. Social / SSO sign-in is planned and not shown as active.
              </p>
            </section>
          ) : null}

          {!busy && tab === "billing" ? (
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
                    <button
                      className="cv-button"
                      type="button"
                      onClick={() => void openBillingPortal()}
                      disabled={Boolean(billingAction)}
                    >
                      {billingAction === "portal" ? "Opening billing…" : "Manage subscription"}
                    </button>
                  ) : null}
                </div>
                <p className="cv-current-plan" role="status">
                  Current access: <strong>{currentPlanName}</strong>
                  {session.trial_days_remaining != null &&
                  currentPlanName.toLowerCase() === "trial"
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
                    const limit = (value: unknown) =>
                      value == null ? "Unlimited" : String(value);
                    const bullets = [
                      `${limit(plan.monthly_bom_limit)} BOM analyses per month`,
                      `${limit(plan.max_parts_per_bom)} components per BOM`,
                      `${limit(plan.max_saved_boms)} saved BOMs`,
                      Number(plan.monitored_parts_limit) > 0 || plan.monitored_parts_limit == null
                        ? `${limit(plan.monitored_parts_limit)} monitored parts`
                        : "Monitoring not included",
                      Number(plan.ai_credits) > 0
                        ? `${limit(plan.ai_credits)} Ask Cadivor credits`
                        : "Ask Cadivor not included",
                      plan.team_features ? "Team collaboration" : "Individual workspace",
                    ].filter(Boolean);
                    let actionText = "Choose plan";
                    if (current) actionText = "Current plan";
                    else if (canManageBilling) actionText = "Change plan in billing";
                    else if (!checkoutEnabled || !hasPrice) actionText = "Temporarily unavailable";
                    if (enterprise) actionText = "Contact sales";
                    return (
                      <article
                        className={`cv-plan-option${current ? " current" : ""}${
                          name === "Professional" ? " featured" : ""
                        }`}
                        key={name}
                      >
                        <div className="cv-plan-option-top">
                          <h4>{name}</h4>
                          {name === "Professional" ? (
                            <span className="cv-plan-popular">Most popular</span>
                          ) : null}
                        </div>
                        <div className="cv-plan-price">{String(plan.price || "Contact us")}</div>
                        <p>{String(plan.description || "")}</p>
                        <ul>
                          {bullets.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                        {enterprise ? (
                          <a
                            className="cv-button"
                            href="mailto:sales@cadivor.com?subject=Cadivor%20Enterprise%20plans"
                          >
                            {actionText}
                          </a>
                        ) : (
                          <button
                            className={current ? "cv-button" : "cv-button primary"}
                            type="button"
                            disabled={
                              current ||
                              !paidPlan ||
                              (!canManageBilling && (!checkoutEnabled || !hasPrice)) ||
                              Boolean(billingAction)
                            }
                            onClick={() => void selectPlan(plan)}
                          >
                            {billingAction === name ? "Opening secure checkout…" : actionText}
                          </button>
                        )}
                      </article>
                    );
                  })}
                </div>
                {billingError ? (
                  <div className="cv-error" role="alert" style={{ marginTop: 12 }}>
                    {billingError}
                  </div>
                ) : null}
                <p className="cv-small-note" style={{ marginTop: 12 }}>
                  Need a single paid BOM report instead of a subscription?{" "}
                  <Link href="/single-bom-report">View the one-time report option</Link>.
                </p>
              </section>

              <section className="cv-card pad" style={{ marginBottom: 14 }}>
                <h3 className="cv-card-title">Plan usage</h3>
                <p className="cv-card-subtitle">Limits and usage for the signed-in workspace.</p>
                <dl className="cv-fact-grid">
                  {Object.entries(usage || {})
                    .filter(([key]) => !/(^id$|_id$|token|secret|password|raw)/i.test(key))
                    .slice(0, 10)
                    .map(([key, value]) => (
                      <div className="cv-fact" key={key}>
                        <dt>{key.replace(/[_-]+/g, " ")}</dt>
                        <dd>
                          {typeof value === "boolean"
                            ? value
                              ? "Enabled"
                              : "Disabled"
                            : value == null || value === ""
                              ? "Not reported"
                              : String(value).slice(0, 120)}
                        </dd>
                      </div>
                    ))}
                </dl>
              </section>

              <section className="cv-card pad" style={{ marginBottom: 14 }}>
                <h3 className="cv-card-title">Service readiness</h3>
                <p className="cv-card-subtitle">
                  Operational availability for monitoring email, scheduler, and billing checkout.
                  CSV file workflows are listed separately from live design-tool or vendor integrations.
                </p>
                <ul className="cv-action-list" style={{ marginTop: 12 }}>
                  <li>
                    <div>
                      <strong>Monitoring email</strong>
                      <small className="cv-small-note">Alert delivery transport configuration</small>
                    </div>
                    <span className="cv-badge gray">
                      {readinessLabel(readiness?.monitoring_email?.status)}
                    </span>
                  </li>
                  <li>
                    <div>
                      <strong>Monitoring scheduler</strong>
                      <small className="cv-small-note">Scheduled refresh and cron hook</small>
                    </div>
                    <span className="cv-badge gray">
                      {readinessLabel(readiness?.scheduler?.status)}
                    </span>
                  </li>
                  <li>
                    <div>
                      <strong>Billing checkout</strong>
                      <small className="cv-small-note">Stripe plan upgrades and portal</small>
                    </div>
                    <span className="cv-badge gray">
                      {readinessUnknown
                        ? "Unknown"
                        : readiness?.billing_checkout?.status
                          ? readinessLabel(readiness.billing_checkout.status)
                          : checkoutEnabled
                            ? "Ready"
                            : "Not connected"}
                    </span>
                  </li>
                  <li>
                    <div>
                      <strong>Live design-tool / vendor connectors</strong>
                      <small className="cv-small-note">
                        Live integrations only — CSV file workflows do not count as ready
                        {typeof readiness?.connectors?.live_ready_count === "number" ||
                        typeof readiness?.connectors?.ready_count === "number"
                          ? ` · ${readiness?.connectors?.live_ready_count ?? readiness?.connectors?.ready_count ?? 0} live ready, ${readiness?.connectors?.blocked_count ?? 0} blocked, ${readiness?.connectors?.file_workflow_count ?? 0} file workflows`
                          : ""}
                      </small>
                    </div>
                    <span className="cv-badge gray">
                      {readinessLabel(readiness?.connectors?.status)}
                    </span>
                  </li>
                </ul>
              </section>

              <section className="cv-card pad" style={{ marginBottom: 14 }}>
                <h3 className="cv-card-title">Connectors and file workflows</h3>
                <p className="cv-card-subtitle">
                  Generic CSV import/export paths are file workflows. Blocked rows are candidate live vendor integrations that still need discovery and credentials.
                </p>
                {connectorRows.length ? (
                  <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                    <table className="cv-table">
                      <thead>
                        <tr>
                          <th>Name</th>
                          <th>Category</th>
                          <th>Kind / status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {connectorRows.map((row) => (
                          <tr key={String(row.id || row.display_name)}>
                            <td>
                              <strong>{String(row.display_name || row.id || "")}</strong>
                            </td>
                            <td>{String(row.category || "")}</td>
                            <td>
                              {String(row.kind || row.status || "") === "file_workflow" ||
                              String(row.status || "") === "file_workflow"
                                ? "File workflow"
                                : String(row.status || row.kind || "")}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState
                    icon="settings"
                    title="No connectors or file workflows listed"
                    body="File workflows and vendor connector options appear here when the workspace catalog is available."
                  />
                )}
              </section>

              <section className="cv-card pad">
                <h3 className="cv-card-title">Compliance pack status</h3>
                <p className="cv-card-subtitle">
                  RoHS pack readiness for this workspace. Packs stay evidence-linked.
                </p>
                <dl className="cv-fact-grid">
                  {Object.entries(compliance || {})
                    .filter(([key]) => !/(^id$|_id$|token|secret|password|raw)/i.test(key))
                    .slice(0, 8)
                    .map(([key, value]) => (
                      <div className="cv-fact" key={key}>
                        <dt>{key.replace(/[_-]+/g, " ")}</dt>
                        <dd>
                          {value == null || value === ""
                            ? "Not reported"
                            : String(value).slice(0, 120)}
                        </dd>
                      </div>
                    ))}
                </dl>
              </section>
            </>
          ) : null}
        </div>
      </div>
    </Shell>
  );
}
