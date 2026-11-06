"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Shell } from "@/components/Shell";
import { EmptyState } from "@/components/EmptyState";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { Icon } from "@/components/Icons";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { fetchProcurement } from "@/lib/api";
import { evidenceSourceLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

export default function ProcurementPage() {
  const session = useRequireSession();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!session) return;
    const last = readLastAnalysis();
    fetchProcurement(session.access_token, last?.analysis_id)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }, [session]);

  const parts = useMemo(() => {
    const rows = ((data?.parts || []) as Array<Record<string, unknown>>) || [];
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((p) =>
      [p.mpn, p.manufacturer, p.lifecycle, p.coverage]
        .map((v) => String(v || "").toLowerCase())
        .some((v) => v.includes(q)),
    );
  }, [data, filter]);

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.procurement}
        actions={<PrimaryLink href="/bom-analyzer">Analyze BOM</PrimaryLink>}
      />
      {typeof data?.gap === "string" ? <GapBanner>{String(data.gap)}</GapBanner> : null}
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
              </div>
              <span className="cv-badge gray">
                Sample evidence · not live distributor quotes
              </span>
            </div>

            <div className="cv-sourcing-controls">
              <select aria-label="Sourcing BOM context" defaultValue="current">
                <option value="current">Current analysis context</option>
              </select>
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter by MPN or supplier"
                aria-label="Filter sourcing rows"
                style={{ width: 240 }}
              />
              <span style={{ flex: 1 }} />
              <span className="cv-badge blue">Sourcing options</span>
            </div>

            {parts.length ? (
              <div className="cv-table-wrap">
                <table className="cv-table">
                  <thead>
                    <tr>
                      <th>MPN</th>
                      <th>Manufacturer</th>
                      <th>Lifecycle</th>
                      <th>Risk</th>
                      <th>Stock</th>
                      <th>Unit price</th>
                      <th>Price source</th>
                      <th>Offers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {parts.map((p, i) => (
                      <tr key={i}>
                        <td>
                          <strong>{String(p.mpn || "")}</strong>
                        </td>
                        <td>{String(p.manufacturer || "")}</td>
                        <td>{String(p.lifecycle || "")}</td>
                        <td>{String(p.risk_level || "")}</td>
                        <td>{String(p.stock ?? "—")}</td>
                        <td>{p.unit_price == null ? "—" : String(p.unit_price)}</td>
                        <td>
                          <span className="cv-badge gray">
                            {evidenceSourceLabel(p.price_source, "Synthetic estimate")}
                          </span>
                        </td>
                        <td>
                          {String(p.offer_count ?? 0)} · {String(p.coverage)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                icon="procure"
                title="No sourcing rows for this filter"
                body="Upload and analyze a BOM, or clear the filter, to review supplier evidence in this workspace."
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
                  <SecondaryLink href="/detailed-risk-report">Open risk report</SecondaryLink>
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
                  <SecondaryLink href="/compare-parts">Compare parts</SecondaryLink>
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
                  <Link className="cv-button" href="/engineering-decisions">
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
