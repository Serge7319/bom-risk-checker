"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { Shell } from "@/components/Shell";
import { listReports } from "@/lib/api";
import {
  cacheVerifiedPublicBomReport,
  completePublicBomAudit,
  fetchVerifiedPublicBomReport,
  normalizeStressReportId,
  peekStressReportId,
  readCachedVerifiedPublicBomReport,
  verifiedReportExportHref,
  type PublicBomVerifiedReport,
} from "@/lib/publicBomStress";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

function ReportsInner() {
  const session = useRequireSession();
  const search = useSearchParams();
  const stressHandoff =
    (search.get("public_bom_stress") || "").trim() === "1";
  const reportIdFromQuery = normalizeStressReportId(search.get("report_id"));

  const [reports, setReports] = useState<Array<Record<string, unknown>>>([]);
  const [gap, setGap] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [stressReport, setStressReport] =
    useState<PublicBomVerifiedReport | null>(null);
  const [stressError, setStressError] = useState("");
  const [stressBusy, setStressBusy] = useState(false);
  const [completeBusy, setCompleteBusy] = useState(false);

  useEffect(() => {
    if (!session) return;
    setBusy(true);
    listReports(session.access_token)
      .then((payload) => {
        setReports(payload.reports || []);
        setGap(payload.gap || "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }, [session]);

  useEffect(() => {
    if (!session) return;
    const identity = session.user_id || session.email;
    // Prefer the handoff selector, then the last opened report id (reload).
    const selectedReportId = reportIdFromQuery || peekStressReportId();
    const cached = readCachedVerifiedPublicBomReport(
      identity,
      selectedReportId,
    );
    if (cached) setStressReport(cached);

    let cancelled = false;
    setStressBusy(true);
    setStressError("");
    setCompleteBusy(false);

    (async () => {
      try {
        let report = await fetchVerifiedPublicBomReport(
          session.access_token,
          selectedReportId,
        );
        const pending = (report.results || []).some(
          (row) => row.enrichment_pending,
        );
        if (!report.full_enriched || pending) {
          setCompleteBusy(true);
          report = await completePublicBomAudit(
            session.access_token,
            report.id || selectedReportId,
          );
        }
        if (cancelled) return;
        setStressReport(report);
        cacheVerifiedPublicBomReport(identity, report);
      } catch (err) {
        if (cancelled) return;
        if (!cached) setStressReport(null);
        if (stressHandoff || selectedReportId) {
          setStressError(
            err instanceof Error
              ? err.message
              : "Your verified public audit is not available yet.",
          );
        }
      } finally {
        if (!cancelled) {
          setStressBusy(false);
          setCompleteBusy(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [session, stressHandoff, reportIdFromQuery]);

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.reports}
        actions={<PrimaryLink href="/bom-analyzer">New BOM analysis</PrimaryLink>}
      />
      {<EvidenceNotice gap={gap} />}

      {stressHandoff || stressReport || stressBusy || stressError ? (
        <section
          className="cv-card pad"
          data-testid="public-bom-verified-report"
          style={{ marginBottom: 18 }}
        >
          <div className="cv-section-heading cv-section-heading--card">
            <div>
              <h2>Free BOM audit</h2>
              <p>
                Complete supplier-backed results unlocked after email
                verification. This audit stays available here after reload.
              </p>
            </div>
          </div>
          {stressBusy && !stressReport ? (
            <LoadingCard
              label={
                completeBusy
                  ? "Finishing supplier lookups for remaining components…"
                  : "Loading your verified public audit…"
              }
            />
          ) : null}
          {stressError && !stressReport ? (
            <div className="cv-error" role="alert">
              {stressError}
            </div>
          ) : null}
          {stressReport ? (
            <>
              <p className="cv-small-note" style={{ marginTop: 0 }}>
                {stressReport.filename || "Uploaded BOM"} ·{" "}
                {stressReport.row_count ?? stressReport.results?.length ?? 0}{" "}
                components
                {stressReport.created_at
                  ? ` · ${new Date(stressReport.created_at).toLocaleString()}`
                  : ""}
                {stressReport.full_enriched ? " · Complete" : ""}
              </p>
              {completeBusy ? (
                <LoadingCard label="Finishing supplier lookups for remaining components…" />
              ) : null}
              <div className="cv-table-wrap">
                <table className="cv-table" data-testid="public-bom-verified-table">
                  <thead>
                    <tr>
                      <th>MPN</th>
                      <th>Manufacturer</th>
                      <th>Qty</th>
                      <th>Lifecycle</th>
                      <th>Reported stock</th>
                      <th>Lead time (weeks)</th>
                      <th>Matching suppliers</th>
                      <th>Risk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(stressReport.results || []).map((row, index) => (
                      <tr key={`${row.mpn || "row"}-${index}`}>
                        <td>{row.mpn || ""}</td>
                        <td>{row.manufacturer || "Not matched"}</td>
                        <td>
                          {row.quantity == null ? "—" : String(row.quantity)}
                        </td>
                        <td>{row.lifecycle || "Unverified"}</td>
                        <td>{row.stock == null ? "—" : String(row.stock)}</td>
                        <td>
                          {row.lead_time_weeks == null
                            ? "—"
                            : String(row.lead_time_weeks)}
                        </td>
                        <td>
                          {row.supplier_count == null
                            ? "—"
                            : String(row.supplier_count)}
                        </td>
                        <td>{row.risk || "Needs verification"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {stressReport.full_enriched !== false ? (
                <div
                  className="cv-actions"
                  style={{ marginTop: 12, display: "flex", gap: 8 }}
                >
                  <a
                    className="cv-button small"
                    data-testid="public-bom-download-csv"
                    href={verifiedReportExportHref(stressReport.id, "csv")}
                    onClick={async (event) => {
                      event.preventDefault();
                      if (!session) return;
                      const res = await fetch(
                        verifiedReportExportHref(stressReport.id, "csv"),
                        {
                          headers: {
                            Authorization: `Bearer ${session.access_token}`,
                          },
                        },
                      );
                      if (!res.ok) return;
                      const blob = await res.blob();
                      const url = URL.createObjectURL(blob);
                      const link = document.createElement("a");
                      link.href = url;
                      link.download = "bom-audit-complete.csv";
                      link.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    Download CSV
                  </a>
                  <a
                    className="cv-button small"
                    data-testid="public-bom-download-xlsx"
                    href={verifiedReportExportHref(stressReport.id, "xlsx")}
                    onClick={async (event) => {
                      event.preventDefault();
                      if (!session) return;
                      const res = await fetch(
                        verifiedReportExportHref(stressReport.id, "xlsx"),
                        {
                          headers: {
                            Authorization: `Bearer ${session.access_token}`,
                          },
                        },
                      );
                      if (!res.ok) return;
                      const blob = await res.blob();
                      const url = URL.createObjectURL(blob);
                      const link = document.createElement("a");
                      link.href = url;
                      link.download = "bom-audit-complete.xlsx";
                      link.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    Download Excel
                  </a>
                </div>
              ) : null}
            </>
          ) : null}
        </section>
      ) : null}

      {busy ? <LoadingCard label="Loading saved reports…" /> : null}
      {error ? <div className="cv-error" role="alert">Reports could not load. {error}</div> : null}
      {!busy && !error ? (
        reports.length ? (
          <section className="cv-card pad">
            <div className="cv-section-heading cv-section-heading--card">
              <div>
                <h2>Saved analyses</h2>
                <p>Open a report to review its evidence and download PDF, Excel, or CSV copies.</p>
              </div>
              <span className="cv-data-note">{reports.length} report{reports.length === 1 ? "" : "s"}</span>
            </div>
            <div className="cv-table-wrap">
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>Analysis</th>
                    <th>Health</th>
                    <th>Components</th>
                    <th>High risk</th>
                    <th>Saved</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((row) => {
                    const id = String(row.id || row.analysis_id || "");
                    return (
                      <tr key={id}>
                        <td><strong>{String(row.filename || row.bom_name || id)}</strong></td>
                        <td>{row.health_score == null ? "Not scored" : `${String(row.health_score)}/100`}</td>
                        <td>{String(row.total_parts ?? "—")}</td>
                        <td>{String(row.high_risk_count ?? "—")}</td>
                        <td>{row.created_at ? new Date(String(row.created_at)).toLocaleDateString() : "—"}</td>
                        <td><Link className="cv-button small" href={`/reports/${encodeURIComponent(id)}`}>Open &amp; download</Link></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        ) : (
          !stressReport ? (
            <EmptyState
              icon="report"
              title="No saved reports yet"
              body="Completed BOM analyses are saved to this workspace and appear here for you to reopen."
              action={<PrimaryLink href="/bom-analyzer">Start a BOM analysis</PrimaryLink>}
            />
          ) : null
        )
      ) : null}
    </Shell>
  );
}

export default function ReportsIndexPage() {
  return (
    <Suspense fallback={<div className="cv-card pad">Loading reports…</div>}>
      <ReportsInner />
    </Suspense>
  );
}
