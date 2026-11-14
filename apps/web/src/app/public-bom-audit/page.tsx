"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { TermsAcceptance } from "@/components/TermsAcceptance";
import {
  fetchPublicBomStatus,
  requestPublicBomFullReport,
  runPublicBomAudit,
  type PublicBomAuditReport,
  type PublicBomStatus,
} from "@/lib/publicBomStress";

const PUBLIC_BOM_LIMIT_MESSAGE =
  "This connection has used its two free BOM audits in the last 24 hours.";
const STATUS_UNAVAILABLE_MESSAGE =
  "The free BOM stress test is temporarily unavailable. Please refresh and try again.";
const STATUS_DISABLED_MESSAGE =
  "The free BOM stress test is being prepared. Please check back soon.";

function leadSourceFromSearch(search: URLSearchParams): string {
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<PublicBomAuditReport | null>(null);
  const [email, setEmail] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [pendingEmail, setPendingEmail] = useState("");
  const [verificationSent, setVerificationSent] = useState(true);
  const [leadBusy, setLeadBusy] = useState(false);
  const [leadError, setLeadError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setStatusResolved(false);
    setStatusError("");
    fetchPublicBomStatus()
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

  async function onAudit(event: FormEvent) {
    event.preventDefault();
    if (!file || busy || status?.enabled !== true) return;
    setBusy(true);
    setError("");
    try {
      const result = await runPublicBomAudit(file);
      setReport(result);
      setPendingEmail("");
      setLeadError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Audit failed.");
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
    } catch (err) {
      setLeadError(
        err instanceof Error ? err.message : "Could not send the verification link.",
      );
    } finally {
      setLeadBusy(false);
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
  }

  const statusLoading = !statusResolved;
  const auditEnabled = status?.enabled === true;
  const shellClass = embedded
    ? "cv-public-stress cv-public-stress-embed"
    : "cv-public-stress";

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
              Drop your BOM (.csv / .xlsx) here for a supplier-backed risk and
              lifecycle review. Results show when a supplier could not verify a
              component. No account is needed to see the first five components.
            </p>
            <p className="cv-small-note">
              Up to {status?.max_rows ?? 30} rows and 1 MB. Supplier lookups may
              take several minutes. Do not upload regulated or export-controlled
              designs.
            </p>
            <form className="cv-public-stress-upload" onSubmit={onAudit}>
              <label className="cv-public-stress-drop">
                <span>Drop your BOM here</span>
                <input
                  type="file"
                  accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  onChange={(event) => {
                    setFile(event.target.files?.[0] || null);
                    setError("");
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
              <button
                type="submit"
                className="cv-button primary"
                data-testid="public-bom-run-audit"
                disabled={!file || busy || !auditEnabled}
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
              First five checked components · verify your email for the complete
              audit.
            </p>
            <p className="cv-success-note">
              Checked {report.row_count} components. Here are the first{" "}
              {report.preview.length} results.
            </p>
            <div className="cv-public-stress-table-wrap">
              <table className="cv-public-stress-table">
                <thead>
                  <tr>
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
                  </tr>
                </thead>
                <tbody>
                  {report.preview.map((row) => (
                    <tr key={`${row.mpn}-${row.manufacturer || ""}`}>
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
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="cv-small-note">
              Blank stock or lead-time values mean the supplier did not report a
              usable figure. Lifecycle is shown only when a supplier provided a
              status; Unknown does not mean Active. Inventory reflects the
              checked supplier sources and can vary by region and time. The free
              audit does not search for alternate parts.
            </p>

            {report.remaining_count > 0 ? (
              <div className="cv-stress-locked">
                <strong>
                  {report.remaining_count} more components are locked ·{" "}
                  {report.remaining_high_risk} verified high-risk dependencies
                </strong>
                Verify your email to see the full report, including lifecycle,
                stock, lead time, and evidence.
                {report.remaining_unverified
                  ? ` ${report.remaining_unverified} components still need supplier verification.`
                  : ""}
              </div>
            ) : (
              <p className="cv-small-note">
                All components fit in the free preview. Verify your email to save
                and download this audit.
              </p>
            )}

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
