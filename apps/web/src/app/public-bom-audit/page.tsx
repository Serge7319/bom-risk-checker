"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { TermsAcceptance } from "@/components/TermsAcceptance";
import { TurnstileWidget } from "@/components/TurnstileWidget";
import { getSession } from "@/lib/api";
import {
  analyticsSessionId,
  marketingAnalyticsAllowed,
  trackMarketingEvent,
} from "@/lib/marketingAnalytics";
import {
  fetchPublicBomStatus,
  createPublicBomSummaryShare,
  requestPublicBomFullReport,
  runPublicBomAudit,
  type PublicBomAuditReport,
  type PublicBomStatus,
} from "@/lib/publicBomStress";

const TURNSTILE_SITE_KEY = (
  process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || ""
).trim();

const PUBLIC_BOM_LIMIT_MESSAGE =
  "This connection has used its two free BOM audits in the last 24 hours.";
const PUBLIC_BOM_MAX_BYTES = 1024 * 1024;
const STATUS_UNAVAILABLE_MESSAGE =
  "The free BOM stress test is temporarily unavailable. Please refresh and try again.";
const STATUS_DISABLED_MESSAGE =
  "The free BOM stress test is being prepared. Please check back soon.";

function leadSourceFromSearch(search: URLSearchParams): string {
  if ((search.get("source") || "").trim() === "free-audit-page") {
    return "free-audit-page";
  }
  if (!marketingAnalyticsAllowed()) return "homepage_stress_test";
  const fields: string[] = [];
  for (const key of ["utm_source", "utm_medium", "utm_campaign"] as const) {
    const raw = (search.get(key) || "").trim();
    const value = raw
      .replace(/[^A-Za-z0-9_.-]+/g, "-")
      .replace(/^[-.]+|[-.]+$/g, "")
      .slice(0, 48);
    if (value) fields.push(value);
  }
  return fields.length ? `utm:${fields.join(":")}` : "homepage_stress_test";
}

