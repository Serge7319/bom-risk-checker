"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { Shell } from "@/components/Shell";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import {
  compareParts,
  listReports,
  recordDecision,
  type DecisionRecord,
} from "@/lib/api";
import { validateOverrideRationale } from "@/lib/decisionValidation";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

type Row = Record<string, unknown>;

function text(value: unknown, fallback = "—") {
  const valueText = String(value ?? "").trim();
  return valueText || fallback;
}

function getAnalysisId(row: Row) {
  return String(row.analysis_id || row.id || "");
}

function reportLabel(row: Row) {
  const bom = text(row.bom_name || row.filename || row.project_name, "Saved analysis");
  const revision = row.revision ? ` · rev ${String(row.revision)}` : "";
  const storedProject = String(row.project_name || "").trim();
  const separator = storedProject.indexOf(" — ");
  const projectName = separator >= 0
    ? storedProject.slice(0, separator).trim()
    : storedProject !== bom ? storedProject : "";
  const project = projectName ? `${projectName} · ` : "";
  return `${project}${bom}${revision}`;
}

function isUnknown(row: Row) {
  const assessment = text(row.Assessment || row.assessment || row.Status || "").toLowerCase();
  return assessment.includes("unable to confirm") || assessment.includes("needs data") || assessment.includes("needs validation");
}

function isMaterialDifference(row: Row) {
  const assessment = text(row.Assessment || row.assessment || row.Status || "").toLowerCase();
  return assessment.includes("material difference") || assessment === "different" || assessment === "difference";
}

function conflictEntriesFromResult(result: Row | null) {
  const rows = (result?.rows || []) as Row[];
  const materialFromRows = rows.filter(isMaterialDifference).map((row) => ({
    attribute: text(row.Attribute || row.attribute),
    part_a: text(row["Part A"] || row.part_a, ""),
    part_b: text(row["Part B"] || row.part_b, ""),
    assessment: text(row.Assessment || row.assessment || row.Status),
  }));
  const listedMaterial = ((result?.material_differences || []) as Row[]).map((row) => ({
    attribute: text(row.attribute || row.Attribute),
    part_a: text(row.part_a || row["Part A"], ""),
    part_b: text(row.part_b || row["Part B"], ""),
    assessment: text(row.assessment || row.Assessment, "Material difference"),
  }));
  const materialByAttr = new Map<string, (typeof materialFromRows)[number]>();
  for (const item of [...listedMaterial, ...materialFromRows]) {
    if (item.attribute && item.attribute !== "—") materialByAttr.set(item.attribute, item);
  }

  const hasRequiredFlag = rows.some((row) => "Required" in row);
  const unknownFromRows = rows
    .filter((row) => {
      if (!isUnknown(row)) return false;
      if (!hasRequiredFlag) return true;
      return Boolean(row.Required);
    })
    .map((row) => ({
      attribute: text(row.Attribute || row.attribute),
      part_a: text(row["Part A"] || row.part_a, ""),
      part_b: text(row["Part B"] || row.part_b, ""),
      assessment: text(row.Assessment || row.assessment || row.Status, "Unable to confirm"),
    }));
  const listedUnknown = ((result?.unknown_required_fields || []) as Row[]).map((row) => ({
    attribute: text(row.attribute || row.Attribute),
    part_a: text(row.part_a || row["Part A"], ""),
    part_b: text(row.part_b || row["Part B"], ""),
    assessment: text(row.assessment || row.Assessment, "Unable to confirm"),
  }));
  const unknownByAttr = new Map<string, (typeof unknownFromRows)[number]>();
  for (const item of [...listedUnknown, ...unknownFromRows]) {
    if (item.attribute && item.attribute !== "—") unknownByAttr.set(item.attribute, item);
  }
  if (!unknownByAttr.size && !hasRequiredFlag) {
    for (const attribute of (result?.unknown_attributes || []) as unknown[]) {
      const label = text(attribute, "");
      if (label) {
        unknownByAttr.set(label, {
          attribute: label,
          part_a: "",
          part_b: "",
          assessment: "Unable to confirm",
        });
      }
    }
  }

  const material = Array.from(materialByAttr.values());
  const unknownRequired = Array.from(unknownByAttr.values());
  const finding = text(result?.finding, "");
  const counts = (result?.counts || {}) as Record<string, unknown>;
  const hasConflicts = Boolean(
    material.length
    || unknownRequired.length
    || Number(counts.material_difference || 0) > 0
    || /material difference/i.test(finding),
  );
  return { material, unknownRequired, hasConflicts, finding };
}

function evidenceLabel(source: unknown) {
  const value = String(source || "").toLowerCase();
  if (value.includes("uploaded-manufacturer-datasheet")) return "Uploaded exact-MPN datasheet · verified";
  if (value.includes("manufacturer-datasheet")) return "Manufacturer datasheet · identity verified";
  if (value.includes("supplier-record")) return "Supplier record · identity needs review";
  if (value.includes("uploaded-datasheet-unverified")) return "Uploaded PDF · identity not verified";
  if (value.includes("verified")) return "Verified source evidence";
  if (value.includes("analysis")) return "Saved analysis fields · synthetic";
  if (value.includes("unverified")) return "No exact-MPN source confirmed";
  return "Offline identity catalog · synthetic";
}

