"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AskCadivorPanel } from "@/components/AskCadivorPanel";
import { Shell } from "@/components/Shell";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import { fetchReport, type Report } from "@/lib/api";
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
  const [error, setError] = useState("");

  useEffect(() => {
    if (!session) return;
    fetchReport(params.id, session.access_token)
      .then((data) => {
        setReport(data);
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
        });
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load report"),
      );
  }, [params.id, session]);

  if (!session) return null;

  const meta = {
    ...PAGE_META.ei,
    title: report?.filename
      ? `EI · ${report.filename}`
      : PAGE_META.ei.title,
  };

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
          </>
        }
      />

      {error ? <div className="cv-error">{error}</div> : null}

      {report ? (
        <>
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
            <KpiCard
              icon="clock"
              label="Created"
              value={
                report.created_at
                  ? new Date(report.created_at).toLocaleString()
                  : "—"
              }
              detail="Saved to this workspace"
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
              Lifecycle and stock fields are offline synthetic estimates, not
              live distributor evidence.
            </p>
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
                  <div className="cv-kpi tone-amber">
                    <span>Top rolled risk</span>
                    <strong>
                      {String(
                        report.hierarchy.top_level.rolled_risk_level || "—",
                      )}
                    </strong>
                    <em>{String(report.hierarchy.top_level.mpn || "")}</em>
                  </div>
                  <div className="cv-kpi">
                    <span>Leaf parts</span>
                    <strong>
                      {String(report.hierarchy.top_level.leaf_count ?? "—")}
                    </strong>
                    <em>Under top assembly</em>
                  </div>
                  <div className="cv-kpi tone-blue">
                    <span>High leaves</span>
                    <strong>
                      {String(
                        report.hierarchy.top_level.high_risk_leaves ?? 0,
                      )}
                    </strong>
                    <em>Need review</em>
                  </div>
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

          <section className="cv-card pad">
            <div style={{ marginBottom: 12 }}>
              <h3 className="cv-card-title">Component signals</h3>
              <p className="cv-card-subtitle">
                Part-level rows with quantity-per-parent and effective quantity
                when hierarchy is present.
              </p>
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
                          <strong>{mpn}</strong>
                          <div className="cv-small-note">
                            {String(part.line_type || part["Line Type"] || "")}
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
