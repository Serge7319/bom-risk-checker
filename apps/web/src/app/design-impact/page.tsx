"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { fetchDesignImpact } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

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
    const last = readLastAnalysis();
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
      <PageHeader meta={PAGE_META.design} actions={<PrimaryLink href="/bom-analyzer">Analyze BOM</PrimaryLink>} />
      {typeof data?.gap === "string" ? <GapBanner>{String(data.gap)}</GapBanner> : null}
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
      {busy ? <LoadingCard label="Building design impact from sandbox analyses…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {!busy && data ? (
        <div className="cv-grid-2">
          <section className="cv-card pad">
            <h3 className="cv-card-title">Component catalog</h3>
            <p className="cv-card-subtitle">{Array.isArray(catalog) ? catalog.length : 0} parts across in-memory analyses</p>
            <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table">
                <thead><tr><th>Part</th><th>Manufacturer</th><th>Lifecycle</th><th>Risk</th></tr></thead>
                <tbody>
                  {(Array.isArray(catalog) ? catalog : []).slice(0, 25).map((row, i) => (
                    <tr key={i}>
                      <td><strong>{String(row["Part Number"] || row.mpn || "")}</strong></td>
                      <td>{String(row.Manufacturer || row.manufacturer || Array.from(row["Manufacturer Values"] || [])[0] || "")}</td>
                      <td>{String(row.Lifecycle || row.lifecycle || "")}</td>
                      <td>{String(row["Risk Level"] || row.risk_level || "")}</td>
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
                ? String(selected["Part Number"] || selected.mpn || "Selected component")
                : "Select or refresh to surface recommended component"}
            </p>
            <dl className="cv-record-meta" style={{ marginTop: 12, gridTemplateColumns: "1fr 1fr" }}>
              <div className="cv-record-field"><dt>Lifecycle</dt><dd>{String(selected.Lifecycle || selected.lifecycle || "—")}</dd></div>
              <div className="cv-record-field"><dt>Risk</dt><dd>{String(selected["Risk Level"] || selected.risk_level || "—")}</dd></div>
            </dl>
            <h3 className="cv-card-title" style={{ marginTop: 16 }}>Affected context</h3>
            <p className="cv-small-note">{Array.isArray(affected) ? `${affected.length} related rows` : "See intelligence payload for project links."}</p>
          </section>
        </div>
      ) : null}
    </Shell>
  );
}
