"use client";

import { FormEvent, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { PageHeader } from "@/components/PageHeader";
import { useRequireSession } from "@/lib/session";
import {
  fetchAdminPlatformSettings,
  updateAdminMaintenanceMode,
  type AdminPlatformOverview,
} from "@/lib/api";
import { PAGE_META } from "@/lib/routes";

const DEFAULT_MESSAGE = "Cadivor is undergoing scheduled maintenance. Please try again shortly.";

export default function PlatformOperationsPage() {
  const session = useRequireSession();
  const [overview, setOverview] = useState<AdminPlatformOverview | null>(null);
  const [maintenanceEnabled, setMaintenanceEnabled] = useState(false);
  const [savedEnabled, setSavedEnabled] = useState(false);
  const [message, setMessage] = useState(DEFAULT_MESSAGE);
  const [savedMessage, setSavedMessage] = useState(DEFAULT_MESSAGE);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!session || session.platform_role !== "admin") return;
    let current = true;
    void fetchAdminPlatformSettings(session.access_token)
      .then(({ overview: next }) => {
        if (!current) return;
        setOverview(next);
        setMaintenanceEnabled(Boolean(next.maintenance_mode));
        setSavedEnabled(Boolean(next.maintenance_mode));
        const nextMessage = next.maintenance_message || DEFAULT_MESSAGE;
        setMessage(nextMessage);
        setSavedMessage(nextMessage);
      })
      .catch((err) => {
        if (current) setError(err instanceof Error ? err.message : "Platform settings could not be loaded.");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [session?.access_token, session?.platform_role]);

  const modeChanged = maintenanceEnabled !== savedEnabled;
  const messageChanged = message.trim() !== savedMessage.trim();
  const availabilityLabel = overview
    ? maintenanceEnabled ? "Maintenance mode is on" : "Cadivor is operational"
    : loading ? "Checking platform status" : "Platform status unavailable";
  const availabilityBadge = overview
    ? maintenanceEnabled ? "Maintenance active" : "Operational"
    : loading ? "Checking" : "Unavailable";
  const confirmationPhrase = modeChanged
    ? maintenanceEnabled ? "ENABLE MAINTENANCE" : "DISABLE MAINTENANCE"
    : "UPDATE MAINTENANCE MESSAGE";

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    if (!modeChanged && !messageChanged) {
      setError("There are no maintenance settings to update.");
      return;
    }
    if (maintenanceEnabled && !message.trim()) {
      setError("Add a customer message before enabling maintenance mode.");
      return;
    }
    if (confirmation.trim() !== confirmationPhrase) {
      setError(`Type ${confirmationPhrase} exactly to apply this change.`);
      return;
    }

    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await updateAdminMaintenanceMode(session.access_token, {
        maintenance_mode: maintenanceEnabled,
        maintenance_message: message.trim(),
        confirmation: confirmationPhrase,
      });
      setMaintenanceEnabled(result.maintenance_mode);
      setSavedEnabled(result.maintenance_mode);
      setMessage(result.maintenance_message || DEFAULT_MESSAGE);
      setSavedMessage(result.maintenance_message || DEFAULT_MESSAGE);
      setConfirmation("");
      setOverview((current) => current ? {
        ...current,
        maintenance_mode: result.maintenance_mode,
        maintenance_message: result.maintenance_message,
      } : current);
      setNotice(result.maintenance_mode
        ? "Maintenance mode is on for non-admin workspace accounts. You can still access this page to restore service."
        : "Maintenance mode is off. Cadivor workspace access is available to customers.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cadivor could not update maintenance mode. No change was confirmed.");
    } finally {
      setBusy(false);
    }
  }

  if (!session) return null;
  if (session.platform_role !== "admin") {
    return (
      <Shell session={session}>
        <PageHeader meta={PAGE_META.platform} />
        <div className="cv-error" role="alert">Platform administrator access is required.</div>
      </Shell>
    );
  }

  return (
    <Shell session={session}>
      <PageHeader meta={PAGE_META.platform} />
      <section className={`cv-card pad cv-platform-status-card${maintenanceEnabled ? " is-maintenance" : ""}`} aria-live="polite">
        <div>
          <p className="cv-eyebrow">Current availability</p>
          <h2 className="cv-card-title">{availabilityLabel}</h2>
          <p className="cv-card-subtitle">
            {!overview
              ? "The current platform state is not confirmed yet. Wait for settings to load or refresh before changing availability."
              : maintenanceEnabled
              ? "Non-admin users are blocked from the authenticated workspace. Administrators retain access to restore service."
              : "Customers can use the authenticated workspace. The maintenance control is ready if you need to pause access."}
          </p>
        </div>
        <span className={`cv-badge ${overview ? maintenanceEnabled ? "amber" : "green" : "gray"}`}>
          {availabilityBadge}
        </span>
      </section>

      <section className="cv-card pad cv-platform-maintenance-card">
        <div className="cv-platform-maintenance-heading">
          <div>
            <h2 className="cv-card-title">Maintenance mode</h2>
            <p className="cv-card-subtitle">
              Pause access to the signed-in workspace and show customers a clear message. The public marketing site stays online, and platform admins can still sign in and turn maintenance off.
            </p>
          </div>
          {overview ? <span className="cv-data-note">Settings are saved in Cadivor’s platform controls</span> : null}
        </div>

        {loading ? <div className="cv-loading-card" role="status">Loading platform settings…</div> : null}
        {error ? <p className="cv-error" role="alert">{error}</p> : null}
        {notice ? <p className="cv-success-note" role="status">{notice}</p> : null}

        {!loading && overview ? (
          <form onSubmit={save} className="cv-platform-maintenance-form">
            <label className="cv-platform-maintenance-toggle">
              <input
                type="checkbox"
                checked={maintenanceEnabled}
                onChange={(event) => {
                  setMaintenanceEnabled(event.target.checked);
                  setConfirmation("");
                  setError("");
                  setNotice("");
                }}
              />
              <span>
                <strong>Enable maintenance mode</strong>
                <small>Only authenticated non-admin workspace access is paused.</small>
              </span>
            </label>

            <label className="cv-field">
              <span>Message shown to customers</span>
              <textarea
                value={message}
                maxLength={280}
                rows={4}
                onChange={(event) => {
                  setMessage(event.target.value);
                  setConfirmation("");
                  setError("");
                  setNotice("");
                }}
              />
              <small>{message.length}/280 characters</small>
            </label>

            <div className="cv-platform-confirm-row">
              <label className="cv-field">
                <span>Type <strong>{confirmationPhrase}</strong> to confirm</span>
                <input
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={confirmationPhrase}
                />
              </label>
              <button
                type="submit"
                className={`cv-button ${maintenanceEnabled ? "cv-button-danger" : "primary"}`}
                disabled={busy || (!modeChanged && !messageChanged)}
              >
                {busy ? "Saving…" : maintenanceEnabled ? "Apply maintenance setting" : "Save maintenance setting"}
              </button>
            </div>
          </form>
        ) : null}
      </section>

      {overview ? (
        <section className="cv-card pad cv-platform-summary-card">
          <h2 className="cv-card-title">Platform snapshot</h2>
          <p className="cv-card-subtitle">Read-only account totals from the platform overview.</p>
          <div className="cv-platform-summary-grid">
            <div><span>Registered users</span><strong>{overview.registered_users ?? "—"}</strong></div>
            <div><span>Active now</span><strong>{overview.active_now ?? "—"}</strong></div>
            <div><span>Active in 30 days</span><strong>{overview.active_last_30_days ?? "—"}</strong></div>
            <div><span>Suspended</span><strong>{overview.suspended_users ?? "—"}</strong></div>
          </div>
        </section>
      ) : null}
    </Shell>
  );
}
