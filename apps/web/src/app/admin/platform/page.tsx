"use client";

import { FormEvent, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { PageHeader } from "@/components/PageHeader";
import { useRequireSession } from "@/lib/session";
import {
  fetchAdminPlatformSettings,
  updateAdminMaintenanceMode,
  updateAdminPlannedMaintenance,
  type AdminPlatformOverview,
} from "@/lib/api";
import { PAGE_META } from "@/lib/routes";

const DEFAULT_MESSAGE = "Cadivor is undergoing scheduled maintenance. Please try again shortly.";

function toLocalDateTime(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return "";
  const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

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
  const [plannedMessage, setPlannedMessage] = useState("");
  const [savedPlannedMessage, setSavedPlannedMessage] = useState("");
  const [plannedStartsAt, setPlannedStartsAt] = useState("");
  const [savedPlannedStartsAt, setSavedPlannedStartsAt] = useState("");
  const [plannedEndsAt, setPlannedEndsAt] = useState("");
  const [savedPlannedEndsAt, setSavedPlannedEndsAt] = useState("");
  const [plannedBusy, setPlannedBusy] = useState(false);
  const [plannedError, setPlannedError] = useState("");
  const [plannedNotice, setPlannedNotice] = useState("");

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
        const nextPlannedMessage = next.planned_maintenance_message || "";
        const nextPlannedStartsAt = toLocalDateTime(next.planned_maintenance_starts_at);
        const nextPlannedEndsAt = toLocalDateTime(next.planned_maintenance_ends_at);
        setPlannedMessage(nextPlannedMessage);
        setSavedPlannedMessage(nextPlannedMessage);
        setPlannedStartsAt(nextPlannedStartsAt);
        setSavedPlannedStartsAt(nextPlannedStartsAt);
        setPlannedEndsAt(nextPlannedEndsAt);
        setSavedPlannedEndsAt(nextPlannedEndsAt);
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
  const plannedChanged = plannedMessage.trim() !== savedPlannedMessage.trim() ||
    plannedStartsAt !== savedPlannedStartsAt || plannedEndsAt !== savedPlannedEndsAt;
  const actualMaintenanceEnabled = Boolean(overview?.maintenance_mode);
  const availabilityLabel = overview
    ? actualMaintenanceEnabled ? "Maintenance mode is on" : "Cadivor is operational"
    : loading ? "Checking platform status" : "Platform status unavailable";
  const availabilityBadge = overview
    ? actualMaintenanceEnabled ? "Maintenance active" : "Operational"
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

  async function savePlannedNotice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    const normalizedMessage = plannedMessage.trim();
    if (Boolean(normalizedMessage) !== Boolean(plannedStartsAt) ||
        Boolean(normalizedMessage) !== Boolean(plannedEndsAt)) {
      setPlannedError("Enter a notice and both dates, or clear all three fields.");
      return;
    }
    if (plannedStartsAt && plannedEndsAt && new Date(plannedEndsAt) <= new Date(plannedStartsAt)) {
      setPlannedError("The end time must be after the start time.");
      return;
    }
    setPlannedBusy(true);
    setPlannedError("");
    setPlannedNotice("");
    try {
      const result = await updateAdminPlannedMaintenance(session.access_token, {
        message: normalizedMessage,
        starts_at: plannedStartsAt ? new Date(plannedStartsAt).toISOString() : null,
        ends_at: plannedEndsAt ? new Date(plannedEndsAt).toISOString() : null,
      });
      const savedStart = toLocalDateTime(result.planned_maintenance_starts_at);
      const savedEnd = toLocalDateTime(result.planned_maintenance_ends_at);
      setPlannedMessage(result.planned_maintenance_message || "");
      setSavedPlannedMessage(result.planned_maintenance_message || "");
      setPlannedStartsAt(savedStart);
      setSavedPlannedStartsAt(savedStart);
      setPlannedEndsAt(savedEnd);
      setSavedPlannedEndsAt(savedEnd);
      setOverview((current) => current ? {
        ...current,
        planned_maintenance_message: result.planned_maintenance_message,
        planned_maintenance_starts_at: result.planned_maintenance_starts_at,
        planned_maintenance_ends_at: result.planned_maintenance_ends_at,
      } : current);
      setPlannedNotice(normalizedMessage
        ? "Planned maintenance notice is published. It does not pause account access."
        : "Planned maintenance notice has been cleared.");
    } catch (err) {
      setPlannedError(err instanceof Error ? err.message : "The planned maintenance notice could not be saved.");
    } finally {
      setPlannedBusy(false);
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
      <section className={`cv-card pad cv-platform-status-card${actualMaintenanceEnabled ? " is-maintenance" : ""}`} aria-live="polite">
        <div>
          <p className="cv-eyebrow">Current availability</p>
          <h2 className="cv-card-title">{availabilityLabel}</h2>
          <p className="cv-card-subtitle">
            {!overview
              ? "The current platform state is not confirmed yet. Wait for settings to load or refresh before changing availability."
              : actualMaintenanceEnabled
              ? "Non-admin users are blocked from the authenticated workspace. Administrators retain access to restore service."
              : "Customers can use the authenticated workspace. The maintenance control is ready if you need to pause access."}
          </p>
          {(modeChanged || messageChanged) ? (
            <p className="cv-platform-unsaved-note">Unsaved changes: the status above reflects what customers currently see.</p>
          ) : null}
        </div>
        <span className={`cv-badge ${overview ? actualMaintenanceEnabled ? "amber" : "green" : "gray"}`}>
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

      <section className="cv-card pad cv-platform-scheduled-card">
        <div className="cv-platform-maintenance-heading">
          <div>
            <h2 className="cv-card-title">Planned maintenance announcement</h2>
            <p className="cv-card-subtitle">
              Show a dated notice on sign-in and in the workspace. This announcement is informational and never pauses access; use the separate maintenance mode switch above to block workspace access.
            </p>
          </div>
          <span className="cv-data-note">Times use your local time zone</span>
        </div>
        {plannedError ? <p className="cv-error" role="alert">{plannedError}</p> : null}
        {plannedNotice ? <p className="cv-success-note" role="status">{plannedNotice}</p> : null}
        <form onSubmit={savePlannedNotice} className="cv-platform-maintenance-form">
          <label className="cv-field">
            <span>Announcement message</span>
            <textarea
              value={plannedMessage}
              maxLength={280}
              rows={3}
              placeholder="Cadivor will receive a planned update. Your account will remain accessible."
              onChange={(event) => {
                setPlannedMessage(event.target.value);
                setPlannedError("");
                setPlannedNotice("");
              }}
            />
            <small>{plannedMessage.length}/280 characters</small>
          </label>
          <div className="cv-platform-notice-time-grid">
            <label className="cv-field">
              <span>Start time</span>
              <input
                type="datetime-local"
                value={plannedStartsAt}
                onChange={(event) => {
                  setPlannedStartsAt(event.target.value);
                  setPlannedError("");
                  setPlannedNotice("");
                }}
              />
            </label>
            <label className="cv-field">
              <span>End time</span>
              <input
                type="datetime-local"
                value={plannedEndsAt}
                onChange={(event) => {
                  setPlannedEndsAt(event.target.value);
                  setPlannedError("");
                  setPlannedNotice("");
                }}
              />
            </label>
          </div>
          <div className="cv-platform-confirm-row">
            <button
              type="button"
              className="cv-button"
              onClick={() => {
                setPlannedMessage("");
                setPlannedStartsAt("");
                setPlannedEndsAt("");
                setPlannedError("");
                setPlannedNotice("");
              }}
            >
              Clear fields
            </button>
            <button type="submit" className="cv-button primary" disabled={plannedBusy || !plannedChanged}>
              {plannedBusy ? "Saving…" : "Save announcement"}
            </button>
          </div>
        </form>
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
