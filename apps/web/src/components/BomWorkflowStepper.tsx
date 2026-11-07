"use client";

import type { WorkflowGuide, WorkflowStage } from "@/lib/bomWorkflow";

const STATUS_LABEL: Record<string, string> = {
  complete: "Complete",
  current: "Current",
  next: "Next",
  blocked: "Blocked",
  error: "Error",
};

type Props = {
  guide: WorkflowGuide;
  analyzing?: boolean;
};

export function BomWorkflowStepper({ guide, analyzing = false }: Props) {
  const current = guide.stages.find((stage) => stage.id === guide.currentStage);

  return (
    <section
      className="cv-bom-workflow"
      aria-label="BOM workflow progress"
    >
      <div className="cv-bom-workflow-groups" aria-hidden={false}>
        <div className="cv-bom-workflow-group">
          <p className="cv-bom-workflow-group-label">Analysis</p>
          <ol className="cv-bom-stages" aria-label="Analysis stages">
            {guide.stages
              .filter((stage) => stage.group === "analysis")
              .map((stage) => (
                <StageItem key={stage.id} stage={stage} currentId={guide.currentStage} />
              ))}
          </ol>
        </div>
        <div className="cv-bom-workflow-group">
          <p className="cv-bom-workflow-group-label">Engineering workflow</p>
          <ol className="cv-bom-stages cv-bom-stages--engineering" aria-label="Engineering stages">
            {guide.stages
              .filter((stage) => stage.group === "engineering")
              .map((stage) => (
                <StageItem key={stage.id} stage={stage} currentId={guide.currentStage} />
              ))}
          </ol>
        </div>
      </div>

      <div
        className={`cv-bom-progress${analyzing ? " is-indeterminate" : ""}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={analyzing ? "Analysis in progress" : `${STATUS_LABEL[current?.status || "next"]}: ${guide.currentStage}`}
        aria-label="Workflow progress"
      >
        <i />
      </div>

      <div className="cv-bom-workflow-status" aria-live="polite" aria-atomic="true">
        <p className="cv-bom-workflow-current">
          <span className="cv-bom-workflow-current-label">Current stage</span>
          <strong>{guide.currentStage}</strong>
          <span className={`cv-bom-stage-pill is-${current?.status || "next"}`}>
            {STATUS_LABEL[current?.status || "next"]}
          </span>
        </p>
        <p className="cv-bom-workflow-explain">{current?.explanation}</p>
        <p className="cv-bom-workflow-next">
          <span>Next useful action</span>
          {current?.nextAction}
        </p>
        <p className="cv-visually-hidden">{guide.announcement}</p>
      </div>
    </section>
  );
}

function StageItem({
  stage,
  currentId,
}: {
  stage: { id: WorkflowStage; status: string; explanation: string };
  currentId: WorkflowStage;
}) {
  const isCurrent = stage.id === currentId;
  return (
    <li
      className={`cv-bom-stage is-${stage.status}${isCurrent ? " is-current" : ""}`}
      aria-current={isCurrent ? "step" : undefined}
    >
      <span className="cv-bom-stage-name">{stage.id}</span>
      <span className="cv-bom-stage-status">{STATUS_LABEL[stage.status] || stage.status}</span>
    </li>
  );
}
