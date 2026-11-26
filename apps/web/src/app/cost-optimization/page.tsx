"use client";

import { Suspense, useEffect, useMemo, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import {
  createCostOptimizationDecision,
  fetchCostOptimization,
  listCostOptimizationDecisions,
  listReports,
  type CostOptimizationDecision,
} from "@/lib/api";
import { cleanUserText, evidenceSourceLabel, userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

type CostRow = Record<string, unknown>;

function analysisLabel(row: CostRow) {
  const project = userFacingLabel(row.project_name, "");
  const bom = userFacingLabel(row.bom_name || row.filename, "");
  const revision = userFacingLabel(row.revision, "");
  const title = [project, bom].filter(Boolean).join(" · ") || "Saved analysis";
  return revision ? `${title} (rev ${revision})` : title;
}

function formatNumber(value: unknown, digits = 2) {
  if (value === null || value === undefined || String(value).trim() === "") return "—";
  const amount = typeof value === "number" ? value : Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(amount)) return String(value);
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: digits }).format(amount);
}

function formatMoney(value: unknown, currency: unknown, digits = 2) {
  if (value === null || value === undefined || String(value).trim() === "") return "—";
  const code = String(currency || "").trim().toUpperCase();
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: /^[A-Z]{3}$/.test(code) ? code : "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: digits,
    }).format(amount);
  } catch {
    return `${code || "Currency"} ${formatNumber(amount, digits)}`;
  }
}

function formatDate(value: unknown) {
  const date = new Date(String(value || ""));
  return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toLocaleDateString();
}

