"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { fetchProcurement } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

export default function ProcurementPage() {
  const session = useRequireSession();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    if (!session) return;
    const last = readLastAnalysis();
    fetchProcurement(session.access_token, last?.analysis_id)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }, [session]);

  if (!session) return null;
  const parts = (data?.parts || []) as Array<Record<string, unknown>>;

  return (
    <Shell session={session}>
      <PageHeader meta={PAGE_META.procurement} actions={<PrimaryLink href="/bom-analyzer">Analyze BOM</PrimaryLink>} />
      {typeof data?.gap === "string" ? <GapBanner>{String(data.gap)}</GapBanner> : null}
      {busy ? <LoadingCard label="Loading procurement coverage…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {!busy && data ? (
        <section className="cv-card pad">
          <h3 className="cv-card-title">Sourcing coverage</h3>
          <p className="cv-card-subtitle">{String(data.recommendation_note || "")}</p>
          <div className="cv-table-wrap" style={{ marginTop: 12 }}>
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
                    <td><strong>{String(p.mpn || "")}</strong></td>
                    <td>{String(p.manufacturer || "")}</td>
                    <td>{String(p.lifecycle || "")}</td>
                    <td>{String(p.risk_level || "")}</td>
                    <td>{String(p.stock ?? "—")}</td>
                    <td>{p.unit_price == null ? "—" : String(p.unit_price)}</td>
                    <td><span className="cv-badge gray">{String(p.price_source || "synthetic-preview")}</span></td>
                    <td>{String(p.offer_count ?? 0)} · {String(p.coverage)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </Shell>
  );
}
