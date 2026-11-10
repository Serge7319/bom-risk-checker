/** Helpers for comparing one current part against multiple candidates. */

export function parseCandidateMpns(raw: string, limit = 4): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const token of String(raw || "").split(/[\n,;]+/)) {
    const mpn = token.trim();
    if (!mpn) continue;
    const key = mpn.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(mpn);
    if (out.length >= limit) break;
  }
  return out;
}

export type CompareRow = Record<string, unknown>;

export type MultiCompareColumn = {
  mpn: string;
  result: CompareRow;
  rows: CompareRow[];
};

export type MultiMatrixRow = {
  attribute: string;
  current: string;
  currentSource: string;
  currentClass: string;
  currentCondition: string;
  unit: string;
  candidates: Array<{
    mpn: string;
    value: string;
    source: string;
    valueClass: string;
    condition: string;
    assessment: string;
    evidence: string;
  }>;
};

function text(value: unknown, fallback = "—") {
  const valueText = String(value ?? "").trim();
  return valueText || fallback;
}

export function buildMultiCompareMatrix(
  currentMpn: string,
  columns: MultiCompareColumn[],
): MultiMatrixRow[] {
  const attributeOrder: string[] = [];
  const byAttribute = new Map<string, MultiMatrixRow>();

  for (const column of columns) {
    for (const row of column.rows) {
      const attribute = text(row.Attribute || row.attribute, "");
      if (!attribute) continue;
      const key = attribute.toLowerCase();
      let matrix = byAttribute.get(key);
      if (!matrix) {
        attributeOrder.push(attribute);
        matrix = {
          attribute,
          current: text(row["Part A"] || row.part_a),
          currentSource: text(row["Part A source"], "Not stated"),
          currentClass: text(row["Part A value class"], "unknown"),
          currentCondition: text(row["Test condition"], "Not stated"),
          unit: text(row.Unit, ""),
          candidates: [],
        };
        byAttribute.set(key, matrix);
      }
      matrix.candidates.push({
        mpn: column.mpn,
        value: text(row["Part B"] || row.part_b),
        source: text(row["Part B source"], "Not stated"),
        valueClass: text(row["Part B value class"], "unknown"),
        condition: text(row["Test condition"], "Not stated"),
        assessment: text(row.Assessment || row.assessment || row.Status, "Needs data"),
        evidence: text(row.Evidence || row.evidence || row.Note, "No source note supplied."),
      });
    }
  }

  // Fill missing candidate cells so every row has one cell per column.
  for (const matrix of byAttribute.values()) {
    const present = new Set(matrix.candidates.map((item) => item.mpn.toLowerCase()));
    for (const column of columns) {
      if (present.has(column.mpn.toLowerCase())) continue;
      matrix.candidates.push({
        mpn: column.mpn,
        value: "—",
        source: "Not stated",
        valueClass: "unknown",
        condition: "Not stated",
        assessment: "Needs data",
        evidence: `No attribute row was returned for ${column.mpn} versus ${currentMpn}.`,
      });
    }
    matrix.candidates.sort((left, right) => {
      const leftIndex = columns.findIndex((column) => column.mpn.toLowerCase() === left.mpn.toLowerCase());
      const rightIndex = columns.findIndex((column) => column.mpn.toLowerCase() === right.mpn.toLowerCase());
      return leftIndex - rightIndex;
    });
  }

  return attributeOrder.map((attribute) => byAttribute.get(attribute.toLowerCase())!);
}

export type MultiSourceRecord = {
  side: string;
  mpn: string;
  sourceLabel: string;
  retrievalNotes: string[];
  fieldEvidence: Array<{
    attribute: string;
    value: string;
    source: string;
    valueClass: string;
    condition: string;
    assessment: string;
    evidence: string;
  }>;
};

export function buildMultiSourceRecords(
  currentMpn: string,
  columns: MultiCompareColumn[],
): MultiSourceRecord[] {
  const records: MultiSourceRecord[] = [];
  const first = columns[0];
  if (first) {
    const evidence = (first.result.evidence_sources || {}) as {
      part_a?: Array<Record<string, unknown>>;
    };
    records.push({
      side: "Part A",
      mpn: text(first.result.part_a || currentMpn, currentMpn),
      sourceLabel: text(first.result.source_a, "Not stated"),
      retrievalNotes: (evidence.part_a || []).map((row) => {
        const label = text(row.label || row.name || row.source || row.url, "Source");
        const retrieved = text(row.retrieved_at, "");
        return retrieved ? `${label} · retrieved ${retrieved}` : label;
      }),
      fieldEvidence: (first.rows || []).map((row) => ({
        attribute: text(row.Attribute || row.attribute),
        value: text(row["Part A"] || row.part_a),
        source: text(row["Part A source"], "Not stated"),
        valueClass: text(row["Part A value class"], "unknown"),
        condition: text(row["Test condition"], "Not stated"),
        assessment: text(row.Assessment || row.assessment || row.Status, "Needs data"),
        evidence: text(row.Evidence || row.evidence || row.Note, "No source note supplied."),
      })),
    });
  }
  for (const column of columns) {
    const evidence = (column.result.evidence_sources || {}) as {
      part_b?: Array<Record<string, unknown>>;
    };
    records.push({
      side: `Candidate · ${column.mpn}`,
      mpn: text(column.result.part_b || column.mpn, column.mpn),
      sourceLabel: text(column.result.source_b, "Not stated"),
      retrievalNotes: (evidence.part_b || []).map((row) => {
        const label = text(row.label || row.name || row.source || row.url, "Source");
        const retrieved = text(row.retrieved_at, "");
        return retrieved ? `${label} · retrieved ${retrieved}` : label;
      }),
      fieldEvidence: (column.rows || []).map((row) => ({
        attribute: text(row.Attribute || row.attribute),
        value: text(row["Part B"] || row.part_b),
        source: text(row["Part B source"], "Not stated"),
        valueClass: text(row["Part B value class"], "unknown"),
        condition: text(row["Test condition"], "Not stated"),
        assessment: text(row.Assessment || row.assessment || row.Status, "Needs data"),
        evidence: text(row.Evidence || row.evidence || row.Note, "No source note supplied."),
      })),
    });
  }
  return records;
}

export function buildMultiDecisionSnapshot(
  currentMpn: string,
  columns: MultiCompareColumn[],
): Record<string, unknown> {
  const matrix = buildMultiCompareMatrix(currentMpn, columns);
  const sourceRecords = buildMultiSourceRecords(currentMpn, columns);
  const primary = columns[0]?.result || {};
  return {
    ...primary,
    part_a: text(primary.part_a || currentMpn, currentMpn),
    part_b: columns.map((column) => column.mpn).join(", "),
    multi_candidate_mpns: columns.map((column) => column.mpn),
    multi_matrix: matrix,
    multi_source_records: sourceRecords,
    candidate_snapshots: columns.map((column) => ({
      mpn: column.mpn,
      part_a: column.result.part_a,
      part_b: column.result.part_b,
      source_a: column.result.source_a,
      source_b: column.result.source_b,
      evidence_sources: column.result.evidence_sources,
      finding: column.result.finding,
      counts: column.result.counts,
      rows: column.result.rows,
      datasheet_identity: column.result.datasheet_identity,
    })),
  };
}
