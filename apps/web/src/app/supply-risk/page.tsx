"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { runSupplyRisk } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function cell(value: unknown, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function SupplyRiskInner() {
  const session = useRequireSession();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const forcePortfolio = useMemo(
    () => searchParams.get("scope") === "portfolio",
    [searchParams],
  );
  const requestedAnalysisId = useMemo(
    () => (searchParams.get("analysis_id") || "").trim(),
    [searchParams],
  );
  const [stockReduction, setStockReduction] = useState(25);
  const [buildQty, setBuildQty] = useState(100);
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [activeAnalysisId, setActiveAnalysisId] = useState(requestedAnalysisId);
  const [scopeSource, setScopeSource] = useState<"url" | "session" | "portfolio" | "explicit">(
    requestedAnalysisId ? "url" : "portfolio",
  );

  async function run(event?: FormEvent, analysisOverride?: string, source?: typeof scopeSource) {
    event?.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    const last = readLastAnalysis(session);
    const analysisId = forcePortfolio
      ? ""
      : (analysisOverride ?? activeAnalysisId ?? requestedAnalysisId ?? last?.analysis_id ?? "").trim();
    try {
      const payload = await runSupplyRisk(session.access_token, {
        analysis_id: analysisId || null,
        build_quantity: buildQty,
        stock_reduction_percent: stockReduction,
        supplier_loss: 0,
        demand_growth_percent: 0,
        include_lifecycle_event: false,
      });
      setData(payload);
      setActiveAnalysisId(String(payload.analysis_id || analysisId || ""));
      if (source) setScopeSource(source);
      else if (!analysisId) setScopeSource("portfolio");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (forcePortfolio) {
      setActiveAnalysisId("");
      setScopeSource("portfolio");
      void run(undefined, "");
      return;
    }
    const last = session ? readLastAnalysis(session) : null;
    const nextId = requestedAnalysisId || last?.analysis_id || "";
    setActiveAnalysisId(nextId);
    setScopeSource(requestedAnalysisId ? "url" : nextId ? "session" : "portfolio");
    void run(undefined, nextId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, requestedAnalysisId, forcePortfolio]);

  if (!session) return null;
  const scenario = (data?.scenario || {}) as Record<string, unknown>;
  const inventoryAvailable =
    data?.inventory_evidence_available !== false &&
    scenario.inventory_evidence_available !== false &&
    String(data?.inventory_status || scenario.inventory_status || "") !==
      "inventory evidence unavailable";
  const rows = (
    inventoryAvailable ? scenario.impacted || scenario.rows || [] : []
  ) as Array<Record<string, unknown>>;
  const scope = String(data?.scope || "").trim();
  const inheritanceNote =
    scopeSource === "url"
      ? "Scope source: analysis_id from URL"
      : scopeSource === "session"
        ? "Scope source: inherited selected analysis from session"
        : scopeSource === "explicit"
          ? "Scope source: explicitly selected analysis"
          : "Scope source: portfolio-wide (no analysis selected)";
  const scopeLabel =
    scope === "analysis"
      ? `Scoped to selected analysis${data?.analysis_label ? ` · ${String(data.analysis_label)}` : ""}`
      : scope === "portfolio"
        ? "Portfolio-wide across saved analyses in this workspace"
        : "Scope unavailable";
  const sourcePartCount = Number(data?.source_part_count ?? 0);
  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.supply}
        actions={
          <PrimaryLink
            href={
              activeAnalysisId
                ? `/reports/${encodeURIComponent(activeAnalysisId)}`
                : "/reports"
            }
          >
            {activeAnalysisId ? "Open selected analysis" : "Choose a saved analysis"}
          </PrimaryLink>
        }
      />
      {<EvidenceNotice gap={data?.gap} />}
      <form className="cv-card pad" style={{ marginBottom: 14 }} onSubmit={(event) => run(event, undefined, activeAnalysisId ? "explicit" : "portfolio")}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="build">Build quantity</label>
            <input id="build" type="number" min={1} value={buildQty} onChange={(e) => setBuildQty(Number(e.target.value) || 1)} />
          </div>
          <div className="cv-field">
            <label htmlFor="stock">Stock reduction %</label>
            <input id="stock" type="number" min={0} max={100} value={stockReduction} onChange={(e) => setStockReduction(Number(e.target.value) || 0)} />
          </div>
        </div>
        <p className="cv-small-note" style={{ marginTop: 10 }} role="status">
          {scopeLabel}
          {Number.isFinite(sourcePartCount) ? ` · ${sourcePartCount} BOM part record${sourcePartCount === 1 ? "" : "s"}` : ""}
          {activeAnalysisId ? ` · analysis_id=${activeAnalysisId}` : " · no analysis_id (portfolio)"}
          {` · ${inheritanceNote}`}
        </p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
          <button className="cv-button primary" type="submit" disabled={busy}>
            {busy ? "Modeling…" : "Run scenario"}
          </button>
          {(activeAnalysisId || scopeSource === "session" || scopeSource === "url") && !forcePortfolio ? (
            <button
              className="cv-button"
              type="button"
              disabled={busy}
              onClick={() => {
                const params = new URLSearchParams(searchParams.toString());
                params.delete("analysis_id");
                params.set("scope", "portfolio");
                setActiveAnalysisId("");
                setScopeSource("portfolio");
                router.replace(`${pathname}?${params.toString()}`, { scroll: false });
              }}
            >
              Clear analysis scope (portfolio-wide)
            </button>
          ) : null}
        </div>
      </form>
      {busy ? <LoadingCard label="Modeling supply scenario…" /> : null}
      {error ? <div className="cv-error" role="alert">The supply scenario could not run. {error}</div> : null}
      {!busy && data ? (
        <>
          <section className="cv-card pad">
            <div className="cv-section-heading cv-section-heading--card">
              <div>
                <h2>Affected components</h2>
                <p>
                  Scenario: {String(scenario.build_quantity ?? buildQty)} units with a {String(scenario.stock_reduction_percent ?? stockReduction)}% stock reduction.
                  {" "}
                  {scope === "portfolio"
                    ? "Showing portfolio-wide impact (all saved analyses)."
                    : "Showing impact for the selected analysis only."}
                </p>
              </div>
              <span className="cv-data-note">{rows.length} component{rows.length === 1 ? "" : "s"}</span>
            </div>
            {!inventoryAvailable ? (
              <EmptyState
                icon="risk"
                title="Inventory evidence unavailable"
                body="Saved BOM parts in this scope do not include recorded stock. Cadivor will not show a zero-impact result when inventory evidence is missing. Re-analyze with supplier stock fields, or clear scope to another analysis that has inventory."
                action={<PrimaryLink href="/reports">Choose a saved analysis</PrimaryLink>}
              />
            ) : rows.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table">
                <thead>
                  <tr>
                    <th>Part</th>
                    <th>Stock</th>
                    <th>Adjusted</th>
                    <th>Lifecycle</th>
                    <th>Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 40).map((row, i) => (
                    <tr key={i}>
                      <td><strong>{cell(row["Part Number"] ?? row.mpn)}</strong></td>
                      <td>{cell(row["Original Stock"] ?? row["Available Stock"] ?? row.stock ?? row.Stock)}</td>
                      <td>{cell(row["Scenario Stock"] ?? row["Adjusted Stock"] ?? row.adjusted_stock)}</td>
                      <td>{cell(row.Lifecycle ?? row.lifecycle)}</td>
                      <td>{cell(row["Scenario Risk"] ?? row["Risk Level"] ?? row.risk_level)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            ) : (
              <EmptyState
                icon="risk"
                title="No affected components found"
                body="Inventory evidence is present, but no components match this scenario. Try another stock reduction or review the saved analysis."
                action={<PrimaryLink href="/reports">Choose a saved analysis</PrimaryLink>}
              />
            )}
          </section>
        </>
      ) : null}
    </Shell>
  );
}

export default function SupplyRiskPage() {
  return (
    <Suspense fallback={<div className="cv-page-loading">Loading supply risk…</div>}>
      <SupplyRiskInner />
    </Suspense>
  );
}
