"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Shell } from "@/components/Shell";
import { GapBanner, LoadingCard } from "@/components/GapBanner";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { compareParts } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function ComparePartsInner() {
  const session = useRequireSession();
  const search = useSearchParams();
  const [partA, setPartA] = useState("");
  const [partB, setPartB] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const a = (search.get("part_a") || search.get("a") || "").trim();
    const b = (search.get("part_b") || search.get("b") || "").trim();
    if (a) setPartA(a);
    if (b) setPartB(b);
  }, [search]);

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
  const finding = String(result?.finding || "See rows");
  const mismatch = Boolean(result?.family_mismatch);

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.compare}
        actions={
          <>
            <PrimaryLink href="/find-replacement">Find a replacement</PrimaryLink>
            <SecondaryLink href="/bom-analyzer">BOM Analyzer</SecondaryLink>
          </>
        }
      />
      <form className="cv-card pad" onSubmit={onSubmit}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="part-a">Part A</label>
            <input
              id="part-a"
              value={partA}
              onChange={(e) => setPartA(e.target.value)}
              placeholder="Manufacturer part number"
              required
            />
          </div>
          <div className="cv-field">
            <label htmlFor="part-b">Part B</label>
            <input
              id="part-b"
              value={partB}
              onChange={(e) => setPartB(e.target.value)}
              placeholder="Manufacturer part number"
              required
            />
          </div>
        </div>
        <div style={{ marginTop: 14 }}>
          <button className="cv-button primary" type="submit" disabled={busy}>
            {busy ? "Comparing…" : "Compare parts"}
          </button>
        </div>
      </form>
      {busy ? (
        <LoadingCard label="Running comparison with available evidence…" />
      ) : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {result ? (
        <>
          {typeof result.gap === "string" ? (
            <GapBanner>{String(result.gap)}</GapBanner>
          ) : null}
          <div className="cv-kpis" style={{ marginTop: 14 }}>
            <KpiCard
              icon="compare"
              tone={mismatch ? "amber" : "blue"}
              label="Finding"
              value={<span style={{ fontSize: 14 }}>{finding}</span>}
              detail={String(result.mode || "")}
            />
            <KpiCard
              icon="file"
              label="Part A source"
              value={<span style={{ fontSize: 14 }}>{String(result.source_a)}</span>}
              detail={String(result.part_a)}
            />
            <KpiCard
              icon="file"
              label="Part B source"
              value={<span style={{ fontSize: 14 }}>{String(result.source_b)}</span>}
              detail={String(result.part_b)}
            />
            <KpiCard
              icon="insight"
              label="Rows"
              value={rows.length}
              detail="Attribute comparisons"
            />
          </div>
          <section className="cv-card pad">
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                alignItems: "baseline",
              }}
            >
              <h3 className="cv-card-title">Attribute comparison</h3>
              <Link
                href={`/find-replacement?mpn=${encodeURIComponent(String(result.part_a || partA))}`}
              >
                Find replacement for Part A →
              </Link>
            </div>
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
                      <td>
                        <strong>
                          {String(row.Attribute || row.attribute || "")}
                        </strong>
                      </td>
                      <td>{String(row["Part A"] || row.part_a || "")}</td>
                      <td>{String(row["Part B"] || row.part_b || "")}</td>
                      <td>
                        {String(
                          row.Assessment ||
                            row.assessment ||
                            row.Status ||
                            "",
                        )}
                      </td>
                      <td>
                        {String(row.Evidence || row.evidence || row.Note || "")}
                      </td>
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

export default function ComparePartsPage() {
  return (
    <Suspense fallback={null}>
      <ComparePartsInner />
    </Suspense>
  );
}
