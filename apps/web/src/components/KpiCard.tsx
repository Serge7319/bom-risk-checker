import type { ReactNode } from "react";
import { Icon, type IconName } from "@/components/Icons";

type Tone = "default" | "blue" | "amber";

export function KpiCard({
  label,
  value,
  detail,
  icon,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  icon: IconName;
  tone?: Tone;
}) {
  const toneClass =
    tone === "blue" ? " tone-blue" : tone === "amber" ? " tone-amber" : "";
  return (
    <div className={`cv-kpi${toneClass}`}>
      <div className="cv-kpi-head">
        <span>{label}</span>
        <span className="cv-kpi-icon" aria-hidden="true">
          <Icon name={icon} />
        </span>
      </div>
      <strong>{value}</strong>
      {detail != null ? <em>{detail}</em> : null}
    </div>
  );
}
