import type { BomReviewProgress, BomValidationPreview } from "@/lib/bomDraft";
import type { AnalyzeSummary } from "@/lib/api";

export const ANALYSIS_STAGES = ["Received", "Validating", "Analyzing"] as const;
export const ENGINEERING_STAGES = ["Risks", "Evidence", "Decision", "Monitor"] as const;
export const WORKFLOW_STAGES = [...ANALYSIS_STAGES, ...ENGINEERING_STAGES] as const;

export type WorkflowStage = (typeof WORKFLOW_STAGES)[number];
export type StageStatus = "complete" | "current" | "next" | "blocked" | "error";

export type WorkflowContext = {
  hasFile: boolean;
  validating: boolean;
  validation: BomValidationPreview | null;
  validationError: string;
  analyzing: boolean;
  analyzeError: string;
  summary: AnalyzeSummary | null;
  analysisId: string | null;
  review: BomReviewProgress | null;
  hasDecisionRecord: boolean;
  monitoringAvailable: boolean;
};

export type StageView = {
  id: WorkflowStage;
  group: "analysis" | "engineering";
  status: StageStatus;
  explanation: string;
  nextAction: string;
};

export type WorkflowGuide = {
  stages: StageView[];
  currentStage: WorkflowStage;
  announcement: string;
  primaryCta: {
    label: string;
    href?: string;
    action?: "analyze" | "choose-file" | "retry-validate" | "retry-analyze" | "clear-error";
    disabled?: boolean;
  };
};

function statusFor(
  stage: WorkflowStage,
  current: WorkflowStage,
  completed: Set<WorkflowStage>,
  errored: Set<WorkflowStage>,
  blocked: Set<WorkflowStage>,
): StageStatus {
  if (errored.has(stage)) return "error";
  if (completed.has(stage)) return "complete";
  if (stage === current) return "current";
  if (blocked.has(stage)) return "blocked";
  return "next";
}

