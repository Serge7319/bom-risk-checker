"use client";

import { useState } from "react";
import { fetchReport, listReports, type Report } from "@/lib/api";

type PartSummary = {
  mpn: string;
  quantity: number | null;
  manufacturer: string;
  description: string;
  risk: string;
  lifecycle: string;
};

type DiffRow = {
  kind: "Added" | "Removed" | "Changed";
  mpn: string;
  details: string[];
  newBlocker: boolean;
};

function text(value: unknown): string {
  return String(value ?? "").trim();
}

function reportId(row: Record<string, unknown>): string {
  return text(row.analysis_id || row.id);
}

function keyForMpn(value: string): string {
  return value.toLocaleLowerCase().replace(/\s+/g, "");
}

function firstPartValue(part: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = text(part[key]);
    if (value) return value;
  }
  return "";
}

function quantityOf(part: Record<string, unknown>): number | null {
  for (const key of ["effective_quantity", "Quantity per Parent", "quantity_per_parent", "Quantity", "quantity"]) {
    const raw = part[key];
    if (raw === null || raw === undefined || text(raw) === "") continue;
    const value = Number(raw);
    if (Number.isFinite(value)) return value;
  }
  return null;
}

function summarizeParts(parts: Array<Record<string, unknown>>): Map<string, PartSummary> {
  const result = new Map<string, PartSummary>();
  for (const part of parts || []) {
    const mpn = firstPartValue(part, "MPN", "mpn", "manufacturer_part_number");
    const key = keyForMpn(mpn);
    if (!key) continue;
    const current = result.get(key);
    const quantity = quantityOf(part);
    const manufacturer = firstPartValue(part, "Manufacturer", "manufacturer");
    const description = firstPartValue(part, "Description", "description");
    const risk = firstPartValue(part, "Risk Level", "risk_level", "risk_level_display", "Risk", "risk");
    const lifecycle = firstPartValue(part, "Lifecycle", "lifecycle", "lifecycle_status");
    if (!current) {
      result.set(key, { mpn, quantity, manufacturer, description, risk, lifecycle });
      continue;
    }
    if (quantity !== null) current.quantity = (current.quantity ?? 0) + quantity;
    if (manufacturer && !current.manufacturer.toLowerCase().split("; ").includes(manufacturer.toLowerCase())) {
      current.manufacturer = [current.manufacturer, manufacturer].filter(Boolean).join("; ");
    }
    if (description && !current.description.toLowerCase().split("; ").includes(description.toLowerCase())) {
      current.description = [current.description, description].filter(Boolean).join("; ");
    }
    if (riskRank(risk) < riskRank(current.risk)) current.risk = risk;
    if (!current.lifecycle && lifecycle) current.lifecycle = lifecycle;
  }
  return result;
}

function riskRank(value: string): number {
  const normalized = value.toLowerCase();
  if (normalized.includes("critical")) return 0;
  if (normalized.includes("high")) return 1;
  if (normalized.includes("medium")) return 2;
  if (normalized.includes("low") || normalized.includes("healthy")) return 3;
  return 4;
}

function isBlocker(value: string): boolean {
  return riskRank(value) <= 1;
}

function revisionDiff(previous: Report, current: Report): DiffRow[] {
  const before = summarizeParts(previous.parts || []);
  const after = summarizeParts(current.parts || []);
  const keys = new Set([...before.keys(), ...after.keys()]);
  const rows: DiffRow[] = [];
  for (const key of keys) {
    const oldPart = before.get(key);
    const newPart = after.get(key);
    if (!oldPart && newPart) {
      rows.push({
        kind: "Added",
        mpn: newPart.mpn,
        details: [
          newPart.quantity === null ? "Quantity not reported" : `Quantity ${newPart.quantity}`,
          newPart.manufacturer ? `Manufacturer ${newPart.manufacturer}` : "Manufacturer not reported",
          newPart.risk ? `Risk ${newPart.risk}` : "Risk not assessed",
        ],
        newBlocker: isBlocker(newPart.risk),
      });
      continue;
    }
    if (oldPart && !newPart) {
      rows.push({
        kind: "Removed",
        mpn: oldPart.mpn,
        details: [oldPart.quantity === null ? "Removed from BOM" : `Removed · prior quantity ${oldPart.quantity}`],
        newBlocker: false,
      });
      continue;
    }
    if (!oldPart || !newPart) continue;
    const details: string[] = [];
    if (oldPart.quantity !== newPart.quantity) {
      details.push(`Quantity ${oldPart.quantity ?? "—"} → ${newPart.quantity ?? "—"}`);
    }
    if (oldPart.manufacturer !== newPart.manufacturer) {
      details.push(`Manufacturer ${oldPart.manufacturer || "—"} → ${newPart.manufacturer || "—"}`);
    }
    if (oldPart.description !== newPart.description) {
      details.push(`Description ${oldPart.description || "—"} → ${newPart.description || "—"}`);
    }
    if (oldPart.risk !== newPart.risk) details.push(`Risk ${oldPart.risk || "—"} → ${newPart.risk || "—"}`);
    if (oldPart.lifecycle !== newPart.lifecycle) details.push(`Lifecycle ${oldPart.lifecycle || "—"} → ${newPart.lifecycle || "—"}`);
    if (details.length) {
      rows.push({ kind: "Changed", mpn: newPart.mpn, details, newBlocker: !isBlocker(oldPart.risk) && isBlocker(newPart.risk) });
    }
  }
  const order = { Added: 0, Changed: 1, Removed: 2 } as const;
  return rows.sort((a, b) => order[a.kind] - order[b.kind] || a.mpn.localeCompare(b.mpn));
}

