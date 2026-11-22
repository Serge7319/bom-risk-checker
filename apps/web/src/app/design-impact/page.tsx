"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader } from "@/components/PageHeader";
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
  return String(row["Part Number"] || row.mpn || "").trim();
}

function isUsablePart(row: Record<string, unknown>) {
  const value = partNumber(row);
  return Boolean(
    value &&
      !["unknown", "not recorded", "n/a", "—", "-"].includes(value.toLowerCase()) &&
      !/^(?:boardtext|gr_text|fp_text|text)\s*\(/i.test(value),
  );
}

function formatAnalysisDate(value: unknown) {
  const raw = String(value || "").trim();
  if (!raw) return "Not recorded";
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(parsed);
}

export default function DesignImpactPage() {
  const session = useRequireSession();
  const [mpn, setMpn] = useState("");
  const [suggestedMpn, setSuggestedMpn] = useState("");
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(true);
  const [showImpact, setShowImpact] = useState(false);

  function load(selected = mpn, reveal = true) {
    if (!session) return;
    const requested = String(selected || "").trim();
    setBusy(true);
    setError("");
    setNotice("");
    setShowImpact(false);

    fetchDesignImpact(session.access_token, { mpn: requested })
      .then((payload) => {
        const nextIntel = (payload.intelligence || {}) as Record<string, unknown>;
        const rawCatalog = (nextIntel.component_catalog || nextIntel.catalog || []) as Array<Record<string, unknown>>;
        const selectable = Array.isArray(rawCatalog) ? rawCatalog.filter(isUsablePart) : [];
        const resolvedMpn = String(nextIntel.selected_mpn || "").trim();
        const inCatalog = (value: string) =>
          selectable.some((row) => partNumber(row).toLowerCase() === value.toLowerCase());
        const fallbackMpn = partNumber(selectable[0] || {});

        setData(payload);

        if (!requested) {
          const suggested = inCatalog(resolvedMpn) ? resolvedMpn : fallbackMpn;
          setMpn(suggested);
          setSuggestedMpn(suggested);
          if (resolvedMpn && !inCatalog(resolvedMpn)) {
            setNotice("A non-component board annotation was excluded. Choose a saved component to review.");
          }
          setShowImpact(false);
          return;
        }

        if (!inCatalog(requested) || !inCatalog(resolvedMpn)) {
          setMpn(fallbackMpn);
          setSuggestedMpn("");
          setNotice("That part number was not found in the saved BOM components. Choose a part from the list.");
          setShowImpact(false);
          return;
        }

        setMpn(resolvedMpn);
        setShowImpact(reveal);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"))
      .finally(() => setBusy(false));
  }

  useEffect(() => {
    const requestedMpn = new URLSearchParams(window.location.search).get("mpn")?.trim() || "";
    setMpn(requestedMpn);
    load(requestedMpn, Boolean(requestedMpn));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  if (!session) return null;

  const intelligence = (data?.intelligence || {}) as Record<string, unknown>;
  const rawCatalog = (intelligence.component_catalog || intelligence.catalog || []) as Array<Record<string, unknown>>;
  const catalog = Array.isArray(rawCatalog) ? rawCatalog.filter(isUsablePart) : [];
  const selectedMpn = String(intelligence.selected_mpn || "").trim();
  const selected =
    catalog.find((row) => partNumber(row).toLowerCase() === selectedMpn.toLowerCase()) || {};
  const affected = (intelligence.affected_projects || []) as Array<Record<string, unknown>>;
  const affectedBomCount = Number(intelligence.affected_bom_count ?? affected.length);
  const projectCount = Number(intelligence.project_count ?? 0);
  const impactLevel = cell(intelligence.impact_level, "Not assessed");
  const impactDrivers = Array.isArray(intelligence.impact_score_drivers)
    ? (intelligence.impact_score_drivers as Array<Record<string, unknown>>)
    : [];
  const selectedLifecycle = cell(
    selected.Lifecycle || selected.lifecycle || selected["Lifecycle Values"],
    "Not recorded",
  );
  const selectedRisk = cell(
    selected["Risk Level"] || selected.risk_level || selected["Risk Level Values"],
    "Not recorded",
  );
  const selectedManufacturer = cell(
    selected.Manufacturer || selected.manufacturer || selected["Manufacturer Values"],
    "Not recorded",
  );
  const selectedPackage = cell(selected.Package || selected.package, "Not recorded");
  const replacementParams = new URLSearchParams({ mpn: selectedMpn });
  if (selectedManufacturer !== "Not recorded" && selectedManufacturer !== "Unknown") {
    replacementParams.set("manufacturer", selectedManufacturer);
  }
  if (affected[0]?.["Analysis ID"]) {
    replacementParams.set("analysis_id", String(affected[0]["Analysis ID"]));
  }
  const replacementHref = "/find-replacement?" + replacementParams.toString();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const requested = mpn.trim();
    if (!requested) {
      setError("Choose a component from your saved BOM analyses.");
      return;
    }
    if (!catalog.some((row) => partNumber(row).toLowerCase() === requested.toLowerCase())) {
      setError("Choose a component from the saved part suggestions.");
      return;
    }
    load(requested, true);
  }

  return (
    <Shell session={session}>
      <PageHeader
        meta={{
          ...PAGE_META.design,
          title: "Where is this part used?",
          eyebrow: "Component impact",
          description:
            "Find the saved BOMs that include a part, then review which designs may need attention if it changes.",
        }}
      />
      <EvidenceNotice gap={data?.gap} />

      {catalog.length ? (
        <section className="cv-card pad" aria-labelledby="component-picker-title">
          <div className="cv-section-heading" style={{ margin: "0 0 12px" }}>
            <div>
              <div className="cv-eyebrow">Step 1</div>
              <h2 id="component-picker-title" className="cv-card-title">Choose a component</h2>
              <p className="cv-card-subtitle">
                Search {catalog.length} parts found in saved BOM analyses.
              </p>
            </div>
          </div>

          <form onSubmit={onSubmit}>
            <div className="cv-form-grid">
              <div className="cv-field">
                <label htmlFor="mpn">Part number</label>
                <input
                  id="mpn"
                  list="saved-component-options"
                  value={mpn}
                  onChange={(event) => {
                    setMpn(event.target.value);
                    setError("");
                    setNotice("");
                    setShowImpact(false);
                  }}
                  placeholder="Type an MPN or choose a saved part"
                  autoComplete="off"
                  aria-describedby="impact-data-note"
                />
                <datalist id="saved-component-options">
                  {catalog.map((row, index) => (
                    <option key={index} value={partNumber(row)}>
                      {cell(row.Manufacturer || row.manufacturer || row["Manufacturer Values"], "Manufacturer not recorded")}
                    </option>
                  ))}
                </datalist>
              </div>
              <div style={{ display: "flex", alignItems: "end" }}>
                <button type="submit" className="cv-button primary" disabled={busy || !mpn.trim()}>
                  {busy
                    ? "Loading…"
                    : showImpact && mpn.toLowerCase() === selectedMpn.toLowerCase()
                      ? "Refresh impact"
                      : "View impact"}
                </button>
              </div>
            </div>
          </form>

          {suggestedMpn && mpn.toLowerCase() === suggestedMpn.toLowerCase() ? (
            <p className="cv-small-note" style={{ marginTop: 12 }}>
              Suggested starting point: <strong>{suggestedMpn}</strong>. Cadivor prioritizes saved parts with recorded risk, lifecycle, or sourcing signals. You can choose any part in the list.
            </p>
          ) : null}
          {notice ? <p className="cv-small-note" role="status" style={{ marginTop: 12 }}>{notice}</p> : null}
          {error ? <div className="cv-error" role="alert" style={{ marginTop: 12 }}>{error}</div> : null}

          <p id="impact-data-note" className="cv-small-note" style={{ marginTop: 12, marginBottom: 0 }}>
            This view reads saved BOM analyses when you open the page and when you select View impact. It does not monitor supplier changes, refresh live stock or pricing, or edit a BOM. For supplier updates, use{" "}
            <Link href="/monitoring" style={{ color: "var(--blue)", textDecoration: "underline" }}>Monitoring</Link>.
          </p>
        </section>
      ) : null}

      {busy ? <LoadingCard label="Checking saved BOM analyses…" /> : null}

      {error && !catalog.length ? (
        <div className="cv-error" role="alert">
          The component impact view could not load. {error}
          <button type="button" className="cv-button" style={{ marginLeft: 10 }} onClick={() => load(mpn, false)}>
            Try again
          </button>
        </div>
      ) : null}

      {!busy && data && !catalog.length ? (
        <EmptyState
          icon="impact"
          title="No saved BOM components to review"
          body="Analyze and save a BOM first. Cadivor will then list its components here so you can see where they are used."
          action={<Link className="cv-button primary" href="/bom-analyzer">Analyze a BOM</Link>}
        />
      ) : null}

      {!busy && data && !showImpact ? (
        <section className="cv-card pad" style={{ marginTop: 14 }} aria-live="polite">
          <h2 className="cv-card-title">Step 2 · Review where it is used</h2>
          <p className="cv-card-subtitle" style={{ marginTop: 8 }}>
            Choose a part above and select <strong>View impact</strong>. Cadivor will show the saved BOMs that contain it and the recorded risk and lifecycle signals. You decide whether those designs need review.
          </p>
        </section>
      ) : null}

      {!busy && data && showImpact && selectedMpn ? (
        <>
          <section className="cv-card pad" style={{ marginTop: 14 }} aria-labelledby="impact-summary-title">
            <div className="cv-section-heading" style={{ marginTop: 0 }}>
              <div>
                <div className="cv-eyebrow">Step 2 · Review impact</div>
                <h2 id="impact-summary-title" className="cv-card-title">
                  {selectedMpn}
                  {selectedManufacturer !== "Not recorded" ? " · " + selectedManufacturer : ""}
                </h2>
                <p className="cv-card-subtitle">
                  A workspace-level view of saved BOMs that include this component.
                </p>
              </div>
            </div>

            <dl className="cv-record-meta" style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
              <div className="cv-record-field"><dt>Saved BOMs affected</dt><dd>{affectedBomCount}</dd></div>
              <div className="cv-record-field"><dt>Projects affected</dt><dd>{projectCount || "—"}</dd></div>
              <div className="cv-record-field"><dt>Quantity in saved BOMs</dt><dd>{cell(intelligence.total_quantity)}</dd></div>
              <div className="cv-record-field"><dt>Impact indicator</dt><dd>{impactLevel}</dd></div>
              <div className="cv-record-field"><dt>Recorded lifecycle</dt><dd>{selectedLifecycle}</dd></div>
              <div className="cv-record-field"><dt>Recorded risk</dt><dd>{selectedRisk}</dd></div>
              <div className="cv-record-field"><dt>Manufacturer</dt><dd>{selectedManufacturer}</dd></div>
              <div className="cv-record-field"><dt>Package</dt><dd>{selectedPackage}</dd></div>
            </dl>

            <p className="cv-small-note" style={{ marginBottom: 0 }}>
              The impact indicator is a triage signal from saved evidence, not an engineering approval or replacement-fit result. Review the source BOM reports before making a design decision.
            </p>

            {impactDrivers.length ? (
              <details style={{ marginTop: 12 }}>
                <summary style={{ cursor: "pointer", color: "var(--blue)", fontSize: 12, fontWeight: 700 }}>
                  Why is the impact indicator {impactLevel.toLowerCase()}?
                </summary>
                <ul className="cv-missing-list">
                  {impactDrivers.map((driver, index) => (
                    <li key={index}>
                      <strong>{cell(driver.label)}:</strong> {cell(driver.detail)}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </section>

          <section className="cv-card pad cv-card--table" style={{ marginTop: 14 }} aria-labelledby="affected-boms-title">
            <div className="cv-section-heading" style={{ marginTop: 0 }}>
              <div>
                <div className="cv-eyebrow">Step 3 · Open a report to review</div>
                <h2 id="affected-boms-title" className="cv-card-title">
                  Saved BOMs containing {selectedMpn}
                </h2>
                <p className="cv-card-subtitle">
                  {affected.length
                    ? affected.length + " saved BOM report" + (affected.length === 1 ? "" : "s") +
                      " across " + projectCount + " project" + (projectCount === 1 ? "" : "s") +
                      " · quantity " + cell(intelligence.total_quantity, "not recorded")
                    : "No matching BOM rows were returned for this component."}
                </p>
              </div>
            </div>

            {affected.length ? (
              <div className="cv-table-wrap cv-table-wrap--fit" style={{ marginTop: 12 }}>
                <table className="cv-table cv-table--fit cv-table--mpn-safe">
                  <thead>
                    <tr>
                      <th>Project</th>
                      <th>BOM</th>
                      <th className="cv-num">Quantity</th>
                      <th>Recorded lifecycle</th>
                      <th>Recorded risk</th>
                      <th>Analysis updated</th>
                      <th>Report</th>
                    </tr>
                  </thead>
                  <tbody>
                    {affected.map((row, index) => {
                      const analysisId = String(row["Analysis ID"] || "");
                      return (
                        <tr key={analysisId || index}>
                          <td data-label="Project">{cell(row.Project || row.project, "Project not recorded")}</td>
                          <td data-label="BOM">{cell(row.BOM || row.Bom || (Array.isArray(row["BOM Names"]) ? row["BOM Names"].join(", ") : ""), "BOM not recorded")}</td>
                          <td className="cv-num" data-label="Quantity">{cell(row.Quantity || row.quantity)}</td>
                          <td data-label="Recorded lifecycle">{cell(row.Lifecycle || row.lifecycle, "Not recorded")}</td>
                          <td data-label="Recorded risk">{cell(row["Risk Level"] || row.risk_level, "Not assessed")}</td>
                          <td data-label="Analysis updated">{formatAnalysisDate(row.Updated || row.updated_at)}</td>
                          <td data-label="Report">
                            {analysisId ? (
                              <Link className="cv-table-open" href={"/reports/" + encodeURIComponent(analysisId)}>
                                Open report
                              </Link>
                            ) : "Not available"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="cv-small-note" style={{ marginTop: 12 }}>
                Analyze and save a BOM containing this part to add it to the impact view.
              </p>
            )}
          </section>

          <section className="cv-card pad" style={{ marginTop: 14 }}>
            <div className="cv-grid-2">
              <div>
                <h2 className="cv-card-title">What to do next</h2>
                <p className="cv-card-subtitle" style={{ marginTop: 8 }}>
                  Open an affected report to confirm its saved evidence. If you are considering a change, search for replacement candidates next.
                </p>
              </div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
                <Link className="cv-button primary" href={replacementHref}>Find replacement options</Link>
              </div>
            </div>
            <p className="cv-small-note" style={{ marginBottom: 0, marginTop: 12 }}>
              Searching for candidates does not change these saved BOMs. Record and apply any approved change in the relevant BOM workflow.
            </p>
          </section>
        </>
      ) : null}
    </Shell>
  );
}
