"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { Shell } from "@/components/Shell";
import { PageHeader, SecondaryLink } from "@/components/PageHeader";
import {
  COMPARE_PARTS_TIMEOUT_MS,
  compareParts,
  listReports,
  recordDecision,
  type DecisionRecord,
} from "@/lib/api";
import {
  formatCompareProgressLabel,
  type CompareProgressState,
} from "@/lib/compareProgress";
import {
  buildMultiCompareMatrix,
  buildMultiDecisionSnapshot,
  buildMultiSourceRecords,
  candidateManufacturer,
  formatCandidateHeading,
  parseCandidateMpns,
  type MultiCompareColumn,
} from "@/lib/multiCompare";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

type CompareProgress = CompareProgressState;

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
  return (
    assessment.includes("unable to confirm")
    || assessment.includes("needs data")
    || assessment.includes("needs validation")
    || assessment.includes("needs verification")
    || assessment.includes("fit unverified")
    || assessment.includes("conflict")
  );
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

function replacementHref(partNumber: string, analysisId: string, manufacturer?: string) {
  const query = new URLSearchParams();
  if (partNumber.trim()) query.set("mpn", partNumber.trim());
  if (manufacturer?.trim()) query.set("manufacturer", manufacturer.trim());
  if (analysisId) query.set("analysis_id", analysisId);
  const suffix = query.toString();
  return suffix ? `/find-replacement?${suffix}` : "/find-replacement";
}

function parseAlignedList(raw: string[], limit = 4): string[] {
  return raw.slice(0, limit).map((item) => String(item || "").trim());
}

