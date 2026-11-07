"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import {
  beginOneTimeReportCheckout,
  fetchOneTimeReportStatus,
  type OneTimeReportStatus,
} from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

function formatPrice(value: OneTimeReportStatus["price"]): string {
  if (!value || !Number.isFinite(value.amount)) return "Price unavailable";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: value.currency || "USD",
  }).format(value.amount / 100);
}

function dateLabel(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function SingleBomReportPage() {
  const session = useRequireSession();
  const [status, setStatus] = useState<OneTimeReportStatus | null>(null);
  const [busy, setBusy] = useState(true);
  const [checkoutBusy, setCheckoutBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    if (!session) return;
    setError("");
    try {
      setStatus(await fetchOneTimeReportStatus(session.access_token));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Purchase status could not load.");
    } finally {
      setBusy(false);
    }
  }, [session]);

  useEffect(() => {
    if (!session) return;
    const checkout = new URLSearchParams(window.location.search).get("checkout");
    if (checkout === "success") {
      setNotice("Checkout returned. Your credit appears after Stripe confirms payment through its signed webhook.");
    } else if (checkout === "cancel") {
      setNotice("Checkout was canceled. No report credit was used.");
    }
    void refresh();
  }, [session, refresh]);

  async function onPurchase() {
    if (!session) return;
    setCheckoutBusy(true);
    setError("");
    try {
      const result = await beginOneTimeReportCheckout(session.access_token);
      const checkoutUrl = result.checkout?.url;
      if (result.checkout?.state === "processing") {
        setNotice("Stripe is confirming your checkout. Refresh status in a moment.");
        await refresh();
        return;
      }
      if (!checkoutUrl) throw new Error(result.detail || "Secure checkout could not be started.");
      window.location.assign(checkoutUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Secure checkout could not be started.");
    } finally {
      setCheckoutBusy(false);
    }
  }

  if (!session) return null;

  const orders = status?.orders || [];
  const existingCheckout = status?.checkout?.state === "open" && status.checkout.url;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.single_bom_report}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">BOM Analyzer</PrimaryLink>
            <SecondaryLink href="/settings">Settings</SecondaryLink>
          </>
        }
      />

      {busy ? <LoadingCard label="Checking one-time report status…" /> : null}
      {error ? <div className="cv-error" role="alert">{error}</div> : null}
      {notice ? <div className="cv-notice" role="status">{notice}</div> : null}

      {!busy && status ? (
        <>
          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <div className="cv-section-heading" style={{ marginTop: 0 }}>
              <div>
                <div className="cv-eyebrow">ONE-TIME PURCHASE</div>
                <h2 className="cv-card-title">One complete report for one BOM</h2>
                <p className="cv-card-subtitle">
                  Use Cadivor’s established BOM risk and alternative workflow, save the full report in your workspace, then download PDF, Excel, or CSV exports.
                </p>
              </div>
              <strong style={{ fontSize: 24, whiteSpace: "nowrap" }}>{formatPrice(status.price)}</strong>
            </div>
            <ul className="cv-bom-checklist" style={{ marginTop: 18 }}>
              <li><span className="cv-bom-check-icon">✓</span><span><strong>Up to {status.max_components} unique components</strong><small>Duplicates are counted once toward the limit.</small></span></li>
              <li><span className="cv-bom-check-icon">✓</span><span><strong>One-time payment</strong><small>No monthly subscription is started.</small></span></li>
              <li><span className="cv-bom-check-icon">✓</span><span><strong>Full saved report and exports</strong><small>Return to your report later from Reports.</small></span></li>
            </ul>

            <div className="cv-header-actions" style={{ justifyContent: "flex-start", marginTop: 18 }}>
              {status.available_credit ? (
                <PrimaryLink href="/bom-analyzer">Analyze a BOM with your report credit</PrimaryLink>
              ) : existingCheckout ? (
                <a className="cv-button primary" href={status.checkout?.url || ""}>Continue secure checkout</a>
              ) : (
                <button
                  type="button"
                  className="cv-button primary"
                  disabled={!status.enabled || checkoutBusy || status.analysis_in_progress}
                  onClick={onPurchase}
                >
                  {checkoutBusy ? "Preparing checkout…" : `Purchase one-time report · ${formatPrice(status.price)}`}
                </button>
              )}
              <button type="button" className="cv-button" onClick={() => void refresh()} disabled={busy}>
                Refresh status
              </button>
            </div>

            {!status.enabled ? (
              <p className="cv-small-note" style={{ marginTop: 12 }}>New one-time purchases are temporarily unavailable. Previously purchased reports remain available below.</p>
            ) : null}
            {status.analysis_in_progress && !status.available_credit ? (
              <p className="cv-small-note" style={{ marginTop: 12 }}>A paid report analysis is already in progress for this account. Finish that analysis before starting another.</p>
            ) : null}
          </section>

          <section className="cv-card pad">
            <h2 className="cv-card-title">Purchase history</h2>
            <p className="cv-card-subtitle">Payment status is confirmed by Stripe’s signed webhook, not by the return page.</p>
            {orders.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead><tr><th>Date</th><th>Status</th><th>Report</th></tr></thead>
                  <tbody>
                    {orders.map((order) => (
                      <tr key={order.id}>
                        <td>{dateLabel(order.created_at)}</td>
                        <td>{order.status.replaceAll("_", " ")}</td>
                        <td>{order.analysis_id ? <Link href={`/reports/${order.analysis_id}`}>Open saved report</Link> : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState icon="report" title="No one-time report purchases yet" body="A purchase credit will appear here after Stripe confirms payment." />
            )}
          </section>
        </>
      ) : null}
    </Shell>
  );
}