function PublicBomAuditInner() {
  const search = useSearchParams();
  const embedded = ["1", "true"].includes(
    (search.get("embed") || "").trim().toLowerCase(),
  );
  const leadSource = useMemo(() => leadSourceFromSearch(search), [search]);

  const [status, setStatus] = useState<PublicBomStatus | null>(null);
  const [statusError, setStatusError] = useState("");
  const [statusResolved, setStatusResolved] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fileDragActive, setFileDragActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<PublicBomAuditReport | null>(null);
  const [email, setEmail] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [pendingEmail, setPendingEmail] = useState("");
  const [verificationSent, setVerificationSent] = useState(true);
  const [leadBusy, setLeadBusy] = useState(false);
  const [leadError, setLeadError] = useState("");
  const [turnstileToken, setTurnstileToken] = useState("");
  const [shareBusy, setShareBusy] = useState(false);
  const [shareUrl, setShareUrl] = useState("");
  const [shareError, setShareError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setStatusResolved(false);
    setStatusError("");
    // Pass bearer when present so API can set qa_verified; never send a QA flag.
    const accessToken = getSession()?.access_token || null;
    fetchPublicBomStatus(accessToken)
      .then((payload) => {
        if (cancelled) return;
        setStatus(payload);
        setStatusError("");
      })
      .catch((err) => {
        if (cancelled) return;
        setStatus(null);
        setStatusError(
          err instanceof Error ? err.message : "Could not load the free audit.",
        );
      })
      .finally(() => {
        if (!cancelled) setStatusResolved(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!embedded) return;
    const root = document.querySelector<HTMLElement>(
      ".cv-public-stress-embed",
    );
    if (!root) return;

    let animationFrame = 0;
    const sendHeight = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(() => {
        const height = Math.ceil(
          Math.max(root.scrollHeight, root.getBoundingClientRect().height),
        );
        window.parent.postMessage(
          { type: "cadivor:public-bom-audit:resize", height },
          "*",
        );
      });
    };
    const observer = new ResizeObserver(sendHeight);
    observer.observe(root);
    sendHeight();
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(animationFrame);
    };
  }, [embedded]);

  // Only server-verified QA may skip Turnstile in the UI. Anonymous and
  // signed-in non-QA still complete the challenge when turnstile_required.
  const qaVerified = status?.qa_verified === true;
  const turnstileRequired =
    status?.turnstile_required === true && !qaVerified;

  async function onAudit(event: FormEvent) {
    event.preventDefault();
    if (!file || busy || status?.enabled !== true) return;
    const session = getSession();
    if (turnstileRequired && !turnstileToken.trim()) {
      setError("Complete the security check and try again.");
      return;
    }
    setBusy(true);
    setError("");
    trackMarketingEvent("free_audit_started", { flow: "public-bom-audit" }, "/public-bom-audit");
    try {
      const result = await runPublicBomAudit(file, {
        turnstileToken: turnstileToken || null,
        accessToken: session?.access_token || null,
      });
      setReport(result);
      trackMarketingEvent("free_audit_completed", { flow: "public-bom-audit" }, "/public-bom-audit");
      setPendingEmail("");
      setLeadError("");
      setTurnstileToken("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Audit failed.");
      setTurnstileToken("");
    } finally {
      setBusy(false);
    }
  }

  async function onLead(event: FormEvent) {
    event.preventDefault();
    if (!report || leadBusy || status?.enabled !== true) return;
    setLeadBusy(true);
    setLeadError("");
    try {
      const result = await requestPublicBomFullReport({
        reportId: report.id,
        email,
        acceptedTerms,
        source: leadSource,
      });
      setPendingEmail(result.email);
      setVerificationSent(result.verification_sent !== false);
      trackMarketingEvent(
        "free_audit_email_requested",
        { flow: "public-bom-audit" },
        "/public-bom-audit",
      );
    } catch (err) {
      setLeadError(
        err instanceof Error ? err.message : "Could not send the verification link.",
      );
    } finally {
      setLeadBusy(false);
    }
  }

  async function onShareSummary() {
    if (!report || shareBusy) return;
    setShareBusy(true);
    setShareError("");
    try {
      const result = await createPublicBomSummaryShare(report.id);
      const url = `${window.location.origin}/audit-share/${encodeURIComponent(result.token)}`;
      setShareUrl(url);
      await navigator.clipboard.writeText(url);
    } catch (err) {
      setShareError(
        err instanceof Error
          ? err.message
          : "Could not create or copy the share link.",
      );
    } finally {
      setShareBusy(false);
    }
  }

  function resetAudit() {
    setReport(null);
    setFile(null);
    setError("");
    setPendingEmail("");
    setVerificationSent(true);
    setLeadError("");
    setEmail("");
    setAcceptedTerms(false);
    setShareUrl("");
    setShareError("");
  }

  function selectBomFile(selectedFile: File | null) {
    setFileDragActive(false);
    if (!selectedFile) return;
    const extensionIsSupported = /\.(csv|xlsx)$/i.test(selectedFile.name);
    if (!extensionIsSupported) {
      setFile(null);
      setError("Choose a CSV or XLSX file.");
      return;
    }
    if (selectedFile.size > PUBLIC_BOM_MAX_BYTES) {
      setFile(null);
      setError("The file must be 1 MB or smaller.");
      return;
    }
    setFile(selectedFile);
    setError("");
  }

  const statusLoading = !statusResolved;
  const auditEnabled = status?.enabled === true;
  const shellClass = embedded
    ? "cv-public-stress cv-public-stress-embed"
    : "cv-public-stress";
  const trialParams = new URLSearchParams({
    auth: "signup",
    intent: "trial",
    source: "free-audit",
  });
  if (marketingAnalyticsAllowed()) {
    const sessionId = analyticsSessionId();
    if (sessionId) trialParams.set("cadivor_visit_id", sessionId);
  }
  const trialSignupHref = `https://app.cadivor.com/?${trialParams.toString()}`;

  return (
    <div className={shellClass} data-testid="public-bom-audit">
      {!embedded ? (
        <header className="cv-stress-site-header">
          <a
            className="cv-stress-brand"
            href="https://www.cadivor.com/#/home"
            target="_self"
            aria-label="Cadivor home"
          >
            <span className="cv-stress-brand-mark" aria-hidden>
              C
            </span>
            <span>
              <span className="cv-stress-brand-name">Cadivor</span>
              <span className="cv-stress-brand-line">
                Engineering Decision Intelligence
              </span>
            </span>
          </a>
          <span className="cv-stress-header-note">Free BOM audit</span>
        </header>
      ) : null}

      <section className="cv-public-stress-panel">
        {statusLoading ? (
          <p className="cv-small-note" data-testid="public-bom-status-loading">
            Checking whether the free BOM audit is available…
          </p>
        ) : null}

        {!statusLoading && statusError ? (
          <div
            className="cv-error"
            role="alert"
            data-testid="public-bom-status-error"
          >
            {statusError}
          </div>
        ) : null}

        {!statusLoading && !auditEnabled ? (
          <p
            className="cv-small-note"
            data-testid="public-bom-status-unavailable"
          >
            {statusError ? STATUS_UNAVAILABLE_MESSAGE : STATUS_DISABLED_MESSAGE}
          </p>
        ) : null}

        {auditEnabled && !report ? (
          <>
            <h1>Free BOM stress test</h1>
            <p>
              Upload a BOM (.csv / .xlsx) for a supplier-backed risk and
              lifecycle review. Cadivor checks every accepted row, then shows
              the five highest-priority findings. Unverified parts stay clearly
              labeled as needing verification.
            </p>
            <p className="cv-small-note">
              Up to {status?.max_rows ?? 30} rows and 1 MB. Supplier lookups may
              take several minutes. Do not upload regulated or export-controlled
              designs.
            </p>
            <form className="cv-public-stress-upload" onSubmit={onAudit}>
              <label
                className={`cv-public-stress-drop${fileDragActive ? " is-dragging" : ""}`}
                onDragEnter={(event) => {
                  event.preventDefault();
                  setFileDragActive(true);
                }}
                onDragOver={(event) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "copy";
                  setFileDragActive(true);
                }}
                onDragLeave={(event) => {
                  const nextTarget = event.relatedTarget;
                  if (
                    nextTarget instanceof Node &&
                    event.currentTarget.contains(nextTarget)
                  ) {
                    return;
                  }
                  setFileDragActive(false);
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  selectBomFile(event.dataTransfer.files?.[0] || null);
                }}
                data-testid="public-bom-drop-zone"
              >
                <span>{fileDragActive ? "Release to add your BOM" : "Drop your BOM here or choose a file"}</span>
                <input
                  type="file"
                  accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  onChange={(event) => {
                    selectBomFile(event.target.files?.[0] || null);
                  }}
                />
                {file ? (
                  <span className="cv-small-note">{file.name}</span>
                ) : (
                  <span className="cv-small-note">CSV or XLSX · max 1 MB</span>
                )}
              </label>
              {error ? <div className="cv-error">{error}</div> : null}
              {error === PUBLIC_BOM_LIMIT_MESSAGE ? (
                <p className="cv-small-note">
                  This allowance resets on a rolling 24-hour window. Return later
                  to run another anonymous audit.
                </p>
              ) : null}
              {turnstileRequired && TURNSTILE_SITE_KEY ? (
                <TurnstileWidget
                  siteKey={TURNSTILE_SITE_KEY}
                  action="public_bom_audit"
                  onToken={setTurnstileToken}
                  onExpire={() => setTurnstileToken("")}
                />
              ) : null}
              <button
                type="submit"
                className="cv-button primary"
                data-testid="public-bom-run-audit"
                disabled={
                  !file ||
                  busy ||
                  !auditEnabled ||
                  (turnstileRequired && !turnstileToken.trim())
                }
              >
                {busy
                  ? "Checking lifecycle and supplier evidence…"
                  : "Run free audit"}
              </button>
            </form>
          </>
        ) : null}

        {auditEnabled && report ? (
          <>
            <div className="cv-public-stress-toolbar">
              <h1>Preliminary BOM audit</h1>
              <button type="button" className="cv-button" onClick={resetAudit}>
                Audit another BOM
              </button>
            </div>
            <p className="cv-small-note">
              Top {report.preview.length} findings across the checked BOM · verify your email to unlock all component details.
            </p>
            <p className="cv-success-note">
              Your BOM contains {report.row_count} components. The preview below ranks the highest-priority findings from the full supplier check.
            </p>
            <section className="cv-public-audit-metrics" aria-label="Findings in the top-ranked preview">
              <div><strong>{report.checked_summary?.blockers ?? "—"}</strong><span>Blockers</span></div>
              <div><strong>{report.checked_summary?.lifecycle_alerts ?? "—"}</strong><span>Lifecycle alerts</span></div>
              <div><strong>{report.checked_summary?.single_source_parts ?? "—"}</strong><span>Single-source parts</span></div>
              <p>
                Counts cover the displayed ranked rows. Only supplier-verified rows count as confirmed blockers or sourcing findings.
              </p>
            </section>
            <div className="cv-public-stress-table-wrap">
              <table className="cv-public-stress-table">
                <thead>
                  <tr>
                    <th>Rank</th>
                    <th>MPN</th>
                    <th>Manufacturer</th>
                    <th>Lifecycle</th>
                    <th>Reported stock</th>
                    <th>Stock evidence</th>
                    <th>Lead time (weeks)</th>
                    <th>Lead time source</th>
                    <th>Matched suppliers</th>
                    <th>Source(s) checked</th>
                    <th>Supplier coverage</th>
                    <th>Risk</th>
                    <th>Why it ranked here</th>
                  </tr>
                </thead>
                <tbody>
                  {report.preview.map((row) => (
                    <tr key={`${row.mpn}-${row.manufacturer || ""}`}>
                      <td>{row.preview_rank ?? "—"}</td>
                      <td>{row.mpn}</td>
                      <td>{row.manufacturer || "Not matched"}</td>
                      <td>{row.lifecycle || "Unknown"}</td>
                      <td>{row.stock == null ? "" : String(row.stock)}</td>
                      <td>
                        {row.stock_evidence ||
                          "Not reported by matched suppliers"}
                      </td>
                      <td>
                        {row.lead_time_weeks == null
                          ? ""
                          : String(row.lead_time_weeks)}
                      </td>
                      <td>{row.lead_time_source || "Not reported"}</td>
                      <td>
                        {row.supplier_count == null
                          ? ""
                          : String(row.supplier_count)}
                      </td>
                      <td>{row.sources || ""}</td>
                      <td>{row.supplier_coverage || ""}</td>
                      <td>{row.risk || ""}</td>
                      <td>{row.risk_reasons?.join(" · ") || (row.verified ? "No specific driver reported" : "Exact part and supplier evidence need verification")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="cv-small-note">
              Blank stock or lead-time values mean the supplier did not report a
              usable figure. Lifecycle is shown only when a supplier provided a
              status; Unknown does not mean Active. Inventory reflects the
              checked supplier sources and can vary by region and time. Verified
              high and medium risks rank first; unverified evidence gaps appear
              before verified low-risk rows. The free audit does not search for
              alternate parts.
            </p>

            {report.remaining_count > 0 ? (
              <div className="cv-stress-locked">
                <strong>
                  Locked preview · {report.remaining_count} additional components
                </strong>
                <p>
                  The details for these {report.remaining_count} checked components remain locked in this preview.
                  Confirm your email to save and unlock the complete audit.
                </p>
              </div>
            ) : (
              <p className="cv-small-note">
                All component details fit in the free preview. Verify your email to save and download this audit.
              </p>
            )}

            <div className="cv-public-audit-share">
              <div>
                <strong>Share this audit summary</strong>
                <p className="cv-small-note">
                  Read-only, aggregate findings only. The link expires in 30 days and does not show component numbers.
                </p>
              </div>
              <button
                type="button"
                className="cv-button"
                onClick={() => void onShareSummary()}
                disabled={shareBusy}
              >
                {shareBusy ? "Creating link…" : shareUrl ? "Copy link again" : "Create share link"}
              </button>
              {shareUrl ? <p className="cv-success-note" role="status">Copied: <a href={shareUrl}>{shareUrl}</a></p> : null}
              {shareError ? <p className="cv-error" role="alert">{shareError}</p> : null}
            </div>

            {pendingEmail ? (
              <p
                className="cv-success-note"
                role="status"
                data-testid="public-bom-lead-status"
              >
                {verificationSent
                  ? `Check ${pendingEmail} for your Cadivor verification email. Open its link to confirm your address, then continue to Reports for the complete audit.`
                  : `A verification email was already sent recently to ${pendingEmail}. Check that inbox (and spam), or wait before requesting another link. Your complete audit still unlocks in Reports after you confirm.`}
              </p>
            ) : (
              <form className="cv-public-stress-lead" onSubmit={onLead}>
                <label>
                  Email address
                  <input
                    type="email"
                    autoComplete="email"
                    placeholder="you@company.com"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                  />
                </label>
                <TermsAcceptance
                  checked={acceptedTerms}
                  onChange={setAcceptedTerms}
                  disabled={leadBusy}
                />
                {leadError ? <div className="cv-error">{leadError}</div> : null}
                <button
                  type="submit"
                  className="cv-button primary"
                  disabled={leadBusy || !email.trim() || !acceptedTerms}
                >
                  {leadBusy ? "Sending…" : "Email my full report"}
                </button>
                <p className="cv-small-note">
                  We&apos;ll send a secure one-time sign-in link. Verify your
                  email to unlock the full audit in Reports.
                </p>
              </form>
            )}

            <div className="cv-public-audit-convert">
              <p><strong>Want to keep working with this BOM?</strong></p>
              <a
                className="cv-button primary"
                href={trialSignupHref}
                onClick={() => trackMarketingEvent(
                  "free_audit_trial_clicked",
                  { flow: "public-bom-audit", cta: "start-trial" },
                  "/public-bom-audit",
                )}
              >
                Start a 14-day trial
              </a>
              <a className="cv-button" href="https://app.cadivor.com/single-bom-report">
                Get a one-time report
              </a>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}

export default function PublicBomAuditPage() {
  return (
    <Suspense
      fallback={
        <div className="cv-public-stress" data-testid="public-bom-audit-loading">
          <p className="cv-small-note">Loading free BOM audit…</p>
        </div>
      }
    >
      <PublicBomAuditInner />
    </Suspense>
  );
}
