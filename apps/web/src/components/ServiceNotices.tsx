"use client";

import { useEffect, useState } from "react";
import type { PublicServiceStatus } from "@/lib/api";

function plannedWindow(start: string | null | undefined, end: string | null | undefined): string | null {
  if (!start || !end || !Number.isFinite(Date.parse(start)) || !Number.isFinite(Date.parse(end))) {
    return null;
  }
  if (Date.parse(end) <= Date.now()) return null;
  const formatter = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
  return `${formatter.format(new Date(start))} – ${formatter.format(new Date(end))}`;
}

export function ServiceNotices({
  status,
  showUnavailable = false,
}: {
  status: PublicServiceStatus | null;
  showUnavailable?: boolean;
}) {
  const [windowLabel, setWindowLabel] = useState("");
  const startsAt = status?.planned_maintenance_starts_at;
  const endsAt = status?.planned_maintenance_ends_at;

  useEffect(() => {
    const refresh = () => setWindowLabel(plannedWindow(startsAt, endsAt) || "");
    refresh();
    const timer = window.setInterval(refresh, 30_000);
    return () => window.clearInterval(timer);
  }, [startsAt, endsAt]);

  if (!status) return null;
  const message = status.planned_maintenance_message.trim();

  return (
    <div className="cv-service-notices">
      {showUnavailable && status.maintenance_mode ? (
        <section className="cv-service-notice is-unavailable" role="alert">
          <strong>Cadivor workspace access is temporarily paused.</strong>
          <p>{status.maintenance_message || "Cadivor is undergoing maintenance. Please try again shortly."}</p>
          <small>Your sign-in details and saved analyses remain safe. Workspace access will return when maintenance mode is turned off.</small>
        </section>
      ) : null}
      {!status.maintenance_mode && message && windowLabel ? (
        <section className="cv-service-notice is-planned" role="status">
          <strong>Planned maintenance · {windowLabel}</strong>
          <p>{message}</p>
          <small>This is an informational notice. It does not change or block account access.</small>
        </section>
      ) : null}
    </div>
  );
}
