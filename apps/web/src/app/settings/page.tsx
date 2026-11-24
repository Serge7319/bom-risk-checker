"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import {
  ApiError,
  beginBillingPortal,
  beginMonitoredPartsAddonCheckout,
  beginProfessionalApiAddonCheckout,
  beginSubscriptionCheckout,
  beginUsageOverageCheckout,
  cancelWorkspaceInvitation,
  changePassword,
  createWorkspace,
  createWorkspaceInvitation,
  fetchBillingStatus,
  fetchCompliancePack,
  fetchConnectors,
  fetchPlanUsage,
  fetchServiceReadiness,
  fetchDeveloperWebhooks,
  createDeveloperWebhook,
  deleteDeveloperWebhook,
  sendDeveloperWebhookTest,
  downloadWorkspaceActivityExport,
  type DeveloperWebhook,
  type DeveloperWebhookDelivery,
  type ServiceReadiness,
  fetchPreferences,
  fetchProfile,
  fetchSecurityStatus,
  fetchWorkspaceSettings,
  removeMonitoredPartsAddon,
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
import { cleanUserText, userFacingError, userFacingLabel, workspaceDisplayName } from "@/lib/display";
import { trackMarketingEvent, trackMarketingEventOnce } from "@/lib/marketingAnalytics";

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

function usageFacts(value: unknown): Array<[string, unknown]> {
  const source = asRecord(value);
  const facts: Array<[string, unknown]> = [];
  for (const [section, entry] of Object.entries(source)) {
    if (["ok", "id", "token", "secret", "password", "raw"].some((part) => section.toLowerCase().includes(part))) {
      continue;
    }
    if (entry && typeof entry === "object" && !Array.isArray(entry)) {
      for (const [key, metric] of Object.entries(entry as Record<string, unknown>)) {
        if (/(^id$|_id$|token|secret|password|raw)/i.test(key)) continue;
        facts.push([`${section}.${key}`, metric]);
      }
    } else {
      facts.push([section, entry]);
    }
  }
  return facts;
}

function usageLabel(key: string): string {
  return key
    .split(".")
    .map((part) => part.replace(/[_-]+/g, " "))
    .join(" · ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function usageValue(value: unknown, key: string): string {
  if (typeof value === "boolean") return value ? "Enabled" : "Disabled";
  if (value == null || value === "") return key.startsWith("limits.") ? "Unlimited" : "Not reported";
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "string") return cleanUserText(value).slice(0, 120);
  return "Not reported";
}

function settingsErrorMessage(err: unknown, fallback: string): string {
  const raw = err instanceof Error ? err.message : "";
  if (!raw || /failed to fetch/i.test(raw) || raw === "NetworkError when attempting to fetch resource.") {
    return "Could not reach Cadivor. Check your connection and try again.";
  }
  return userFacingError(raw, fallback);
}