const VALIDATION_CHECKS = [
  ["manufacturer_datasheet_reviewed", "Manufacturer datasheet reviewed"],
  ["package_pinout_verified", "Package, footprint, and pinout verified"],
  ["electrical_limits_verified", "Electrical limits and timing checked"],
  ["thermal_environmental_limits_verified", "Thermal and environmental limits checked"],
  ["lifecycle_and_supply_reviewed", "Lifecycle and supply evidence reviewed"],
  ["prototype_validation_completed", "Prototype or bench validation completed"],
] as const;

const APPROVAL_CHECKS = [
  "manufacturer_datasheet_reviewed",
  "package_pinout_verified",
  "electrical_limits_verified",
];

function reportDate(value: unknown) {
  if (!value) return "recently";
  const date = new Date(String(value));
  return Number.isNaN(date.getTime())
    ? "recently"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function replacementHref(partNumber: string, analysisId: string) {
  const query = new URLSearchParams();
  if (partNumber.trim()) query.set("mpn", partNumber.trim());
  if (analysisId) query.set("analysis_id", analysisId);
  const suffix = query.toString();
  return suffix ? `/find-replacement?${suffix}` : "/find-replacement";
}

function ComparePartsInner() {
  const session = useRequireSession();
  const search = useSearchParams();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [partA, setPartA] = useState("");
  const [partB, setPartB] = useState("");
  const [datasheetA, setDatasheetA] = useState<File | null>(null);
  const [datasheetB, setDatasheetB] = useState<File | null>(null);
  const [analysisId, setAnalysisId] = useState("");
  const [reports, setReports] = useState<Row[]>([]);
  const [reportsError, setReportsError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Row | null>(null);
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [decisionAnalysisId, setDecisionAnalysisId] = useState("");
  const [decisionPartA, setDecisionPartA] = useState("");
  const [decisionPartB, setDecisionPartB] = useState("");
  const [decision, setDecision] = useState("hold_for_review");
  const [reviewer, setReviewer] = useState("");
  const [rationale, setRationale] = useState("");
  const [validationChecks, setValidationChecks] = useState<string[]>([]);
  const [followUpAction, setFollowUpAction] = useState("");
  const [followUpOwner, setFollowUpOwner] = useState("");
  const [followUpDueDate, setFollowUpDueDate] = useState("");
  const [residualRisk, setResidualRisk] = useState("unknown");
  const [conflictAcknowledgement, setConflictAcknowledgement] = useState(false);
  const [overrideRationale, setOverrideRationale] = useState("");
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  const [decisionSuccess, setDecisionSuccess] = useState<DecisionRecord | null>(null);

  useEffect(() => {
    const a = (search.get("part_a") || search.get("a") || "").trim();
    const b = (search.get("part_b") || search.get("b") || "").trim();
    if (a) setPartA(a);
    if (b) setPartB(b);
  }, [search]);

  useEffect(() => {
    if (!decisionOpen || !result) return;
    // Any comparison identity change while the dialog is open invalidates prior ack/override.
    resetConflictGuard();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally keyed to comparison identity only
  }, [
    decisionOpen,
    String(result?.part_a || ""),
    String(result?.part_b || ""),
    String(result?.analysis_id || ""),
    String(result?.finding || ""),
  ]);

  useEffect(() => {
    if (!session) return;
    let active = true;
    const queryAnalysis = (search.get("analysis_id") || "").trim();
    const last = readLastAnalysis(session);
    const preferredAnalysis = queryAnalysis || last?.analysis_id || "";
    setAnalysisId(preferredAnalysis);
    setReviewer(session.email || "");
    listReports(session.access_token)
      .then(({ reports: rows }) => {
        if (active) {
          setReports(rows || []);
          if (!preferredAnalysis && rows?.[0]) {
            const defaultAnalysis = getAnalysisId(rows[0]);
            setAnalysisId(defaultAnalysis);
            setDecisionAnalysisId((current) => current || defaultAnalysis);
          }
        }
      })
      .catch((err) => {
        if (active) setReportsError(err instanceof Error ? err.message : "Saved BOMs could not load.");
      });
    return () => {
      active = false;
    };
  }, [session, search]);

  useEffect(() => {
    if (!decisionOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !decisionBusy) setDecisionOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    dialogRef.current?.querySelector<HTMLElement>("select, input, textarea, button")?.focus();
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [decisionOpen, decisionBusy]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    setResult(null);
    setDecisionSuccess(null);
    try {
      const last = readLastAnalysis(session);
      const selectedAnalysis = analysisId || last?.analysis_id;
      const data = await compareParts(session.access_token, partA, partB, selectedAnalysis, {
        a: datasheetA,
        b: datasheetB,
      });
      setResult(data);
      if (data.analysis_id) setAnalysisId(String(data.analysis_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Compare failed");
    } finally {
      setBusy(false);
    }
  }

  function resetConflictGuard() {
    setConflictAcknowledgement(false);
    setOverrideRationale("");
  }

  function openDecisionDialog() {
    setDecisionAnalysisId(String(result?.analysis_id || analysisId || ""));
    setDecisionPartA(String(result?.part_a || partA || ""));
    setDecisionPartB(String(result?.part_b || partB || ""));
    setDecision("hold_for_review");
    setReviewer(session?.email || "");
    setRationale("");
    setValidationChecks([]);
    setFollowUpAction("");
    setFollowUpOwner("");
    setFollowUpDueDate("");
    setResidualRisk("unknown");
    resetConflictGuard();
    setDecisionError("");
    setDecisionSuccess(null);
    setDecisionOpen(true);
  }

  async function changeDecisionAnalysis(nextAnalysisId: string) {
    if (!session) return;
    const previousAnalysisId = decisionAnalysisId;
    setDecisionAnalysisId(nextAnalysisId);
    if (!result) return;
    setDecisionBusy(true);
    setDecisionError("");
    try {
      const data = await compareParts(
        session.access_token,
        decisionPartA || String(result.part_a || partA),
        decisionPartB || String(result.part_b || partB),
        nextAnalysisId || undefined,
        { a: datasheetA, b: datasheetB },
      );
      setResult(data);
      setAnalysisId(String(data.analysis_id || ""));
      setDecisionAnalysisId(String(data.analysis_id || nextAnalysisId || ""));
      // Comparison identity changed — prior ack/override must not carry over.
      resetConflictGuard();
    } catch (err) {
      setDecisionAnalysisId(previousAnalysisId);
      setDecisionError(err instanceof Error ? err.message : "Could not refresh the comparison for that BOM.");
    } finally {
      setDecisionBusy(false);
    }
  }

  function onDecisionPartChange(side: "a" | "b", value: string) {
    if (side === "a") setDecisionPartA(value);
    else setDecisionPartB(value);
    // Editing MPNs while the dialog is open invalidates any prior conflict ack.
    resetConflictGuard();
    setDecisionError("");
  }

  function onDecisionTypeChange(next: string) {
    setDecision(next);
    if (next !== "approve_alternate") {
      resetConflictGuard();
    }
  }

  async function onRecordDecision(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    if (!decisionPartA.trim() || !decisionPartB.trim()) {
      setDecisionError("Enter both manufacturer part numbers before recording this decision.");
      return;
    }
    if (decision === "approve_alternate" && !APPROVAL_CHECKS.every((item) => validationChecks.includes(item))) {
      setDecisionError("Complete the datasheet, package/pinout, and electrical-limit checks before approving an alternate.");
      return;
    }
    if (["conditional_approval", "defer_for_validation"].includes(decision) && !followUpAction.trim()) {
      setDecisionError("Add the required follow-up action for this decision.");
      return;
    }
    if (decision === "approve_alternate" && residualRisk === "unknown") {
      setDecisionError("Record an explicit residual-risk assessment before approving an alternate.");
      return;
    }
    const previewConflicts = conflictEntriesFromResult(result);
    if (decision === "approve_alternate" && previewConflicts.hasConflicts) {
      if (!conflictAcknowledgement) {
        setDecisionError(
          "Acknowledge the material differences and unknown required fit fields before approving.",
        );
        return;
      }
      const overrideError = validateOverrideRationale(overrideRationale, rationale);
      if (overrideError) {
        setDecisionError(overrideError);
        return;
      }
    }
    setDecisionBusy(true);
    setDecisionError("");
    try {
      const resultMatchesDraft =
        result &&
        String(result.part_a || "").trim().toLowerCase() === decisionPartA.trim().toLowerCase() &&
        String(result.part_b || "").trim().toLowerCase() === decisionPartB.trim().toLowerCase() &&
        String(result.analysis_id || "") === String(decisionAnalysisId || "");
      const comparison = resultMatchesDraft
        ? result
        : await compareParts(
            session.access_token,
            decisionPartA.trim(),
            decisionPartB.trim(),
            decisionAnalysisId || undefined,
            { a: datasheetA, b: datasheetB },
          );
      const comparisonIdentityChanged = Boolean(
        result
        && (
          String(result.part_a || "").trim().toLowerCase() !== String(comparison.part_a || "").trim().toLowerCase()
          || String(result.part_b || "").trim().toLowerCase() !== String(comparison.part_b || "").trim().toLowerCase()
          || String(result.analysis_id || "") !== String(comparison.analysis_id || "")
          || String(result.finding || "") !== String(comparison.finding || "")
        ),
      );
      setResult(comparison);
      if (comparisonIdentityChanged) {
        // Fresh comparison — do not reuse ack/override from the prior snapshot.
        resetConflictGuard();
        const freshConflicts = conflictEntriesFromResult(comparison as Row);
        if (decision === "approve_alternate" && freshConflicts.hasConflicts) {
          setDecisionError(
            "The comparison changed. Re-acknowledge the conflicts and provide a specific override rationale before approving.",
          );
          return;
        }
      }
      const response = await recordDecision(session.access_token, {
        analysis_id: String(comparison.analysis_id || decisionAnalysisId || "") || null,
        part_a: decisionPartA.trim(),
        part_b: decisionPartB.trim(),
        decision,
        reviewer,
        rationale,
        validation_checks: validationChecks,
        follow_up_action: followUpAction,
        follow_up_owner: followUpOwner,
        follow_up_due_date: followUpDueDate || null,
        residual_risk: residualRisk,
        conflict_acknowledgement: comparisonIdentityChanged ? false : conflictAcknowledgement,
        override_rationale: comparisonIdentityChanged ? undefined : (overrideRationale.trim() || undefined),
      }, { a: datasheetA, b: datasheetB });
      setDecisionSuccess(response.record);
      setDecisionOpen(false);
    } catch (err) {
      setDecisionError(err instanceof Error ? err.message : "Decision could not be recorded.");
    } finally {
      setDecisionBusy(false);
    }
  }

  if (!session) return null;

  const rows = (result?.rows || []) as Row[];
  const unknownRows = rows.filter(isUnknown);
  const cards = (result?.part_cards || {}) as { a?: Row; b?: Row };
  const evidenceSources = (result?.evidence_sources || {}) as { part_a?: unknown[]; part_b?: unknown[] };
  const packageDimensionEvidence = (result?.package_dimension_evidence || {}) as {
    part_a?: Array<Record<string, unknown>>;
    part_b?: Array<Record<string, unknown>>;
    conflicts?: string[];
  };
  const packageDimensionConflicts = packageDimensionEvidence.conflicts || [];
  const hasPackageDimensionEvidence = Boolean(
    packageDimensionEvidence.part_a?.length || packageDimensionEvidence.part_b?.length,
  );
  const resultFinding = text(result?.finding, "No compatibility conclusion");
  const evidenceCounts = (result?.counts || {}) as Record<string, unknown>;
  const approvalConflicts = conflictEntriesFromResult(result);
  const reportOptions = [...reports];
  if (decisionAnalysisId && !reportOptions.some((row) => getAnalysisId(row) === decisionAnalysisId)) {
    reportOptions.unshift({ id: decisionAnalysisId, project_name: "Current comparison", bom_name: "Saved analysis context" });
  }

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.compare}
        actions={
          <>
            <span className={`cv-compare-state${result ? " preview" : ""}`}>
              <i aria-hidden="true" />
              {result?.mode === "legacy-supplier-engine"
                ? "Supplier / datasheet review"
                : result?.mode === "uploaded-datasheet-review"
                  ? "Uploaded datasheet review"
                  : result
                    ? "Sample / offline evidence"
                    : "Ready to compare"}
            </span>
            <SecondaryLink href={replacementHref(String(result?.part_a || partA), String(result?.analysis_id || analysisId))}>Find a replacement</SecondaryLink>
            <button
              type="button"
              className="cv-button primary"
              onClick={openDecisionDialog}
              aria-describedby="record-decision-help"
            >
              +&nbsp; Record a decision
            </button>
          </>
        }
      />

      <form className="cv-card pad cv-compare-input-card" onSubmit={onSubmit}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="part-a">Part A · current design</label>
            <input
              id="part-a"
              value={partA}
              onChange={(e) => setPartA(e.target.value)}
              placeholder="Manufacturer part number"
              autoComplete="off"
              required
            />
          </div>
          <div className="cv-field">
            <label htmlFor="part-b">Part B · candidate</label>
            <input
              id="part-b"
              value={partB}
              onChange={(e) => setPartB(e.target.value)}
              placeholder="Manufacturer part number"
              autoComplete="off"
              required
            />
          </div>
        </div>
        <div className="cv-compare-form-footer">
          <div>
            {reports.length ? (
              <p className="cv-small-note">
                Comparing against {reportLabel(reports.find((row) => getAnalysisId(row) === analysisId) || reports[0])}.
              </p>
            ) : reportsError ? (
              <p className="cv-small-note">{reportsError} You can still compare without a saved BOM.</p>
            ) : (
              <p className="cv-small-note">BOM context is optional. Source data stays labeled.</p>
            )}
            <span className="cv-small-note" id="record-decision-help">
              {result ? "The recorded decision will include this comparison snapshot." : "Compare two parts to enable decision recording."}
            </span>
          </div>
          <button className="cv-button primary" type="submit" disabled={busy || !partA.trim() || !partB.trim()}>
            {busy ? "Comparing…" : "Compare parts"}
          </button>
        </div>
        <details className="cv-compare-upload">
          <summary>Optional: add manufacturer datasheets for stronger evidence</summary>
          <p>
            Upload a PDF when a linked source is missing or blocked. Cadivor uses its values only when the extracted text names the exact part number. Each file is limited to 8 MB; scanned PDFs without selectable text remain unverified.
          </p>
          <div className="cv-form-grid">
            <label className="cv-field">
              <span>Part A datasheet (PDF)</span>
              <input
                type="file"
                accept="application/pdf,.pdf"
                onChange={(event) => setDatasheetA(event.target.files?.[0] || null)}
                disabled={busy}
              />
              <small>{datasheetA?.name || "Optional exact-MPN manufacturer PDF · up to 8 MB"}</small>
            </label>
            <label className="cv-field">
              <span>Part B datasheet (PDF)</span>
              <input
                type="file"
                accept="application/pdf,.pdf"
                onChange={(event) => setDatasheetB(event.target.files?.[0] || null)}
                disabled={busy}
              />
              <small>{datasheetB?.name || "Optional exact-MPN manufacturer PDF · up to 8 MB"}</small>
            </label>
          </div>
        </details>
      </form>

      {busy ? <LoadingCard label="Comparing available part attributes and evidence…" /> : null}
      {error ? <div className="cv-error" role="alert">The comparison could not complete. {error}</div> : null}
      {decisionSuccess ? (
        <div className="cv-success" role="status">
          <span>Decision recorded for {decisionSuccess.part_a} → {decisionSuccess.part_b}.</span>
          <Link href={decisionSuccess.analysis_id ? `/engineering-decisions?analysis_id=${encodeURIComponent(decisionSuccess.analysis_id)}` : "/engineering-decisions"}>
            Open Engineering Decisions →
          </Link>
        </div>
      ) : null}

      {result ? (
        <>
          {<EvidenceNotice gap={result.gap} />}

          <div className="cv-compare-screening" role="status">
            <span className="cv-compare-screening-icon" aria-hidden="true">!</span>
            <div>
              <strong>{resultFinding}</strong>
              <p>{text(result.engineering_evidence_summary, "No primary manufacturer evidence was retrieved for this comparison.")}</p>
            </div>
          </div>

          <div className="cv-compare-parts-grid">
            {([
              ["a", "Part A · current design", result.part_a],
              ["b", "Part B · candidate", result.part_b],
            ] as Array<[string, string, unknown]>).map(([key, heading, mpn]) => {
              const card = (key === "a" ? cards.a : cards.b) || {};
              const source = key === "a" ? result.source_a : result.source_b;
              const sourceRows = (key === "a" ? evidenceSources.part_a : evidenceSources.part_b) || [];
              const manufacturer = text(card.manufacturer, "Manufacturer not confirmed");
              const description = text(card.description, "No verified description available.");
              const lifecycle = text(card.lifecycle_status, "Not confirmed");
              const imageUrl = String(card.image_url || "").trim();
              return (
                <section className="cv-card pad cv-compare-part-card" key={key}>
                  <div className="cv-compare-part-top">
                    {imageUrl ? (
                      <img
                        className="cv-compare-part-image"
                        src={imageUrl}
                        alt={`${text(mpn)} component image`}
                        loading="lazy"
                        referrerPolicy="no-referrer"
                        onError={(event) => { event.currentTarget.hidden = true; }}
                      />
                    ) : null}
                    <div>
                      <span className="cv-compare-part-label">{heading}</span>
                      <h2>{text(mpn)}</h2>
                      <p>{manufacturer}{description !== "No verified description available." ? ` · ${description}` : ""}</p>
                    </div>
                    <span className="cv-badge gray">{lifecycle}</span>
                  </div>
                  <div className="cv-compare-part-foot">
                    <span className="cv-badge blue">{evidenceLabel(source)}</span>
                    <span className="cv-small-note">
                      {sourceRows.length ? `${sourceRows.length} source reference${sourceRows.length === 1 ? "" : "s"}` : "No primary source cited"}
                    </span>
                  </div>
                </section>
              );
            })}
          </div>

          <section className="cv-card pad cv-compare-spec-card">
            <div className="cv-compare-section-heading">
              <div>
                <div className="cv-eyebrow">Specification comparison</div>
                <h2 className="cv-card-title">Differences that affect fit</h2>
              <p className="cv-card-subtitle">
                  {text(result?.family, "Component family")}: the full family-specific matrix is shown below. Missing source data stays unknown; it does not establish drop-in compatibility.
                </p>
              </div>
              <div className="cv-compare-counts" aria-label="Comparison attribute counts">
                <span><strong>{text(evidenceCounts.compatible, "0")}</strong> attributes align</span>
                <span><strong>{text(evidenceCounts.material_difference, "0")}</strong> differences</span>
                <span><strong>{text(evidenceCounts.needs_data, String(unknownRows.length))}</strong> unknown</span>
              </div>
            </div>
            {rows.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 14 }}>
                <table className="cv-table cv-compare-table">
                  <thead><tr><th>Property</th><th>Current part</th><th>Candidate</th><th>Assessment</th><th>Evidence / review note</th></tr></thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={`${String(row.Attribute || "attr")}-${index}`}>
                        <td><strong>{text(row.Attribute || row.attribute)}</strong></td>
                        <td>{text(row["Part A"] || row.part_a)}</td>
                        <td>{text(row["Part B"] || row.part_b)}</td>
                        <td>
                          <span className={`cv-compare-assessment${isUnknown(row) ? " unknown" : ""}`}>
                            {text(row.Assessment || row.assessment || row.Status)}
                          </span>
                        </td>
                        <td>{text(row.Evidence || row.evidence || row.Note, "No source note supplied.")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                icon="compare"
                title="No source-backed attributes to compare"
                body="This result cannot determine whether the candidate fits. Add manufacturer or datasheet evidence before using it to make a substitution decision."
              />
            )}
            {unknownRows.length ? (
              <p className="cv-compare-open-count">All {unknownRows.length} unverified attributes are visible in the matrix above.</p>
            ) : null}
          </section>

          {hasPackageDimensionEvidence ? (
            <section className="cv-card pad cv-compare-dimensions-card">
              <div>
                <div className="cv-eyebrow">Mechanical fit review</div>
                <h2 className="cv-card-title">Package outline evidence</h2>
                <p className="cv-card-subtitle">
                  Text excerpts from identity-verified datasheets. Inspect the original outline drawings,
                  tolerances, and recommended land patterns before concluding that footprints match.
                </p>
              </div>
              {packageDimensionConflicts.length ? (
                <div className="cv-compare-dimension-warning" role="status">
                  <strong>Dimension differences found in extracted text</strong>
                  <ul>
                    {packageDimensionConflicts.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
                  </ul>
                </div>
              ) : (
                <p className="cv-compare-dimension-note">
                  No direct dimensional conflict was confirmed from extracted text. This does not establish a footprint match.
                </p>
              )}
              <div className="cv-compare-dimension-grid">
                {([
                  ["Part A", packageDimensionEvidence.part_a || []],
                  ["Part B", packageDimensionEvidence.part_b || []],
                ] as Array<[string, Array<Record<string, unknown>>]>).map(([side, items]) => (
                  <div className="cv-compare-dimension-item" key={side}>
                    <strong>{side}</strong>
                    {items.length ? (
                      <ul>
                        {items.map((item, index) => (
                          <li key={`${String(item.document || "document")}-${String(item.page || index)}-${index}`}>
                            <span>{text(item.excerpt)}</span>
                            <small>{text(item.document, "Datasheet")}{item.page ? ` · p. ${String(item.page)}` : ""}</small>
                          </li>
                        ))}
                      </ul>
                    ) : <p>No package-dimension excerpt was extracted from this verified source.</p>}
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section className="cv-card pad cv-compare-evidence-card">
            <div>
              <div className="cv-eyebrow">Evidence</div>
              <h2 className="cv-card-title">Source records</h2>
              <p className="cv-card-subtitle">Review the source basis before documenting a component decision.</p>
            </div>
            <div className="cv-compare-evidence-grid">
              {([
                ["Part A", result.source_a, evidenceSources.part_a],
                ["Part B", result.source_b, evidenceSources.part_b],
              ] as Array<[string, unknown, unknown[] | undefined]>).map(([name, source, sourceRows]) => (
                <div className="cv-compare-evidence-item" key={name}>
                  <span className="cv-compare-part-label">{name} · {evidenceLabel(source)}</span>
                  {sourceRows?.length ? (
                    <ul>
                      {sourceRows.map((item, index) => {
                        const row = (item || {}) as Row;
                        const href = String(row.url || row.source_url || "");
                        return (
                          <li key={`${href}-${index}`}>
                            {href ? <a href={href} target="_blank" rel="noreferrer">{text(row.label || row.name || href)}</a> : text(row.label || row.name || row.source)}
                            {row.retrieved_at ? <small> · retrieved {reportDate(row.retrieved_at)}</small> : null}
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <p>No manufacturer datasheet or live supplier source was retrieved.</p>
                  )}
                </div>
              ))}
            </div>
          </section>
        </>
      ) : !busy && !error ? (
        <section className="cv-compare-empty">
          <div>
            <div className="cv-eyebrow">Side-by-side comparison</div>
            <h2>Start with two manufacturer part numbers</h2>
            <p>Cadivor will show the attributes it can support and make missing evidence visible. It will not turn unknown values into a match.</p>
          </div>
          <Link href="/find-replacement" className="cv-button secondary">Find a replacement</Link>
        </section>
      ) : null}

      {decisionOpen ? (
        <div
          className="cv-modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !decisionBusy) setDecisionOpen(false);
          }}
        >
          <section
            className="cv-modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="decision-dialog-title"
            ref={dialogRef}
          >
            <div className="cv-modal-heading">
              <div>
                <div className="cv-eyebrow">Engineering decision record</div>
                <h2 id="decision-dialog-title">Record an engineering decision</h2>
                <p>Save your reviewer choice and the comparison snapshot to this workspace.</p>
              </div>
              <span className="cv-badge blue">Human review</span>
            </div>

            <form onSubmit={onRecordDecision}>
              {reportOptions.length ? (
                <>
                  <label className="cv-field cv-modal-project">
                    <span>Project / BOM</span>
                    <select
                      value={decisionAnalysisId}
                      onChange={(event) => void changeDecisionAnalysis(event.target.value)}
                      disabled={decisionBusy}
                    >
                      {reportOptions.map((row) => (
                        <option key={getAnalysisId(row)} value={getAnalysisId(row)}>{reportLabel(row)}</option>
                      ))}
                    </select>
                  </label>
                  <div className="cv-modal-component-pair">
                    <label className="cv-field">
                      <span>Current part</span>
                      <input
                        value={decisionPartA}
                        onChange={(event) => onDecisionPartChange("a", event.target.value)}
                        maxLength={160}
                        placeholder="Current manufacturer part number"
                        autoComplete="off"
                        required
                      />
                    </label>
                    <label className="cv-field">
                      <span>Candidate part</span>
                      <input
                        value={decisionPartB}
                        onChange={(event) => onDecisionPartChange("b", event.target.value)}
                        maxLength={160}
                        placeholder="Candidate manufacturer part number"
                        autoComplete="off"
                        required
                      />
                    </label>
                  </div>
                </>
              ) : (
                <>
                  <div className="cv-modal-context">
                    <strong>Workspace-level decision</strong>
                    <span>Not linked to a saved BOM. The comparison will be captured with the decision.</span>
                  </div>
                  <div className="cv-modal-component-pair">
                    <label className="cv-field">
                      <span>Current part</span>
                      <input
                        value={decisionPartA}
                        onChange={(event) => onDecisionPartChange("a", event.target.value)}
                        maxLength={160}
                        placeholder="Current manufacturer part number"
                        autoComplete="off"
                        required
                      />
                    </label>
                    <label className="cv-field">
                      <span>Candidate part</span>
                      <input
                        value={decisionPartB}
                        onChange={(event) => onDecisionPartChange("b", event.target.value)}
                        maxLength={160}
                        placeholder="Candidate manufacturer part number"
                        autoComplete="off"
                        required
                      />
                    </label>
                  </div>
                </>
              )}

              <div className="cv-form-grid cv-form-grid-two cv-modal-grid">
                <label className="cv-field">
                  <span>Decision</span>
                  <select
                    value={decision}
                    onChange={(event) => onDecisionTypeChange(event.target.value)}
                    disabled={decisionBusy}
                  >
                    <option value="hold_for_review">Hold for review</option>
                    <option value="approve_alternate">Approve alternate</option>
                    <option value="conditional_approval">Conditional approval</option>
                    <option value="reject_alternate">Reject alternate</option>
                    <option value="retain_current_part">Retain current part</option>
                    <option value="defer_for_validation">Defer pending validation</option>
                    <option value="accept_residual_risk">Accept residual risk</option>
                  </select>
                </label>
                <label className="cv-field">
                  <span>Reviewer</span>
                  <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} maxLength={120} required />
                </label>
              </div>

              <label className="cv-field cv-modal-rationale">
                <span>Rationale</span>
                <textarea
                  value={rationale}
                  onChange={(event) => setRationale(event.target.value)}
                  placeholder="Document what was reviewed, why this decision was selected, and any follow-up required."
                  maxLength={3000}
                  required
                  rows={4}
                />
              </label>

              <fieldset className="cv-modal-checklist">
                <legend>Validation completed</legend>
                <p>Select the engineering checks that were completed for this decision.</p>
                <div>
                  {VALIDATION_CHECKS.map(([value, label]) => (
                    <label key={value}>
                      <input
                        type="checkbox"
                        checked={validationChecks.includes(value)}
                        onChange={(event) => setValidationChecks((current) => event.target.checked
                          ? [...current, value]
                          : current.filter((item) => item !== value))}
                        disabled={decisionBusy}
                      />
                      <span>{label}</span>
                    </label>
                  ))}
                </div>
                {decision === "approve_alternate" ? (
                  <small>Alternate approval requires the datasheet, package/pinout, and electrical-limit checks above.</small>
                ) : null}
              </fieldset>

              {decision === "approve_alternate" && approvalConflicts.hasConflicts ? (
                <fieldset className="cv-modal-conflict-guard">
                  <legend>Comparison conflicts require an override</legend>
                  <p>
                    The recomputed comparison reports {approvalConflicts.finding || "fit conflicts"}.
                    Review the material differences and unknown required fit fields before approving.
                  </p>
                  {approvalConflicts.material.length ? (
                    <div className="cv-modal-conflict-block">
                      <strong>Material differences</strong>
                      <ul>
                        {approvalConflicts.material.map((item) => (
                          <li key={`material-${item.attribute}`}>
                            <span>{item.attribute}</span>
                            {(item.part_a || item.part_b) ? (
                              <small>{item.part_a || "—"} → {item.part_b || "—"}</small>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {approvalConflicts.unknownRequired.length ? (
                    <div className="cv-modal-conflict-block">
                      <strong>Unknown required fit fields</strong>
                      <ul>
                        {approvalConflicts.unknownRequired.map((item) => (
                          <li key={`unknown-${item.attribute}`}>
                            <span>{item.attribute}</span>
                            <small>{item.assessment}</small>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <label className="cv-modal-ack">
                    <input
                      type="checkbox"
                      checked={conflictAcknowledgement}
                      onChange={(event) => setConflictAcknowledgement(event.target.checked)}
                      disabled={decisionBusy}
                      required
                    />
                    <span>
                      I have reviewed these material differences and unknown required fit fields and still want to approve this alternate.
                    </span>
                  </label>
                  <label className="cv-field cv-modal-rationale">
                    <span>Override rationale · required</span>
                    <textarea
                      value={overrideRationale}
                      onChange={(event) => setOverrideRationale(event.target.value)}
                      placeholder="Explain specifically why approval is justified despite the conflicts above. This is stored separately from the general rationale."
                      maxLength={3000}
                      required
                      rows={3}
                      disabled={decisionBusy}
                    />
                  </label>
                </fieldset>
              ) : null}

              <div className="cv-form-grid cv-form-grid-two cv-modal-followup">
                <label className="cv-field">
                  <span>Follow-up action{["conditional_approval", "defer_for_validation"].includes(decision) ? " · required" : " · optional"}</span>
                  <input
                    value={followUpAction}
                    onChange={(event) => setFollowUpAction(event.target.value)}
                    maxLength={1000}
                    placeholder="e.g. Complete thermal validation before release"
                    required={["conditional_approval", "defer_for_validation"].includes(decision)}
                    disabled={decisionBusy}
                  />
                </label>
                <label className="cv-field">
                  <span>Follow-up owner · optional</span>
                  <input value={followUpOwner} onChange={(event) => setFollowUpOwner(event.target.value)} maxLength={120} disabled={decisionBusy} />
                </label>
                <label className="cv-field">
                  <span>Due date · optional</span>
                  <input type="date" value={followUpDueDate} onChange={(event) => setFollowUpDueDate(event.target.value)} disabled={decisionBusy} />
                </label>
                <label className="cv-field">
                  <span>Residual risk{decision === "approve_alternate" ? " · required" : ""}</span>
                  <select
                    value={residualRisk}
                    onChange={(event) => setResidualRisk(event.target.value)}
                    disabled={decisionBusy}
                    required={decision === "approve_alternate"}
                  >
                    <option value="unknown">Not assessed</option>
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
              </div>

              <div className="cv-decision-evidence-note">
                {result?.mode === "legacy-supplier-engine"
                  ? "The comparison uses Cadivor’s supplier and datasheet review engine. The record captures your human decision; it does not automatically approve fit or change the BOM."
                  : result?.mode === "uploaded-datasheet-review"
                    ? "The comparison includes the PDFs uploaded for this review. The record captures your human decision; it does not automatically approve fit or change the BOM."
                    : "The comparison uses synthetic or offline evidence. The record captures your human decision; it does not qualify a drop-in replacement or change the BOM."}
              </div>
              {decisionError ? <div className="cv-error" role="alert">{decisionError}</div> : null}

              <div className="cv-modal-actions">
                <button type="button" className="cv-button" onClick={() => setDecisionOpen(false)} disabled={decisionBusy}>Cancel</button>
                <button
                  type="submit"
                  className="cv-button primary"
                  disabled={
                    decisionBusy
                    || !decisionPartA.trim()
                    || !decisionPartB.trim()
                    || !reviewer.trim()
                    || !rationale.trim()
                    || (decision === "approve_alternate" && !APPROVAL_CHECKS.every((item) => validationChecks.includes(item)))
                    || (decision === "approve_alternate" && residualRisk === "unknown")
                    || (
                      decision === "approve_alternate"
                      && approvalConflicts.hasConflicts
                      && (
                        !conflictAcknowledgement
                        || Boolean(validateOverrideRationale(overrideRationale, rationale))
                      )
                    )
                    || (["conditional_approval", "defer_for_validation"].includes(decision) && !followUpAction.trim())
                    || (decision === "accept_residual_risk" && residualRisk === "unknown")
                  }
                >
                  {decisionBusy ? "Saving comparison and decision…" : "Record decision"}
                </button>
              </div>
            </form>
          </section>
        </div>
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
