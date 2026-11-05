"use client";

import { FormEvent, useState } from "react";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { compareParts } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

export default function ComparePartsPage() {
  const session = useRequireSession();
  const [partA, setPartA] = useState("");
  const [partB, setPartB] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const last = readLastAnalysis();
      const data = await compareParts(
        session.access_token,
        partA,
        partB,
        last?.analysis_id,
      );
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Compare failed");
    } finally {
      setBusy(false);
    }
  }

  if (!session) return null;
  const rows = (result?.rows || []) as Array<Record<string, unknown>>;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.compare}
        actions={<PrimaryLink href="/bom-analyzer">BOM Analyzer</PrimaryLink>}
      />
      <form className="cv-card pad" onSubmit={onSubmit}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="part-a">Part A</label>
            <input id="part-a" value={partA} onChange={(e) => setPartA(e.target.value)} placeholder="Manufacturer part number" required />
          </div>
          <div className="cv-field">
            <label htmlFor="part-b">Part B</label>
            <input id="part-b" value={partB} onChange={(e) => setPartB(e.target.value)} placeholder="Manufacturer part number" required />
          </div>
        </div>
        <div style={{ marginTop: 14 }}>
          <button className="cv-button primary" type="submit" disabled={busy}>
            {busy ? "Comparing…" : "Compare parts"}
          </button>
        </div>
      </form>
      {busy ? <LoadingCard label="Running comparison without live supplier lookup…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {result ? (
        <>
          {typeof result.gap === "string" ? <GapBanner>{String(result.gap)}</GapBanner> : null}
          <div className="cv-kpis" style={{ marginTop: 14 }}>
            <div className="cv-kpi tone-blue"><span>Finding</span><strong style={{ fontSize: 14 }}>{String(result.finding || "See rows")}</strong><em>{String(result.mode)}</em></div>
            <div className="cv-kpi"><span>Part A source</span><strong style={{ fontSize: 14 }}>{String(result.source_a)}</strong><em>{String(result.part_a)}</em></div>
            <div className="cv-kpi"><span>Part B source</span><strong style={{ fontSize: 14 }}>{String(result.source_b)}</strong><em>{String(result.part_b)}</em></div>
            <div className="cv-kpi"><span>Rows</span><strong>{rows.length}</strong><em>Attribute comparisons</em></div>
          </div>
          <section className="cv-card pad">
            <h3 className="cv-card-title">Attribute comparison</h3>
            <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>Attribute</th>
                    <th>Part A</th>
                    <th>Part B</th>
                    <th>Assessment</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i}>
                      <td><strong>{String(row.Attribute || row.attribute || "")}</strong></td>
                      <td>{String(row["Part A"] || row.part_a || "")}</td>
                      <td>{String(row["Part B"] || row.part_b || "")}</td>
                      <td>{String(row.Assessment || row.assessment || row.Status || "")}</td>
                      <td>{String(row.Evidence || row.evidence || row.Note || "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </Shell>
  );
}