function billingErrorMessage(err: unknown, fallback: string): string {
  const message = settingsErrorMessage(err, fallback);
  const reference =
    err instanceof ApiError && typeof err.payload.support_reference === "string"
      ? userFacingLabel(err.payload.support_reference, "")
      : "";
  return reference ? message + " (Support reference: " + reference + ")" : message;
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
  const [activityAuditDetail, setActivityAuditDetail] = useState(false);
  const [activityExporting, setActivityExporting] = useState(false);
  const [usage, setUsage] = useState<Record<string, unknown> | null>(null);
  const [billing, setBilling] = useState<Record<string, unknown> | null>(null);
  const [connectors, setConnectors] = useState<Record<string, unknown> | null>(null);
  const [readiness, setReadiness] = useState<ServiceReadiness | null>(null);
  const [readinessUnknown, setReadinessUnknown] = useState(false);
  const [compliance, setCompliance] = useState<Record<string, unknown> | null>(null);
  const [billingAction, setBillingAction] = useState("");
  const [billingError, setBillingError] = useState("");
  const [billingNotice, setBillingNotice] = useState("");
  const [billingInterval, setBillingInterval] = useState<"month" | "year">("month");
  const [developerWebhooks, setDeveloperWebhooks] = useState<DeveloperWebhook[]>([]);
  const [developerWebhookDeliveries, setDeveloperWebhookDeliveries] = useState<DeveloperWebhookDelivery[]>([]);
  const [developerWebhookEvents, setDeveloperWebhookEvents] = useState<string[]>([]);
  const [developerWebhookEncryptionReady, setDeveloperWebhookEncryptionReady] = useState(false);
  const [developerWebhookName, setDeveloperWebhookName] = useState("");
  const [developerWebhookUrl, setDeveloperWebhookUrl] = useState("");
  const [developerWebhookSelectedEvents, setDeveloperWebhookSelectedEvents] = useState<string[]>(["monitoring.alerts.created"]);
  const [developerWebhookSecret, setDeveloperWebhookSecret] = useState("");
  const [developerWebhookError, setDeveloperWebhookError] = useState("");
  const [developerWebhookNotice, setDeveloperWebhookNotice] = useState("");

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("engineer");
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const notificationPrefs = useMemo(
    () => asRecord(preferences.notification_preferences),
    [preferences],
  );
  const complianceSummary = asRecord(compliance?.summary);
  const complianceFacts: Array<[string, unknown]> = [
    ["Pack type", compliance?.pack_type],
    ["Evidence source mode", compliance?.mode],
    ["Evidence rows", complianceSummary.total],
    ["Evidence linked", complianceSummary.evidence_linked],
    ["Missing evidence", complianceSummary.missing_evidence],
    ["Compliance claimed", complianceSummary.compliance_claimed],
    ["Generated at", compliance?.generated_at],
  ];

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
      setActivityAuditDetail(activityRes.audit_detail === true);
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
    if (billingRes) {
      setBilling(billingRes);
      if (billingRes.subscription_billing_interval === "year" || billingRes.subscription_billing_interval === "month") {
        setBillingInterval(billingRes.subscription_billing_interval);
      }
    }
    const usageLimits = asRecord(usageRes?.limits);
    const apiAccessAvailable = usageLimits.api_access === true || billingRes?.api_access_addon_active === true;
    if (apiAccessAvailable) {
      const webhooksRes = await settledValue(fetchDeveloperWebhooks(token));
      if (webhooksRes?.ok) {
        setDeveloperWebhooks(webhooksRes.webhooks || []);
        setDeveloperWebhookDeliveries(webhooksRes.deliveries || []);
        setDeveloperWebhookEvents(webhooksRes.allowed_event_types || []);
        setDeveloperWebhookEncryptionReady(webhooksRes.encryption_configured === true);
        setDeveloperWebhookError("");
      } else {
        setDeveloperWebhooks([]);
        setDeveloperWebhookDeliveries([]);
        setDeveloperWebhookEncryptionReady(false);
        setDeveloperWebhookError("Webhook settings could not be loaded.");
      }
    } else {
      setDeveloperWebhooks([]);
      setDeveloperWebhookDeliveries([]);
      setDeveloperWebhookError("");
      setDeveloperWebhookSecret("");
    }
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
    if (!session || typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const requestedTab = params.get("tab");
    if (requestedTab && TABS.some((item) => item.id === requestedTab)) {
      setTab(requestedTab as TabId);
    }
    if (params.get("billing") !== "success") return;
    let active = true;
    void fetchBillingStatus(session.access_token).then((result) => {
      if (!active || result.has_active_subscription !== true) return;
      trackMarketingEventOnce(
        "subscription_created",
        `subscription_created:${session.user_id || ""}`,
        { intent: String(result.current_plan || "subscription").toLowerCase() },
        "/settings",
      );
    }).catch(() => undefined);
    return () => { active = false; };
  }, [session]);

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
  const manualBillingMode = String(billing?.manual_billing_mode || "");
  const invoiceBilling = manualBillingMode === "invoice" || manualBillingMode === "invoice_pending";
  const manualInvoiceStatus = String(billing?.manual_invoice_status || "");
  const checkoutEnabled = billing?.checkout_enabled === true;
  const billingAddons = asRecord(billing?.addons);
  const analysisOverage = asRecord(billingAddons.bom_analysis);
  const monitoredOverage = asRecord(billingAddons.monitored_parts);
  const addonBillingInterval = billing?.subscription_billing_interval === "year" ? "year" : "month";
  const monitoredOveragePrice = asRecord(monitoredOverage[addonBillingInterval === "year" ? "annual" : "monthly"]);
  const apiOverage = asRecord(billingAddons.professional_api);
  const usageCredits = asRecord(billing?.usage_credits);
  const hasProfessionalApiAddon = billing?.api_access_addon_active === true;
  const hasMonitoredPartsAddon = billing?.monitored_parts_addon_active === true;
  const monitoredPartsAddonCapacity = Number(billing?.monitored_parts_addon_capacity || 0);
  const paidSubscription = billing?.has_active_subscription === true &&
    ["starter", "professional", "business"].includes(currentPlan);
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
    trackMarketingEvent("upgrade_clicked", { plan: token, intent: "subscription" }, "/settings");
    try {
      let result: Awaited<ReturnType<typeof beginSubscriptionCheckout>>;
      let checkoutStarted = !canManageBilling;
      if (canManageBilling) {
        let portalNeedsReplacement = false;
        try {
          const portal = await beginBillingPortal(session.access_token);
          if (portal.ok && portal.checkout?.url) {
            window.location.assign(portal.checkout.url);
            return;
          }
          portalNeedsReplacement = portal.code === "billing_subscription_not_found";
          if (!portalNeedsReplacement) {
            throw new ApiError(
              portal.detail || "Secure billing could not be opened.",
              409,
              portal as unknown as Record<string, unknown>,
            );
          }
        } catch (err) {
          portalNeedsReplacement = err instanceof ApiError &&
            err.payload.code === "billing_subscription_not_found";
          if (!portalNeedsReplacement) throw err;
        }
        // Older or test-mode subscription links can remain on a profile after
        // Stripe has no active live subscription. Let the owner start a fresh
        // Checkout session instead of leaving every plan change stranded in the
        // billing portal error state.
        result = await beginSubscriptionCheckout(session.access_token, token, billingInterval);
        checkoutStarted = true;
      } else {
        result = await beginSubscriptionCheckout(session.access_token, token, billingInterval);
      }
      const url = result.checkout?.url;
      if (!result.ok || !url) {
        throw new ApiError(
          result.detail || "Secure billing could not be opened.",
          409,
          result as unknown as Record<string, unknown>,
        );
      }
      if (checkoutStarted) {
        trackMarketingEvent("checkout_started", { plan: token, intent: "subscription" }, "/settings");
      }
      window.location.assign(url);
    } catch (err) {
      setBillingError(billingErrorMessage(err, "Secure billing could not be opened."));
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
        throw new ApiError(
          result.detail || "Billing settings could not be opened.",
          409,
          result as unknown as Record<string, unknown>,
        );
      }
      window.location.assign(result.checkout.url);
    } catch (err) {
      setBillingError(billingErrorMessage(err, "Billing settings could not be opened."));
      setBillingAction("");
    }
  }

  function addonPriceLabel(addon: Record<string, unknown>, suffix: string) {
    const amount = Number(addon.amount);
    if (addon.enabled !== true || !Number.isFinite(amount) || amount <= 0) return "Not configured";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: String(addon.currency || "usd").toUpperCase(),
    }).format(amount / 100) + suffix;
  }

  async function openAddonCheckout(kind: "bom_analysis" | "monitored_parts_capacity" | "professional_api") {
    if (!session) return;
    setBillingAction("addon-" + kind);
    setBillingError("");
    setBillingNotice("");
    try {
      if (kind === "monitored_parts_capacity") {
        const result = await beginMonitoredPartsAddonCheckout(session.access_token, addonBillingInterval);
        if (!result.ok || !result.addon_added) {
          throw new Error(result.detail || "Monitored-parts capacity could not be added.");
        }
        setBillingNotice(result.detail || "Monitored-parts capacity is active.");
        const [billingRes, usageRes] = await Promise.all([
          settledValue(fetchBillingStatus(session.access_token)),
          settledValue(fetchPlanUsage(session.access_token)),
        ]);
        if (billingRes) setBilling(billingRes);
        if (usageRes) setUsage(usageRes);
        setBillingAction("");
        return;
      }
      const result = kind === "professional_api"
        ? await beginProfessionalApiAddonCheckout(session.access_token)
        : await beginUsageOverageCheckout(session.access_token, "bom_analysis");
      if (!result.ok || !result.checkout?.url) {
        throw new Error(result.detail || "Secure add-on checkout could not be opened.");
      }
      window.location.assign(result.checkout.url);
    } catch (err) {
      setBillingError(billingErrorMessage(err, "Secure add-on checkout could not be opened."));
      setBillingAction("");
    }
  }

  async function removeMonitoredCapacity() {
    if (!session || !window.confirm("Remove the monitored-parts capacity add-on? Any unused time is prorated on your next subscription invoice.")) return;
    setBillingAction("addon-monitored_parts_remove");
    setBillingError("");
    setBillingNotice("");
    try {
      const result = await removeMonitoredPartsAddon(session.access_token);
      if (!result.ok || !result.addon_removed) {
        throw new Error(result.detail || "The monitored-parts add-on could not be removed.");
      }
      setBillingNotice(result.detail || "Monitored-parts capacity was removed.");
      const [billingRes, usageRes] = await Promise.all([
        settledValue(fetchBillingStatus(session.access_token)),
        settledValue(fetchPlanUsage(session.access_token)),
      ]);
      if (billingRes) setBilling(billingRes);
      if (usageRes) setUsage(usageRes);
    } catch (err) {
      setBillingError(billingErrorMessage(err, "The monitored-parts add-on could not be removed."));
    } finally {
      setBillingAction("");
    }
  }

  async function createWebhook(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !developerWebhookName.trim() || !developerWebhookUrl.trim() || !developerWebhookSelectedEvents.length) return;
    setBillingAction("webhook-create");
    setDeveloperWebhookError("");
    setDeveloperWebhookNotice("");
    setDeveloperWebhookSecret("");
    try {
      const result = await createDeveloperWebhook(session.access_token, {
        name: developerWebhookName.trim(),
        url: developerWebhookUrl.trim(),
        event_types: developerWebhookSelectedEvents,
      });
      setDeveloperWebhooks((current) => [result.webhook, ...current]);
      setDeveloperWebhookSecret(result.signing_secret);
      setDeveloperWebhookName("");
      setDeveloperWebhookUrl("");
      setDeveloperWebhookNotice("Webhook created. Copy the signing secret now; it cannot be shown again.");
    } catch (err) {
      setDeveloperWebhookError(settingsErrorMessage(err, "Webhook could not be created."));
    } finally {
      setBillingAction("");
    }
  }

  async function copyDeveloperWebhookSecret() {
    if (!developerWebhookSecret) return;
    try {
      await navigator.clipboard.writeText(developerWebhookSecret);
      setDeveloperWebhookNotice("Signing secret copied.");
    } catch {
      setDeveloperWebhookError("Clipboard access is unavailable. Select and copy the signing secret manually.");
    }
  }

  async function testWebhook(webhookId: string) {
    if (!session) return;
    setBillingAction("webhook-test:" + webhookId);
    setDeveloperWebhookError("");
    setDeveloperWebhookNotice("");
    try {
      const result = await sendDeveloperWebhookTest(session.access_token, webhookId);
      const state = String(result.delivery?.status || "pending");
      setDeveloperWebhookNotice(state === "delivered"
        ? "Test event delivered successfully."
        : state === "failed"
          ? "Test delivery failed. Review delivery history and destination settings."
          : "Test event queued for delivery.");
      const latest = await fetchDeveloperWebhooks(session.access_token);
      if (latest.ok) setDeveloperWebhookDeliveries(latest.deliveries || []);
    } catch (err) {
      setDeveloperWebhookError(settingsErrorMessage(err, "Test delivery could not be completed."));
    } finally {
      setBillingAction("");
    }
  }

  async function removeWebhook(webhookId: string) {
    if (!session) return;
    setBillingAction("webhook-delete:" + webhookId);
    setDeveloperWebhookError("");
    setDeveloperWebhookNotice("");
    try {
      await deleteDeveloperWebhook(session.access_token, webhookId);
      setDeveloperWebhooks((current) => current.filter((hook) => hook.id !== webhookId));
      setDeveloperWebhookNotice("Webhook disabled.");
    } catch (err) {
      setDeveloperWebhookError(settingsErrorMessage(err, "Webhook could not be disabled."));
    } finally {
      setBillingAction("");
    }
  }

  function toggleWebhookEvent(eventType: string, enabled: boolean) {
    setDeveloperWebhookSelectedEvents((current) => enabled
      ? [...new Set([...current, eventType])]
      : current.filter((item) => item !== eventType));
  }

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.settings}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">BOM Analyzer</PrimaryLink>
            <SecondaryLink href="/single-bom-report">One-time report</SecondaryLink>
            {session?.platform_role === "admin" ? <SecondaryLink href="/admin/entitlements">Account entitlements</SecondaryLink> : null}
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
                            setError(settingsErrorMessage(err, "Could not switch workspace"));
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
                          {userFacingLabel(row.name || row.workspace_name, "Engineering workspace")}
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
                  {userFacingLabel(workspace.name, workspaceDisplayName(session.workspace))}.
                </p>
                <div className="cv-form-grid" style={{ marginTop: 14 }}>
                  <div className="cv-field">
                    <label htmlFor="ws-name">Workspace name</label>
                    <input
                      id="ws-name"
                      value={workspaceDisplayName(workspace.name)}
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
                <div className="cv-section-heading">
                  <div>
                    <h3 className="cv-card-title">Activity</h3>
                    <p className="cv-card-subtitle">Recent workspace changes and access events.</p>
                  </div>
                  {activityAuditDetail ? (
                    <button
                      className="cv-button"
                      type="button"
                      disabled={activityExporting}
                      onClick={() => void (async () => {
                        if (!session) return;
                        setActivityExporting(true);
                        setError("");
                        try {
                          await downloadWorkspaceActivityExport(session.access_token);
                        } catch (err) {
                          setError(err instanceof Error ? err.message : "Could not export workspace activity.");
                        } finally {
                          setActivityExporting(false);
                        }
                      })()}
                    >
                      {activityExporting ? "Preparing CSV…" : "Download audit CSV"}
                    </button>
                  ) : null}
                </div>
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
                            <td>{String(row.action || row.event || "")}</td>
                            <td>{cleanUserText(row.summary || row.message)}</td>
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
                          setError(settingsErrorMessage(err, "Password reset could not start"));
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
                        setError(settingsErrorMessage(err, "Password could not be changed"));
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
                          setError(settingsErrorMessage(err, "Could not revoke sessions"));
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
                      Your plan controls analysis limits, monitoring, and team access. Annual billing appears when discounted yearly pricing is available.
                    </p>
                  </div>
                  {canManageBilling && !invoiceBilling ? (
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
                {!canManageBilling && !invoiceBilling ? (
                  <div className="cv-billing-interval-picker" role="group" aria-label="Billing interval">
                    <button
                      type="button"
                      className={billingInterval === "month" ? "active" : ""}
                      aria-pressed={billingInterval === "month"}
                      onClick={() => setBillingInterval("month")}
                    >Monthly</button>
                    <button
                      type="button"
                      className={billingInterval === "year" ? "active" : ""}
                      aria-pressed={billingInterval === "year"}
                      onClick={() => setBillingInterval("year")}
                    >Annual</button>
                  </div>
                ) : null}
                <p className="cv-current-plan" role="status">
                  Current access: <strong>{currentPlanName}</strong>
                  {session.trial_days_remaining != null &&
                  currentPlanName.toLowerCase() === "trial"
                    ? ` · ${session.trial_days_remaining} days remaining`
                    : ""}
                </p>
                {invoiceBilling ? (
                  <div className="cv-evidence-context" role="status" style={{ margin: "12px 0", padding: 12 }}>
                    <strong>Invoice billing</strong>
                    <p style={{ margin: "5px 0 0" }}>
                      {manualBillingMode === "invoice"
                        ? manualInvoiceStatus === "payment_recorded"
                          ? `The payment for your next term is recorded and is being confirmed. You do not need to pay again. Current access continues through ${billing?.manual_access_ends_at ? new Date(String(billing.manual_access_ends_at)).toLocaleDateString() : "the end of your paid term"}.`
                          : `This plan is paid for a fixed term and does not renew automatically${billing?.manual_access_ends_at ? ` · access through ${new Date(String(billing.manual_access_ends_at)).toLocaleDateString()}` : ""}.${manualInvoiceStatus === "open" ? " A new invoice is awaiting payment; its term starts after current paid access ends." : " Contact Cadivor to renew or change the plan."}`
                        : manualInvoiceStatus === "payment_recorded"
                          ? "Your payment is recorded and is being confirmed. You do not need to pay again. Plan access begins after payment is confirmed."
                          : manualInvoiceStatus === "creating"
                            ? "Your invoice is being prepared. Plan access begins only after payment is confirmed."
                            : "An invoice is awaiting payment. Plan access begins only after payment is confirmed."}
                    </p>
                    {manualInvoiceStatus === "open" && typeof billing?.manual_invoice_url === "string" && billing.manual_invoice_url ? (
                      <p style={{ margin: "8px 0 0" }}>
                        <a href={billing.manual_invoice_url} target="_blank" rel="noreferrer">Open invoice payment page</a>
                      </p>
                    ) : null}
                    {manualInvoiceStatus === "open" && typeof billing?.manual_invoice_pdf === "string" && billing.manual_invoice_pdf ? (
                      <p style={{ margin: "5px 0 0" }}>
                        <a href={billing.manual_invoice_pdf} target="_blank" rel="noreferrer">Download invoice PDF</a>
                      </p>
                    ) : null}
                  </div>
                ) : null}
                <div className="cv-plan-grid">
                  {planCatalog.map((plan) => {
                    const name = String(plan.name || "");
                    const token = String(plan.purchase_token || "");
                    const current = currentPlan === name.toLowerCase();
                    const providerPlan = stripePlans.find((row) => String(row.name || "") === name);
                    const annualPrice = asRecord(providerPlan?.annual);
                    const hasPrice = billingInterval === "year"
                      ? annualPrice.enabled === true
                      : providerPlan?.enabled === true;
                    const monthlyPrice = String(plan.price || "Contact us");
                    const annualAmount = Number(annualPrice.amount);
                    const displayPrice = billingInterval === "year"
                      ? annualPrice.enabled === true && Number.isFinite(annualAmount)
                        ? `$${(annualAmount / 100).toFixed(2)}/year`
                        : "Annual price unavailable"
                      : monthlyPrice;
                    const annualDiscount = Number(annualPrice.discount_percent);
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
                      plan.team_features
                        ? plan.included_users == null
                          ? "Team collaboration · unlimited members"
                          : `Team collaboration · up to ${limit(plan.included_users)} members`
                        : "Individual workspace",
                      plan.api_access ? "API access included" : "",
                    ].filter(Boolean);
                    let actionText = "Choose plan";
                    if (current) actionText = "Current plan";
                    else if (invoiceBilling) actionText = "Plan changes by invoice";
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
                        <div className="cv-plan-price">{displayPrice}</div>
                        {billingInterval === "year" && annualPrice.enabled === true && annualDiscount > 0 ? (
                          <p className="cv-plan-annual-savings">Save {annualDiscount}% versus twelve monthly payments</p>
                        ) : null}
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
                              invoiceBilling ||
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
                <p className="cv-small-note" style={{ marginTop: 12 }}>
                  Need a single paid BOM report instead of a subscription?{" "}
                  <Link href="/single-bom-report">View the one-time report option</Link>.
                </p>
              </section>

              {asRecord(usage?.limits).api_access === true || hasProfessionalApiAddon ? (
                <section className="cv-card pad" style={{ marginBottom: 14 }}>
                  <h3 className="cv-card-title">Developer integrations</h3>
                  <p className="cv-card-subtitle">
                    Manage API keys from the new <Link href="/apis">APIs page</Link> in the main workspace menu.
                    Webhook destinations and delivery history remain here.
                  </p>
                  <div style={{ marginTop: 28, paddingTop: 22, borderTop: "1px solid #e3eaf3" }}>
                    <h4 className="cv-card-title">Outgoing webhooks</h4>
                    <p className="cv-card-subtitle">
                      Send signed events to your systems when an API analysis completes or scheduled monitoring finds an alert. Destinations receive the event details you select, including affected part numbers and source evidence.
                    </p>
                    {!developerWebhookEncryptionReady ? (
                      <p className="cv-small-note" role="status" style={{ marginTop: 10 }}>
                        Webhook encryption is not configured on the Cadivor API service. Set <code>CADIVOR_DEVELOPER_WEBHOOK_ENCRYPTION_KEY</code> or the existing <code>CADIVOR_SLACK_WEBHOOK_ENCRYPTION_KEY</code> in Railway before adding a destination.
                      </p>
                    ) : null}
                    <form className="cv-form-grid" onSubmit={(event) => void createWebhook(event)} style={{ marginTop: 14 }}>
                      <div className="cv-field">
                        <label htmlFor="developer-webhook-name">Webhook name</label>
                        <input id="developer-webhook-name" value={developerWebhookName} maxLength={80} onChange={(event) => setDeveloperWebhookName(event.target.value)} placeholder="e.g. Engineering alerts" required />
                      </div>
                      <div className="cv-field">
                        <label htmlFor="developer-webhook-url">HTTPS destination URL</label>
                        <input id="developer-webhook-url" type="url" value={developerWebhookUrl} onChange={(event) => setDeveloperWebhookUrl(event.target.value)} placeholder="https://your-service.example/webhooks/cadivor" required />
                      </div>
                      <div className="cv-field" style={{ gridColumn: "1 / -1" }}>
                        <span className="cv-small-note" style={{ display: "block", marginBottom: 7 }}>Events</span>
                        <div style={{ display: "grid", gap: 4, maxWidth: 620 }}>
                          {developerWebhookEvents.map((eventType) => (
                            <label className="cv-settings-toggle" key={eventType}>
                              <span><strong>{eventType}</strong><small>{eventType === "analysis.completed" ? "A developer API BOM analysis was saved." : eventType === "monitoring.alerts.created" ? "Scheduled monitoring recorded source-backed alert changes." : "A test event sent from this settings page."}</small></span>
                              <input type="checkbox" checked={developerWebhookSelectedEvents.includes(eventType)} onChange={(event) => toggleWebhookEvent(eventType, event.target.checked)} />
                            </label>
                          ))}
                        </div>
                      </div>
                      <div style={{ alignSelf: "end" }}>
                        <button className="cv-button primary" type="submit" disabled={!developerWebhookEncryptionReady || !developerWebhookSelectedEvents.length || Boolean(billingAction)}>{billingAction === "webhook-create" ? "Saving…" : "Add webhook"}</button>
                      </div>
                    </form>
                    {developerWebhookSecret ? (
                      <div className="cv-api-key-secret" role="status" style={{ marginTop: 14 }}>
                        <strong>Copy your signing secret now</strong>
                        <code>{developerWebhookSecret}</code>
                        <button className="cv-button small" type="button" onClick={() => void copyDeveloperWebhookSecret()}>Copy secret</button>
                      </div>
                    ) : null}
                    {developerWebhookError ? <div className="cv-error" role="alert" style={{ marginTop: 12 }}>{developerWebhookError}</div> : null}
                    {developerWebhookNotice ? <p className="cv-small-note" role="status" style={{ marginTop: 10 }}>{developerWebhookNotice}</p> : null}
                    {developerWebhooks.length ? (
                      <ul className="cv-api-key-list">
                        {developerWebhooks.map((hook) => (
                          <li key={hook.id}>
                            <span><strong>{cleanUserText(hook.name)}</strong><small>{cleanUserText(hook.destination_host || "Encrypted destination")} · {hook.event_types.join(", ")}</small></span>
                            {hook.active ? (
                              <span style={{ display: "flex", gap: 8 }}>
                                <button className="cv-button small" type="button" disabled={Boolean(billingAction)} onClick={() => void testWebhook(hook.id)}>{billingAction === `webhook-test:${hook.id}` ? "Sending…" : "Send test"}</button>
                                <button className="cv-button small" type="button" disabled={Boolean(billingAction)} onClick={() => void removeWebhook(hook.id)}>{billingAction === `webhook-delete:${hook.id}` ? "Disabling…" : "Disable"}</button>
                              </span>
                            ) : <small>Disabled</small>}
                          </li>
                        ))}
                      </ul>
                    ) : <p className="cv-small-note" style={{ marginTop: 12 }}>No outgoing webhooks are connected.</p>}
                    {developerWebhookDeliveries.length ? (
                      <div style={{ marginTop: 16 }}>
                        <strong className="cv-small-note">Recent deliveries</strong>
                        <ul className="cv-api-key-list">
                          {developerWebhookDeliveries.slice(0, 8).map((delivery) => (
                            <li key={delivery.id}>
                              <span><strong>{delivery.event_type}</strong><small>{delivery.status} · attempt {delivery.attempt_count}{delivery.response_status ? ` · HTTP ${delivery.response_status}` : ""}{delivery.failure_code ? ` · ${delivery.failure_code}` : ""}</small></span>
                              <small>{delivery.created_at ? new Date(delivery.created_at).toLocaleString() : ""}</small>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    <p className="cv-small-note" style={{ marginTop: 12 }}>
                      Cadivor signs the exact JSON body using HMAC-SHA256. Verify <code>X-Cadivor-Webhook-Signature</code> with your one-time secret and the timestamp header. Failed deliveries retry on later scheduled runs up to five times; redirects and non-public destinations are rejected.
                    </p>
                  </div>
                </section>
              ) : null}

              <section className="cv-card pad" style={{ marginBottom: 14 }}>
                <h3 className="cv-card-title">Usage add-ons</h3>
                <p className="cv-card-subtitle">
                  Buy extra BOM analysis credits or monitored-parts capacity when you need it. Monitoring capacity renews with your plan; any prorated adjustment appears on your next subscription invoice.
                </p>
                <div className="cv-addon-grid">
                  <article className="cv-addon-card">
                    <h4>BOM analysis pack</h4>
                    <p>{Number(analysisOverage.credits || 0).toLocaleString()} additional BOM analyses · {addonPriceLabel(analysisOverage, " one time")}</p>
                    <p className="cv-small-note">Available analysis credits: {Number(usageCredits.bom_analysis || 0).toLocaleString()}</p>
                    <button className="cv-button" type="button" disabled={!paidSubscription || analysisOverage.enabled !== true || Boolean(billingAction)} onClick={() => void openAddonCheckout("bom_analysis")}>
                      {billingAction === "addon-bom_analysis" ? "Opening checkout…" : "Buy analysis pack"}
                    </button>
                  </article>
                  <article className="cv-addon-card">
                    <h4>Monitored-parts capacity</h4>
                    <p>{Number(monitoredOverage.capacity || 0) > 0 ? `+${Number(monitoredOverage.capacity).toLocaleString()} monitored parts` : "Additional monitoring capacity"} · {addonPriceLabel(monitoredOveragePrice, addonBillingInterval === "year" ? " / year" : " / month")}</p>
                    <p className="cv-small-note">
                      {hasMonitoredPartsAddon
                        ? `${monitoredPartsAddonCapacity.toLocaleString()} additional monitored parts are active on this subscription.`
                        : "Recurring add-on for active Starter and Professional plans. Any partial-period charge appears on the next subscription invoice."}
                    </p>
                    {hasMonitoredPartsAddon ? (
                      <button className="cv-button" type="button" disabled={Boolean(billingAction)} onClick={() => void removeMonitoredCapacity()}>
                        {billingAction === "addon-monitored_parts_remove" ? "Removing…" : "Remove capacity add-on"}
                      </button>
                    ) : (
                      <button className="cv-button" type="button" disabled={!paidSubscription || !["starter", "professional"].includes(currentPlan) || monitoredOveragePrice.enabled !== true || Boolean(billingAction)} onClick={() => void openAddonCheckout("monitored_parts_capacity")}>
                        {billingAction === "addon-monitored_parts_capacity" ? "Adding capacity…" : "Add monitored capacity"}
                      </button>
                    )}
                  </article>
                  <article className="cv-addon-card">
                    <h4>Professional API access</h4>
                    <p>{addonPriceLabel(apiOverage, " / month")}</p>
                    <p className="cv-small-note">Requires an active Professional subscription. {hasProfessionalApiAddon ? "API access add-on is active." : "Billed separately from the Professional plan."}</p>
                    <button className="cv-button" type="button" disabled={!paidSubscription || currentPlan !== "professional" || hasProfessionalApiAddon || apiOverage.enabled !== true || Boolean(billingAction)} onClick={() => void openAddonCheckout("professional_api")}>
                      {hasProfessionalApiAddon ? "Active" : billingAction === "addon-professional_api" ? "Opening checkout…" : "Add API access"}
                    </button>
                  </article>
                </div>
                {!paidSubscription ? <p className="cv-small-note" style={{ marginTop: 10 }}>Choose an active paid plan before purchasing add-ons.</p> : null}
                {currentPlan === "business" || currentPlan === "enterprise" ? <p className="cv-small-note" style={{ marginTop: 10 }}>Business and Enterprise already include unlimited monitored parts.</p> : null}
                {billingNotice ? <div className="cv-success" role="status" style={{ marginTop: 12 }}>{billingNotice}</div> : null}
                {billingError ? <div className="cv-error" role="alert" style={{ marginTop: 12 }}>{billingError}</div> : null}
              </section>

              <section className="cv-card pad" style={{ marginBottom: 14 }}>
                <h3 className="cv-card-title">Plan usage</h3>
                <p className="cv-card-subtitle">Limits and usage for the signed-in workspace.</p>
                <dl className="cv-fact-grid">
                  {usageFacts(usage)
                    .slice(0, 10)
                    .map(([key, value]) => (
                      <div className="cv-fact" key={key}>
                        <dt>{usageLabel(key)}</dt>
                        <dd>{usageValue(value, key)}</dd>
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
                <ul className="cv-action-list cv-service-readiness-list">
                  <li>
                    <div className="cv-service-readiness-copy">
                      <strong>Monitoring email</strong>
                      <small className="cv-small-note">Alert delivery transport configuration</small>
                    </div>
                    <span className="cv-badge gray">
                      {readinessLabel(readiness?.monitoring_email?.status)}
                    </span>
                  </li>
                  <li>
                    <div className="cv-service-readiness-copy">
                      <strong>Monitoring scheduler</strong>
                      <small className="cv-small-note">Scheduled refresh and cron hook</small>
                    </div>
                    <span className="cv-badge gray">
                      {readinessLabel(readiness?.scheduler?.status)}
                    </span>
                  </li>
                  <li>
                    <div className="cv-service-readiness-copy">
                      <strong>Billing checkout</strong>
                      <small className="cv-small-note">Plan upgrades and billing portal</small>
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
                    <div className="cv-service-readiness-copy">
                      <strong>Live design-tool / vendor connectors</strong>
                      <small className="cv-small-note">
                        Live integrations only — CSV file workflows do not count as ready
                        {typeof readiness?.connectors?.live_ready_count === "number" ||
                        typeof readiness?.connectors?.ready_count === "number"
                          ? ` · ${readiness?.connectors?.live_ready_count ?? readiness?.connectors?.ready_count ?? 0} live ready, ${readiness?.connectors?.configured_unverified_count ?? 0} configured but unverified, ${readiness?.connectors?.blocked_count ?? 0} blocked, ${readiness?.connectors?.file_workflow_count ?? 0} file workflows`
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
                  Generic CSV paths are file workflows. The KiCad 9 IPC plugin is distributed separately and authenticates with a Developer API key; it does not appear as a server-side connector here. Direct PLM and ERP integrations still need a provider choice and sandbox access.
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
                              <strong>{userFacingLabel(row.display_name, "Connector")}</strong>
                            </td>
                            <td>{String(row.category || "")}</td>
                            <td>
                              {String(row.kind || row.status || "") === "file_workflow" ||
                              String(row.status || "") === "file_workflow"
                                ? "File workflow"
                                : String(row.status || row.kind || "") === "configured_unverified"
                                  ? "Configured · not verified"
                                  : String(row.status || "") === "ready"
                                    ? "Live verified"
                                  : String(row.status || row.kind || "") === "blocked"
                                    ? "Needs setup"
                                    : String(row.status || row.kind || "")}
                              {row.status === "ready" && row.last_verified_at ? (
                                <small className="cv-small-note">
                                  Checked {String(row.last_verified_at)}
                                </small>
                              ) : null}
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
                  {complianceFacts.map(([label, value]) => (
                    <div className="cv-fact" key={label}>
                      <dt>{label}</dt>
                      <dd>
                        {value == null || value === ""
                          ? label === "Evidence source mode" && !compliance?.analysis_id
                            ? "No saved analysis selected"
                            : "Not reported"
                          : typeof value === "boolean"
                            ? value
                              ? "Yes"
                              : "No"
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
