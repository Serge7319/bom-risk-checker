import type { ReactNode } from "react";
import { Icon, type IconName } from "@/components/Icons";

type Tone = "default" | "blue" | "amber" | "red" | "green";
type ChipTone = "blue" | "amber" | "red" | "green" | "gray";

export function KpiCard({
  label,
  value,
  detail,
  icon,
  tone = "default",
  status,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  icon: IconName;
  tone?: Tone;
  status?: { label: string; tone: ChipTone };
}) {
  const toneClass = tone === "default" ? "" : ` tone-${tone}`;
  return (
    <div className={`cv-kpi${toneClass}`}>
      <div className="cv-kpi-head">
        <span>{label}</span>
        <span className="cv-kpi-icon" aria-hidden="true">
          <Icon name={icon} />
        </span>
      </div>
      <strong>{value}</strong>
      {status ? (
        <em className="cv-kpi-footnote cv-kpi-footnote--status">
          <span className={`cv-kpi-status-chip cv-kpi-status-chip--${status.tone}`}>{status.label}</span>
          {detail != null ? <span className="cv-kpi-detail-text">{detail}</span> : null}
        </em>
      ) : detail != null ? <em>{detail}</em> : null}
    </div>
  );
}
