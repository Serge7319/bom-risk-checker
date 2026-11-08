"use client";

import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { fetchDesignImpact } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function cell(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) {
    const joined = value.map((item) => String(item || "").trim()).filter(Boolean).join(", ");
    return joined || fallback;
  }
  return String(value);
}

export default function DesignImpactPage() {
  const session = useRequireSession();
  const [mpn, setMpn] = useState("");
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  function load(selected = mpn) {
    if (!session) return;
    setBusy(true);
    setError("");
    const last = readLastAnalysis(session);
    fetchDesignImpact(session.access_token, {
      analysisId: last?.analysis_id,
      mpn: selected,
    })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  if (!session) return null;
  const intel = (data?.intelligence || {}) as Record<string, unknown>;
  const catalog = (intel.component_catalog || intel.catalog || []) as Array<Record<string, unknown>>;
  const selectedMpn = String(intel.selected_mpn || "");
  const selected =
    catalog.find(
      (row) =>
        String(row["Part Number"] || "").toLowerCase() ===
        selectedMpn.toLowerCase(),
    ) || {};
  const affected = (intel.affected_projects || []) as Array<Record<string, unknown>>;

  return (
    <Shell session={session}>
      <PageHeader meta={PAGE_META.design} actions={<PrimaryLink href="/compare-parts">Compare parts</PrimaryLink>} />
      {<EvidenceNotice gap={data?.gap} />}
      <div className="cv-card pad" style={{ marginBottom: 14 }}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="mpn">Focus MPN (optional)</label>
            <input id="mpn" value={mpn} onChange={(e) => setMpn(e.target.value)} placeholder="e.g. from catalog" />
          </div>
          <div style={{ display: "flex", alignItems: "end" }}>
            <button type="button" className="cv-button primary" onClick={() => load(mpn)} disabled={busy}>
              {busy ? "Loading…" : "Refresh impact"}
            </button>
          </div>
        </div>
      </div>
      {busy ? <LoadingCard label="Building design impact from saved analyses…" /> : null}
      {error ? <div className="cv-error" role="alert">Design impact could not load. {error}</div> : null}
      {!busy && data ? (
        catalog.length ? (
          <div className="cv-stack" style={{ gap: 14 }}>
            <div className="cv-grid-2 cv-grid-2--tables">
              <section className="cv-card pad cv-card--table">
                <h3 className="cv-card-title">Component catalog</h3>
                <p className="cv-card-subtitle">{Array.isArray(catalog) ? catalog.length : 0} parts from saved analyses</p>
                <div className="cv-table-wrap cv-table-wrap--fit" style={{ marginTop: 12 }}>
                  <table className="cv-table cv-table--fit cv-table--mpn-safe">
                    <thead>
                      <tr>
                        <th>Part</th>
                        <th>Manufacturer</th>
                        <th>Lifecycle</th>
                        <th className="cv-num">Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(Array.isArray(catalog) ? catalog : []).slice(0, 25).map((row, i) => (
                        <tr key={i}>
                          <td data-label="Part" className="cv-mpn-cell">
                            <strong>{cell(row["Part Number"] || row.mpn)}</strong>
                          </td>
                          <td data-label="Manufacturer">
                            {cell(
                              row.Manufacturer
                                || row.manufacturer
                                || (Array.isArray(row["Manufacturer Values"])
                                  ? row["Manufacturer Values"][0]
                                  : ""),
                            )}
                          </td>
                          <td data-label="Lifecycle">{cell(row.Lifecycle || row.lifecycle)}</td>
                          <td className="cv-num" data-label="Risk">{cell(row["Risk Level"] || row.risk_level)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
              <section className="cv-card pad">
                <h3 className="cv-card-title">Selected impact</h3>
                <p className="cv-card-subtitle">
                  {Object.keys(selected).length
                    ? cell(selected["Part Number"] || selected.mpn, "Selected component")
                    : "Select or refresh to surface recommended component"}
                </p>
                <dl className="cv-record-meta" style={{ marginTop: 12, gridTemplateColumns: "1fr 1fr" }}>
                  <div className="cv-record-field"><dt>Lifecycle</dt><dd>{cell(selected.Lifecycle || selected.lifecycle)}</dd></div>
                  <div className="cv-record-field"><dt>Risk</dt><dd>{cell(selected["Risk Level"] || selected.risk_level)}</dd></div>
                  <div className="cv-record-field"><dt>Manufacturer</dt><dd>{cell(selected.Manufacturer || selected.manufacturer)}</dd></div>
                  <div className="cv-record-field"><dt>Package</dt><dd>{cell(selected.Package || selected.package)}</dd></div>
                  <div className="cv-record-field"><dt>Qty across BOMs</dt><dd>{cell(selected.Quantity || intel.total_quantity)}</dd></div>
                  <div className="cv-record-field"><dt>Impact level</dt><dd>{cell(intel.impact_level)}</dd></div>
                </dl>
              </section>
            </div>
            <section className="cv-card pad cv-card--table">
              <h3 className="cv-card-title">Affected BOM rows</h3>
              <p className="cv-card-subtitle">
                {affected.length
                  ? `${affected.length} project/BOM usage row${affected.length === 1 ? "" : "s"} for ${cell(selectedMpn, "the selected part")}`
                  : "No affected BOM rows were returned for the selected part."}
              </p>
              {affected.length ? (
                <div className="cv-table-wrap cv-table-wrap--fit" style={{ marginTop: 12 }}>
                  <table className="cv-table cv-table--fit cv-table--mpn-safe">
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>BOM</th>
                        <th>Part</th>
                        <th className="cv-num">Qty</th>
                        <th>Manufacturer</th>
                        <th>Lifecycle</th>
                        <th>Risk</th>
                        <th>Package</th>
                      </tr>
                    </thead>
                    <tbody>
                      {affected.map((row, i) => (
                        <tr key={i}>
                          <td data-label="Project">{cell(row.Project || row.project)}</td>
                          <td data-label="BOM">{cell(row.BOM || row.Bom || (Array.isArray(row["BOM Names"]) ? row["BOM Names"].join(", ") : ""))}</td>
                          <td data-label="Part" className="cv-mpn-cell">
                            <strong>{cell(row["Part Number"] || row.mpn || selectedMpn)}</strong>
                          </td>
                          <td className="cv-num" data-label="Qty">{cell(row.Quantity || row.quantity)}</td>
                          <td data-label="Manufacturer">{cell(row.Manufacturer || row.manufacturer)}</td>
                          <td data-label="Lifecycle">{cell(row.Lifecycle || row.lifecycle)}</td>
                          <td data-label="Risk">{cell(row["Risk Level"] || row.risk_level)}</td>
                          <td data-label="Package">{cell(row.Package || row.package)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="cv-small-note" style={{ marginTop: 12 }}>
                  Analyze a BOM that includes this MPN to populate affected row details.
                </p>
              )}
            </section>
          </div>
        ) : (
          <EmptyState
            icon="impact"
            title="No saved BOM components to trace"
            body="Design impact uses saved BOM analyses to find affected projects and parts. Analyze a BOM to start a trace."
            action={<PrimaryLink href="/bom-analyzer">Analyze a BOM</PrimaryLink>}
          />
        )
      ) : null}
    </Shell>
  );
}
