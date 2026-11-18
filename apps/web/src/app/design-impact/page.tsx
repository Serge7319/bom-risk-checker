"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { RiskLevelBadge } from "@/components/RiskLevelBadge";
import { fetchDesignImpact } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

function cell(value: unknown, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) {
    const joined = value.map((item) => String(item || "").trim()).filter(Boolean).join(", ");
    return joined || fallback;
  }
  return String(value);
}

function partNumber(row: Record<string, unknown>) {
  return cell(row["Part Number"] || row.mpn, "");
}

function reportId(row: Record<string, unknown>) {
  const direct = String(row["Analysis ID"] || row.analysis_id || "").trim();
  if (direct) return direct;
  const ids = row["Analysis IDs"];
  if (Array.isArray(ids)) {
    const first = String(ids[0] || "").trim();
    if (first) return first;
  }
  return "";
}

export default function DesignImpactPage() {
  const session = useRequireSession();
  const [mpn, setMpn] = useState("");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [choice, setChoice] = useState<"suggested" | "selected">("suggested");
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);

  function load(selected = mpn, mode: "suggested" | "selected" = selected.trim() ? "selected" : "suggested") {
    if (!session) return;
    setChoice(mode);
    setBusy(true);
    setError("");
    // Aggregate across every saved BOM in the workspace. Passing the last
    // analysis_id silently collapsed same-MPN usage to a single report.
    fetchDesignImpact(session.access_token, {
      mpn: selected,
    })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    load("", "suggested");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  const intel = (data?.intelligence || {}) as Record<string, unknown>;
  const catalog = useMemo(
    () => (intel.component_catalog || intel.catalog || []) as Array<Record<string, unknown>>,
    [intel.component_catalog, intel.catalog],
  );
  const selectedMpn = String(intel.selected_mpn || "");
  const filteredCatalog = useMemo(() => {
    const query = catalogQuery.trim().toLowerCase();
    if (!query) return catalog;
    return catalog.filter((row) => {
      const manufacturer = cell(
        row.Manufacturer
          || row.manufacturer
          || (Array.isArray(row["Manufacturer Values"]) ? row["Manufacturer Values"][0] : ""),
        "",
      );
      return `${partNumber(row)} ${manufacturer}`.toLowerCase().includes(query);
    });
  }, [catalog, catalogQuery]);
  const selected =
    catalog.find(
      (row) => partNumber(row).toLowerCase() === selectedMpn.toLowerCase(),
    ) || {};
  const affected = (intel.affected_projects || []) as Array<Record<string, unknown>>;
  const activeLabel = choice === "selected" ? "Selected part" : "Suggested part";
  const compareHref = selectedMpn
    ? `/compare-parts?part_a=${encodeURIComponent(selectedMpn)}`
    : "/compare-parts";

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.design}
        actions={
          selectedMpn ? (
            <SecondaryLink href={compareHref}>Compare parts</SecondaryLink>
          ) : (
            <PrimaryLink href="/bom-analyzer">Analyze a BOM</PrimaryLink>
          )
        }
      />
      <section className="cv-card pad cv-impact-intro">
        <p>
          This page traces a part that already appears in saved BOMs and shows the recorded exposure.
          It does not simulate a proposed design change, predict replacement fit, approve a replacement, or modify a BOM.
        </p>
        <ol className="cv-impact-steps">
          <li>Find or select a part in the catalog, or type an MPN and refresh.</li>
          <li>Review the affected BOM rows and quantities for that part.</li>
          <li>Open a saved report or compare the part as a baseline. Neither action changes the BOM.</li>
        </ol>
      </section>
      {<EvidenceNotice gap={data?.gap} />}
      <div className="cv-card pad" style={{ marginBottom: 14 }}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="mpn">MPN to trace</label>
            <input
              id="mpn"
              value={mpn}
              onChange={(e) => setMpn(e.target.value)}
              placeholder="Type an MPN from a saved BOM"
            />
          </div>
          <div style={{ display: "flex", alignItems: "end" }}>
            <button
              type="button"
              className="cv-button primary"
              onClick={() => load(mpn)}
              disabled={busy}
            >
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
                <p className="cv-card-subtitle">{catalog.length} parts from saved analyses</p>
                <div className="cv-field" style={{ marginTop: 12 }}>
                  <label htmlFor="catalog-filter">Find an MPN</label>
                  <input
                    id="catalog-filter"
                    value={catalogQuery}
                    onChange={(event) => setCatalogQuery(event.target.value)}
                    placeholder="Filter by MPN or manufacturer"
                    aria-label="Filter catalog by MPN or manufacturer"
                  />
                </div>
                {filteredCatalog.length ? (
                  <div className="cv-table-wrap cv-table-wrap--fit" style={{ marginTop: 12 }}>
                    <table className="cv-table cv-table--fit cv-table--mpn-safe">
                      <thead>
                        <tr>
                          <th>Part</th>
                          <th>Manufacturer</th>
                          <th>Lifecycle</th>
                          <th>Risk</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredCatalog.map((row, i) => {
                          const mpnLabel = partNumber(row) || "Part number not recorded";
                          const active = mpnLabel.toLowerCase() === selectedMpn.toLowerCase();
                          return (
                            <tr
                              key={`${mpnLabel}-${i}`}
                              className={active ? "is-active" : undefined}
                              aria-selected={active}
                            >
                              <td data-label="Part" className="cv-mpn-cell">
                                <button
                                  type="button"
                                  className="cv-impact-select"
                                  aria-pressed={active}
                                  onClick={() => {
                                    setMpn(mpnLabel);
                                    load(mpnLabel, "selected");
                                  }}
                                >
                                  {mpnLabel}
                                </button>
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
                              <td data-label="Risk">
                                <RiskLevelBadge value={row["Risk Level"] || row.risk_level} />
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState
                    icon="impact"
                    title="No catalog parts match this search"
                    body="Try another MPN or manufacturer, or type the MPN above and refresh impact."
                  />
                )}
              </section>
              <section className="cv-card pad" aria-live="polite">
                <h3 className="cv-card-title">{activeLabel}</h3>
                <p className="cv-card-subtitle">
                  {selectedMpn
                    ? selectedMpn
                    : "No part is active yet."}
                </p>
                <p className="cv-small-note">
                  {choice === "selected"
                    ? "You chose this part. The rows below are recorded uses in saved BOMs."
                    : "Shown from saved evidence until you choose a part. This is not a selection you made."}
                </p>
                <dl className="cv-record-meta" style={{ marginTop: 12, gridTemplateColumns: "1fr 1fr" }}>
                  <div className="cv-record-field"><dt>Lifecycle</dt><dd>{cell(selected.Lifecycle || selected.lifecycle)}</dd></div>
                  <div className="cv-record-field"><dt>Risk</dt><dd>{selectedMpn ? <RiskLevelBadge value={selected["Risk Level"] || selected.risk_level} /> : "—"}</dd></div>
                  <div className="cv-record-field"><dt>Manufacturer</dt><dd>{cell(selected.Manufacturer || selected.manufacturer)}</dd></div>
                  <div className="cv-record-field"><dt>Package</dt><dd>{cell(selected.Package || selected.package)}</dd></div>
                  <div className="cv-record-field">
                    <dt>Qty across BOMs</dt>
                    <dd>{cell(intel.total_quantity)}</dd>
                  </div>
                  <div className="cv-record-field">
                    <dt>Saved BOMs</dt>
                    <dd>{cell(intel.affected_bom_count || affected.length)}</dd>
                  </div>
                </dl>
                {selectedMpn ? (
                  <div className="cv-impact-actions">
                    <SecondaryLink href={compareHref}>Compare parts</SecondaryLink>
                    <a className="cv-button" href="#affected-bom-rows">Review affected BOM rows</a>
                  </div>
                ) : null}
              </section>
            </div>
            <section className="cv-card pad cv-card--table" id="affected-bom-rows">
              <h3 className="cv-card-title">Affected BOM rows</h3>
              <p className="cv-card-subtitle">
                {affected.length
                  ? `${affected.length} saved BOM row${affected.length === 1 ? "" : "s"} for ${cell(selectedMpn, "the active part")} · combined quantity ${cell(intel.total_quantity, "—")}`
                  : "No affected BOM rows were returned for the active part."}
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
                        <th>Next</th>
                      </tr>
                    </thead>
                    <tbody>
                      {affected.map((row, i) => {
                        const savedReportId = reportId(row);
                        return (
                          <tr key={`${cell(row.BOM || row.Project, "bom")}-${i}`}>
                            <td data-label="Project">{cell(row.Project || row.project)}</td>
                            <td data-label="BOM">{cell(row.BOM || row.Bom || (Array.isArray(row["BOM Names"]) ? row["BOM Names"].join(", ") : ""))}</td>
                            <td data-label="Part" className="cv-mpn-cell">
                              <strong>{cell(row["Part Number"] || row.mpn || selectedMpn)}</strong>
                            </td>
                            <td className="cv-num" data-label="Qty">{cell(row.Quantity || row.quantity)}</td>
                            <td data-label="Manufacturer">{cell(row.Manufacturer || row.manufacturer)}</td>
                            <td data-label="Lifecycle">{cell(row.Lifecycle || row.lifecycle)}</td>
                            <td data-label="Risk">
                              <RiskLevelBadge value={row["Risk Level"] || row.risk_level} />
                            </td>
                            <td data-label="Next" className="cv-impact-row-actions">
                              {savedReportId ? (
                                <Link href={`/reports/${encodeURIComponent(savedReportId)}`}>Open saved report</Link>
                              ) : (
                                <span>No saved report link</span>
                              )}
                              {selectedMpn ? (
                                <Link href={compareHref}>Compare parts</Link>
                              ) : null}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState
                  icon="impact"
                  title="No affected BOM rows"
                  body="Choose a part that appears in a saved analysis, or analyze a BOM that includes this MPN."
                  action={<PrimaryLink href="/bom-analyzer">Analyze a BOM</PrimaryLink>}
                />
              )}
            </section>
          </div>
        ) : (
          <EmptyState
            icon="impact"
            title="No saved BOM components to trace"
            body="Design impact uses saved BOM analyses to find where a part is already used. It does not simulate a design change. Analyze a BOM to start a trace."
            action={<PrimaryLink href="/bom-analyzer">Analyze a BOM</PrimaryLink>}
          />
        )
      ) : null}
    </Shell>
  );
}
