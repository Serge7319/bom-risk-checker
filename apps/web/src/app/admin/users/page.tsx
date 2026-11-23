"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/Shell";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { useRequireSession } from "@/lib/session";
import {
  deleteAdminAccount,
  fetchAdminAccountProfile,
  fetchAdminAccounts,
  type AdminAccount,
  updateAdminAccountStatus,
} from "@/lib/api";
import { PAGE_META } from "@/lib/routes";

type Dialog = { kind: "status" | "delete"; account: AdminAccount } | null;

function formatDate(value?: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function isDeletionPending(account: AdminAccount): boolean {
  return account.suspended_reason === "Account deletion pending";
}

export default function AdminUsersPage() {
  const session = useRequireSession();
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [search, setSearch] = useState("");
  const [selectedProfile, setSelectedProfile] = useState<AdminAccount | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [confirmationEmail, setConfirmationEmail] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function refresh(token: string) {
    const result = await fetchAdminAccounts(token);
    setAccounts(result.users || []);
  }

  async function openProfile(account: AdminAccount) {
    if (!session?.access_token) return;
    setDialog(null);
    setSelectedProfile(account);
    setProfileLoading(true);
    setProfileError("");
    try {
      const result = await fetchAdminAccountProfile(session.access_token, account.id);
      setSelectedProfile(result.user);
    } catch (cause) {
      setProfileError(cause instanceof Error ? cause.message : "Could not load this user profile.");
    } finally {
      setProfileLoading(false);
    }
  }

  useEffect(() => {
    if (!session?.access_token) return;
    let current = true;
    setLoading(true);
    fetchAdminAccounts(session.access_token)
      .then((result) => {
        if (current) setAccounts(result.users || []);
      })
      .catch((cause) => {
        if (current) setError(cause instanceof Error ? cause.message : "Could not load user accounts.");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => { current = false; };
  }, [session?.access_token]);

  const filteredAccounts = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return accounts;
    return accounts.filter((account) => [
      account.email,
      account.full_name,
      account.role_title,
      account.company_name,
      account.role,
      account.plan,
      account.account_status,
    ].some((value) => String(value || "").toLowerCase().includes(query)));
  }, [accounts, search]);

  function openDialog(kind: "status" | "delete", account: AdminAccount) {
    setSelectedProfile(null);
    setDialog({ kind, account });
    setConfirmationEmail("");
    setReason("");
    setError("");
    setNotice("");
  }

  async function submitDialog(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !dialog) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (dialog.kind === "status") {
        const nextStatus = dialog.account.account_status === "active" ? "suspended" : "active";
        await updateAdminAccountStatus(session.access_token, dialog.account.id, nextStatus, reason.trim());
        setNotice(nextStatus === "suspended" ? "Account suspended." : "Account restored.");
      } else {
        await deleteAdminAccount(session.access_token, dialog.account.id, confirmationEmail.trim());
        setNotice("Account deleted. Private workspace data was erased; shared workspaces and anonymized billing records were retained.");
      }
      await refresh(session.access_token).catch(() => undefined);
      setDialog(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The account change could not be completed.");
      await refresh(session.access_token).catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  if (!session) return null;
  if (session.platform_role !== "admin") {
    return (
      <Shell session={session}>
        <PageHeader meta={PAGE_META.settings} />
        <div className="cv-error" role="alert">Platform administrator access is required.</div>
      </Shell>
    );
  }

  const pending = dialog?.kind === "delete" && isDeletionPending(dialog.account);
  const typedEmailMatches = Boolean(
    dialog?.kind === "delete" &&
    confirmationEmail.trim().toLowerCase() === dialog.account.email.trim().toLowerCase(),
  );
  const profileImageUrl = (() => {
    if (!selectedProfile?.profile_image_url) return null;
    try {
      const url = new URL(selectedProfile.profile_image_url);
      return url.protocol === "https:" ? url.toString() : null;
    } catch {
      return null;
    }
  })();
  const profileFields: Array<[string, string | null | undefined]> = selectedProfile ? [
    ["Position", selectedProfile.role_title],
    ["Company", selectedProfile.company_name],
    ["Email", selectedProfile.email],
    ["Account ID", selectedProfile.id],
    ["Plan", selectedProfile.plan],
    ["Platform role", selectedProfile.role],
    ["Access status", selectedProfile.account_status],
    ["Status reason", selectedProfile.suspended_reason],
    ["Current activity", selectedProfile.activity_status],
    ["Signed up", selectedProfile.signup_at ? formatDate(selectedProfile.signup_at) : null],
    ["Last sign-in", selectedProfile.last_sign_in_at ? formatDate(selectedProfile.last_sign_in_at) : null],
    ["Last active", selectedProfile.last_active_at ? formatDate(selectedProfile.last_active_at) : null],
    ["Trial started", selectedProfile.trial_started_at ? formatDate(selectedProfile.trial_started_at) : null],
    ["Trial ends", selectedProfile.trial_ends_at ? formatDate(selectedProfile.trial_ends_at) : null],
    ["Plan last changed", selectedProfile.plan_changed_at ? formatDate(selectedProfile.plan_changed_at) : null],
  ] : [];

  return (
    <Shell session={session}>
      <PageHeader
        meta={{
          ...PAGE_META.settings,
          title: "User accounts",
          eyebrow: "Platform",
          description: "Review authenticated accounts and manage access, recovery, and deletion.",
        }}
        actions={<SecondaryLink href="/admin/entitlements">Account entitlements</SecondaryLink>}
      />

      <section className="cv-card pad" style={{ marginBottom: 16 }}>
        <h2 className="cv-card-title">Account directory</h2>
        <p className="cv-card-subtitle">
          Suspended accounts are blocked from Cadivor sign-in and authenticated API access. Deletion removes private BOMs and reports, transfers shared workspace ownership when needed, cancels subscriptions, and retains anonymized billing and audit history.
        </p>
        <div className="cv-form-grid" style={{ gridTemplateColumns: "minmax(240px, 1fr) auto", marginTop: 14 }}>
          <div className="cv-field">
            <label htmlFor="admin-account-search">Search accounts</label>
            <input
              id="admin-account-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Email, name, role, or plan"
            />
          </div>
          <div style={{ alignSelf: "end" }}>
            <button
              className="cv-button"
              type="button"
              disabled={loading || busy}
              onClick={() => {
                setError("");
                if (session.access_token) void refresh(session.access_token).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not refresh accounts."));
              }}
            >
              {loading ? "Loading…" : "Refresh"}
            </button>
          </div>
        </div>
        {error ? <div className="cv-error" role="alert">{error}</div> : null}
        {notice ? <div className="cv-evidence-context" role="status" style={{ marginTop: 10 }}>{notice}</div> : null}
      </section>

      <section className="cv-card cv-card--table">
        {loading ? (
          <div className="cv-card pad">Loading authenticated accounts…</div>
        ) : filteredAccounts.length === 0 ? (
          <div className="cv-card pad">{accounts.length ? "No accounts match this search." : "No authenticated accounts were found."}</div>
        ) : (
          <div className="cv-table-wrap">
            <table className="cv-table">
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Plan</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Last active</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredAccounts.map((account) => {
                  const self = account.id === session.user_id;
                  const deletionPending = isDeletionPending(account);
                  return (
                    <tr key={account.id}>
                      <td className="cv-cell-wrap">
                        <button
                          className="admin-account-profile-link"
                          type="button"
                          aria-label={`View profile for ${account.full_name || account.email}`}
                          onClick={() => void openProfile(account)}
                        >
                          <strong>{account.full_name || account.email}</strong>
                        </button>
                        <div>{account.email}</div>
                        {account.role_title ? <small>{account.role_title}</small> : null}
                        {account.company_name ? <small>{account.company_name}</small> : null}
                        {deletionPending ? <div className="cv-error">Deletion pending — retry to finish cleanup.</div> : null}
                      </td>
                      <td>{account.plan || "—"}</td>
                      <td>{account.role || "user"}</td>
                      <td>
                        <strong>{account.account_status === "suspended" ? "Suspended" : "Active"}</strong>
                        {account.suspended_reason && !deletionPending ? <div className="cv-cell-wrap">{account.suspended_reason}</div> : null}
                        <small>{account.activity_status || "offline"}</small>
                      </td>
                      <td>{formatDate(account.last_active_at || account.last_sign_in_at)}</td>
                      <td>
                        <div style={{ display: "grid", gap: 6, minWidth: 118 }}>
                          <button
                            className="cv-button"
                            type="button"
                            disabled={busy}
                            onClick={() => void openProfile(account)}
                          >
                            View profile
                          </button>
                          <button
                            className="cv-button"
                            type="button"
                            disabled={busy || self || deletionPending}
                            onClick={() => openDialog("status", account)}
                          >
                            {account.account_status === "suspended" ? "Restore" : "Suspend"}
                          </button>
                          <button
                            className="cv-button"
                            type="button"
                            disabled={busy || self}
                            style={{ color: "#9b2929", borderColor: "#e2b7b7" }}
                            onClick={() => openDialog("delete", account)}
                          >
                            {deletionPending ? "Retry deletion" : "Delete account"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selectedProfile ? (
        <div
          role="presentation"
          onClick={(event) => {
            if (event.target === event.currentTarget && !profileLoading) {
              setSelectedProfile(null);
              setProfileError("");
            }
          }}
          style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(12, 26, 45, .54)", display: "grid", placeItems: "center", padding: 16 }}
        >
          <section
            className="cv-card pad"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-user-profile-title"
            style={{ width: "min(760px, 100%)", maxHeight: "90vh", overflowY: "auto", boxShadow: "0 24px 70px rgba(0,0,0,.24)" }}
          >
            <h2 id="admin-user-profile-title" className="cv-card-title">User profile</h2>
            <p className="cv-card-subtitle" style={{ marginTop: 8 }}>
              <strong style={{ color: "#17365d", fontSize: 18 }}>{selectedProfile.full_name || "Name not provided"}</strong>
              <br />{selectedProfile.email}
            </p>
            {profileLoading ? <p role="status" style={{ marginTop: 18 }}>Loading profile details…</p> : null}
            {profileError ? (
              <div className="cv-error" role="alert" style={{ marginTop: 14 }}>
                {profileError}{" "}
                <button className="cv-button" type="button" onClick={() => void openProfile(selectedProfile)}>
                  Retry
                </button>
              </div>
            ) : null}
            {!profileLoading && !profileError ? (
              <dl style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12, margin: "20px 0 0" }}>
              {profileFields.map(([label, value]) => (
                <div key={label} style={{ border: "1px solid #dce4ef", borderRadius: 10, padding: "11px 13px", minWidth: 0 }}>
                  <dt style={{ color: "#65758b", fontSize: 12, fontWeight: 700, marginBottom: 5 }}>{label}</dt>
                  <dd className="cv-cell-wrap" style={{ margin: 0, color: "#17365d", fontWeight: 600 }}>{value || "Not provided"}</dd>
                </div>
              ))}
              </dl>
            ) : null}
            {profileImageUrl ? (
              <p style={{ marginTop: 14 }}>
                <a href={profileImageUrl} target="_blank" rel="noreferrer">Open profile image</a>
              </p>
            ) : null}
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 20 }}>
              <button className="cv-button" type="button" disabled={profileLoading} onClick={() => { setSelectedProfile(null); setProfileError(""); }}>Close</button>
            </div>
          </section>
        </div>
      ) : null}

      {dialog ? (
        <div
          role="presentation"
          style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(12, 26, 45, .54)", display: "grid", placeItems: "center", padding: 16 }}
        >
          <section
            className="cv-card pad"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-account-dialog-title"
            style={{ width: "min(620px, 100%)", maxHeight: "90vh", overflowY: "auto", boxShadow: "0 24px 70px rgba(0,0,0,.24)" }}
          >
            <h2 id="admin-account-dialog-title" className="cv-card-title">
              {dialog.kind === "status"
                ? dialog.account.account_status === "active" ? "Suspend account" : "Restore account"
                : pending ? "Retry account deletion" : "Delete account"}
            </h2>
            <p className="cv-card-subtitle"><strong>{dialog.account.email}</strong></p>
            {dialog.kind === "status" ? (
              <>
                <p style={{ marginTop: 14 }}>
                  {dialog.account.account_status === "active"
                    ? "This blocks new sign-ins and Cadivor API access. The account data stays available for a later restore."
                    : "This restores account access and removes the temporary Auth sign-in ban."}
                </p>
                {dialog.account.account_status === "active" ? (
                  <div className="cv-field" style={{ marginTop: 14 }}>
                    <label htmlFor="suspension-reason">Reason (optional)</label>
                    <textarea id="suspension-reason" rows={3} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
                  </div>
                ) : null}
              </>
            ) : (
              <>
                <ul style={{ margin: "14px 0", paddingLeft: 22, lineHeight: 1.6 }}>
                  <li>Private BOMs, reports, and personal settings are erased.</li>
                  <li>Shared workspaces and their records are preserved; ownership moves to an active member.</li>
                  <li>Subscriptions are canceled. Billing and audit history is retained with account identifiers removed where supported.</li>
                  <li>This cannot be undone.</li>
                </ul>
                <div className="cv-field">
                  <label htmlFor="delete-account-confirmation">Type the exact account email to confirm</label>
                  <input
                    id="delete-account-confirmation"
                    type="text"
                    autoComplete="off"
                    spellCheck={false}
                    value={confirmationEmail}
                    onChange={(event) => setConfirmationEmail(event.target.value)}
                    placeholder={dialog.account.email}
                  />
                </div>
              </>
            )}
            {error ? <div className="cv-error" role="alert">{error}</div> : null}
            <form onSubmit={submitDialog} style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
              <button className="cv-button" type="button" disabled={busy} onClick={() => setDialog(null)}>Cancel</button>
              <button
                className="cv-button primary"
                type="submit"
                disabled={busy || (dialog.kind === "delete" && !typedEmailMatches)}
                style={dialog.kind === "delete" ? { background: "#a22929", borderColor: "#a22929" } : undefined}
              >
                {busy
                  ? "Working…"
                  : dialog.kind === "status"
                    ? dialog.account.account_status === "active" ? "Suspend account" : "Restore account"
                    : pending ? "Retry deletion" : "Delete account"}
              </button>
            </form>
          </section>
        </div>
      ) : null}
    </Shell>
  );
}
