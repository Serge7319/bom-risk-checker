"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import {
  listReports,
  listSupplyRiskScenarios,
  runSupplyRisk,
  saveSupplyRiskScenario,
  type SavedSupplyScenario,
} from "@/lib/api";
import { cleanUserText, userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

type Row = Record<string, unknown>;

function analysisLabel(row: Row) {
  const project = userFacingLabel(row.project_name, "");
  const bom = userFacingLabel(row.bom_name || row.filename, "");
  const revision = userFacingLabel(row.revision, "");
  const title = [project, bom].filter(Boolean).join(" · ") || "Saved analysis";
  return revision ? `${title} (rev ${revision})` : title;
}

function value(valueToFormat: unknown, fallback = "—") {
  if (valueToFormat === null || valueToFormat === undefined || valueToFormat === "") return fallback;
  const number = Number(valueToFormat);
  return Number.isFinite(number) ? Math.floor(number).toLocaleString() : cleanUserText(String(valueToFormat)) || fallback;
}

function dateLabel(valueToFormat: unknown) {
  const date = new Date(String(valueToFormat || ""));
  return Number.isNaN(date.getTime()) ? "Observation date not recorded" : date.toLocaleDateString();
}

function SupplyRiskInner() {
  const session = useRequireSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedAnalysisId = useMemo(
    () => (searchParams.get("analysis_id") || "").trim(),
    [searchParams],
  );
  const [stockReduction, setStockReduction] = useState(25);
  const [buildQty, setBuildQty] = useState(100);
  const [data, setData] = useState<Row | null>(null);
  const [reports, setReports] = useState<Row[]>([]);
  const [savedScenarios, setSavedScenarios] = useState<SavedSupplyScenario[]>([]);
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [savedMessage, setSavedMessage] = useState("");
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activeAnalysisId, setActiveAnalysisId] = useState("");

  async function runScenario(analysisId: string, build = buildQty, reduction = stockReduction) {
    if (!session || !analysisId) {
      setData(null);
      setBusy(false);
      return;
    }
    setBusy(true);
    setError("");
    setSavedMessage("");
    try {
      const payload = await runSupplyRisk(session.access_token, {
        analysis_id: analysisId,
        build_quantity: build,
        stock_reduction_percent: reduction,
        supplier_loss: 0,
        demand_growth_percent: 0,
        include_lifecycle_event: false,
      });
      setData(payload);
      setActiveAnalysisId(String(payload.analysis_id || analysisId));
      try {
        const saved = await listSupplyRiskScenarios(session.access_token, analysisId);
        setSavedScenarios(saved.scenarios || []);
      } catch {
        setSavedScenarios([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "The scenario could not be calculated.");
      setData(null);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    let active = true;
    setBusy(true);
    listReports(session.access_token)
      .then(async ({ reports: reportRows }) => {
        if (!active) return;
        const available = ((reportRows || []) as Row[])
          .filter((row) => String(row.id || "").trim())
          .sort((a, b) => {
            const aTime = new Date(String(a.created_at || "")).getTime() || 0;
            const bTime = new Date(String(b.created_at || "")).getTime() || 0;
            return bTime - aTime;
          });
        setReports(available);
        const chosen = available.some((row) => String(row.id) === requestedAnalysisId)
          ? requestedAnalysisId
          : String(available[0]?.id || "");
        setActiveAnalysisId(chosen);
        if (!chosen) {
          setData(null);
          setSavedScenarios([]);
          setBusy(false);
          return;
        }
        try {
          const payload = await runSupplyRisk(session.access_token, {
            analysis_id: chosen,
            build_quantity: buildQty,
            stock_reduction_percent: stockReduction,
            supplier_loss: 0,
            demand_growth_percent: 0,
            include_lifecycle_event: false,
          });
          if (active) setData(payload);
        } catch (err) {
          if (active) setError(err instanceof Error ? err.message : "The scenario could not be calculated.");
        }
        try {
          const saved = await listSupplyRiskScenarios(session.access_token, chosen);
          if (active) setSavedScenarios(saved.scenarios || []);
        } catch {
          if (active) setSavedScenarios([]);
        } finally {
          if (active) setBusy(false);
        }
      })
      .catch((err) => {
        if (active) {
          setReports([]);
          setError(err instanceof Error ? err.message : "Saved analyses could not load.");
          setBusy(false);
        }
      });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, requestedAnalysisId]);

  if (!session) return null;
  const scenario = (data?.scenario || {}) as Row;
  const coverageGap = (
    (data?.stock_coverage_gap as Row | undefined) ||
    (scenario.stock_coverage_gap as Row | undefined) ||
    {}
  );
  const rows = (scenario.rows || []) as Row[];
  const shortages = (scenario.shortfall_rows || []) as Row[];
  const unknownCount = Number(
    coverageGap.unknown_stock_components ?? scenario.unknown_stock_components ?? 0
  );
  const knownCount = Number(
    coverageGap.known_stock_components ?? scenario.known_stock_components ?? 0
  );
  const partCount = Number(
    coverageGap.component_count ?? scenario.component_count ?? rows.length
  );
  const coverage = String(data?.stock_coverage || scenario.stock_coverage || "absent");
  const inventoryAbsent = coverage === "absent";
  const limiting = (scenario.limiting_part || null) as Row | null;
  const status = String(scenario.buildability_status || (inventoryAbsent ? "Unknown" : "At risk"));
  const report = reports.find((row) => String(row.id || "") === activeAnalysisId) || {};
  const reportTitle = analysisLabel(report);
  const replacementHref = (mpn: unknown, manufacturer: unknown) => {
    const query = new URLSearchParams({ analysis_id: activeAnalysisId, mpn: String(mpn || "") });
    if (manufacturer) query.set("manufacturer", String(manufacturer));
    return `/find-replacement?${query.toString()}`;
  };
  const procurementHref = (mpn: unknown) => {
    const query = new URLSearchParams({ analysis_id: activeAnalysisId, part_number: String(mpn || "") });
    return `/procurement?${query.toString()}`;
  };
  const decisionHref = (mpn: unknown, manufacturer: unknown) => {
    const query = new URLSearchParams({ analysis_id: activeAnalysisId, part_a: String(mpn || "") });
    if (manufacturer) query.set("manufacturer_a", String(manufacturer));
    return `/compare-parts?${query.toString()}`;
  };
  const buildable = scenario.buildable_units;
  const baselineBuildable = scenario.baseline_buildable_units;
  const scenarioMatchesInputs =
    Number(scenario.build_quantity) === buildQty &&
    Number(scenario.stock_reduction_percent) === stockReduction;

  async function onSaveScenario(event: FormEvent) {
    event.preventDefault();
    if (!session || !activeAnalysisId) return;
    setSaving(true);
    setSaveError("");
    setSavedMessage("");
    try {
      const result = await saveSupplyRiskScenario(session.access_token, {
        analysis_id: activeAnalysisId,
        build_quantity: buildQty,
        stock_reduction_percent: stockReduction,
      });
      setSavedScenarios((current) => [result.scenario, ...current.filter((row) => row.id !== result.scenario.id)]);
      setSavedMessage("Scenario saved to this BOM report.");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "The scenario could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.supply}
        actions={activeAnalysisId ? <PrimaryLink href={`/reports/${encodeURIComponent(activeAnalysisId)}`}>Open selected report</PrimaryLink> : null}
      />
      {data ? <EvidenceNotice gap={data.gap} /> : null}
      <form className="cv-card pad" style={{ marginBottom: 14 }} onSubmit={(event) => {
        event.preventDefault();
        void runScenario(activeAnalysisId, buildQty, stockReduction);
      }}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="supply-analysis">Saved BOM analysis</label>
            <select
              id="supply-analysis"
              value={activeAnalysisId}
              disabled={busy && reports.length === 0}
              onChange={(event) => {
                const nextId = event.target.value;
                setActiveAnalysisId(nextId);
                setData(null);
                setSavedScenarios([]);
                setBusy(true);
                setError("");
                router.replace(
                  nextId ? `/supply-risk?analysis_id=${encodeURIComponent(nextId)}` : "/supply-risk",
                  { scroll: false },
                );
              }}
            >
              <option value="">Select a saved analysis</option>
              {reports.map((row) => {
                const id = String(row.id || "");
                return id ? <option key={id} value={id}>{analysisLabel(row)}</option> : null;
              })}
            </select>
          </div>
          <div className="cv-field">
            <label htmlFor="supply-build">Build quantity</label>
            <input id="supply-build" type="number" min={1} max={10000000} value={buildQty} onChange={(event) => setBuildQty(Math.max(1, Number(event.target.value) || 1))} />
          </div>
          <div className="cv-field">
            <label htmlFor="supply-reduction">Stock reduction %</label>
            <input id="supply-reduction" type="number" min={0} max={100} value={stockReduction} onChange={(event) => setStockReduction(Math.min(100, Math.max(0, Number(event.target.value) || 0)))} />
          </div>
        </div>
        <p className="cv-small-note" style={{ marginTop: 10 }}>
          {reportTitle} · Stock values come from the saved analysis fields; they are indicative and are not live supplier inventory or a guarantee. Stock source and observation date appear by part when recorded.
        </p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
          <button className="cv-button primary" type="submit" disabled={busy || !activeAnalysisId}>
            {busy ? "Modeling…" : "Run scenario"}
          </button>
        </div>
      </form>

      {busy ? <LoadingCard label="Modeling build capacity from recorded stock…" /> : null}
      {data && !scenarioMatchesInputs ? (
        <div className="cv-notice" role="status" style={{ marginBottom: 14 }}>
          Inputs changed. The results below are from the last run; run the scenario again before saving it.
        </div>
      ) : null}
      {error ? <div className="cv-error" role="alert">Supply Risk Scenario could not load. {error}</div> : null}
      {!busy && !reports.length ? (
        <EmptyState icon="risk" title="Analyze a BOM to start" body="Supply scenarios need one saved BOM to calculate part quantities and build capacity. Run a BOM analysis first." action={<PrimaryLink href="/bom-analyzer">Start BOM analysis</PrimaryLink>} />
      ) : null}
      {!busy && reports.length > 0 && !activeAnalysisId ? (
        <EmptyState icon="risk" title="Select a saved analysis" body="Choose the BOM to model before running a supply scenario." />
      ) : null}

      {!busy && data ? (
        <>
          <section className="cv-grid cv-grid--3" style={{ marginBottom: 14 }}>
            <article className="cv-card pad">
              <div className="cv-small-note">Known-stock build ceiling after scenario</div>
              <h2 style={{ margin: "8px 0" }}>{inventoryAbsent ? "Unknown" : `${value(buildable)} of ${Number(scenario.build_quantity || buildQty).toLocaleString()}`}</h2>
              <div className="cv-small-note">{knownCount} of {partCount} parts have stock records{unknownCount ? " · unknown stock may lower this capacity" : ""}</div>
            </article>
            <article className="cv-card pad">
              <div className="cv-small-note">Baseline builds supported</div>
              <h2 style={{ margin: "8px 0" }}>{inventoryAbsent ? "Unknown" : value(baselineBuildable)}</h2>
              <div className="cv-small-note">Before stock reduction · same BOM and build assumptions</div>
            </article>
            <article className={`cv-card pad ${status === "Short" ? "cv-card--warning" : ""}`}>
              <div className="cv-small-note">Scenario status</div>
              <h2 style={{ margin: "8px 0" }}>{inventoryAbsent ? "Unknown" : status}</h2>
              <div className="cv-small-note">Covered: ≥125% of need · At risk: 100–124% · Short: below required quantity</div>
            </article>
          </section>

          {coverage !== "complete" ? (
            <div className="cv-notice" role="status" style={{ marginBottom: 14 }}>
              {cleanUserText(String(coverageGap.message || "Stock evidence is incomplete."))}
              {" "}Unknown stock is not treated as zero. The displayed ceiling uses only parts with recorded stock; missing stock could lower the actual build capacity.
            </div>
          ) : null}

          {limiting && !inventoryAbsent ? (
            <section className="cv-card pad" style={{ marginBottom: 14 }}>
              <div className="cv-small-note">Limiting part under this scenario</div>
              <h2 style={{ margin: "6px 0" }}>{String(limiting["Part Number"] || "Unknown part")}</h2>
              <p className="cv-small-note">
                Supports {value(limiting["Scenario Buildable Units"])} builds from {value(limiting["Scenario Stock"])} units of stock; {value(limiting["Quantity per Build"])} required per build.
              </p>
            </section>
          ) : null}

          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <div className="cv-section-heading cv-section-heading--card">
              <div><h2>Parts that fall short</h2><p>Sorted by missing units. Savings and supply mitigations require review before a sourcing or engineering decision.</p></div>
              <span className="cv-data-note">{shortages.length} short</span>
            </div>
            {shortages.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead><tr><th>Part</th><th className="cv-num">Required</th><th className="cv-num">Stock before</th><th className="cv-num">Stock after</th><th className="cv-num">Shortfall</th><th>Stock source / date</th><th>Sources</th><th>Status</th><th>Mitigation</th></tr></thead>
                  <tbody>
                    {shortages.slice(0, 50).map((row, index) => (
                      <tr key={`${String(row["Part Number"])}-${index}`}>
                        <td><strong>{String(row["Part Number"] || "")}</strong><div className="cv-small-note">{cleanUserText(String(row.Manufacturer || "Manufacturer not recorded"))}</div></td>
                        <td className="cv-num">{value(row["Required Units"])}</td>
                        <td className="cv-num">{value(row["Original Stock"])}</td>
                        <td className="cv-num">{value(row["Scenario Stock"])}</td>
                        <td className="cv-num"><strong>{value(row["Shortage Units"])}</strong></td>
                        <td>{cleanUserText(String(row["Stock Source"] || "Saved analysis stock field"))}<div className="cv-small-note">{dateLabel(row["Stock Retrieved At"])}</div></td>
                        <td>{value(row["Scenario Sources"] ?? row["Original Sources"], "Unknown")}</td>
                        <td>{cleanUserText(String(row.Status || "Short"))}</td>
                        <td>
                          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            <Link className="cv-link" href={replacementHref(row["Part Number"], row.Manufacturer)}>Find replacement</Link>
                            <Link className="cv-link" href={procurementHref(row["Part Number"])}>Add source</Link>
                            <Link className="cv-link" href={decisionHref(row["Part Number"], row.Manufacturer)}>Compare / decide</Link>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : inventoryAbsent ? (
              <EmptyState icon="risk" title="Inventory evidence unavailable" body="No stock-based shortfall can be calculated from this report. Refresh supplier evidence in Procurement Advisor; missing stock is not zero." action={<PrimaryLink href={procurementHref("")}>Open Procurement Advisor</PrimaryLink>} />
            ) : (
              <EmptyState icon="risk" title={unknownCount ? "No shortfall in recorded stock" : "No short parts under this scenario"} body={unknownCount ? `Known stock covers this plan for the recorded parts. Stock remains unknown for ${unknownCount} part(s), so that finding is incomplete.` : "Recorded stock covers the requested build quantity for every BOM part."} />
            )}
          </section>

          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <div className="cv-section-heading cv-section-heading--card">
              <div><h2>Compare baseline and scenario</h2><p>Per-part quantities use recorded stock, with the configured reduction applied once per unique MPN and manufacturer.</p></div>
              <span className="cv-data-note">{rows.length} parts</span>
            </div>
            {rows.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead><tr><th>Part</th><th className="cv-num">Qty / build</th><th className="cv-num">Need for plan</th><th className="cv-num">Baseline capacity</th><th className="cv-num">Scenario capacity</th><th>Stock source / date</th><th>Scenario status</th></tr></thead>
                  <tbody>
                    {rows.slice(0, 100).map((row, index) => (
                      <tr key={`${String(row["Part Number"])}-${index}`}>
                        <td><strong>{String(row["Part Number"] || "")}</strong></td>
                        <td className="cv-num">{value(row["Quantity per Build"])}</td>
                        <td className="cv-num">{value(row["Required Units"])}</td>
                        <td className="cv-num">{value(row["Baseline Buildable Units"])}</td>
                        <td className="cv-num">{value(row["Scenario Buildable Units"])}</td>
                        <td>{cleanUserText(String(row["Stock Source"] || "Saved analysis stock field"))}<div className="cv-small-note">{dateLabel(row["Stock Retrieved At"])}</div></td>
                        <td>{cleanUserText(String(row.Status || "Unknown"))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="cv-small-note">No BOM component records were found in the selected analysis.</p>}
          </section>

          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <div className="cv-section-heading cv-section-heading--card">
              <div><h2>Save scenario to this report</h2><p>Saved scenarios keep the input assumptions and result snapshot linked to the selected BOM.</p></div>
            </div>
            <form onSubmit={onSaveScenario}>
              <button className="cv-button primary" type="submit" disabled={saving || !activeAnalysisId || inventoryAbsent || !scenarioMatchesInputs}>
                {saving ? "Saving…" : "Save scenario to report"}
              </button>
              {savedMessage ? <span className="cv-success" role="status" style={{ marginLeft: 10 }}>{savedMessage}</span> : null}
              {saveError ? <div className="cv-error" role="alert" style={{ marginTop: 10 }}>{saveError}</div> : null}
            </form>
            {savedScenarios.length ? (
              <div style={{ marginTop: 16 }}>
                <h3>Saved scenarios</h3>
                <div className="cv-table-wrap">
                  <table className="cv-table">
                    <thead><tr><th>Saved</th><th>Scenario</th><th>Build ceiling</th><th>Status</th><th>Report</th></tr></thead>
                    <tbody>
                      {savedScenarios.map((item) => {
                        const summary = (item.summary || {}) as Row;
                        const params = (item.parameters || {}) as Row;
                        return (
                          <tr key={item.id}>
                            <td>{new Date(item.created_at).toLocaleString()}</td>
                            <td>{cleanUserText(item.title || `Stock reduction ${String(params.stock_reduction_percent || 0)}%`)}</td>
                            <td>{value(summary.buildable_units)}</td>
                            <td>{cleanUserText(String(summary.buildability_status || "Unknown"))}</td>
                            <td><Link className="cv-link" href={`/reports/${encodeURIComponent(activeAnalysisId)}`}>Open report</Link></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </section>
        </>
      ) : null}
    </Shell>
  );
}

export default function SupplyRiskPage() {
  return (
    <Suspense fallback={<div className="cv-page-loading">Loading Supply Risk Scenario…</div>}>
      <SupplyRiskInner />
    </Suspense>
  );
}
