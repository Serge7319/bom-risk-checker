"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/Shell";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { useRequireSession } from "@/lib/session";
import {
  adminManualPlanBillingAction,
  deleteAdminAccount,
  fetchAdminManualPlanBilling,
  fetchAdminAccountProfile,
  fetchAdminAccounts,
  type AdminAccount,
  type AdminManualPlanInvoice,
  updateAdminAccountStatus,
} from "@/lib/api";
import { PAGE_META } from "@/lib/routes";

type Dialog = { kind: "status" | "delete"; account: AdminAccount } | null;

function formatDate(value?: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function formatInvoiceAmount(value: number, currency: string): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: String(currency || "usd").toUpperCase(),
  }).format(Number(value || 0) / 100);
}

function isDeletionPending(account: AdminAccount): boolean {
  return account.suspended_reason === "Account deletion pending";
}

export default function AdminUsersPage() {
  const session = useRequireSession();
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [search, setSearch] = useState("");
  const [selectedProfile, setSelectedProfile] = useState<AdminAccount | null>(null);
  const [manualInvoices, setManualInvoices] = useState<AdminManualPlanInvoice[]>([]);
  const [manualLoading, setManualLoading] = useState(false);
  const [manualBillingError, setManualBillingError] = useState("");
  const [manualBillingNotice, setManualBillingNotice] = useState("");
  const [manualBusy, setManualBusy] = useState("");
  const [invoiceFormOpen, setInvoiceFormOpen] = useState(false);
  const [invoicePlan, setInvoicePlan] = useState("Professional");
  const [invoiceInterval, setInvoiceInterval] = useState<"month" | "year">("month");
  const [invoiceDueDays, setInvoiceDueDays] = useState(30);
  const [paymentInvoice, setPaymentInvoice] = useState<AdminManualPlanInvoice | null>(null);
  const [paymentMethod, setPaymentMethod] = useState<"cash" | "check">("cash");
  const [paymentReference, setPaymentReference] = useState("");
  const [receivedPaymentConfirmed, setReceivedPaymentConfirmed] = useState(false);
  const [voidConfirmInvoiceId, setVoidConfirmInvoiceId] = useState("");
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
    setManualInvoices([]);
    setManualLoading(true);
    setManualBillingError("");
    setManualBillingNotice("");
    setInvoiceFormOpen(false);
    setPaymentInvoice(null);
    setVoidConfirmInvoiceId("");
    try {
      const result = await fetchAdminAccountProfile(session.access_token, account.id);
      setSelectedProfile(result.user);
    } catch (cause) {
      setProfileError(cause instanceof Error ? cause.message : "Could not load this user profile.");
    } finally {
      setProfileLoading(false);
    }
    try {
      const result = await fetchAdminManualPlanBilling(session.access_token, account.id);
      setManualInvoices(result.invoices || []);
    } catch (cause) {
      setManualBillingError(cause instanceof Error ? cause.message : "Manual billing history could not be loaded.");
    } finally {
      setManualLoading(false);
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

  async function refreshManualInvoices(userId: string, token: string) {
    const result = await fetchAdminManualPlanBilling(token, userId);
    setManualInvoices(result.invoices || []);
  }

  async function createManualInvoice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !selectedProfile) return;
    setManualBusy("create");
    setManualBillingError("");
    setManualBillingNotice("");
    try {
      await adminManualPlanBillingAction(session.access_token, selectedProfile.id, {
        action: "create_invoice",
        plan: invoicePlan,
        billing_interval: invoiceInterval,
        due_days: invoiceDueDays,
      });
      await refreshManualInvoices(selectedProfile.id, session.access_token);
      setInvoiceFormOpen(false);
      setManualBillingNotice("Invoice created. Review it below, then email the invoice or share its payment link.");
    } catch (cause) {
      setManualBillingError(cause instanceof Error ? cause.message : "Invoice could not be created.");
      await refreshManualInvoices(selectedProfile.id, session.access_token).catch(() => undefined);
    } finally {
      setManualBusy("");
    }
  }

  async function resumeManualInvoice(invoice: AdminManualPlanInvoice) {
    if (!session || !selectedProfile || invoice.status !== "creating") return;
    setManualBusy(`resume:${invoice.id}`);
    setManualBillingError("");
    setManualBillingNotice("");
    try {
      await adminManualPlanBillingAction(session.access_token, selectedProfile.id, {
        action: "create_invoice",
        plan: invoice.plan,
        billing_interval: invoice.billing_interval,
        due_days: invoice.due_days || 30,
      });
      await refreshManualInvoices(selectedProfile.id, session.access_token);
      setInvoiceFormOpen(false);
      setManualBillingNotice("Invoice setup resumed. Review the payment link below; it has not been emailed.");
    } catch (cause) {
      setManualBillingError(cause instanceof Error ? cause.message : "Invoice setup could not be resumed.");
      await refreshManualInvoices(selectedProfile.id, session.access_token).catch(() => undefined);
    } finally {
      setManualBusy("");
    }
  }

  async function sendManualInvoice(invoice: AdminManualPlanInvoice) {
    if (!session || !selectedProfile) return;
    setManualBusy(`send:${invoice.id}`);
    setManualBillingError("");
    setManualBillingNotice("");
    try {
      await adminManualPlanBillingAction(session.access_token, selectedProfile.id, {
        action: "send_invoice",
        invoice_id: invoice.id,
      });
      await refreshManualInvoices(selectedProfile.id, session.access_token);
      setManualBillingNotice("Invoice email sent to the account's verified email address.");
    } catch (cause) {
      setManualBillingError(cause instanceof Error ? cause.message : "Invoice email could not be sent.");
    } finally {
      setManualBusy("");
    }
  }

  async function recordManualPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !selectedProfile || !paymentInvoice || !receivedPaymentConfirmed) return;
    setManualBusy(`pay:${paymentInvoice.id}`);
    setManualBillingError("");
    setManualBillingNotice("");
    try {
      const result = await adminManualPlanBillingAction(session.access_token, selectedProfile.id, {
        action: "record_payment",
        invoice_id: paymentInvoice.id,
        payment_method: paymentMethod,
        payment_reference: paymentReference.trim(),
      });
      await refreshManualInvoices(selectedProfile.id, session.access_token);
      await refresh(session.access_token).catch(() => undefined);
      const grantStartsAt = typeof result.grant_starts_at === "string" ? result.grant_starts_at : "";
      const grantEndsAt = typeof result.grant_ends_at === "string" ? result.grant_ends_at : "";
      const grantOutcome = String(result.outcome || "");
      setManualBillingNotice(grantOutcome === "account_deleted" || grantOutcome === "account_unavailable"
        ? "Payment was confirmed, but this account is unavailable, so Cadivor did not grant access. Review the account before issuing another invoice."
        : grantStartsAt && Date.parse(grantStartsAt) > Date.now()
          ? `Payment confirmed. The ${paymentInvoice.plan} term is scheduled to start ${formatDate(grantStartsAt)} and run through ${formatDate(grantEndsAt)}.`
          : grantEndsAt
            ? `Payment confirmed. ${paymentInvoice.plan} access is active through ${formatDate(grantEndsAt)}.`
            : "Payment confirmed. Refresh the account billing history to review its access term.");
      setPaymentInvoice(null);
      setPaymentReference("");
      setReceivedPaymentConfirmed(false);
    } catch (cause) {
      setManualBillingError(cause instanceof Error ? cause.message : "Payment could not be recorded.");
    } finally {
      setManualBusy("");
    }
  }

  async function voidManualInvoice(invoice: AdminManualPlanInvoice) {
    if (!session || !selectedProfile) return;
    setManualBusy(`void:${invoice.id}`);
    setManualBillingError("");
    setManualBillingNotice("");
    try {
      await adminManualPlanBillingAction(session.access_token, selectedProfile.id, {
        action: "void_invoice",
        invoice_id: invoice.id,
      });
      await refreshManualInvoices(selectedProfile.id, session.access_token);
      setVoidConfirmInvoiceId("");
      setManualBillingNotice("Invoice voided. It can no longer be paid.");
    } catch (cause) {
      setManualBillingError(cause instanceof Error ? cause.message : "Invoice could not be voided.");
    } finally {
      setManualBusy("");
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
            <section style={{ marginTop: 24, paddingTop: 18, borderTop: "1px solid #dce4ef" }} aria-labelledby="admin-manual-billing-title">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start" }}>
                <div>
                  <h3 id="admin-manual-billing-title" className="cv-card-title">Manual invoice billing</h3>
                  <p className="cv-card-subtitle" style={{ marginTop: 6 }}>
                    Create a one-time monthly or annual invoice. Access starts only after payment is confirmed and expires at the end of the paid term; it does not renew automatically.
                  </p>
                </div>
                {selectedProfile.role !== "admin" ? (
                  <button
                    className="cv-button primary"
                    type="button"
                    disabled={manualLoading || Boolean(manualBusy) || manualInvoices.some((invoice) => ["creating", "open", "payment_recorded"].includes(invoice.status))}
                    onClick={() => { setInvoiceFormOpen((value) => !value); setManualBillingError(""); setManualBillingNotice(""); }}
                  >
                    {invoiceFormOpen ? "Close invoice form" : "Create invoice"}
                  </button>
                ) : null}
              </div>
              {selectedProfile.role === "admin" ? <p className="cv-small-note" style={{ marginTop: 12 }}>Platform administrator accounts are not billable.</p> : null}
              {manualBillingError ? <div className="cv-error" role="alert" style={{ marginTop: 12 }}>{manualBillingError}</div> : null}
              {manualBillingNotice ? <p role="status" className="cv-small-note" style={{ marginTop: 12 }}>{manualBillingNotice}</p> : null}
              {manualLoading ? <p role="status" className="cv-small-note" style={{ marginTop: 12 }}>Loading invoice history…</p> : null}
              {invoiceFormOpen && selectedProfile.role !== "admin" ? (
                <form onSubmit={(event) => void createManualInvoice(event)} className="cv-form-grid" style={{ marginTop: 14, padding: 14, border: "1px solid #dce4ef", borderRadius: 12, background: "#f8fbff" }}>
                  <div className="cv-field">
                    <label htmlFor="manual-invoice-plan">Plan</label>
                    <select id="manual-invoice-plan" value={invoicePlan} onChange={(event) => setInvoicePlan(event.target.value)}>
                      <option value="Starter">Starter</option>
                      <option value="Professional">Professional</option>
                      <option value="Business">Business</option>
                    </select>
                  </div>
                  <div className="cv-field">
                    <label htmlFor="manual-invoice-interval">Term</label>
                    <select id="manual-invoice-interval" value={invoiceInterval} onChange={(event) => setInvoiceInterval(event.target.value as "month" | "year")}>
                      <option value="month">One month</option>
                      <option value="year">One year</option>
                    </select>
                  </div>
                  <div className="cv-field">
                    <label htmlFor="manual-invoice-due-days">Payment due in days</label>
                    <input id="manual-invoice-due-days" type="number" min={1} max={90} value={invoiceDueDays} onChange={(event) => setInvoiceDueDays(Number(event.target.value))} required />
                  </div>
                  <p className="cv-small-note" style={{ gridColumn: "1 / -1", margin: 0 }}>
                    The amount comes from Cadivor&apos;s configured plan price and cannot be edited here. Creating an invoice does not grant access.
                  </p>
                  <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end" }}>
                    <button className="cv-button primary" type="submit" disabled={Boolean(manualBusy) || manualLoading}>
                      {manualBusy === "create" ? "Creating invoice…" : "Create one-time invoice"}
                    </button>
                  </div>
                </form>
              ) : null}
              {!manualLoading && manualInvoices.length === 0 ? (
                <p className="cv-small-note" style={{ marginTop: 14 }}>No manual invoices or invoice-funded plan terms.</p>
              ) : null}
              {manualInvoices.length ? (
                <div style={{ display: "grid", gap: 10, marginTop: 14 }}>
                  {manualInvoices.map((invoice) => {
                    const currentGrant = invoice.status === "paid" && invoice.grant_starts_at && invoice.grant_ends_at &&
                      Date.parse(invoice.grant_starts_at) <= Date.now() && Date.parse(invoice.grant_ends_at) > Date.now();
                    const statusLabel = invoice.status === "creating" ? invoice.stripe_invoice_id ? "Draft saved · setup incomplete" : "Setup incomplete" :
                      invoice.status === "open" ? "Awaiting payment" :
                        invoice.status === "payment_recorded" ? "Payment recorded" :
                          invoice.status === "paid" ? currentGrant ? "Paid · access active" : "Paid · term complete or upcoming" : "Voided";
                    return (
                      <article key={invoice.id} style={{ border: "1px solid #dce4ef", borderRadius: 11, padding: 12, background: "#fff" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                          <div>
                            <strong>{invoice.plan} · {invoice.billing_interval === "year" ? "Annual" : "Monthly"}</strong>
                            <div className="cv-small-note" style={{ marginTop: 4 }}>
                              {formatInvoiceAmount(invoice.amount_minor, invoice.currency)} · {statusLabel}
                            </div>
                            {invoice.due_at && invoice.status === "open" ? <small>Due {formatDate(invoice.due_at)}</small> : null}
                            {invoice.payment_method ? <small style={{ display: "block" }}>Payment: {invoice.payment_method === "offline_unclassified" ? "Offline payment" : invoice.payment_method}{invoice.payment_reference ? ` · ${invoice.payment_reference}` : ""}</small> : null}
                            {invoice.status === "paid" && invoice.grant_ends_at ? (
                              <small style={{ display: "block" }}>Access term: {formatDate(invoice.grant_starts_at)} – {formatDate(invoice.grant_ends_at)}</small>
                            ) : null}
                            {invoice.invoice_sent_at ? <small style={{ display: "block" }}>Invoice emailed {formatDate(invoice.invoice_sent_at)}</small> : null}
                          </div>
                          {invoice.status === "creating" ? (
                            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "start" }}>
                              <button className="cv-button primary" type="button" disabled={Boolean(manualBusy)} onClick={() => void resumeManualInvoice(invoice)}>
                                {manualBusy === `resume:${invoice.id}` ? "Resuming…" : "Resume invoice setup"}
                              </button>
                            </div>
                          ) : null}
                          {invoice.status === "open" || invoice.status === "payment_recorded" ? (
                            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "start" }}>
                              {invoice.hosted_invoice_url ? <a className="cv-button" href={invoice.hosted_invoice_url} target="_blank" rel="noreferrer">Open payment page</a> : null}
                              {invoice.invoice_pdf ? <a className="cv-button" href={invoice.invoice_pdf} target="_blank" rel="noreferrer">Download PDF</a> : null}
                              {invoice.status === "open" && !invoice.invoice_sent_at ? (
                                <button className="cv-button" type="button" disabled={Boolean(manualBusy)} onClick={() => void sendManualInvoice(invoice)}>
                                  {manualBusy === `send:${invoice.id}` ? "Sending…" : "Email invoice"}
                                </button>
                              ) : null}
                              <button
                                className="cv-button"
                                type="button"
                                disabled={Boolean(manualBusy)}
                                onClick={() => {
                                  setPaymentInvoice(invoice);
                                  setPaymentMethod(invoice.payment_method === "check" ? "check" : "cash");
                                  setPaymentReference(invoice.payment_reference || "");
                                  setReceivedPaymentConfirmed(false);
                                }}
                              >
                                {invoice.status === "payment_recorded" ? "Retry payment confirmation" : "Record cash/check"}
                              </button>
                              {invoice.status === "open" ? (
                                <button className="cv-button" type="button" disabled={Boolean(manualBusy)} onClick={() => setVoidConfirmInvoiceId(invoice.id)}>
                                  Void invoice
                                </button>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                        {invoice.status === "creating" ? (
                          <p className="cv-small-note" style={{ margin: "10px 0 0" }}>
                            No invoice email was sent and no access was granted. Resume continues this invoice record instead of creating another.
                          </p>
                        ) : null}
                        {voidConfirmInvoiceId === invoice.id ? (
                          <div style={{ marginTop: 10, padding: 10, borderRadius: 8, background: "#fff7f5", border: "1px solid #efc4ba" }}>
                            <p style={{ margin: "0 0 8px" }}>Void this unpaid invoice? The payment link will stop working.</p>
                            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                              <button className="cv-button" type="button" disabled={Boolean(manualBusy)} onClick={() => setVoidConfirmInvoiceId("")}>Keep invoice</button>
                              <button className="cv-button" type="button" disabled={Boolean(manualBusy)} onClick={() => void voidManualInvoice(invoice)}>
                                {manualBusy === `void:${invoice.id}` ? "Voiding…" : "Confirm void"}
                              </button>
                            </div>
                          </div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              ) : null}
              <p className="cv-small-note" style={{ marginTop: 12 }}>
                Record cash or check only after the full payment is in hand. Use a short reference if helpful; do not enter a full check or bank account number.
              </p>
            </section>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 20 }}>
              <button className="cv-button" type="button" disabled={profileLoading} onClick={() => { setSelectedProfile(null); setProfileError(""); }}>Close</button>
            </div>
          </section>
        </div>
      ) : null}

      {paymentInvoice ? (
        <div
          role="presentation"
          style={{ position: "fixed", inset: 0, zIndex: 1100, background: "rgba(12, 26, 45, .62)", display: "grid", placeItems: "center", padding: 16 }}
        >
          <section className="cv-card pad" role="dialog" aria-modal="true" aria-labelledby="manual-payment-title" style={{ width: "min(540px, 100%)", boxShadow: "0 24px 70px rgba(0,0,0,.24)" }}>
            <h2 id="manual-payment-title" className="cv-card-title">Record payment received</h2>
            <p className="cv-card-subtitle" style={{ marginTop: 8 }}>
              {paymentInvoice.plan} · {paymentInvoice.billing_interval === "year" ? "annual" : "monthly"} · {formatInvoiceAmount(paymentInvoice.amount_minor, paymentInvoice.currency)}
            </p>
            <form onSubmit={(event) => void recordManualPayment(event)} style={{ display: "grid", gap: 12, marginTop: 18 }}>
              <div className="cv-field">
                <label htmlFor="manual-payment-method">Payment method</label>
                <select id="manual-payment-method" value={paymentMethod} onChange={(event) => setPaymentMethod(event.target.value as "cash" | "check")}>
                  <option value="cash">Cash</option>
                  <option value="check">Check</option>
                </select>
              </div>
              <div className="cv-field">
                <label htmlFor="manual-payment-reference">Short reference (optional)</label>
                <input id="manual-payment-reference" maxLength={120} value={paymentReference} onChange={(event) => setPaymentReference(event.target.value)} placeholder="e.g. Check received Nov 24" />
              </div>
              <label style={{ display: "flex", gap: 9, alignItems: "start", lineHeight: 1.45 }}>
                <input type="checkbox" checked={receivedPaymentConfirmed} onChange={(event) => setReceivedPaymentConfirmed(event.target.checked)} style={{ marginTop: 3 }} />
                <span>I have received the full payment outside the payment page. The new access term may start after existing paid access ends.</span>
              </label>
              {manualBillingError ? <div className="cv-error" role="alert">{manualBillingError}</div> : null}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 4 }}>
                <button className="cv-button" type="button" disabled={Boolean(manualBusy)} onClick={() => { setPaymentInvoice(null); setManualBillingError(""); }}>Cancel</button>
                <button className="cv-button primary" type="submit" disabled={Boolean(manualBusy) || !receivedPaymentConfirmed}>
                  {manualBusy === `pay:${paymentInvoice.id}` ? "Confirming payment…" : "Confirm payment received"}
                </button>
              </div>
            </form>
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