export function buildWorkflowGuide(ctx: WorkflowContext): WorkflowGuide {
  const completed = new Set<WorkflowStage>();
  const errored = new Set<WorkflowStage>();
  const blocked = new Set<WorkflowStage>();

  const canAnalyze = Boolean(ctx.validation?.can_analyze);
  const hasSummary = Boolean(ctx.summary || ctx.analysisId);
  const risksOpened = Boolean(ctx.review?.risksOpenedAt);
  const evidenceReviewed = Boolean(ctx.review?.evidenceReviewedAt);
  const decisionDone = Boolean(ctx.hasDecisionRecord || ctx.review?.decisionRecordedAt);
  const monitorOpened = Boolean(ctx.review?.monitorOpenedAt);
  const reportId = String(ctx.analysisId || ctx.summary?.analysis_id || "");

  if (ctx.hasFile) completed.add("Received");
  if (canAnalyze || hasSummary) completed.add("Validating");
  if (hasSummary) {
    completed.add("Received");
    completed.add("Validating");
    completed.add("Analyzing");
  }
  if (risksOpened) completed.add("Risks");
  if (evidenceReviewed) completed.add("Evidence");
  if (decisionDone) completed.add("Decision");
  if (monitorOpened) completed.add("Monitor");

  if (
    ctx.hasFile &&
    !ctx.validating &&
    !hasSummary &&
    (ctx.validationError || (ctx.validation && !ctx.validation.can_analyze))
  ) {
    errored.add("Validating");
  }
  if (ctx.analyzeError && !ctx.analyzing && !hasSummary) {
    errored.add("Analyzing");
  }

  if (!ctx.hasFile) {
    for (const stage of WORKFLOW_STAGES) {
      if (stage !== "Received") blocked.add(stage);
    }
  } else if (!canAnalyze && !hasSummary) {
    blocked.add("Analyzing");
    blocked.add("Risks");
    blocked.add("Evidence");
    blocked.add("Decision");
    blocked.add("Monitor");
  } else if (!hasSummary) {
    blocked.add("Risks");
    blocked.add("Evidence");
    blocked.add("Decision");
    blocked.add("Monitor");
  } else if (!risksOpened) {
    blocked.add("Evidence");
    blocked.add("Decision");
    blocked.add("Monitor");
  } else if (!evidenceReviewed) {
    blocked.add("Decision");
    blocked.add("Monitor");
  } else if (!decisionDone) {
    blocked.add("Monitor");
  }

  let current: WorkflowStage = "Received";
  if (ctx.analyzing) {
    current = "Analyzing";
  } else if (ctx.validating) {
    current = "Validating";
  } else if (!ctx.hasFile) {
    current = "Received";
  } else if (!canAnalyze && !hasSummary) {
    current = "Validating";
  } else if (ctx.analyzeError && !hasSummary) {
    current = "Analyzing";
  } else if (!hasSummary) {
    current = "Analyzing";
  } else if (!risksOpened) {
    current = "Risks";
  } else if (!evidenceReviewed) {
    current = "Evidence";
  } else if (!decisionDone) {
    current = "Decision";
  } else {
    current = "Monitor";
  }

  const explanations: Record<WorkflowStage, string> = {
    Received: ctx.hasFile
      ? "BOM file is selected and kept for this draft."
      : "Choose a CSV or XLSX BOM to begin. You can leave anytime and resume later.",
    Validating: ctx.validating
      ? "Checking columns, row counts, and required fields."
      : canAnalyze || hasSummary
        ? `Validated ${ctx.validation?.unique_part_count ?? ctx.summary?.total_parts ?? 0} parts across ${ctx.validation?.row_count ?? 0} rows.`
        : ctx.validation
          ? "Fix the listed validation issues before analysis can run."
          : "Validation starts after a file is selected.",
    Analyzing: ctx.analyzing
      ? "Running the existing BOM risk analysis and saving the report."
      : hasSummary
        ? "Analysis finished and the report is saved in this workspace."
        : ctx.analyzeError
          ? "Analysis did not finish. Your file and project details are still here."
          : "Analysis runs only after required validation passes.",
    Risks: hasSummary
      ? risksOpened
        ? "Saved risk report has been opened."
        : "Review high and medium risks in the saved report."
      : "Opens after a successful analysis.",
    Evidence: evidenceReviewed
      ? "Evidence labels on this report have been reviewed."
      : "Check evidence source labels before acting on a risk.",
    Decision: decisionDone
      ? "At least one engineering decision is recorded for this BOM."
      : "Record an engineering decision when a replacement or keep decision is made.",
    Monitor: !ctx.monitoringAvailable
      ? "Derived monitoring signals are available; scheduled refresh and email alerts are currently disabled."
      : monitorOpened
        ? "Monitoring view opened for this analysis."
        : "Watch lifecycle and stock signals derived from the saved analysis.",
  };

  const nextActions: Record<WorkflowStage, string> = {
    Received: ctx.hasFile ? "Continue to validation results." : "Select a BOM file.",
    Validating: canAnalyze
      ? "Run analysis when ready."
      : "Resolve required validation errors, then analyze.",
    Analyzing: hasSummary
      ? "Open the saved risk report."
      : ctx.analyzing
        ? "Stay on this page or leave — the request continues in this browser session."
        : "Start analysis after validation passes.",
    Risks: "Open the saved report and review risk counts.",
    Evidence: "Review evidence labels on component rows.",
    Decision: "Open Decision queue or Compare parts to record a decision.",
    Monitor: ctx.monitoringAvailable
      ? "Open Monitoring for this analysis."
      : "Open Monitoring for derived signals (scheduled alerts unavailable).",
  };

  const stages: StageView[] = WORKFLOW_STAGES.map((id) => ({
    id,
    group: (ANALYSIS_STAGES as readonly string[]).includes(id) ? "analysis" : "engineering",
    status: statusFor(id, current, completed, errored, blocked),
    explanation: explanations[id],
    nextAction: nextActions[id],
  }));

  let primaryCta: WorkflowGuide["primaryCta"];
  if (!ctx.hasFile) {
    primaryCta = { label: "Choose BOM file", action: "choose-file" };
  } else if (ctx.validating) {
    primaryCta = { label: "Validating…", disabled: true };
  } else if (ctx.validation && !ctx.validation.can_analyze && !hasSummary) {
    primaryCta = { label: "Fix file and re-check", action: "choose-file" };
  } else if (ctx.analyzing) {
    primaryCta = { label: "Analysis in progress…", disabled: true };
  } else if (ctx.analyzeError && !hasSummary) {
    primaryCta = { label: "Retry analysis", action: "retry-analyze" };
  } else if (hasSummary && !risksOpened) {
    primaryCta = {
      label: "Open saved risk report",
      href: `/reports/${encodeURIComponent(reportId)}`,
    };
  } else if (hasSummary && risksOpened && !evidenceReviewed) {
    primaryCta = {
      label: "Review evidence on report",
      href: `/reports/${encodeURIComponent(reportId)}#report-evidence`,
    };
  } else if (hasSummary && evidenceReviewed && !decisionDone) {
    primaryCta = {
      label: "Open Decision queue",
      href: "/engineering-decisions",
    };
  } else if (hasSummary) {
    primaryCta = {
      label: "Open Monitoring",
      href: "/monitoring",
    };
  } else if (canAnalyze) {
    primaryCta = { label: "Analyze BOM", action: "analyze" };
  } else {
    primaryCta = { label: "Choose BOM file", action: "choose-file" };
  }

  const currentView = stages.find((stage) => stage.id === current)!;
  const announcement = `${current} is current. ${currentView.explanation} Next: ${currentView.nextAction}`;

  return { stages, currentStage: current, announcement, primaryCta };
}
