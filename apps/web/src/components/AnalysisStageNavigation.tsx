import Link from "next/link";

export type AnalysisStage = "risks" | "evidence" | "decision" | "monitor";

const stages: Array<{ id: AnalysisStage; label: string; path: string }> = [
  { id: "risks", label: "Risks", path: "/detailed-risk-report" },
  { id: "evidence", label: "Evidence", path: "/evidence-review" },
  { id: "decision", label: "Decision", path: "/engineering-decisions" },
  { id: "monitor", label: "Monitor", path: "/monitoring" },
];

export function AnalysisStageNavigation({
  analysisId,
  current,
}: {
  analysisId: string;
  current: AnalysisStage;
}) {
  if (!analysisId) return null;

  return (
    <nav className="cv-analysis-stage-nav" aria-label="Review this analysis">
      {stages.map((stage) => {
        const href = `${stage.path}?analysis_id=${encodeURIComponent(analysisId)}`;
        const active = stage.id === current;
        return (
          <Link
            key={stage.id}
            href={href}
            className={active ? "is-active" : undefined}
            aria-current={active ? "page" : undefined}
          >
            {stage.label}
          </Link>
        );
      })}
    </nav>
  );
}