function dateTime(value: unknown): number | null {
  const parsed = Date.parse(String(value || ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function displayRevision(report: Report): string {
  const revision = text(report.revision);
  return revision ? `Rev ${revision}` : "Saved revision";
}

export function RevisionDiff({ report, token }: { report: Report; token: string }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [previous, setPrevious] = useState<Report | null>(null);
  const [diff, setDiff] = useState<DiffRow[] | null>(null);
  const [searched, setSearched] = useState(false);

  async function comparePrevious() {
    if (loading || !token) return;
    setLoading(true);
    setError("");
    setSearched(true);
    try {
      const currentId = String(report.analysis_id || report.id || "");
      const bomId = String(report.bom_id || "");
      if (!bomId) throw new Error("This report is not attached to a saved BOM revision history.");
      const { reports } = await listReports(token);
      const currentTime = dateTime(report.created_at);
      const siblings = (reports || [])
        .filter((row) => String(row.bom_id || "") === bomId && reportId(row) !== currentId)
        .map((row, index) => ({ row, index, time: dateTime(row.created_at) }))
        .filter((item) => currentTime === null || item.time === null || item.time < currentTime)
        .sort((a, b) => {
          if (a.time !== null && b.time !== null && a.time !== b.time) return b.time - a.time;
          return a.index - b.index;
        });
      const candidate = siblings[0]?.row;
      if (!candidate) {
        setPrevious(null);
        setDiff([]);
        return;
      }
      const loaded = await fetchReport(reportId(candidate), token);
      setPrevious(loaded);
      setDiff(revisionDiff(loaded, report));
    } catch (err) {
      setError(err instanceof Error ? err.message : "The previous revision could not be compared.");
      setPrevious(null);
      setDiff(null);
    } finally {
      setLoading(false);
    }
  }

  const added = diff?.filter((row) => row.kind === "Added").length ?? 0;
  const removed = diff?.filter((row) => row.kind === "Removed").length ?? 0;
  const changed = diff?.filter((row) => row.kind === "Changed").length ?? 0;
  const blockers = diff?.filter((row) => row.newBlocker).length ?? 0;

  return (
    <section className="cv-card pad" style={{ marginBottom: 14 }} data-testid="revision-diff">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h2 className="cv-card-title">BOM revision comparison</h2>
          <p className="cv-card-subtitle">Compare this report with the nearest earlier revision of the same saved BOM. Added and removed MPNs, changed fields, and newly high-risk parts are called out.</p>
        </div>
        <button type="button" className="cv-button secondary" onClick={() => void comparePrevious()} disabled={loading || !token}>
          {loading ? "Comparing revisions…" : searched ? "Compare again" : "Compare with previous revision"}
        </button>
      </div>
      {error ? <p className="cv-error" role="alert" style={{ marginTop: 12 }}>{error}</p> : null}
      {searched && !error && !previous ? <p className="cv-small-note" role="status" style={{ marginTop: 12 }}>No earlier saved revision was found for this BOM.</p> : null}
      {previous && diff ? (
        <div style={{ marginTop: 14 }}>
          <p className="cv-small-note" style={{ margin: "0 0 10px" }}>
            Comparing {displayRevision(previous)} with {displayRevision(report)}. Rows are grouped by normalized MPN; duplicate MPN quantities are summed.
          </p>
          <div className="cv-public-audit-metrics" aria-label="Revision change counts">
            <div><strong>{added}</strong><span>Added</span></div>
            <div><strong>{removed}</strong><span>Removed</span></div>
            <div><strong>{changed}</strong><span>Changed</span></div>
            <div><strong>{blockers}</strong><span>New high-risk parts</span></div>
          </div>
          {diff.length ? (
            <div className="cv-table-wrap" style={{ marginTop: 12 }}>
              <table className="cv-table">
                <thead><tr><th>Change</th><th>MPN</th><th>Details</th><th>Risk change</th></tr></thead>
                <tbody>
                  {diff.map((row) => (
                    <tr key={`${row.kind}-${keyForMpn(row.mpn)}`}>
                      <td><span className={`cv-badge ${row.kind === "Added" ? "blue" : row.kind === "Removed" ? "gray" : "amber"}`}>{row.kind}</span></td>
                      <td><strong>{row.mpn}</strong></td>
                      <td>{row.details.join(" · ")}</td>
                      <td>{row.newBlocker ? <span className="cv-badge red">New high risk</span> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="cv-success-note" role="status">No MPN or tracked report fields changed. No new high-risk parts were found.</p>}
        </div>
      ) : null}
    </section>
  );
}