function ComparePartsInner() {
  const session = useRequireSession();
  const search = useSearchParams();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [partA, setPartA] = useState("");
  const [partB, setPartB] = useState("");
  const [manufacturerA, setManufacturerA] = useState("");
  const [manufacturerB, setManufacturerB] = useState("");
  const [manufacturerBByMpn, setManufacturerBByMpn] = useState<Record<string, string>>({});
  const [datasheetA, setDatasheetA] = useState<File | null>(null);
  const [datasheetB, setDatasheetB] = useState<File | null>(null);
  const [analysisId, setAnalysisId] = useState("");
  const [reports, setReports] = useState<Row[]>([]);
  const [reportsError, setReportsError] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState<CompareProgress | null>(null);
  const [result, setResult] = useState<Row | null>(null);
  const [multiColumns, setMultiColumns] = useState<MultiCompareColumn[]>([]);
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
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  const [decisionSuccess, setDecisionSuccess] = useState<DecisionRecord | null>(null);
  /** True while multi-candidate scope refresh is incomplete or failed. */
  const [decisionScopeStale, setDecisionScopeStale] = useState(false);
  const [decisionScopeProgress, setDecisionScopeProgress] = useState("");

  useEffect(() => {
    const a = (search.get("part_a") || search.get("a") || "").trim();
    const multi = search.getAll("part_b").concat(search.getAll("b"));
    const joined = multi.map((item) => item.trim()).filter(Boolean);
    const b = joined.length
      ? joined.join(", ")
      : (search.get("part_b") || search.get("b") || "").trim();
    const mfrA = (
      search.get("manufacturer_a")
      || search.get("manufacturer")
      || ""
    ).trim();
    const mfrBList = parseAlignedList(
      search.getAll("manufacturer_b").concat(search.getAll("manufacturerB")),
      4,
    );
    const byMpn: Record<string, string> = {};
    joined.forEach((mpn, index) => {
      const brand = String(mfrBList[index] || "").trim();
      if (mpn && brand) byMpn[mpn] = brand;
    });
    if (a) setPartA(a);
    if (b) setPartB(b);
    if (mfrA) setManufacturerA(mfrA);
    if (joined.length === 1 && mfrBList[0]) {
      setManufacturerB(mfrBList[0]);
    } else if (!joined.length) {
      const singleB = (search.get("manufacturer_b") || "").trim();
      if (singleB) setManufacturerB(singleB);
    }
    if (Object.keys(byMpn).length) setManufacturerBByMpn(byMpn);
  }, [search]);

  useEffect(() => {
    if (!session) return;
    let active = true;
    // Only attach BOM context when the handoff URL carried analysis_id.
    // Standalone Compare Parts must not silently bind the latest/first BOM.
    const queryAnalysis = (search.get("analysis_id") || "").trim();
    setAnalysisId(queryAnalysis);
    setReviewer(session.email || "");
    listReports(session.access_token)
      .then(({ reports: rows }) => {
        if (active) {
          setReports(rows || []);
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
    setProgress(null);
    setResult(null);
    setMultiColumns([]);
    setDecisionSuccess(null);
    try {
      // Explicit BOM selection only — never fall back to last-analysis localStorage.
      const selectedAnalysis = analysisId.trim() || undefined;
      const candidates = parseCandidateMpns(partB, 4);
      if (!candidates.length) {
        throw new Error("Enter one to four candidate manufacturer part numbers.");
      }
      if (candidates.some((mpn) => mpn.toLowerCase() === partA.trim().toLowerCase())) {
        throw new Error("Candidate MPNs must differ from the current design part.");
      }
      const baselineMpn = partA.trim();
      const brandA = manufacturerA.trim();
      const brandForCandidate = (mpn: string) =>
        String(manufacturerBByMpn[mpn] || manufacturerB || "").trim();
      if (candidates.length === 1) {
        setProgress({
          total: 1,
          completed: 0,
          baselineMpn,
          candidateMpn: candidates[0],
          failures: [],
        });
        const data = await compareParts(
          session.access_token,
          partA,
          candidates[0],
          selectedAnalysis,
          { a: datasheetA, b: datasheetB },
          {
            timeoutMs: COMPARE_PARTS_TIMEOUT_MS,
            manufacturerA: brandA || undefined,
            manufacturerB: brandForCandidate(candidates[0]) || undefined,
          },
        );
        setProgress({
          total: 1,
          completed: 1,
          baselineMpn,
          failures: [],
        });
        setResult(data);
        setMultiColumns([]);
        // Never attach a BOM the user did not select / hand off.
        if (selectedAnalysis) {
          setAnalysisId(selectedAnalysis);
        } else {
          setAnalysisId("");
          if (data.analysis_id) {
            setResult({ ...data, analysis_id: null });
          }
        }
        return;
      }
      // Multi-alternate: compare each candidate against the same design part.
      // Bounded per-pair timeout; failures stay visible and never become
      // “no candidates” or a Compatible fit verdict. Progress updates as each
      // pairwise request settles (not only after allSettled finishes).
      const failures: string[] = [];
      const columnsSlot: Array<MultiCompareColumn | null> = candidates.map(() => null);
      let completedCount = 0;
      const publishProgress = (candidateMpn?: string) => {
        setProgress({
          total: candidates.length,
          completed: completedCount,
          baselineMpn,
          candidateMpn,
          failures: [...failures],
        });
        const ready = columnsSlot.filter(Boolean) as MultiCompareColumn[];
        if (ready.length) {
          setMultiColumns(ready);
          setResult(
            ready.find((column) => column.result.ok !== false)?.result || ready[0]?.result || null,
          );
        }
      };
      publishProgress(candidates[0]);
      await Promise.allSettled(
        candidates.map((candidate, index) =>
          compareParts(
            session.access_token,
            partA,
            candidate,
            selectedAnalysis,
            { a: datasheetA },
            {
              timeoutMs: COMPARE_PARTS_TIMEOUT_MS,
              manufacturerA: brandA || undefined,
              manufacturerB: brandForCandidate(candidate) || undefined,
            },
          )
            .then((data) => {
              const brand = brandForCandidate(candidate);
              const stamped: Record<string, unknown> = {
                ...(data as Record<string, unknown>),
                analysis_id: selectedAnalysis || null,
              };
              if (brand && !stamped.manufacturer_b) {
                stamped.manufacturer_b = brand;
              }
              columnsSlot[index] = {
                mpn: candidate,
                manufacturer: brand || undefined,
                result: stamped,
                rows: (stamped.rows || []) as Row[],
              };
              completedCount += 1;
              const nextPending = candidates.find((_, i) => columnsSlot[i] == null);
              publishProgress(nextPending);
              return { candidate, data: stamped };
            })
            .catch((reason) => {
              const detail =
                reason instanceof Error
                  ? reason.message
                  : `Comparison failed for ${candidate}.`;
              failures.push(detail);
              columnsSlot[index] = {
                mpn: candidate,
                manufacturer: brandForCandidate(candidate) || undefined,
                result: {
                  ok: false,
                  status: "comparison_failed",
                  finding: "Needs verification",
                  gap: detail,
                  part_a: partA,
                  part_b: candidate,
                  manufacturer_b: brandForCandidate(candidate) || null,
                  analysis_id: selectedAnalysis || null,
                  rows: [],
                },
                rows: [],
              };
              completedCount += 1;
              const nextPending = candidates.find((_, i) => columnsSlot[i] == null);
              publishProgress(nextPending);
              throw reason;
            }),
        ),
      );
      const columns = columnsSlot.filter(Boolean) as MultiCompareColumn[];
      setProgress({
        total: candidates.length,
        completed: candidates.length,
        baselineMpn,
        failures,
      });
      setMultiColumns(columns);
      setResult(columns.find((column) => column.result.ok !== false)?.result || columns[0]?.result || null);
      // Keep the user's explicit BOM selection (or standalone empty) — never the
      // first/latest saved BOM echoed by a pairwise response.
      setAnalysisId(selectedAnalysis || "");
      if (failures.length && failures.length === candidates.length) {
        setError(
          `All ${candidates.length} pairwise comparisons failed or timed out. This is not a fit verdict and does not mean there are no candidates. ${failures[0]}`,
        );
      } else if (failures.length) {
        setError(
          `${failures.length} of ${candidates.length} pairwise comparisons failed or timed out. Completed columns are shown; failures stay Needs verification — not Compatible. ${failures[0]}`,
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Compare failed");
    } finally {
      setBusy(false);
    }
  }

  function normalizeScopeId(value: unknown): string {
    return String(value || "").trim();
  }

  function columnMatchesScope(column: MultiCompareColumn, scopedId: string): boolean {
    return normalizeScopeId(column.result?.analysis_id) === scopedId
      && Boolean(String(column.result?.snapshot_token || "").trim())
      && column.result?.ok !== false;
  }

  function openDecisionDialog() {
    // Form BOM context is the source of truth — never prefer a stale
    // result.analysis_id that would make the first saved BOM appear selected.
    const scopedId = analysisId.trim();
    setDecisionAnalysisId(scopedId);
    setDecisionPartA(String(result?.part_a || partA || ""));
    setDecisionPartB(
      multiColumns.length > 1
        ? multiColumns.map((column) => column.mpn).join(", ")
        : String(result?.part_b || partB || ""),
    );
    setDecision("hold_for_review");
    setReviewer(session?.email || "");
    setRationale("");
    setValidationChecks([]);
    setFollowUpAction("");
    setFollowUpOwner("");
    setFollowUpDueDate("");
    setResidualRisk("unknown");
    setDecisionError("");
    setDecisionSuccess(null);
    const multiReady =
      multiColumns.length <= 1
      || multiColumns.every((column) => columnMatchesScope(column, scopedId));
    setDecisionScopeStale(!multiReady);
    setDecisionScopeProgress("");
    setDecisionOpen(true);
  }

  async function recompareMultiCandidatesForScope(scopedId: string): Promise<MultiCompareColumn[]> {
    if (!session) throw new Error("Sign in to refresh the comparison scope.");
    const baseline = (decisionPartA || partA || String(result?.part_a || "")).trim();
    if (!baseline) throw new Error("Current part is required before refreshing BOM scope.");
    const brandA =
      manufacturerA.trim()
      || String(result?.manufacturer_a || "").trim()
      || "";
    const candidates = multiColumns.map((column) => ({
      mpn: column.mpn,
      manufacturer:
        column.manufacturer
        || manufacturerBByMpn[column.mpn]
        || candidateManufacturer(column)
        || manufacturerB.trim()
        || "",
    }));
    if (candidates.length < 2) {
      throw new Error("Multi-candidate scope refresh requires at least two candidates.");
    }
    const columnsSlot: Array<MultiCompareColumn | null> = candidates.map(() => null);
    const failures: string[] = [];
    let completed = 0;
    setDecisionScopeProgress(
      `Refreshing 0 of ${candidates.length} candidates for ${scopedId || "workspace-level"} scope…`,
    );
    await Promise.all(
      candidates.map(async (candidate, index) => {
        try {
          const data = await compareParts(
            session.access_token,
            baseline,
            candidate.mpn,
            scopedId || undefined,
            { a: datasheetA },
            {
              timeoutMs: COMPARE_PARTS_TIMEOUT_MS,
              manufacturerA: brandA || undefined,
              manufacturerB: candidate.manufacturer || undefined,
            },
          );
          const stamped: Record<string, unknown> = {
            ...data,
            analysis_id: scopedId || null,
            manufacturer_b: candidate.manufacturer || data.manufacturer_b || null,
          };
          if (!String(stamped.snapshot_token || "").trim()) {
            throw new Error(
              `Comparison for ${candidate.mpn} did not return a signed snapshot token.`,
            );
          }
          columnsSlot[index] = {
            mpn: candidate.mpn,
            manufacturer: candidate.manufacturer || undefined,
            result: stamped,
            rows: (stamped.rows || []) as Row[],
          };
        } catch (reason) {
          const detail =
            reason instanceof Error
              ? reason.message
              : `Comparison failed for ${candidate.mpn}.`;
          failures.push(`${candidate.mpn}: ${detail}`);
        } finally {
          completed += 1;
          setDecisionScopeProgress(
            `Refreshing ${completed} of ${candidates.length} candidates for ${scopedId || "workspace-level"} scope…`,
          );
        }
      }),
    );
    if (failures.length) {
      throw new Error(
        `Could not refresh every candidate under the selected scope. ${failures.join(" · ")}`,
      );
    }
    const ready = columnsSlot.filter(Boolean) as MultiCompareColumn[];
    if (ready.length !== candidates.length) {
      throw new Error("Multi-candidate scope refresh returned an incomplete comparison set.");
    }
    return ready;
  }

  async function changeDecisionAnalysis(nextAnalysisId: string) {
    if (!session) return;
    const previousAnalysisId = decisionAnalysisId;
    const previousColumns = multiColumns;
    const previousResult = result;
    const scopedId = nextAnalysisId.trim();
    setDecisionAnalysisId(scopedId);
    setAnalysisId(scopedId);
    if (!result) return;

    setDecisionBusy(true);
    setDecisionError("");
    setDecisionScopeStale(true);
    setDecisionScopeProgress("");
    try {
      if (multiColumns.length > 1) {
        // Never stamp a new analysis_id onto old tokens — re-compare every candidate.
        const refreshed = await recompareMultiCandidatesForScope(scopedId);
        setMultiColumns(refreshed);
        const primary =
          refreshed.find((column) => column.result.ok !== false)?.result
          || refreshed[0]?.result;
        if (primary) {
          setResult({
            ...(primary as Record<string, unknown>),
            analysis_id: scopedId || null,
          });
        }
        setDecisionScopeStale(false);
        setDecisionScopeProgress(
          `Refreshed ${refreshed.length} candidates under ${scopedId || "workspace-level"} scope.`,
        );
        return;
      }

      const data = await compareParts(
        session.access_token,
        decisionPartA || String(result.part_a || partA),
        decisionPartB.split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean)[0]
          || String(result.part_b || partB),
        scopedId || undefined,
        { a: datasheetA, b: datasheetB },
        {
          manufacturerA:
            manufacturerA.trim()
            || String(result.manufacturer_a || "").trim()
            || undefined,
          manufacturerB:
            manufacturerB.trim()
            || String(result.manufacturer_b || "").trim()
            || undefined,
        },
      );
      const normalized = {
        ...data,
        analysis_id: scopedId || null,
      };
      setResult(normalized);
      setAnalysisId(scopedId);
      setDecisionAnalysisId(scopedId);
      setDecisionScopeStale(false);
    } catch (err) {
      setDecisionAnalysisId(previousAnalysisId);
      setAnalysisId(previousAnalysisId);
      setMultiColumns(previousColumns);
      setResult(previousResult);
      setDecisionScopeStale(previousColumns.length > 1);
      setDecisionError(
        err instanceof Error
          ? err.message
          : "Could not refresh the comparison for that BOM scope.",
      );
    } finally {
      setDecisionBusy(false);
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
    setDecisionBusy(true);
    setDecisionError("");
    try {
      const primaryCandidate =
        multiColumns[0]?.mpn ||
        decisionPartB.trim().split(/[\n,;]+/).map((item) => item.trim()).filter(Boolean)[0] ||
        decisionPartB.trim();
      const resolvedManufacturerA =
        manufacturerA.trim()
        || String(result?.manufacturer_a || "").trim()
        || "";
      const resolvedManufacturerB =
        String(manufacturerBByMpn[primaryCandidate] || manufacturerB || "").trim()
        || String(result?.manufacturer_b || "").trim()
        || "";
      // Explicit decision-dialog BOM selection wins. Empty = workspace-level
      // (analysis_id=null) — never fall back to a stale comparison analysis_id.
      const scopedAnalysisId = decisionAnalysisId.trim() || null;
      const scopedKey = scopedAnalysisId || "";
      if (multiColumns.length > 1) {
        if (decisionScopeStale) {
          throw new Error(
            "Wait for every candidate to finish refreshing under the selected Project / BOM before recording this decision.",
          );
        }
        const incomplete = multiColumns.filter(
          (column) => !columnMatchesScope(column, scopedKey),
        );
        if (incomplete.length) {
          throw new Error(
            `Multi-candidate decision is incomplete for this scope. Re-select Project / BOM to refresh: ${incomplete.map((column) => column.mpn).join(", ")}.`,
          );
        }
      }
      const columnsForSnapshot = multiColumns.map((column) => ({
        ...column,
        manufacturer:
          column.manufacturer
          || manufacturerBByMpn[column.mpn]
          || candidateManufacturer(column)
          || undefined,
      }));
      const multiSnapshot: Record<string, unknown> | null =
        columnsForSnapshot.length > 1
          ? {
              ...buildMultiDecisionSnapshot(
                decisionPartA.trim() || partA.trim(),
                columnsForSnapshot,
              ),
              ok: true,
              part_a: decisionPartA.trim(),
              part_b: primaryCandidate,
              manufacturer_a: resolvedManufacturerA || null,
              manufacturer_b:
                String(
                  manufacturerBByMpn[primaryCandidate]
                  || columnsForSnapshot[0]?.manufacturer
                  || columnsForSnapshot[0]?.result?.manufacturer_b
                  || resolvedManufacturerB
                  || "",
                ).trim() || null,
              analysis_id: scopedAnalysisId,
            }
          : null;
      const resultMatchesDraft =
        result &&
        String(result.part_a || "").trim().toLowerCase() === decisionPartA.trim().toLowerCase() &&
        String(result.part_b || "").trim().toLowerCase() === primaryCandidate.toLowerCase() &&
        String(result.analysis_id || "") === String(scopedAnalysisId || "");
      const needsFreshCompare =
        !multiSnapshot && (Boolean(datasheetA || datasheetB) || !resultMatchesDraft);
      const comparison: Record<string, unknown> = multiSnapshot
        ? multiSnapshot
        : needsFreshCompare
          ? await compareParts(
              session.access_token,
              decisionPartA.trim(),
              primaryCandidate,
              scopedAnalysisId || undefined,
              { a: datasheetA, b: datasheetB },
              {
                manufacturerA: resolvedManufacturerA || undefined,
                manufacturerB: resolvedManufacturerB || undefined,
              },
            )
          : (result as Record<string, unknown>);
      const scopedComparison: Record<string, unknown> = {
        ...comparison,
        analysis_id: scopedAnalysisId,
      };
      setResult(scopedComparison);
      const snapshotManufacturerA =
        String(scopedComparison.manufacturer_a || resolvedManufacturerA || "").trim() || null;
      const snapshotManufacturerB =
        String(
          scopedComparison.manufacturer_b
          || manufacturerBByMpn[primaryCandidate]
          || resolvedManufacturerB
          || "",
        ).trim() || null;
      const response = await recordDecision(session.access_token, {
        analysis_id: scopedAnalysisId,
        part_a: decisionPartA.trim(),
        part_b: primaryCandidate,
        manufacturer_a: snapshotManufacturerA,
        manufacturer_b: snapshotManufacturerB,
        decision,
        reviewer,
        rationale,
        validation_checks: validationChecks,
        follow_up_action: followUpAction,
        follow_up_owner: followUpOwner,
        follow_up_due_date: followUpDueDate || null,
        residual_risk: residualRisk,
        // Reuse the on-screen comparison so the API skips a second full rebuild.
        comparison_snapshot: needsFreshCompare && !multiSnapshot ? null : {
          ...scopedComparison,
          analysis_id: scopedAnalysisId,
          manufacturer_a: snapshotManufacturerA,
          manufacturer_b: snapshotManufacturerB,
        },
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
  const reportOptions = [...reports];
  if (decisionAnalysisId && !reportOptions.some((row) => getAnalysisId(row) === decisionAnalysisId)) {
    reportOptions.unshift({ id: decisionAnalysisId, project_name: "Current comparison", bom_name: "Saved analysis context" });
  }
  const multiMatrix =
    multiColumns.length > 1
      ? buildMultiCompareMatrix(partA.trim() || text(result?.part_a), multiColumns)
      : [];
  const multiSourceRecords =
    multiColumns.length > 1
      ? buildMultiSourceRecords(partA.trim() || text(result?.part_a), multiColumns)
      : [];
  const isMultiCompare = multiMatrix.length > 0;

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
            <SecondaryLink href={replacementHref(
              String(result?.part_a || partA),
              String(result?.analysis_id || analysisId),
              String(result?.manufacturer_a || manufacturerA || ""),
            )}>Find a replacement</SecondaryLink>
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
            <label htmlFor="part-a">Current · design MPN</label>
            <input
              id="part-a"
              value={partA}
              onChange={(e) => setPartA(e.target.value)}
              placeholder="Manufacturer part number"
              autoComplete="off"
              required
            />
            <label htmlFor="manufacturer-a" style={{ marginTop: 10 }}>
              Current · manufacturer (identity constraint)
            </label>
            <input
              id="manufacturer-a"
              value={manufacturerA}
              onChange={(e) => setManufacturerA(e.target.value)}
              placeholder="e.g. Texas Instruments"
              autoComplete="organization"
            />
            <p className="cv-small-note" style={{ marginTop: 6 }}>
              Required for dual-source MPNs such as LM358N. Typed text constrains lookup; it is not identity proof by itself.
            </p>
          </div>
          <div className="cv-field">
            <label htmlFor="part-b">Candidate · MPN (1–4, comma or newline separated)</label>
            <textarea
              id="part-b"
              value={partB}
              onChange={(e) => setPartB(e.target.value)}
              placeholder={"One candidate, or up to four:\nLM358N, LM358P, LM358ADR2G"}
              autoComplete="off"
              required
              rows={3}
            />
            <label htmlFor="manufacturer-b" style={{ marginTop: 10 }}>
              Candidate · manufacturer (independent of Part A)
            </label>
            <input
              id="manufacturer-b"
              value={manufacturerB}
              onChange={(e) => setManufacturerB(e.target.value)}
              placeholder="Candidate brand when known"
              autoComplete="organization"
            />
            <p className="cv-small-note" style={{ marginTop: 6 }}>
              Multi-candidate mode builds one property matrix versus the current part. Each candidate brand stays independent of Part A and does not imply drop-in compatibility.
            </p>
          </div>
        </div>
        <div className="cv-compare-form-footer">
          <div>
            <div className="cv-field" style={{ marginBottom: 8, maxWidth: 420 }}>
              <label htmlFor="compare-bom-context">BOM context (optional)</label>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <select
                  id="compare-bom-context"
                  value={analysisId}
                  onChange={(event) => setAnalysisId(event.target.value)}
                  disabled={busy}
                  aria-describedby="compare-bom-help"
                >
                  <option value="">No BOM — standalone compare</option>
                  {reports.map((row) => {
                    const id = getAnalysisId(row);
                    return (
                      <option key={id} value={id}>
                        {reportLabel(row)}
                      </option>
                    );
                  })}
                </select>
                {analysisId ? (
                  <button
                    type="button"
                    className="cv-button secondary"
                    onClick={() => {
                      setAnalysisId("");
                      if (result) setResult({ ...result, analysis_id: null });
                      if (multiColumns.length) {
                        setMultiColumns(
                          multiColumns.map((column) => ({
                            ...column,
                            result: { ...column.result, analysis_id: null },
                          })),
                        );
                      }
                    }}
                    disabled={busy}
                  >
                    Clear BOM
                  </button>
                ) : null}
              </div>
              <p className="cv-small-note" id="compare-bom-help" style={{ marginTop: 6 }}>
                {analysisId
                  ? `BOM context attached: ${reportLabel(reports.find((row) => getAnalysisId(row) === analysisId) || { id: analysisId })}.`
                  : reportsError
                    ? `${reportsError} You can still compare without a saved BOM.`
                    : "Standalone compare unless a BOM is selected or handed off via analysis_id."}
              </p>
            </div>
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

      {busy ? (
        <LoadingCard
          label={
            progress
              ? formatCompareProgressLabel(progress, COMPARE_PARTS_TIMEOUT_MS)
              : "Comparing available part attributes and evidence…"
          }
        />
      ) : null}
      {!busy && progress && progress.failures.length ? (
        <div className="cv-card pad" role="status" style={{ marginBottom: 14 }}>
          <h3 className="cv-card-title">Bounded comparison failures</h3>
          <p className="cv-card-subtitle">
            Timeouts and request failures stay Needs verification. They are not a Compatible fit verdict and do not mean “no candidates.”
          </p>
          <ul className="cv-small-note" style={{ marginTop: 8, paddingLeft: 18 }}>
            {progress.failures.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
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
              ["a", "Current", result.part_a],
              ["b", "Candidate", result.part_b],
            ] as Array<[string, string, unknown]>).map(([key, heading, mpn]) => {
              const card = (key === "a" ? cards.a : cards.b) || {};
              const source = key === "a" ? result.source_a : result.source_b;
              const sourceRows = (key === "a" ? evidenceSources.part_a : evidenceSources.part_b) || [];
              const manufacturer = text(card.manufacturer, "Manufacturer not confirmed");
              const description = text(card.description, "No verified description available.");
              const lifecycle = text(card.lifecycle_status, "Not confirmed");
              const lifecycleConflict = Boolean(card.lifecycle_conflict);
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
                    <span className={`cv-badge ${lifecycleConflict ? "amber" : "gray"}`}>
                      {lifecycleConflict ? `${lifecycle} · conflict` : lifecycle}
                    </span>
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
                <span>
                  <strong>{text(evidenceCounts.compatible, "0")}</strong>{" "}
                  {Number(evidenceCounts.compatible) === 1 ? "verified match" : "verified matches"}
                </span>
                <span>
                  <strong>{text(evidenceCounts.listing_agreement, "0")}</strong>{" "}
                  {Number(evidenceCounts.listing_agreement) === 1
                    ? "catalog agreement"
                    : "catalog agreements"}
                </span>
                <span>
                  <strong>{text(evidenceCounts.material_difference, "0")}</strong>{" "}
                  {Number(evidenceCounts.material_difference) === 1
                    ? "material difference"
                    : "material differences"}
                </span>
                <span>
                  <strong>{text(evidenceCounts.needs_data, String(unknownRows.length))}</strong>{" "}
                  need verification
                </span>
              </div>
            </div>
            {isMultiCompare ? (
              <div className="cv-table-wrap" style={{ marginTop: 14 }}>
                <p className="cv-small-note" style={{ marginBottom: 10 }}>
                  Comparing {multiColumns.length} candidates against {text(partA || result?.part_a)}.
                  Each column keeps its own source, units/class, conditions, and unknown/conflict assessment.
                  This matrix does not imply drop-in compatibility or auto-approve any candidate.
                </p>
                <table className="cv-table cv-compare-multi-table">
                  <thead>
                    <tr>
                      <th>Property</th>
                      <th>
                        Current · {text(partA || result?.part_a)}
                        {manufacturerA.trim() || result?.manufacturer_a
                          ? ` · ${text(manufacturerA || result?.manufacturer_a)}`
                          : ""}
                      </th>
                      {multiColumns.map((column) => {
                        const brand =
                          column.manufacturer
                          || manufacturerBByMpn[column.mpn]
                          || candidateManufacturer(column);
                        return (
                          <th key={column.mpn} data-testid={`multi-col-${column.mpn}`}>
                            {formatCandidateHeading(column.mpn, brand)}
                          </th>
                        );
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {multiMatrix.map((row) => (
                      <tr key={row.attribute}>
                        <td>
                          <strong>{row.attribute}</strong>
                          {row.unit ? <div className="cv-small-note">{row.unit}</div> : null}
                        </td>
                        <td>
                          {row.current}
                          <div className="cv-small-note">Source: {row.currentSource}</div>
                          <div className="cv-small-note">
                            {row.currentClass} · {row.currentCondition}
                          </div>
                        </td>
                        {row.candidates.map((candidate) => (
                          <td key={`${row.attribute}-${candidate.mpn}`}>
                            {candidate.value}
                            <div className="cv-small-note">Source: {candidate.source}</div>
                            <div className="cv-small-note">
                              {candidate.valueClass} · {candidate.condition}
                            </div>
                            <div>
                              <span
                                className={`cv-compare-assessment${
                                  /need|unknown|conflict|unable|verif/i.test(candidate.assessment)
                                    ? " unknown"
                                    : ""
                                }`}
                              >
                                {candidate.assessment}
                              </span>
                            </div>
                            <div className="cv-small-note">{candidate.evidence}</div>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : rows.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 14 }}>
                <table className="cv-table cv-compare-table">
                  <thead>
                    <tr>
                      <th>Property</th>
                      <th>Current</th>
                      <th>Candidate</th>
                      <th>Sources</th>
                      <th>Class / condition</th>
                      <th>Assessment</th>
                      <th>Evidence / review note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={`${String(row.Attribute || "attr")}-${index}`}>
                        <td><strong>{text(row.Attribute || row.attribute)}</strong></td>
                        <td>
                          {text(row["Part A"] || row.part_a)}
                          {row["Part A MPN"] ? <div className="cv-small-note">{text(row["Part A MPN"])}</div> : null}
                          {row.Unit ? <div className="cv-small-note">{text(row.Unit)}</div> : null}
                        </td>
                        <td>
                          {text(row["Part B"] || row.part_b)}
                          {row["Part B MPN"] ? <div className="cv-small-note">{text(row["Part B MPN"])}</div> : null}
                        </td>
                        <td>
                          <div className="cv-small-note">A: {text(row["Part A source"], "Not stated")}</div>
                          <div className="cv-small-note">B: {text(row["Part B source"], "Not stated")}</div>
                        </td>
                        <td>
                          <div className="cv-small-note">
                            {text(row["Part A value class"], "unknown")} → {text(row["Part B value class"], "unknown")}
                          </div>
                          <div className="cv-small-note">
                            Part A: {text(row["Part A test condition"] || row["Test condition"], "Not stated")}
                          </div>
                          <div className="cv-small-note">
                            Part B: {text(row["Part B test condition"], "Not stated")}
                          </div>
                        </td>
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
              <p className="cv-card-subtitle">
                Review the exact MPN, source, retrieval details, and field-level evidence for Part A
                {isMultiCompare ? " and each candidate" : " and the candidate"} before documenting a decision.
              </p>
            </div>
            {isMultiCompare ? (
              <div className="cv-compare-evidence-grid" data-testid="multi-source-records">
                {multiSourceRecords.map((record) => (
                  <div
                    className="cv-compare-evidence-item"
                    key={`${record.side}-${record.mpn}`}
                    data-testid={`multi-evidence-${record.mpn}`}
                  >
                    <span className="cv-compare-part-label">
                      {record.side}
                      {record.manufacturer && !record.side.includes(record.manufacturer)
                        ? ` · ${record.manufacturer}`
                        : ""}
                      {" · "}
                      {record.mpn}
                      {" · "}
                      {record.sourceLabel}
                    </span>
                    {record.retrievalNotes.length ? (
                      <ul>
                        {record.retrievalNotes.map((note) => (
                          <li key={note}>{note}</li>
                        ))}
                      </ul>
                    ) : (
                      <p>No manufacturer datasheet or live supplier source was retrieved.</p>
                    )}
                    <details style={{ marginTop: 8 }}>
                      <summary>Field-level evidence ({record.fieldEvidence.length})</summary>
                      <ul>
                        {record.fieldEvidence.slice(0, 12).map((field) => (
                          <li key={`${record.mpn}-${field.attribute}`}>
                            <strong>{field.attribute}</strong>: {field.value}
                            <small>
                              {" "}
                              · {field.source} · {field.valueClass} · {field.condition} · {field.assessment}
                            </small>
                          </li>
                        ))}
                      </ul>
                    </details>
                  </div>
                ))}
              </div>
            ) : (
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
            )}
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
              <label className="cv-field cv-modal-project">
                <span>Project / BOM</span>
                <select
                  id="decision-bom-scope"
                  data-testid="decision-bom-scope"
                  value={decisionAnalysisId}
                  onChange={(event) => void changeDecisionAnalysis(event.target.value)}
                  disabled={decisionBusy}
                  aria-describedby="decision-bom-scope-help"
                >
                  <option value="">No BOM — workspace-level decision</option>
                  {reportOptions.map((row) => (
                    <option key={getAnalysisId(row)} value={getAnalysisId(row)}>
                      {reportLabel(row)}
                    </option>
                  ))}
                </select>
                <p className="cv-small-note" id="decision-bom-scope-help" style={{ marginTop: 6 }}>
                  {decisionAnalysisId
                    ? `Linked to BOM ${reportLabel(
                        reportOptions.find((row) => getAnalysisId(row) === decisionAnalysisId)
                        || { id: decisionAnalysisId },
                      )}.`
                    : "Workspace-level decision — not linked to a saved BOM. Saved with analysis_id unset."}
                </p>
                {decisionScopeProgress ? (
                  <p className="cv-small-note" data-testid="decision-scope-progress" style={{ marginTop: 6 }}>
                    {decisionScopeProgress}
                  </p>
                ) : null}
                {decisionScopeStale ? (
                  <p className="cv-error" role="status" data-testid="decision-scope-stale" style={{ marginTop: 6 }}>
                    Candidate comparisons for this Project / BOM are still refreshing. Recording is blocked until every candidate finishes under the selected scope.
                  </p>
                ) : null}
              </label>
              <div className="cv-modal-component-pair">
                <label className="cv-field">
                  <span>Current</span>
                  <input
                    value={decisionPartA}
                    onChange={(event) => setDecisionPartA(event.target.value)}
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
                    onChange={(event) => setDecisionPartB(event.target.value)}
                    maxLength={160}
                    placeholder="Candidate manufacturer part number"
                    autoComplete="off"
                    required
                  />
                </label>
              </div>

              <div className="cv-form-grid cv-form-grid-two cv-modal-grid">
                <label className="cv-field">
                  <span>Decision</span>
                  <select
                    value={decision}
                    onChange={(event) => setDecision(event.target.value)}
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
                  <span>Residual risk</span>
                  <select value={residualRisk} onChange={(event) => setResidualRisk(event.target.value)} disabled={decisionBusy}>
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
                  disabled={decisionBusy || decisionScopeStale || !decisionPartA.trim() || !decisionPartB.trim() || !reviewer.trim() || !rationale.trim() || (decision === "approve_alternate" && !APPROVAL_CHECKS.every((item) => validationChecks.includes(item))) || (["conditional_approval", "defer_for_validation"].includes(decision) && !followUpAction.trim()) || (decision === "accept_residual_risk" && residualRisk === "unknown")}
                >
                  {decisionBusy
                    ? (decisionScopeProgress ? "Refreshing candidates…" : "Saving comparison and decision…")
                    : "Record decision"}
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
