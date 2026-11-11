"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Shell } from "@/components/Shell";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { Icon } from "@/components/Icons";
import { PartThumbnail } from "@/components/PartThumbnail";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { fetchProcurement, listReports } from "@/lib/api";
import { evidenceSourceLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function analysisLabel(row: Record<string, unknown>) {
  const project = String(row.project_name || "").trim();
  const bom = String(row.bom_name || row.filename || "").trim();
  const revision = String(row.revision || "").trim();
  const title = [project, bom].filter(Boolean).join(" · ") || "Saved analysis";
  return revision ? `${title} (rev ${revision})` : title;
}

function withAnalysisId(href: string, analysisId: string) {
  if (!analysisId) return href;
  const joiner = href.includes("?") ? "&" : "?";
  return `${href}${joiner}analysis_id=${encodeURIComponent(analysisId)}`;
}

function ProcurementPageInner() {
  const session = useRequireSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [reports, setReports] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [filter, setFilter] = useState("");
  const [selectedAnalysisId, setSelectedAnalysisId] = useState("");

  const requestedAnalysisId = useMemo(
    () => (searchParams.get("analysis_id") || "").trim(),
    [searchParams],
  );

  useEffect(() => {
    if (!session) return;
    let active = true;
    const last = readLastAnalysis(session);
    const analysisId = requestedAnalysisId || last?.analysis_id || "";
    setSelectedAnalysisId(analysisId);
    setBusy(true);
    setError("");
    setData(null);
    Promise.all([
      listReports(session.access_token).catch(() => ({ reports: [] as Array<Record<string, unknown>> })),
      fetchProcurement(session.access_token, analysisId || undefined),
    ])
      .then(([reportPayload, procurement]) => {
        if (!active) return;
        setReports((reportPayload.reports || []) as Array<Record<string, unknown>>);
        setData(procurement);
        const resolved = String(procurement.analysis_id || analysisId || "").trim();
        if (resolved) setSelectedAnalysisId(resolved);
        if (procurement.ok === false) {
          setError(String(procurement.gap || "Procurement could not load that analysis."));
        }
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed");
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [session, requestedAnalysisId]);

  const parts = useMemo(() => {
    const rows = ((data?.parts || []) as Array<Record<string, unknown>>) || [];
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((p) =>
      [p.mpn, p.manufacturer, p.category, p.supplier, p.recommendation, p.lifecycle, p.coverage]
        .map((v) => String(v || "").toLowerCase())
        .some((v) => v.includes(q)),
    );
  }, [data, filter]);

  const evidenceSummary = (data?.evidence_summary || {}) as Record<string, unknown>;
  const liveParts = Number(evidenceSummary.live_parts || 0);
  const sampleParts = Number(evidenceSummary.sample_parts || 0);
  const missingParts = Number(evidenceSummary.parts_without_verified_supplier_evidence || 0);
  const partsTotal = Number(evidenceSummary.parts_total || ((data?.parts as unknown[]) || []).length || 0);
  const sourcingBadge = `Live: ${liveParts}; synthetic/preview: ${sampleParts}; no supplier match: ${missingParts} (of ${partsTotal})`;
  const activeAnalysisId = String(data?.analysis_id || selectedAnalysisId || "").trim();
  const contextLabel = [
    String(data?.project_name || "").trim(),
    String(data?.bom_name || data?.filename || "").trim(),
    data?.revision ? `rev ${String(data.revision)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const display = (value: unknown, fallback = "Not recorded") => {
    if (value === null || value === undefined || String(value).trim() === "") return fallback;
    return String(value);
  };

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.procurement}
        actions={
          <div className="cv-page-head-actions">
            <PrimaryLink href="/bom-analyzer">Run new BOM analysis</PrimaryLink>
            <SecondaryLink href={withAnalysisId("/cost-optimization", activeAnalysisId)}>Cost optimization</SecondaryLink>
            <SecondaryLink href={withAnalysisId("/compare-parts", activeAnalysisId)}>Compare alternatives</SecondaryLink>
          </div>
        }
      />
      {<EvidenceNotice gap={data?.gap} />}
      {busy ? <LoadingCard label="Loading procurement coverage…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {!busy && data ? (
        <>
          <section className="cv-card pad">
            <div className="cv-section-heading" style={{ marginTop: 0 }}>
              <div>
                <h2 className="cv-card-title" style={{ fontSize: 15 }}>
                  Supplier evidence
                </h2>
                <p className="cv-card-subtitle">
                  {String(data.recommendation_note || "Review sourcing coverage from the selected analysis.")}
                </p>
                <p className="cv-small-note" style={{ marginTop: 8 }} data-testid="procurement-context">
                  {contextLabel
                    ? `Showing ${contextLabel}${activeAnalysisId ? ` · ${activeAnalysisId}` : ""}`
                    : activeAnalysisId
                      ? `Showing analysis ${activeAnalysisId}`
                      : "No analysis selected — choose a saved BOM below."}
                </p>
              </div>
              <span className="cv-badge gray">
                {sourcingBadge}
              </span>
            </div>

            <div className="cv-sourcing-controls">
              <select
                aria-label="Sourcing BOM context"
                value={selectedAnalysisId}
                onChange={(event) => {
                  const nextId = event.target.value;
                  setSelectedAnalysisId(nextId);
                  router.replace(nextId ? `/procurement?analysis_id=${encodeURIComponent(nextId)}` : "/procurement");
                }}
              >
                <option value="">Select a saved analysis</option>
                {reports.map((row) => {
                  const id = String(row.id || "").trim();
                  if (!id) return null;
                  return (
                    <option key={id} value={id}>
                      {analysisLabel(row)}
                    </option>
                  );
                })}
              </select>
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter by MPN or supplier"
                aria-label="Filter sourcing rows"
                style={{ width: 240 }}
              />
              <span style={{ flex: 1 }} />
            </div>

            {parts.length ? (
              <div className="cv-table-wrap">
                <table className="cv-table cv-procurement-table">
                  <thead>
                    <tr>
                      <th>MPN</th>
                      <th>Manufacturer</th>
                      <th>Recommended action</th>
                      <th>Required quantity</th>
                      <th>Lifecycle</th>
                      <th>Risk</th>
                      <th>Supplier coverage</th>
                      <th>Stock</th>
                      <th>Unit price</th>
                      <th>Lead time</th>
                      <th>Evidence source</th>
                      <th>Offers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {parts.map((p, i) => (
                      <tr key={`${String(p.mpn || "part")}-${i}`}>
                        <td>
                          <div className="cv-part-cell">
                            <PartThumbnail part={p} />
                            <div>
                              <strong>{display(p.mpn, "MPN not recorded")}</strong>
                              {p.description ? <small className="cv-procurement-description">{String(p.description)}</small> : null}
                              {p.category ? <small className="cv-procurement-description">Category: {String(p.category)}</small> : null}
                            </div>
                          </div>
                        </td>
                        <td>{display(p.manufacturer, "Not provided")}</td>
                        <td className="cv-procurement-recommendation">
                          <strong>{display(p.recommendation, "Check an authorized source")}</strong>
                          {p.next_step ? <small>{String(p.next_step)}</small> : null}
                        </td>
                        <td>{display(p.quantity)}</td>
                        <td>{display(p.lifecycle, "Unknown")}</td>
                        <td>{display(p.risk_level, "Needs verification")}</td>
                        <td>
                          <strong>{display(p.supplier, "No primary supplier recorded")}</strong>
                          <small className="cv-procurement-description">
                            {p.supplier_count == null
                              ? "Supplier count not reported"
                              : String(p.supplier_count) + " source" + (Number(p.supplier_count) === 1 ? "" : "s")}
                          </small>
                        </td>
                        <td>{display(p.stock, "Not reported")}</td>
                        <td>
                          {p.unit_price == null
                            ? "Price absent"
                            : `${String(p.unit_price)}${p.currency ? ` ${String(p.currency)}` : " (currency not recorded)"}`}
                          {p.price_type ? (
                            <small className="cv-procurement-description">Type: {String(p.price_type)}</small>
                          ) : null}
                        </td>
                        <td>{p.lead_time_weeks == null ? "Not reported" : `${String(p.lead_time_weeks)} weeks`}</td>
                        <td>
                          <span className="cv-badge gray">
                            {evidenceSourceLabel(p.price_source, "Not recorded")}
                          </span>
                          {p.identity_source ? (
                            <small className="cv-procurement-description">
                              Identity: {evidenceSourceLabel(p.identity_source, "Not recorded")}
                            </small>
                          ) : null}
                          {p.price_retrieved_at || p.retrieved_at ? (
                            <small className="cv-procurement-timestamp">
                              {String(p.price_retrieved_at || p.retrieved_at)}
                            </small>
                          ) : null}
                        </td>
                        <td>
                          {Array.isArray(p.supplier_offers) && p.supplier_offers.length ? (
                            <details className="cv-procurement-offers">
                              <summary>{p.supplier_offers.length} saved offer{p.supplier_offers.length === 1 ? "" : "s"}</summary>
                              <div className="cv-procurement-offer-list">
                                {p.supplier_offers.map((rawOffer, offerIndex) => {
                                  const offer = rawOffer as Record<string, unknown>;
                                  const supplierName = display(offer.supplier, "Supplier not recorded");
                                  const productUrl = String(offer.product_url || "");
                                  return (
                                    <div className="cv-procurement-offer" key={`${supplierName}-${offerIndex}`}>
                                      <strong>{supplierName}</strong>
                                      <span>
                                        {offer.unit_price == null
                                          ? "Price not reported"
                                          : `${String(offer.unit_price)}${offer.currency ? ` ${String(offer.currency)}` : " (currency not recorded)"}`}
                                      </span>
                                      <span>Stock: {display(offer.stock, "Not reported")}</span>
                                      <span>Lead: {offer.lead_time_weeks == null ? "Not reported" : `${String(offer.lead_time_weeks)} weeks`}</span>
                                      <span>
                                        Qty break:{" "}
                                        {offer.price_break_quantity == null
                                          ? "Not recorded"
                                          : String(offer.price_break_quantity)}
                                      </span>
                                      {offer.region ? <span>Region: {String(offer.region)}</span> : null}
                                      {offer.retrieved_at ? <span>Retrieved: {String(offer.retrieved_at)}</span> : null}
                                      {productUrl.startsWith("https://") || productUrl.startsWith("http://") ? (
                                        <a href={productUrl} target="_blank" rel="noreferrer">Supplier listing</a>
                                      ) : null}
                                    </div>
                                  );
                                })}
                              </div>
                            </details>
                          ) : (
                            <span>{display(p.coverage, "No saved offers")}</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                icon="procure"
                title={filter ? "No sourcing rows match this filter" : "No sourcing rows available"}
                body={filter ? "Try another part number, manufacturer, lifecycle, or coverage term." : "Analyze a BOM to review its available supplier coverage and source labels here."}
                action={<PrimaryLink href="/bom-analyzer">Open BOM Analyzer</PrimaryLink>}
              />
            )}
          </section>

          <div className="cv-next-steps">
            <div className="cv-section-heading">
              <div>
                <h2>Next steps</h2>
                <p>
                  Keep sourcing signals connected to engineering qualification
                  and the release decision.
                </p>
              </div>
            </div>
            <div className="cv-next-steps-grid">
              <section className="cv-card pad">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <h3 className="cv-card-title">Review lifecycle concerns</h3>
                    <p className="cv-card-subtitle">
                      Open the detailed risk report for the current analysis.
                    </p>
                  </div>
                  <span className="cv-page-head-icon" aria-hidden>
                    <Icon name="risk" />
                  </span>
                </div>
                <div style={{ marginTop: 14 }}>
                  <SecondaryLink href={withAnalysisId("/detailed-risk-report", activeAnalysisId)}>Open risk report</SecondaryLink>
                </div>
              </section>
              <section className="cv-card pad">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <h3 className="cv-card-title">Compare an alternate</h3>
                    <p className="cv-card-subtitle">
                      Confirm package and electrical fit before substitution.
                    </p>
                  </div>
                  <span className="cv-page-head-icon" aria-hidden>
                    <Icon name="compare" />
                  </span>
                </div>
                <div style={{ marginTop: 14 }}>
                  <SecondaryLink href={withAnalysisId("/compare-parts", activeAnalysisId)}>Compare parts</SecondaryLink>
                </div>
              </section>
              <section className="cv-card pad">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <h3 className="cv-card-title">Record sourcing decision</h3>
                    <p className="cv-card-subtitle">
                      Attach rationale to the selected BOM revision.
                    </p>
                  </div>
                  <span className="cv-page-head-icon" aria-hidden>
                    <Icon name="decisions" />
                  </span>
                </div>
                <div style={{ marginTop: 14 }}>
                  <Link className="cv-button" href={withAnalysisId("/engineering-decisions", activeAnalysisId)}>
                    Open decisions
                  </Link>
                </div>
              </section>
            </div>
          </div>
        </>
      ) : null}
    </Shell>
  );
}

export default function ProcurementPage() {
  return (
    <Suspense fallback={<LoadingCard label="Loading procurement…" />}>
      <ProcurementPageInner />
    </Suspense>
  );
}

