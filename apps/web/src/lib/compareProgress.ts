/** Pure helpers for Compare Parts multi-candidate progress and settlement. */

export type CompareProgressState = {
  total: number;
  completed: number;
  /** Design / baseline MPN (form Part A). */
  baselineMpn: string;
  /** Candidate MPN currently in flight, if any. */
  candidateMpn?: string;
  failures: string[];
};

export function formatCompareProgressLabel(
  progress: CompareProgressState,
  timeoutMs: number,
): string {
  const total = Math.max(0, Number(progress.total) || 0);
  const completed = Math.max(0, Number(progress.completed) || 0);
  const baseline = String(progress.baselineMpn || "").trim() || "design part";
  const candidate = String(progress.candidateMpn || "").trim();
  const seconds = Math.round(Math.max(0, timeoutMs) / 1000);
  const pair = candidate
    ? ` · design ${baseline} vs candidate ${candidate}`
    : ` · design ${baseline}`;
  return `Comparing ${completed} of ${total} candidate${total === 1 ? "" : "s"}${pair} (bounded ${seconds}s each)…`;
}

export type SettledPairResult = {
  mpn: string;
  ok: boolean;
  finding: string;
  result: Record<string, unknown>;
};

/** Count settled slots so progress can advance while other pairs are in flight. */
export function settledPairCount(slots: Array<SettledPairResult | null>): number {
  return slots.filter(Boolean).length;
}

export function nextPendingCandidate(
  candidates: string[],
  slots: Array<SettledPairResult | null>,
): string | undefined {
  const index = slots.findIndex((row) => row == null);
  if (index < 0) return undefined;
  return candidates[index];
}

export function mapSettledColumnsByMpn(
  candidates: string[],
  slots: Array<SettledPairResult | null>,
): Record<string, SettledPairResult> {
  const out: Record<string, SettledPairResult> = {};
  candidates.forEach((mpn, index) => {
    const row = slots[index];
    if (row) out[mpn] = row;
  });
  return out;
}

export function timeoutSettlement(mpn: string, detail: string): SettledPairResult {
  return {
    mpn,
    ok: false,
    finding: "Needs verification",
    result: {
      ok: false,
      status: "comparison_failed",
      finding: "Needs verification",
      gap: detail,
      part_b: mpn,
      rows: [],
    },
  };
}
