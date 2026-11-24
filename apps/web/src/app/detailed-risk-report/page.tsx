"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { userFacingLabel } from "@/lib/display";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { StatusPill } from "@/components/StatusPill";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { fetchDetailedRisk } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function cell(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function DetailedRiskPageInner() {
  const searchParams = useSearchParams();
  const requestedAnalysisId = (searchParams.get("analysis_id") || "").trim();
  const session = useRequireSession();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [activeAnalysisId, setActiveAnalysisId] = useState("");

  useEffect(() => {
    if (!session) return;
    let active = true;
    const last = readLastAnalysis(session);
    const analysisId = requestedAnalysisId || last?.analysis_id || "";
    setActiveAnalysisId(analysisId);
    setBusy(true);
    setError("");
    setData(null);
    fetchDetailedRisk(session.access_token, analysisId || undefined)
      .then((payload) => {
        if (!active) return;
        setData(payload);
        setActiveAnalysisId(String(payload.analysis_id || analysisId));
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Failed");
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [session, requestedAnalysisId]);

  if (!session) return null;
  const rows = (data?.rows || []) as Array<Record<string, unknown>>;
  const summary = (data?.summary || {}) as Record<string, unknown>;
  const healthScore = data?.health_score;
  const healthScoreNumber = Number(healthScore);
  const healthTone = healthScore == null || !Number.isFinite(healthScoreNumber)
    ? "blue"
    : healthScoreNumber >= 80 ? "green" : healthScoreNumber >= 60 ? "amber" : "red";
  const highRiskValue = data?.high_risk_count ?? summary.high_risk_component_count;
  const highRiskNumber = Number(highRiskValue);
  const assessmentScored = healthScore != null && Number.isFinite(healthScoreNumber);
  const highRiskTone = highRiskValue == null || !Number.isFinite(highRiskNumber)
    ? "blue"
    : highRiskNumber > 0 ? "red" : assessmentScored ? "green" : "blue";
  const healthStatusLabel = userFacingLabel(data?.health_status, healthScore == null ? "Not scored" : "Health reported");
  const highRiskStatus = highRiskValue == null || !Number.isFinite(highRiskNumber)
    ? { label: "Not reported", tone: "gray" as const }
    : highRiskNumber > 0
      ? { label: "Needs review", tone: "red" as const }
      : assessmentScored
        ? { label: "None in rated rows", tone: "green" as const }
        : { label: "Risk not scored", tone: "gray" as const };

  return (
    <Shell session={session}>
      <PageHeader
        meta={{
          ...PAGE_META.risk,
          title: data?.filename ? `Risk evidence · ${userFacingLabel(data.filename, "Saved analysis")}` : PAGE_META.risk.title,
        }}
        record
        actions={
          <>
            {activeAnalysisId ? (
              <PrimaryLink href={`/reports/${encodeURIComponent(activeAnalysisId)}`}>Back to full report</PrimaryLink>
            ) : null}
            <SecondaryLink href="/reports">Saved reports</SecondaryLink>
          </>
        }
      />
      {<EvidenceNotice gap={data?.gap} />}
      {activeAnalysisId ? (
        <p className="cv-risk-detail-context" role="note">
          This is the component evidence drill-down for the selected saved revision. Use <strong>Back to full report</strong> to return to the Risks overview, revision comparison, exports, and the linked Evidence, Decision, and Monitor workflow.
        </p>
      ) : null}
      {!busy && data?.evidence_summary ? (
        <p className="cv-small-note" style={{ marginBottom: 12 }} data-testid="detailed-risk-evidence-summary">
          {(() => {
            const summary = data.evidence_summary as Record<string, unknown>;
            const live = Number(summary.live_count || 0);
            const synthetic = Number(summary.synthetic_count || 0);
            const missing = Number(summary.missing_count || 0);
            const unverified = Number(summary.unverified_count || 0);
            return `Row evidence for this analysis: exact supplier identity verified ${live}; unverified supplier identity ${unverified}; synthetic/preview ${synthetic}; no supplier match ${missing}. Identity matches do not verify price, stock, or lifecycle fields. Mode: ${String(data.mode || "not reported")}.`;
          })()}
        </p>
      ) : null}
      {busy ? <LoadingCard label="Loading detailed risk rows…" /> : null}
      {error ? <div className="cv-error" role="alert">Risk details could not load. {error}</div> : null}
      {!busy && data ? (
        rows.length ? <>
          <div className="cv-kpis">
            <KpiCard
              icon="shield"
              tone={healthTone}
              label="Health score"
              value={healthScore == null ? "Not scored" : `${String(healthScore)}/100`}
              status={{ label: healthStatusLabel, tone: healthTone === "blue" ? "gray" : healthTone }}
              detail={assessmentScored
                ? "Screening index: 100 minus average component risk score."
                : String(data.summary_message || "Withheld until every BOM line has complete, current evidence. Individual risk labels may still appear.")}
            />
            <KpiCard icon="box" tone="blue" label="Components assessed" value={rows.length} status={{ label: "In this report", tone: "blue" }} detail="Rows assessed" />
            <KpiCard
              icon="risk"
              tone={highRiskTone}
              label="High-risk signals"
              value={String(
                highRiskValue ?? "Not reported",
              )}
              status={highRiskStatus}
              detail={assessmentScored ? "Verified priority findings to review" : "Not scored; zero does not mean risk-free"}
            />
          </div>
          <section className="cv-card pad">
            <h3 className="cv-card-title">Component risk detail</h3>
            <p className="cv-small-note" style={{ marginTop: 6 }}>
              Lifecycle, stock, and price each show their own evidence status. Supplier API observations are point-in-time snapshots tied to exact MPN listings; stock totals may sum those listings. They are not authenticated checkout inventory, reservations, or purchase quotes. “Not reported” means the source did not return that field.
            </p>
            <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>MPN</th>
                    <th>Manufacturer</th>
                    <th>Lifecycle</th>
                    <th>Lead time</th>
                    <th>Risk</th>
                    <th>Stock</th>
                    <th>Unit price</th>
                    <th>Sources</th>
                    <th>Reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 50).map((row, i) => {
                    const rawLinks = row.supplier_links ?? row["supplier_links"];
                    const supplierLinks = Array.isArray(rawLinks)
                      ? (rawLinks as Array<Record<string, unknown>>).filter((link) =>
                          typeof link.url === "string" && /^https?:\/\//i.test(link.url),
                        )
                      : [];
                    const rawQueries = row.supplier_query_details ?? row["Supplier Query Details"];
                    const supplierQueries = Array.isArray(rawQueries)
                      ? rawQueries as Array<Record<string, unknown>>
                      : [];
                    const primaryListing = String(row["Supplier product URL"] || "");
                    const sourcesChecked = row.supplier_sources_checked
                      ?? row["Supplier Sources Checked"]
                      ?? row["Supplier sources checked"];
                    const supplierCoverage = row.supplier_coverage ?? row["Supplier coverage"];
                    return (
                    <tr key={i}>
                      <td><strong>{cell(row.MPN ?? row.mpn ?? row["Part number"])}</strong></td>
                      <td>{cell(row.Manufacturer ?? row.manufacturer)}</td>
                      <td>
                        <StatusPill kind="lifecycle" value={cell(row.Lifecycle ?? row.lifecycle ?? row["Lifecycle status"], "Unknown")} />
                        <div style={{ marginTop: 4 }}>
                          <StatusPill
                            kind="verification"
                            value={cell(row["Lifecycle evidence status"], "missing") === "live-authorized-supplier"
                              ? "API snapshot"
                              : cell(row["Lifecycle evidence status"], "missing") === "reported-unverified"
                                ? "Unverified"
                                : cell(row["Lifecycle evidence status"], "missing") === "synthetic-preview"
                                  ? "Preview estimate"
                                  : "Not reported"}
                          />
                        </div>
                        {row["Lifecycle evidence note"] ? (
                          <div className="cv-small-note">{cell(row["Lifecycle evidence note"])}</div>
                        ) : null}
                      </td>
                      <td>
                        <strong>{cell(row["Lead time (weeks)"], "Not reported")}</strong>
                        <div className="cv-small-note">
                          {cell(row["Lead-time source"], "Source not recorded")}
                          {row["Lead-time checked at"] ? ` · ${cell(row["Lead-time checked at"])}` : ""}
                        </div>
                      </td>
                      <td><StatusPill kind="risk" value={cell(row.Risk ?? row["Risk level"] ?? row["Risk Level"] ?? row.risk_level, "Unknown")} /></td>
                      <td>
                        {cell(row.Stock ?? row.stock)}
                        <div style={{ marginTop: 4 }}>
                          <StatusPill
                            kind="verification"
                            value={cell(row["Stock evidence status"], "missing") === "live-authorized-supplier"
                              ? "API snapshot"
                              : cell(row["Stock evidence status"], "missing") === "reported-unverified"
                                ? "Unverified"
                                : cell(row["Stock evidence status"], "missing") === "synthetic-preview"
                                  ? "Preview estimate"
                                  : "Not reported"}
                          />
                        </div>
                        <div className="cv-small-note">{cell(row["Stock evidence"], "No per-supplier stock detail")}</div>
                        {row["Stock evidence note"] ? (
                          <div className="cv-small-note">{cell(row["Stock evidence note"])}</div>
                        ) : null}
                      </td>
                      <td>
                        {cell(row["Unit price"] ?? row.unit_price)} {cell(row["Unit price currency"], "")}
                        <div style={{ marginTop: 4 }}>
                          <StatusPill
                            kind="verification"
                            value={cell(row["Price evidence status"], "missing") === "live-authorized-supplier"
                              ? "API snapshot"
                              : cell(row["Price evidence status"], "missing") === "reported-unverified"
                                ? "Unverified"
                                : cell(row["Price evidence status"], "missing") === "synthetic-preview"
                                  ? "Preview estimate"
                                  : "Not reported"}
                          />
                        </div>
                        <div className="cv-small-note">
                          {cell(row["Price source"], "Source not recorded")}
                          {row["Price checked at"] ? " · checked " + cell(row["Price checked at"]) : ""}
                          {row["Price break quantity"] && row["Price break quantity"] !== "Not reported"
                            ? " · break " + cell(row["Price break quantity"])
                            : " · quantity break not returned"}
                        </div>
                        {row["Price evidence note"] ? (
                          <div className="cv-small-note">{cell(row["Price evidence note"])}</div>
                        ) : null}
                      </td>
                      <td>
                        {supplierLinks.length ? supplierLinks.slice(0, 4).map((link, linkIndex) => (
                          <div key={`${String(link.url)}-${linkIndex}`} style={{ marginBottom: 4 }}>
                            <a href={String(link.url)} target="_blank" rel="noreferrer">
                              {cell(link.source, "Supplier")} listing
                            </a>
                            <div className="cv-small-note">
                              {cell(link.evidence_types, "Supplier evidence")}
                              {link.retrieved_at ? ` · checked ${cell(link.retrieved_at)}` : ""}
                            </div>
                          </div>
                        )) : primaryListing && primaryListing !== "—" ? (
                          <a href={primaryListing} target="_blank" rel="noreferrer">Supplier listing</a>
                        ) : <span className="cv-small-note">No exact-part listing link was saved</span>}
                        {supplierLinks.length > 4 ? (
                          <div className="cv-small-note">+{supplierLinks.length - 4} more source links</div>
                        ) : null}
                        {row["Datasheet URL"] && row["Datasheet URL"] !== "—" ? (
                          <div><a href={String(row["Datasheet URL"])} target="_blank" rel="noreferrer">Datasheet</a></div>
                        ) : null}
                        <div className="cv-small-note">
                          {cell(sourcesChecked, "Supplier query coverage was not saved for this analysis")}
                        </div>
                        <div className="cv-small-note">
                          {cell(supplierCoverage, "")}
                        </div>
                        {supplierQueries.length ? (
                          <details className="cv-small-note" style={{ marginTop: 4 }}>
                            <summary>Supplier query results</summary>
                            {supplierQueries.map((query, queryIndex) => (
                              <div key={`${String(query.source || "supplier")}-${queryIndex}`}>
                                {cell(query.source, "Supplier")}: {cell(query.label, "Status not recorded")}
                                {query.detail ? ` — ${cell(query.detail)}` : ""}
                              </div>
                            ))}
                          </details>
                        ) : null}
                      </td>
                      <td className="cv-small-note">{cell(row.Why ?? row["Risk reasons"] ?? row.reasons).slice(0, 120)}</td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </> : (
          <EmptyState
            icon="risk"
            title={
              data.mode === "analysis-not-found"
                ? "Saved analysis not found"
                : "No component risk rows found"
            }
            body={
              data.mode === "analysis-not-found"
                ? "This saved report could not be found in your workspace. Choose another saved report or run a new BOM analysis."
                : "Open a saved analysis with component data to view the detailed risk breakdown."
            }
            action={
              <PrimaryLink href={data.mode === "analysis-not-found" ? "/bom-analyzer" : "/reports"}>
                {data.mode === "analysis-not-found" ? "Open BOM Analyzer" : "Choose a saved report"}
              </PrimaryLink>
            }
          />
        )
      ) : null}
    </Shell>
  );
}

export default function DetailedRiskPage() {
  return (
    <Suspense fallback={null}>
      <DetailedRiskPageInner />
    </Suspense>
  );
}

