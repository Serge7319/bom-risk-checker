"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AskCadivorPanel } from "@/components/AskCadivorPanel";
import { Shell } from "@/components/Shell";
import { KpiCard } from "@/components/KpiCard";
import { Icon } from "@/components/Icons";
import { PartThumbnail } from "@/components/PartThumbnail";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import {
  downloadReportExport,
  fetchReport,
  listDecisionRecords,
  type DecisionRecord,
  type Report,
  type ReportExportFormat,
} from "@/lib/api";
import {
  markReviewProgress,
  readReviewProgress,
  type BomReviewProgress,
} from "@/lib/bomDraft";
import { analysisModeLabel, evidenceSourceLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { rememberAnalysis, useRequireSession } from "@/lib/session";

function riskBadge(level: string) {
  const normalized = level.toLowerCase();
  if (normalized.includes("high")) return "red";
  if (normalized.includes("medium")) return "amber";
  if (normalized.includes("low")) return "green";
  return "gray";
}

export default function ReportPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const session = useRequireSession();
  const [report, setReport] = useState<Report | null>(null);
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [decisionError, setDecisionError] = useState("");
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState<ReportExportFormat | null>(null);
  const [review, setReview] = useState<BomReviewProgress | null>(null);

  useEffect(() => {
    if (!session) return;
    const analysisKey = String(params.id || "");
    setReview(readReviewProgress(analysisKey, session));
    fetchReport(params.id, session.access_token)
      .then((data) => {
        setReport(data);
        const id = String(data.analysis_id || data.id || analysisKey);
        setReview(
          markReviewProgress(
            id,
            { risksOpenedAt: new Date().toISOString() },
            session,
          ),
        );
        rememberAnalysis({
          analysis_id: data.analysis_id || data.id,
          total_parts: data.total_parts,
          health_score: data.health_score,
          health_status: data.health_status,
          high_risk_count: data.high_risk_count,
          medium_risk_count: data.medium_risk_count,
          low_risk_count: data.low_risk_count,
          mode: data.mode,
          filename: data.filename,
        }, session);
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load report"),
      );
    listDecisionRecords(session.access_token, params.id)
      .then(({ records }) => {
        setDecisions(records || []);
        if ((records || []).length) {
          setReview(
            markReviewProgress(
              analysisKey,
              { decisionRecordedAt: new Date().toISOString() },
              session,
            ),
          );
        }
      })
      .catch((err) => setDecisionError(err instanceof Error ? err.message : "Decision history could not load."));
  }, [params.id, session]);

  const reviewGuide = useMemo(() => {
    const progress = review || readReviewProgress(String(params.id || ""), session || undefined);
    const hasDecision = decisions.length > 0 || Boolean(progress.decisionRecordedAt);
    const evidenceDone = Boolean(progress.evidenceReviewedAt);
    const monitorDone = Boolean(progress.monitorOpenedAt);
    let current: "Risks" | "Evidence" | "Decision" | "Monitor" = "Evidence";
    if (!evidenceDone) current = "Evidence";
    else if (!hasDecision) current = "Decision";
    else current = "Monitor";
    return { progress, hasDecision, evidenceDone, monitorDone, current };
  }, [review, decisions, params.id, session]);

  async function onDownload(format: ReportExportFormat) {
    if (!session || !report) return;
    setExporting(format);
    setExportError("");
    try {
      await downloadReportExport(
        String(report.analysis_id || report.id),
        session.access_token,
        format,
      );
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "The report could not be downloaded.");
    } finally {
      setExporting(null);
    }
  }

  if (!session) return null;

  const meta = {
    ...PAGE_META.ei,
    title: report?.filename
      ? `EI · ${report.filename}`
      : PAGE_META.ei.title,
  };
  const verifiedSupplierRows = (report?.parts || []).filter((part) =>
    part.supplier_data_verified === true || part["Supplier Data Verified"] === true,
  ).length;

  return (
    <Shell session={session}>
      <PageHeader
        meta={meta}
        record
        actions={
          <>
            <SecondaryLink href="/bom-analyzer">New analysis</SecondaryLink>
            <SecondaryLink href="/engineering-decisions">
              Decision queue
            </SecondaryLink>
            <SecondaryLink href={`/compare-parts?analysis_id=${encodeURIComponent(params.id)}`}>
              Compare parts
            </SecondaryLink>
          </>
        }
      />

      {error ? (
        <div className="cv-error" role="alert">
          This saved report could not be opened. {error} <Link href="/reports">Return to saved reports</Link>
        </div>
      ) : null}

      {report ? (
        <>
          <section className="cv-card pad cv-bom-review-guide" aria-label="Engineering review workflow">
            <div className="cv-bom-review-guide-copy">
              <p className="cv-eyebrow">Engineering workflow</p>
              <h2 className="cv-card-title">Risks → Evidence → Decision → Monitor</h2>
              <p className="cv-card-subtitle">
                Analysis stages are complete for this saved report. Continue review without locking other navigation.
              </p>
              <ol className="cv-bom-review-steps">
                <li className="is-complete">
                  <strong>Risks</strong>
                  <span>Complete — report opened</span>
                </li>
                <li className={reviewGuide.evidenceDone ? "is-complete" : reviewGuide.current === "Evidence" ? "is-current" : ""}>
                  <strong>Evidence</strong>
                  <span>{reviewGuide.evidenceDone ? "Complete — evidence reviewed" : "Current — confirm evidence labels below"}</span>
                </li>
                <li className={reviewGuide.hasDecision ? "is-complete" : reviewGuide.current === "Decision" ? "is-current" : ""}>
                  <strong>Decision</strong>
                  <span>
                    {reviewGuide.hasDecision
                      ? "Complete — decision record saved"
                      : "Next — record a keep/replace decision"}
                  </span>
                </li>
                <li className={reviewGuide.monitorDone ? "is-complete" : reviewGuide.current === "Monitor" ? "is-current" : ""}>
                  <strong>Monitor</strong>
                  <span>
                    Derived signals available; scheduled refresh and email delivery are currently disabled.
                  </span>
                </li>
              </ol>
            </div>
            <div className="cv-bom-review-guide-actions">
              {!reviewGuide.evidenceDone ? (
                <a
                  className="cv-button primary"
                  href="#report-evidence"
                  onClick={() => {
                    setReview(
                      markReviewProgress(
                        String(params.id),
                        { evidenceReviewedAt: new Date().toISOString() },
                        session,
                      ),
                    );
                  }}
                >
                  Review evidence
                </a>
              ) : !reviewGuide.hasDecision ? (
                <Link className="cv-button primary" href="/engineering-decisions">
                  Open Decision queue
                </Link>
              ) : (
                <Link
                  className="cv-button primary"
                  href={`/monitoring?analysis_id=${encodeURIComponent(String(report.analysis_id || report.id || params.id))}`}
                >
                  Open Monitoring
                </Link>
              )}
              <Link
                className="cv-button"
                href={`/compare-parts?analysis_id=${encodeURIComponent(params.id)}`}
              >
                Compare parts
              </Link>
            </div>
          </section>

          <dl className="cv-record-meta">
            <div className="cv-record-field">
              <dt>Health</dt>
              <dd>
                {report.health_score == null
                  ? "—"
                  : `${report.health_score}/100`}
              </dd>
            </div>
            <div className="cv-record-field">
              <dt>Status</dt>
              <dd>{report.health_status}</dd>
            </div>
            <div className="cv-record-field">
              <dt>Components</dt>
              <dd>{report.total_parts}</dd>
            </div>
            <div className="cv-record-field">
              <dt>Evidence basis</dt>
              <dd>{analysisModeLabel(report.mode)}</dd>
            </div>
          </dl>

          <section className="cv-card pad cv-report-export" aria-labelledby="report-export-title">
            <div>
              <h2 id="report-export-title" className="cv-card-title">Download this report</h2>
              <p className="cv-card-subtitle">
                Export the saved component risk, hierarchy, and evidence labels for review.
              </p>
            </div>
            <div className="cv-report-export-controls">
              <button type="button" className="cv-button" onClick={() => onDownload("pdf")} disabled={exporting !== null}>
                <Icon name="download" /> {exporting === "pdf" ? "Preparing PDF…" : "Download PDF"}
              </button>
              <button type="button" className="cv-button" onClick={() => onDownload("xlsx")} disabled={exporting !== null}>
                <Icon name="download" /> {exporting === "xlsx" ? "Preparing Excel…" : "Download Excel"}
              </button>
              <button type="button" className="cv-button" onClick={() => onDownload("csv")} disabled={exporting !== null}>
                <Icon name="download" /> {exporting === "csv" ? "Preparing CSV…" : "Download CSV audit"}
              </button>
            </div>
            {exportError ? <div className="cv-error" role="alert">{exportError}</div> : null}
            {report.mode === "synthetic-preview" ? (
              <p className="cv-small-note">This report uses synthetic preview evidence. Stock, prices, and lifecycle estimates are not live supplier verification.</p>
            ) : null}
          </section>

          <div className="cv-kpis">
            <KpiCard
              icon="risk"
              tone="amber"
              label="High risk"
              value={report.high_risk_count}
              detail="Needs review"
            />
            <KpiCard
              icon="bell"
              tone="blue"
              label="Medium risk"
              value={report.medium_risk_count}
              detail="Follow up"
            />
            <KpiCard
              icon="check"
              label="Low risk"
              value={report.low_risk_count}
              detail="Within BOM"
            />
          </div>

          <AskCadivorPanel
            token={session.access_token}
            analysisId={String(report.analysis_id || report.id)}
          />

          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <div className="cv-eyebrow">Engineering decision record</div>
            <h2 className="cv-card-title" style={{ fontSize: 20, marginTop: 8 }}>
              {report.project_name || report.filename || "Saved analysis"}
            </h2>
            <p className="cv-card-subtitle">
              {[
                report.bom_name ? `BOM ${report.bom_name}` : null,
                report.revision ? `rev ${report.revision}` : null,
                report.persisted ? "Saved to this workspace" : null,
              ]
                .filter(Boolean)
                .join(" · ") ||
                report.summary_message ||
                "Synthetic analysis; live supplier data is not included."}
            </p>
            <p className="cv-small-note" style={{ marginTop: 8 }}>
              {report.mode === "synthetic-preview"
                ? "Supplier prices, stock, and lifecycle are synthetic estimates, not live distributor evidence."
                : verifiedSupplierRows > 0
                  ? `Verified supplier evidence is present for ${verifiedSupplierRows} of ${report.parts.length} component rows. Review each source and timestamp before acting.`
                  : "Supplier price, stock, and lifecycle data were not verified for this report. Treat these fields as unconfirmed and check current authorized sources."}
            </p>
          </section>

          <section className="cv-card pad cv-report-decisions" style={{ marginBottom: 14 }}>
            <div className="cv-eyebrow">Comparison history</div>
            <h2 className="cv-card-title" style={{ marginTop: 8 }}>Engineering decisions for this BOM</h2>
            <p className="cv-card-subtitle">Each entry preserves the reviewer’s rationale and the comparison evidence snapshot used at the time.</p>
            {decisionError ? <div className="cv-error" role="alert">Decision history could not load. {decisionError}</div> : null}
            {decisions.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead>
                    <tr><th>Saved</th><th>Current part</th><th>Candidate</th><th>Decision</th><th>Reviewer / rationale</th><th>Evidence status</th></tr>
                  </thead>
                  <tbody>
                    {decisions.map((decision) => (
                      <tr key={decision.id}>
                        <td>{decision.created_at ? new Date(decision.created_at).toLocaleDateString() : "—"}</td>
                        <td><strong>{decision.part_a}</strong></td>
                        <td><strong>{decision.part_b}</strong></td>
                        <td><span className="cv-badge blue">{decision.decision_label}</span></td>
                        <td>{decision.reviewer}<div className="cv-muted">{decision.rationale}</div></td>
                        <td><span className="cv-badge amber">Not qualified by Cadivor</span><div className="cv-small-note">{decision.qualification_note}</div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : !decisionError ? (
              <div className="cv-small-note" style={{ marginTop: 12 }}>No comparison decisions have been recorded for this analysis.</div>
            ) : null}
          </section>

          {report.hierarchy?.has_hierarchy ? (
            <section className="cv-card pad" style={{ marginBottom: 14 }}>
              <div style={{ marginBottom: 12 }}>
                <h3 className="cv-card-title">Assembly risk roll-up</h3>
                <p className="cv-card-subtitle">
                  Parent/child quantities multiplied along the path. Assembly
                  risk is the worst leaf risk under that node — drill into
                  contributors for evidence.
                </p>
              </div>
              {report.hierarchy.top_level ? (
                <div className="cv-kpis" style={{ marginBottom: 12 }}>
                  <KpiCard
                    icon="risk"
                    tone="amber"
                    label="Highest assembly risk"
                    value={String(report.hierarchy.top_level.rolled_risk_level || "Not reported")}
                    detail={String(report.hierarchy.top_level.mpn || "Top assembly")}
                  />
                  <KpiCard
                    icon="box"
                    label="Leaf components"
                    value={String(report.hierarchy.top_level.leaf_count ?? "Not reported")}
                    detail="Components beneath the top assembly"
                  />
                  <KpiCard
                    icon="risk"
                    tone="blue"
                    label="High-risk leaf components"
                    value={String(report.hierarchy.top_level.high_risk_leaves ?? 0)}
                    detail="Need engineering review"
                  />
                </div>
              ) : null}
              <div className="cv-table-wrap">
                <table className="cv-table">
                  <thead>
                    <tr>
                      <th>Assembly</th>
                      <th>Path</th>
                      <th>Eff. qty</th>
                      <th>Rolled risk</th>
                      <th>High / Med leaves</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(report.hierarchy.assemblies || []).map((row, index) => (
                      <tr key={`${String(row.mpn)}-${index}`}>
                        <td>
                          <strong>{String(row.mpn)}</strong>
                          <div className="cv-small-note">
                            {String(row.description || "")}
                          </div>
                        </td>
                        <td>{String(row.bom_path || "")}</td>
                        <td>{String(row.effective_quantity ?? "")}</td>
                        <td>
                          <span
                            className={`cv-badge ${riskBadge(String(row.rolled_risk_level || ""))}`}
                          >
                            {String(row.rolled_risk_level || "—")}
                          </span>
                        </td>
                        <td>
                          {String(row.high_risk_leaves ?? 0)} /{" "}
                          {String(row.medium_risk_leaves ?? 0)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {(report.hierarchy.priority_contributors || []).length ? (
                <>
                  <h3
                    className="cv-card-title"
                    style={{ fontSize: 15, marginTop: 16 }}
                  >
                    Drill-down contributors
                  </h3>
                  <div className="cv-table-wrap" style={{ marginTop: 8 }}>
                    <table className="cv-table">
                      <thead>
                        <tr>
                          <th>Part</th>
                          <th>Path</th>
                          <th>Eff. qty</th>
                          <th>Risk</th>
                          <th>Evidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(report.hierarchy.priority_contributors || []).map(
                          (row, index) => (
                            <tr key={`${String(row.mpn)}-c-${index}`}>
                              <td>
                                <strong>{String(row.mpn)}</strong>
                                <div className="cv-small-note">
                                  {String(row.why || "")}
                                </div>
                              </td>
                              <td>{String(row.bom_path || "")}</td>
                              <td>{String(row.effective_quantity ?? "")}</td>
                              <td>
                                <span
                                  className={`cv-badge ${riskBadge(String(row.risk_level || ""))}`}
                                >
                                  {String(row.risk_level || "—")}
                                </span>
                              </td>
                              <td>
                                {String(
                                  evidenceSourceLabel(row.evidence_source),
                                )}
                              </td>
                            </tr>
                          ),
                        )}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : null}
            </section>
          ) : null}

          <section className="cv-card pad" id="report-evidence">
            <div style={{ marginBottom: 12 }}>
              <h3 className="cv-card-title">Component signals</h3>
              <p className="cv-card-subtitle">
                Part-level rows with quantity-per-parent and effective quantity
                when hierarchy is present. Evidence labels appear with each risk signal.
              </p>
              {!reviewGuide.evidenceDone ? (
                <button
                  type="button"
                  className="cv-button"
                  style={{ marginTop: 10 }}
                  onClick={() => {
                    setReview(
                      markReviewProgress(
                        String(params.id),
                        { evidenceReviewedAt: new Date().toISOString() },
                        session,
                      ),
                    );
                  }}
                >
                  Mark evidence reviewed
                </button>
              ) : null}
            </div>
            <div className="cv-table-wrap">
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>MPN</th>
                    <th>Parent</th>
                    <th>Qty / parent</th>
                    <th>Eff. qty</th>
                    <th>Lifecycle</th>
                    <th>Risk</th>
                    <th className="cv-table-action">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {report.parts.map((part, index) => {
                    const risk = String(part["Risk Level"] || "");
                    const mpn = String(part.MPN || "");
                    return (
                      <tr key={`${mpn}-${index}`}>
                        <td>
                          <div className="cv-part-cell">
                            <PartThumbnail part={part} />
                            <span>
                              <strong>{mpn}</strong>
                              <span className="cv-small-note">
                                {String(part.line_type || part["Line Type"] || "")}
                              </span>
                            </span>
                          </div>
                        </td>
                        <td>
                          {String(
                            part.parent_mpn || part["Parent MPN"] || "—",
                          )}
                        </td>
                        <td>
                          {String(
                            part.quantity_per_parent ?? part.Quantity ?? "",
                          )}
                        </td>
                        <td>
                          {String(
                            part.effective_quantity ?? part.Quantity ?? "",
                          )}
                        </td>
                        <td>{String(part.Lifecycle || "")}</td>
                        <td>
                          <span className={`cv-badge ${riskBadge(risk)}`}>
                            {risk || "—"}
                          </span>
                        </td>
                        <td className="cv-table-action">
                          {mpn ? (
                            <Link
                              className="cv-table-open"
                              href={`/find-replacement?mpn=${encodeURIComponent(mpn)}&analysis_id=${encodeURIComponent(String(report.analysis_id || report.id))}&manufacturer=${encodeURIComponent(String(part.Manufacturer || ""))}`}
                            >
                              Replace
                            </Link>
                          ) : (
                            "—"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : !error ? (
        <section className="cv-loading">
          Loading saved report…
          <div className="cv-progress" aria-hidden>
            <i />
          </div>
        </section>
      ) : (
        <button
          type="button"
          className="cv-button"
          onClick={() => router.push("/bom-analyzer")}
        >
          Return to BOM Analyzer
        </button>
      )}
    </Shell>
  );
}