function csvCell(value: unknown) {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCostPlan(optimization: CostRow, context: CostRow, buildQuantity: number) {
  const rows = (optimization.rows || []) as CostRow[];
  const opportunities = (optimization.opportunities || []) as CostRow[];
  const output: unknown[][] = [
    ["Cadivor Cost Plan"],
    ["Analysis", context.bom_name || context.filename || context.project_name || ""],
    ["Build quantity", buildQuantity],
    ["Price coverage", `${optimization.priced_component_count ?? 0} of ${optimization.component_count ?? 0} component lines`],
    ["Pricing note", "Saved supplier prices are indicative snapshots, not live quotes or guarantees."],
    [],
    ["BOM line items"],
    ["Part number", "Manufacturer", "Quantity per build", "Order quantity", "Unit price", "Currency", "Supplier", "Price date", "Extended cost per build", "Extended cost at build quantity"],
    ...rows.map((row) => [
      row["Part Number"], row.Manufacturer, row["Quantity per Build"], row["Order Quantity"],
      row["Unit Price"], row.Currency, row["Price Source"], row["Price Retrieved At"],
      row["Extended Cost per Build"], row["Extended Cost at Build Quantity"],
    ]),
    [],
    ["Savings opportunities"],
    ["Part number", "Type", "Current supplier", "Suggested supplier", "Order quantity", "Extra quantity", "Current unit price", "Target unit price", "Estimated net savings", "Currency", "Current price date", "Target price date"],
    ...opportunities.map((row) => [
      row["Part Number"], row.Category, row["Current Supplier"], row.Supplier,
      row["Required Order Quantity"], row["Extra Quantity"], row["Current Unit Price"],
      row["Estimated Target Price"], row["Estimated Run Savings"], row.Currency,
      row["Current Price Retrieved At"], row["Target Price Retrieved At"],
    ]),
  ];
  const csv = output.map((row) => row.map(csvCell).join(",")).join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "cadivor-cost-plan.csv";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function CostOptimizationInner() {
  const session = useRequireSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedAnalysisId = useMemo(
    () => (searchParams.get("analysis_id") || "").trim(),
    [searchParams],
  );
  const [qty, setQty] = useState(100);
  const [targetCost, setTargetCost] = useState("");
  const [data, setData] = useState<CostRow | null>(null);
  const [reports, setReports] = useState<CostRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [selectedAnalysisId, setSelectedAnalysisId] = useState("");
  const [decisions, setDecisions] = useState<CostOptimizationDecision[]>([]);
  const [decisionOpportunity, setDecisionOpportunity] = useState<CostRow | null>(null);
  const [decisionReviewer, setDecisionReviewer] = useState("");
  const [decisionRationale, setDecisionRationale] = useState("");
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  const [decisionMessage, setDecisionMessage] = useState("");

  async function load(buildQuantity: number, analysisId: string, unitTarget = targetCost) {
    if (!session || !analysisId) {
      setData(null);
      setBusy(false);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const parsedTarget = Number(unitTarget);
      const result = await fetchCostOptimization(session.access_token, {
        analysisId,
        buildQuantity,
        targetUnitCost: Number.isFinite(parsedTarget) && parsedTarget > 0 ? parsedTarget : undefined,
      });
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cost analysis could not load.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!session) return;
    let active = true;
    setBusy(true);
    setError("");
    listReports(session.access_token)
      .then(async ({ reports: reportRows }) => {
        if (!active) return;
        const available = ((reportRows || []) as CostRow[])
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
        setSelectedAnalysisId(chosen);
        if (!chosen) {
          setData(null);
          setBusy(false);
          return;
        }
        const parsedTarget = Number(targetCost);
        try {
          const result = await fetchCostOptimization(session.access_token, {
            analysisId: chosen,
            buildQuantity: qty,
            targetUnitCost: Number.isFinite(parsedTarget) && parsedTarget > 0 ? parsedTarget : undefined,
          });
          if (active) setData(result);
        } catch (err) {
          if (active) setError(err instanceof Error ? err.message : "Cost analysis could not load.");
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
    // Load the report directory when the selected BOM in the URL changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, requestedAnalysisId]);

  useEffect(() => {
    if (!session || !selectedAnalysisId) {
      setDecisions([]);
      return;
    }
    let active = true;
    listCostOptimizationDecisions(session.access_token, selectedAnalysisId)
      .then(({ decisions: rows }) => { if (active) setDecisions(rows || []); })
      .catch(() => { if (active) setDecisions([]); });
    return () => { active = false; };
  }, [session, selectedAnalysisId]);

  useEffect(() => {
    if (!decisionReviewer && session?.email) setDecisionReviewer(String(session.email));
  }, [session, decisionReviewer]);

  async function submitDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !activeAnalysisId || !decisionOpportunity || !calculationMatchesInputs) return;
    setDecisionBusy(true);
    setDecisionError("");
    setDecisionMessage("");
    try {
      const parsedTarget = Number(targetCost);
      const result = await createCostOptimizationDecision(session.access_token, {
        analysis_id: activeAnalysisId,
        build_quantity: Number(opt.build_quantity || qty),
        ...(Number.isFinite(parsedTarget) && parsedTarget > 0 ? { target_unit_cost: parsedTarget } : {}),
        part_number: String(decisionOpportunity["Part Number"] || ""),
        manufacturer: String(decisionOpportunity.Manufacturer || ""),
        category: String(decisionOpportunity.Category || ""),
        supplier: String(decisionOpportunity.Supplier || ""),
        recommended_purchase_quantity: Number(decisionOpportunity["Recommended Purchase Quantity"] || decisionOpportunity["Required Order Quantity"] || 0),
        target_unit_price: Number(decisionOpportunity["Estimated Target Price"] || 0),
        reviewer: decisionReviewer.trim(),
        rationale: decisionRationale.trim(),
      });
      setDecisions((current) => [result.decision, ...current.filter((item) => item.id !== result.decision.id)]);
      setDecisionMessage("Decision saved to this BOM report as pending review.");
      setDecisionOpportunity(null);
      setDecisionRationale("");
    } catch (err) {
      setDecisionError(err instanceof Error ? err.message : "Decision could not be saved.");
    } finally {
      setDecisionBusy(false);
    }
  }

  if (!session) return null;
  const opt = (data?.optimization || {}) as CostRow;
  const opportunities = (opt.opportunities || []) as CostRow[];
  const drivers = (opt.top_cost_parts || []) as CostRow[];
  const missingRows = (opt.missing_price_rows || []) as CostRow[];
  const activeAnalysisId = String(data?.analysis_id || selectedAnalysisId || "").trim();
  const componentCount = Number(opt.component_count || 0);
  const pricedCount = Number(opt.priced_component_count || 0);
  const coverage = componentCount ? Math.round((pricedCount / componentCount) * 100) : 0;
  const currencies = (opt.currencies || []) as string[];
  const currency = String(opt.currency || "");
  const partial = pricedCount < componentCount;
  const subtotalPerBoard = opt.current_cost_per_build;
  const runSubtotal = opt.production_run_cost;
  const targetGap = opt.target_cost_gap;
  const enteredTarget = Number(targetCost);
  const normalizedEnteredTarget =
    Number.isFinite(enteredTarget) && enteredTarget > 0 ? enteredTarget : null;
  const recordedTarget =
    opt.target_unit_cost === null || opt.target_unit_cost === undefined || opt.target_unit_cost === ""
      ? null
      : Number(opt.target_unit_cost);
  const calculationMatchesInputs =
    Number(opt.build_quantity || 0) === qty && normalizedEnteredTarget === recordedTarget;
  const procurementFor = (mpn: unknown) => {
    const query = new URLSearchParams();
    if (activeAnalysisId) query.set("analysis_id", activeAnalysisId);
    if (mpn) query.set("part_number", String(mpn));
    return `/procurement?${query.toString()}`;
  };

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.cost}
        actions={
          <PrimaryLink href={activeAnalysisId ? `/procurement?analysis_id=${encodeURIComponent(activeAnalysisId)}` : "/procurement"}>
            Review sourcing
          </PrimaryLink>
        }
      />
      {data ? <EvidenceNotice gap={data.gap} /> : null}
      {data && componentCount > 0 && pricedCount < componentCount ? (
        <div className="cv-notice" role="status" style={{ marginBottom: 12 }}>
          <strong>
            {pricedCount === 0
              ? "Next step: add supplier prices for this BOM."
              : `Price coverage is ${pricedCount} of ${componentCount} BOM lines.`}
          </strong>{" "}
          {pricedCount === 0
            ? "Changing build quantity alone will not produce a cost total. Add or refresh quotes in Procurement Advisor for this saved BOM, then return and select Recalculate."
            : "Totals and savings are partial until prices are saved for the remaining BOM lines."}{" "}
          <PrimaryLink href={procurementFor("")}>Add or refresh quotes</PrimaryLink>
        </div>
      ) : null}
      {data && componentCount > 0 ? (
        <details className="cv-card pad" style={{ marginBottom: 14 }}>
          <summary style={{ cursor: "pointer", fontWeight: 700 }}>How Cost Optimization works</summary>
          <div style={{ marginTop: 10 }}>
            <p className="cv-small-note">
              Cost Optimization uses supplier prices saved to the selected BOM analysis. Changing build quantity does not fetch prices from suppliers; it changes required order quantities and evaluates saved price breaks when you recalculate.
            </p>
            <ol style={{ margin: "8px 0 12px", paddingLeft: 22 }}>
              <li>Add or refresh quotes in Procurement Advisor for this BOM. Quotes are saved as price evidence for the selected parts.</li>
              <li>Return here, enter your build quantity and optional target cost per unit, then select <strong>Recalculate</strong>.</li>
              <li>Review price coverage, the BOM subtotal, savings opportunities, and any parts still missing prices. Partial coverage produces a partial subtotal.</li>
            </ol>
            <p className="cv-small-note" style={{ margin: "0 0 10px" }}>
              The illustrative example below is fixed sample data; it does not change with your inputs and is not evidence for this BOM. Saved prices are point-in-time indications, not live quotes or guarantees.
            </p>
            <PrimaryLink href={procurementFor("")}>Open Procurement Advisor for this BOM</PrimaryLink>
          </div>
        </details>
      ) : null}
      <div className="cv-card pad" style={{ marginBottom: 14, display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
        <div className="cv-field" style={{ minWidth: 260 }}>
          <label htmlFor="cost-analysis">Saved BOM analysis</label>
          <select
            id="cost-analysis"
            aria-label="Cost optimization BOM context"
            value={selectedAnalysisId}
            disabled={busy && reports.length === 0}
            onChange={(event) => {
              const nextId = event.target.value;
              setSelectedAnalysisId(nextId);
              setData(null);
              setBusy(true);
              setError("");
              router.replace(
                nextId ? `/cost-optimization?analysis_id=${encodeURIComponent(nextId)}` : "/cost-optimization",
                { scroll: false },
              );
            }}
          >
            <option value="">Select a saved analysis</option>
            {reports.map((row) => {
              const id = String(row.id || "").trim();
              return id ? <option key={id} value={id}>{analysisLabel(row)}</option> : null;
            })}
          </select>
        </div>
        <div className="cv-field" style={{ minWidth: 145 }}>
          <label htmlFor="cost-build-quantity">Build quantity</label>
          <input id="cost-build-quantity" type="number" min={1} max={10000000} value={qty} onChange={(event) => setQty(Math.max(1, Number(event.target.value) || 1))} />
        </div>
        <div className="cv-field" style={{ minWidth: 145 }}>
          <label htmlFor="cost-target">Target cost per unit (optional)</label>
          <input id="cost-target" type="number" min="0.0001" step="0.0001" value={targetCost} onChange={(event) => setTargetCost(event.target.value)} placeholder="e.g. 42.00" />
        </div>
        <button type="button" className="cv-button primary" disabled={busy || !selectedAnalysisId} onClick={() => load(qty, selectedAnalysisId)}>
          {busy ? "Calculating…" : "Recalculate"}
        </button>
        {!busy && data ? (
          <button
            type="button"
            className="cv-button"
            disabled={!calculationMatchesInputs}
            onClick={() => downloadCostPlan(opt, data, qty)}
          >
            Export cost plan
          </button>
        ) : null}
      </div>

      {busy ? <LoadingCard label="Calculating BOM cost and savings from saved price evidence…" /> : null}
      {data && !calculationMatchesInputs ? (
        <div className="cv-notice" role="status" style={{ marginBottom: 14 }}>
          Inputs changed. The displayed totals still reflect the last calculation. Recalculate before exporting or creating a sourcing decision.
        </div>
      ) : null}
      {error ? <div className="cv-error" role="alert">Cost Optimization could not load. {error}</div> : null}
      {!busy && !reports.length ? (
        <EmptyState icon="cost" title="Analyze a BOM to start" body="Cost Optimization uses a saved analysis. Run a BOM analysis first, then return here to see its priced subtotal, coverage, and sourcing opportunities." action={<PrimaryLink href="/bom-analyzer">Start BOM analysis</PrimaryLink>} />
      ) : null}
      {!busy && reports.length > 0 && !data && !error ? (
        <EmptyState icon="cost" title="Select a saved analysis" body="Choose the BOM report to model. Cost results are scoped to that saved analysis." />
      ) : null}
      {!busy && data ? (
        <>
          <section className="cv-grid cv-grid--3" style={{ marginBottom: 14 }}>
            <article className="cv-card pad">
              <div className="cv-small-note">{partial ? "Priced subtotal per build unit" : "BOM cost per build unit"}</div>
              <h2 style={{ margin: "8px 0" }}>{currencies.length > 1 ? "Multiple currencies" : formatMoney(subtotalPerBoard, currency)}</h2>
              <div className="cv-small-note">{pricedCount} of {componentCount} component lines priced{partial ? " · incomplete subtotal" : " · full coverage"}</div>
            </article>
            <article className="cv-card pad">
              <div className="cv-small-note">{partial ? "Priced subtotal for this build" : "Total BOM cost at this build quantity"}</div>
              <h2 style={{ margin: "8px 0" }}>{currencies.length > 1 ? "Multiple currencies" : formatMoney(runSubtotal, currency)}</h2>
              <div className="cv-small-note">Build quantity: {Number(opt.build_quantity || qty).toLocaleString()} · Coverage: {coverage}%</div>
            </article>
            <article className="cv-card pad">
              <div className="cv-small-note">Target cost check</div>
              <h2 style={{ margin: "8px 0" }}>
                {targetCost
                  ? currencies.length > 1
                    ? "Cannot compare currencies"
                    : targetGap === null || targetGap === undefined
                      ? "Needs full price coverage"
                      : Number(targetGap) > 0
                      ? `${formatMoney(targetGap, currency)} over target`
                      : `${formatMoney(Math.abs(Number(targetGap)), currency)} under target`
                  : "Add a target"}
              </h2>
              <div className="cv-small-note">
                {targetCost ? currencies.length > 1 ? "Choose one currency before comparing a mixed-currency BOM." : `Target: ${formatMoney(Number(targetCost), currency)} per build unit` : "Optional comparison against your target unit cost."}
              </div>
            </article>
          </section>

          {currencies.length > 1 ? (
            <p className="cv-small-note" role="status">
              Prices use different currencies and are not converted. Priced subtotals: {Object.entries((opt.priced_subtotals_at_build_quantity || {}) as Record<string, unknown>).map(([code, amount]) => `${code} ${formatNumber(amount)}`).join(" · ")}.
            </p>
          ) : null}
          <p className="cv-small-note" style={{ margin: "10px 0 18px" }}>
            Saved supplier prices are point-in-time indications, not live quotes or guarantees. Each opportunity uses exact-part, authorized-source evidence at the displayed order quantity; confirm price, availability, freight, tax, and minimum order quantity with the supplier.
          </p>

          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <div className="cv-section-heading cv-section-heading--card">
              <div>
                <h2>Savings opportunities</h2>
                <p>Ranked by estimated net savings for this build quantity. Price-break savings subtract the cost of any extra units required to reach the break.</p>
              </div>
              <span className="cv-data-note">{opportunities.length} opportunities</span>
            </div>
            {opportunities.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead>
                    <tr>
                      <th>Part and opportunity</th>
                      <th>Current → suggested source</th>
                      <th className="cv-num">Required / buy qty</th>
                      <th className="cv-num">Price per unit</th>
                      <th className="cv-num">Net savings</th>
                      <th>Risk review</th>
                      <th>Evidence</th>
                      <th>Next step</th>
                    </tr>
                  </thead>
                  <tbody>
                    {opportunities.slice(0, 30).map((row, index) => {
                      const mpn = String(row["Part Number"] || "");
                      const nextSource = String(row.Supplier || "");
                      const extraQty = Number(row["Extra Quantity"] || 0);
                      return (
                        <tr key={`${mpn}-${String(row.Category)}-${index}`}>
                          <td><strong>{mpn}</strong><div className="cv-small-note">{cleanUserText(String(row.Category || "Savings opportunity"))}</div></td>
                          <td>{cleanUserText(String(row["Current Supplier"] || "Current supplier"))} → {cleanUserText(nextSource)}</td>
                          <td className="cv-num">{Number(row["Required Order Quantity"] || 0).toLocaleString()} / {Number(row["Recommended Purchase Quantity"] || row["Required Order Quantity"] || 0).toLocaleString()}{extraQty ? <div className="cv-small-note">includes {extraQty.toLocaleString()} extra</div> : null}</td>
                          <td className="cv-num">{formatMoney(row["Current Unit Price"], row.Currency, 4)} → {formatMoney(row["Estimated Target Price"], row.Currency, 4)}</td>
                          <td className="cv-num"><strong>{formatMoney(row["Estimated Run Savings"], row.Currency)}</strong></td>
                          <td className="cv-cell-wrap">
                            <strong>{cleanUserText(String(row["Risk Label"] || "Needs evidence"))}</strong>
                            <div className="cv-small-note">{cleanUserText(String(row["Risk Context"] || "Check lifecycle, stock, and supplier coverage."))}</div>
                          </td>
                          <td className="cv-cell-wrap">
                            <strong>{cleanUserText(String(row["Risk Label"] || "Needs evidence"))}</strong>
                            <div className="cv-small-note">{cleanUserText(String(row["Risk Context"] || "Check lifecycle, stock, and supplier coverage."))}</div>
                          </td>
                          <td className="cv-cell-wrap">
                            <div>{evidenceSourceLabel("authorized supplier snapshot", "Saved supplier snapshot")}</div>
                            <div className="cv-small-note">Current {formatDate(row["Current Price Retrieved At"])} · suggested {formatDate(row["Target Price Retrieved At"])}</div>
                          </td>
                          <td>
                            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 7 }}>
                              <PrimaryLink href={procurementFor(mpn)}>Review quote</PrimaryLink>
                              <button
                                className="cv-button"
                                type="button"
                                disabled={!calculationMatchesInputs}
                                onClick={() => {
                                  setDecisionOpportunity(row);
                                  setDecisionError("");
                                  setDecisionMessage("");
                                }}
                              >
                                Create decision
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                icon="cost"
                title="No verified savings opportunity"
                body={pricedCount ? "No lower current authorized supplier price or net-positive saved price break was verified for this BOM at the entered volume. We do not infer savings from an unverified alternate." : "Add supplier pricing to the saved BOM before estimating savings."}
                action={<PrimaryLink href={activeAnalysisId ? procurementFor("") : "/procurement"}>Add or refresh quotes</PrimaryLink>}
              />
            )}
            {pricedCount === 0 && componentCount > 0 ? (
              <div className="cv-card pad" style={{ marginTop: 12, background: "#f8fbff", borderStyle: "dashed" }} aria-label="Illustrative cost example">
                <div className="cv-section-heading cv-section-heading--card">
                  <div>
                    <div className="cv-data-note" style={{ marginBottom: 5 }}>ILLUSTRATIVE EXAMPLE · NOT FROM THIS BOM</div>
                    <h3 style={{ margin: 0 }}>What a priced BOM result looks like</h3>
                    <p>Your selected analysis has no verified saved prices, so its actual total and savings cannot be calculated yet.</p>
                  </div>
                  <span className="cv-data-note">Example</span>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(155px, 1fr))", gap: 10, marginTop: 12 }}>
                  <div style={{ border: "1px solid #dce6f3", borderRadius: 10, padding: 12, background: "#fff" }}>
                    <div className="cv-small-note">Example BOM total</div><strong>$41,200</strong><div className="cv-small-note">1,000 units · $41.20 per unit</div>
                  </div>
                  <div style={{ border: "1px solid #dce6f3", borderRadius: 10, padding: 12, background: "#fff" }}>
                    <div className="cv-small-note">Example price coverage</div><strong>9 of 10 parts</strong><div className="cv-small-note">One line still needs a quote</div>
                  </div>
                  <div style={{ border: "1px solid #dce6f3", borderRadius: 10, padding: 12, background: "#fff" }}>
                    <div className="cv-small-note">Example net savings</div><strong>$380</strong><div className="cv-small-note">Price break, including extra units</div>
                  </div>
                </div>
                <p className="cv-small-note" style={{ margin: "11px 0 0" }}>These sample figures demonstrate the calculation only; they are not prices, savings, or supplier evidence for your selected BOM.</p>
              </div>
            ) : null}
          </section>

          {decisionOpportunity ? (
            <section className="cv-card pad" style={{ marginBottom: 14 }} aria-labelledby="cost-decision-title">
              <div className="cv-section-heading cv-section-heading--card">
                <div>
                  <h2 id="cost-decision-title">Record a sourcing decision</h2>
                  <p>
                    {String(decisionOpportunity["Part Number"] || "")}: {String(decisionOpportunity["Current Supplier"] || "")} → {String(decisionOpportunity.Supplier || "")}.
                    The quote is saved as pending review; this does not approve a purchase.
                  </p>
                </div>
                <button type="button" className="cv-button" onClick={() => setDecisionOpportunity(null)}>Cancel</button>
              </div>
              <form onSubmit={submitDecision} style={{ display: "grid", gap: 12, maxWidth: 760 }}>
                <div className="cv-field">
                  <label htmlFor="cost-decision-reviewer">Reviewer</label>
                  <input id="cost-decision-reviewer" maxLength={120} required value={decisionReviewer} onChange={(event) => setDecisionReviewer(event.target.value)} />
                </div>
                <div className="cv-field">
                  <label htmlFor="cost-decision-rationale">Rationale</label>
                  <textarea id="cost-decision-rationale" maxLength={3000} rows={4} required value={decisionRationale} onChange={(event) => setDecisionRationale(event.target.value)} placeholder="Explain why this price break or sourcing option should be considered." />
                </div>
                {decisionError ? <div className="cv-error" role="alert">{decisionError}</div> : null}
                <div>
                  <button className="cv-button primary" type="submit" disabled={decisionBusy || !calculationMatchesInputs || !decisionReviewer.trim() || !decisionRationale.trim()}>
                    {decisionBusy ? "Saving…" : "Save pending decision"}
                  </button>
                </div>
              </form>
            </section>
          ) : null}
          {decisionMessage ? <p className="cv-success" role="status">{decisionMessage}</p> : null}

          <section className="cv-card pad" style={{ marginBottom: 14 }}>
            <div className="cv-section-heading cv-section-heading--card">
              <div><h2>Largest cost drivers</h2><p>Top five parts by extended spend at the selected build quantity.</p></div>
              <span className="cv-data-note">{currencies.length > 1 ? "Top five per currency; no conversion" : "Top five"}</span>
            </div>
            {drivers.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead><tr><th>Part</th><th>Manufacturer</th><th className="cv-num">Qty per build unit</th><th className="cv-num">Unit price</th><th>Source / date</th><th className="cv-num">Extended cost</th></tr></thead>
                  <tbody>
                    {drivers.map((row, index) => (
                      <tr key={`${String(row["Part Number"])}-${String(row.Currency)}-${index}`}>
                        <td><strong>{String(row["Part Number"] || "")}</strong></td>
                        <td>{cleanUserText(String(row.Manufacturer || "Not recorded"))}</td>
                        <td className="cv-num">{Number(row["Quantity per Build"] || 0).toLocaleString()}</td>
                        <td className="cv-num">{formatMoney(row["Unit Price"], row.Currency, 4)}</td>
                        <td>{cleanUserText(String(row["Price Source"] || "Not verified"))}<div className="cv-small-note">{formatDate(row["Price Retrieved At"])}</div></td>
                        <td className="cv-num"><strong>{formatMoney(row["Extended Cost at Build Quantity"], row.Currency)}</strong></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="cv-small-note">No verified prices are available to rank cost drivers.</p>}
          </section>

          <section className="cv-card pad">
            <div className="cv-section-heading cv-section-heading--card">
              <div><h2>Parts missing verified prices</h2><p>Each link opens Procurement Advisor with the BOM and part preselected.</p></div>
              <span className="cv-data-note">{missingRows.length} missing</span>
            </div>
            {missingRows.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead><tr><th>Part</th><th>Manufacturer</th><th className="cv-num">Qty per build unit</th><th>Recorded state</th><th>Action</th></tr></thead>
                  <tbody>
                    {missingRows.map((row, index) => (
                      <tr key={`${String(row["Part Number"])}-${index}`}>
                        <td><strong>{String(row["Part Number"] || "")}</strong></td>
                        <td>{cleanUserText(String(row.Manufacturer || "Not recorded"))}</td>
                        <td className="cv-num">{Number(row["Quantity per Build"] || 0).toLocaleString()}</td>
                        <td>Needs current, exact-part price evidence</td>
                        <td><PrimaryLink href={procurementFor(row["Part Number"])}>Add quote</PrimaryLink></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="cv-small-note">Every BOM component line has a verified saved supplier price.</p>}
          </section>
          <section className="cv-card pad" style={{ marginTop: 14 }} data-testid="cost-decisions">
            <div className="cv-section-heading cv-section-heading--card">
              <div><h2>Saved sourcing decisions</h2><p>Decisions preserve the reviewer and price evidence snapshot used when the option was recorded.</p></div>
              <span className="cv-data-note">{decisions.length} saved</span>
            </div>
            {decisions.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead><tr><th>Saved</th><th>Part / option</th><th>Supplier choice</th><th>Estimated savings</th><th>Status</th><th>Reviewer / rationale</th></tr></thead>
                  <tbody>
                    {decisions.map((decision) => (
                      <tr key={decision.id}>
                        <td>{formatDate(decision.created_at)}</td>
                        <td><strong>{cleanUserText(decision.part_number || "Part")}</strong><div className="cv-small-note">{cleanUserText(decision.title || "")}</div></td>
                        <td>{cleanUserText(decision.current_supplier || "Current")} → {cleanUserText(decision.recommended_supplier || "Suggested")}</td>
                        <td>{formatMoney(decision.estimated_net_savings, decision.currency)}</td>
                        <td>{cleanUserText(decision.status || "Pending review")}</td>
                        <td>{cleanUserText(decision.reviewer || "Reviewer")}<div className="cv-small-note">{cleanUserText(decision.rationale || "")}</div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="cv-small-note">No sourcing decisions have been recorded for this BOM.</p>}
          </section>
        </>
      ) : null}
    </Shell>
  );
}

export default function CostOptimizationPage() {
  return (
    <Suspense fallback={<div className="cv-page-loading">Loading Cost Optimization…</div>}>
      <CostOptimizationInner />
    </Suspense>
  );
}
