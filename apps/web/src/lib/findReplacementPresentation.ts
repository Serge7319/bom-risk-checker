/**
 * Presentation helpers for Find a replacement empty/candidate states.
 * Does not change the search algorithm — only formats API discovery for the UI.
 */

export type ProviderChannelStatus =
  | "not_configured"
  | "failed"
  | "timeout"
  | "searched_no_results"
  | "returned_results"
  | "not_supported"
  | "unknown";

export type ProviderStatusRow = {
  name: string;
  channel: "lookup" | "catalog" | "substitutions" | "family_search" | "parametric_search" | "overall";
  status: ProviderChannelStatus;
  label: string;
  message: string;
};

export type FindReplacementViewModel = {
  emptyHeadline: string;
  emptyDetail: string;
  providerRows: ProviderStatusRow[];
  missingEvidence: string[];
  gap: string;
  candidatesUnverifiedNote: string;
};

const SECRET_PATTERN =
  /\b(api[_-]?key|client[_-]?secret|client[_-]?id|password|token|authorization|bearer|secret)\b\s*[:=]\s*["']?[^\s"',;]+/gi;
const BEARER_PATTERN = /\bBearer\s+[A-Za-z0-9\-._~+/]+=*/gi;

export function redactCredentialValues(message: string): string {
  let text = String(message || "");
  text = text.replace(SECRET_PATTERN, "$1=<redacted>");
  text = text.replace(BEARER_PATTERN, "Bearer <redacted>");
  // Drop long opaque tokens that look like credentials.
  text = text.replace(/\b[A-Za-z0-9_\-]{32,}\b/g, "<redacted>");
  return text.trim();
}

function normalizeStatus(value: unknown): string {
  return String(value || "").trim().toLowerCase();
}

function classifyChannelStatus(raw: string, count?: number): ProviderChannelStatus {
  const status = normalizeStatus(raw);
  if (!status || status === "not_requested") return "unknown";
  if (status === "not_configured") return "not_configured";
  if (status === "timeout") return "timeout";
  if (status === "error" || status === "failed" || status === "rate_limited") return "failed";
  if (status === "not_supported") return "not_supported";
  if (status === "ok" || status === "available") {
    return typeof count === "number" && count > 0 ? "returned_results" : "searched_no_results";
  }
  return "unknown";
}

function statusLabel(status: ProviderChannelStatus): string {
  switch (status) {
    case "not_configured":
      return "Not configured";
    case "failed":
      return "Failed";
    case "timeout":
      return "Timed out";
    case "searched_no_results":
      return "Searched — no results";
    case "returned_results":
      return "Returned results";
    case "not_supported":
      return "Not supported by provider";
    default:
      return "Status unavailable";
  }
}

function channelCount(status: Record<string, unknown>, channel: string): number | undefined {
  if (channel === "catalog") {
    const n = Number(status.catalog_count);
    return Number.isFinite(n) ? n : undefined;
  }
  if (channel === "substitutions") {
    const n = Number(status.explicit_count);
    return Number.isFinite(n) ? n : undefined;
  }
  if (channel === "parametric_search") {
    const n = Number(status.parametric_count);
    return Number.isFinite(n) ? n : undefined;
  }
  return undefined;
}

/** Build per-provider status rows from discovery.providers. */
export function providerStatusRows(discovery: unknown): ProviderStatusRow[] {
  if (!discovery || typeof discovery !== "object") return [];
  const providers = (discovery as Record<string, unknown>).providers;
  if (!providers || typeof providers !== "object") return [];

  const rows: ProviderStatusRow[] = [];
  for (const [name, raw] of Object.entries(providers as Record<string, unknown>)) {
    if (!raw || typeof raw !== "object") continue;
    const status = raw as Record<string, unknown>;
    const message = redactCredentialValues(String(status.message || ""));
    const channels: Array<{
      key: ProviderStatusRow["channel"];
      rawKey: string;
    }> = [
      { key: "lookup", rawKey: "lookup" },
      { key: "substitutions", rawKey: "substitutions" },
      { key: "catalog", rawKey: "catalog" },
      { key: "family_search", rawKey: "family_search" },
      { key: "parametric_search", rawKey: "parametric_search" },
    ];

    let emitted = false;
    for (const channel of channels) {
      const rawStatus = normalizeStatus(status[channel.rawKey]);
      if (!rawStatus || rawStatus === "not_requested") continue;
      const classified = classifyChannelStatus(rawStatus, channelCount(status, channel.rawKey));
      rows.push({
        name,
        channel: channel.key,
        status: classified,
        label: `${statusLabel(classified)} (${channel.key.replace(/_/g, " ")})`,
        message,
      });
      emitted = true;
    }

    if (!emitted) {
      // Fall back to an overall row when only a message / incomplete flag exists.
      const overall = classifyChannelStatus(
        String(status.lookup || status.catalog || status.substitutions || "unknown"),
      );
      rows.push({
        name,
        channel: "overall",
        status: overall,
        label: statusLabel(overall),
        message,
      });
    }
  }
  return rows;
}

export function buildFindReplacementViewModel(
  result: Record<string, unknown> | null | undefined,
): FindReplacementViewModel {
  const discovery = result?.discovery;
  const providerRows = providerStatusRows(discovery);
  const missingEvidence = (
    Array.isArray(result?.missing_evidence) ? result!.missing_evidence : []
  )
    .map((item) => redactCredentialValues(String(item || "")))
    .filter(Boolean);
  const gap = redactCredentialValues(String(result?.gap || "").trim());

  const anyConfiguredSearch = providerRows.some(
    (row) =>
      row.status === "searched_no_results" ||
      row.status === "returned_results" ||
      row.status === "failed" ||
      row.status === "timeout",
  );
  const onlyUnconfigured =
    providerRows.length > 0 &&
    providerRows.every(
      (row) => row.status === "not_configured" || row.status === "not_supported" || row.status === "unknown",
    );

  let emptyHeadline = "No candidates were returned by the available sources.";
  let emptyDetail =
    "This does not confirm that no replacement exists. Review supplier coverage below, then check manufacturer documentation and authorized distributors.";
  if (onlyUnconfigured) {
    emptyHeadline = "No candidates were returned by the available sources.";
    emptyDetail =
      "Supplier providers are not configured for this environment, so Cadivor could not search live catalogs. This does not confirm that no replacement exists.";
  } else if (!anyConfiguredSearch && providerRows.length === 0) {
    emptyDetail =
      "No supplier coverage details were returned with this search. This does not confirm that no replacement exists.";
  }

  return {
    emptyHeadline,
    emptyDetail,
    providerRows,
    missingEvidence,
    gap,
    candidatesUnverifiedNote:
      "Candidates are unverified research leads. Fit is not confirmed until engineering reviews datasheet and qualification evidence.",
  };
}
