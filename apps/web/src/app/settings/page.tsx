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
    if (billingRes) setBilling(billingRes);
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
  const checkoutEnabled = billing?.checkout_enabled === true;
  const billingAddons = asRecord(billing?.addons);
  const analysisOverage = asRecord(billingAddons.bom_analysis);
  const monitoredOverage = asRecord(billingAddons.monitored_parts);
  const apiOverage = asRecord(billingAddons.professional_api);
  const usageCredits = asRecord(billing?.usage_credits);
  const hasProfessionalApiAddon = billing?.api_access_addon_active === true;
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
   