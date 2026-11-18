"use client";

import { useMemo, useState } from "react";
import type {
  BomIntakeColumn,
  BomIntakeField,
  BomIntakeIssue,
  BomIntakeOptions,
  BomIntakeRow,
  BomValidationPreview,
} from "@/lib/api";

const IGNORE = "ignore";

/** Fields shown per row. Quantity and part number are always required. */
const ROW_FIELDS: Array<{ id: string; label: string }> = [
  { id: "mpn", label: "Part number" },
  { id: "quantity", label: "Quantity" },
  { id: "manufacturer", label: "Manufacturer" },
  { id: "supplier", label: "Supplier" },
];

const CONFIDENCE_LABEL: Record<string, string> = {
  recognized: "Recognized from header",
  "supplier-export": "Distributor code (reference only)",
  confirm: "Generic header — please confirm",
  choose: "Several matches — choose one",
  "not-used": "Not used",
  user: "Set by you",
};

const ROW_STATUS_LABEL: Record<BomIntakeRow["status"], string> = {
  ok: "OK",
  warning: "Review",
  error: "Fix needed",
  excluded: "Left out",
};

const SEVERITY_LABEL: Record<BomIntakeIssue["severity"], string> = {
  error: "Error",
  warning: "Warning",
  info: "Note",
};

const REQUIREMENT_LABEL: Record<BomIntakeField["requirement"], string> = {
  required: "required",
  recommended: "recommended",
  supplier_specific: "needed for supplier-specific sourcing",
  optional: "optional",
};

function shown(value: unknown): string {
  if (value === null || value === undefined) return "—";
  const text = String(value);
  return text.trim() === "" ? "(blank)" : text;
}

type Props = {
  validation: BomValidationPreview;
  options: BomIntakeOptions;
  onChange: (next: BomIntakeOptions) => void;
  onApply: () => void;
  /** True when the options differ from what the preview below was built with. */
  dirty: boolean;
  /** A check or an analysis is in flight. */
  busy: boolean;
};

export function BomIntakeReview({ validation, options, onChange, onApply, dirty, busy }: Props) {
  const fields = useMemo(() => validation.fields || [], [validation.fields]);
  const columns = validation.columns || [];
  const rows = validation.rows || [];
  const effectiveMapping = options.columnMapping ?? validation.applied_mapping ?? {};
  const needsConfirmation =
    validation.mapping_source !== "user" &&
    (validation.issues || []).some((issue) => issue.code === "mapping_needs_confirmation");
  const counts = validation.counts || {};
  const hasFlagged = rows.some((row) => row.status === "error" || row.status === "warning");
  const [filter, setFilter] = useState<"attention" | "all">(hasFlagged ? "attention" : "all");
  const [editing, setEditing] = useState<Set<number>>(new Set());

  const showSupplier = options.supplierSpecific || Object.values(effectiveMapping).includes("supplier");
  const rowFields = ROW_FIELDS.filter((field) => field.id !== "supplier" || showSupplier);
  const visibleRows = filter === "attention" ? rows.filter((row) => row.status !== "ok") : rows;
  const notes = (validation.issues || []).filter((issue) => issue.severity === "info");

  function setRole(column: BomIntakeColumn, role: string) {
    const next: Record<string, string> = { ...effectiveMapping };
    if (role !== IGNORE) {
      // One column per role: move the role rather than leaving two columns on it.
      for (const [key, value] of Object.entries(next)) {
        if (value === role) next[key] = IGNORE;
      }
    }
    next[String(column.index)] = role;
    onChange({ ...options, columnMapping: next });
  }

  function setCorrection(row: BomIntakeRow, field: string, value: string) {
    const rowKey = String(row.row_number);
    const corrections = { ...options.rowCorrections };
    const forRow = { ...(corrections[rowKey] || {}) };
    if (value === (row.raw[field] ?? "")) {
      delete forRow[field];
    } else {
      forRow[field] = value;
    }
    if (Object.keys(forRow).length) corrections[rowKey] = forRow;
    else delete corrections[rowKey];
    onChange({ ...options, rowCorrections: corrections });
  }

  function toggleEditing(rowNumber: number) {
    setEditing((current) => {
      const next = new Set(current);
      if (next.has(rowNumber)) next.delete(rowNumber);
      else next.add(rowNumber);
      return next;
    });
  }

  const pendingCorrections = Object.values(options.rowCorrections).reduce(
    (sum, forRow) => sum + Object.keys(forRow).length,
    0,
  );

  return (
    <div className="cv-intake" data-testid="bom-intake-review">
      <div className="cv-intake-heading">
        <h4>Review before analysis</h4>
        <p className="cv-small-note">
          {validation.format ? `${validation.format.toUpperCase()} file` : "File"}
          {validation.sheet ? ` · sheet “${validation.sheet}”` : ""}
          {validation.header_row ? ` · header on row ${validation.header_row}` : ""}
          {validation.supplier_profile && validation.supplier_profile.id !== "generic"
            ? ` · column names look like: ${validation.supplier_profile.label} (guessed from column names only)`
            : ""}
          . Nothing is analyzed until you choose Analyze.
        </p>
      </div>

      <dl className="cv-bom-validation-stats">
        <div>
          <dt>Rows needing a fix</dt>
          <dd>{counts.rows_with_errors ?? 0}</dd>
        </div>
        <div>
          <dt>Rows to review</dt>
          <dd>{counts.rows_with_warnings ?? 0}</dd>
        </div>
        <div>
          <dt>Rows clean</dt>
          <dd>{counts.rows_clean ?? 0}</dd>
        </div>
        <div>
          <dt>Corrections by you</dt>
          <dd>{validation.corrections_applied ?? 0}</dd>
        </div>
      </dl>

      {columns.length ? (
        <section aria-labelledby="intake-mapping-title" className="cv-intake-section">
          <h5 id="intake-mapping-title">1. Check column roles</h5>
          <p className="cv-small-note">
            Cadivor only assigns a role when the header is specific. Anything unclear stays
            unassigned until you choose.
          </p>
          <div className="cv-table-wrap">
            <table className="cv-table cv-intake-table">
              <thead>
                <tr>
                  <th>Column in your file</th>
                  <th>Example values</th>
                  <th>Role</th>
                  <th>How it was decided</th>
                </tr>
              </thead>
              <tbody>
                {columns.map((column) => {
                  const role = effectiveMapping[String(column.index)] ?? IGNORE;
                  return (
                    <tr key={column.index}>
                      <td data-label="Column">
                        <strong>{column.source}</strong>
                      </td>
                      <td data-label="Examples">
                        {column.sample.length ? column.sample.map(shown).join(" · ") : "—"}
                      </td>
                      <td data-label="Role">
                        <select
                          aria-label={`Role for column ${column.source}`}
                          value={role}
                          disabled={busy}
                          onChange={(event) => setRole(column, event.target.value)}
                        >
                          <option value={IGNORE}>Don’t use</option>
                          {fields.map((field) => (
                            <option key={field.id} value={field.id}>
                              {field.label} ({REQUIREMENT_LABEL[field.requirement]})
                            </option>
                          ))}
                        </select>
                      </td>
                      <td data-label="Decision">
                        <span className="cv-intake-confidence">
                          {CONFIDENCE_LABEL[column.confidence] || column.confidence}
                        </span>
                        {column.note ? <small>{column.note}</small> : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {needsConfirmation ? (
            <p className="cv-bom-validation-warnings" role="status">
              A generic header such as “Part Number” was used as the manufacturer part number.
              Confirm it is right, or change the role above.{" "}
              <button
                type="button"
                className="cv-button small"
                disabled={busy}
                onClick={() => onChange({ ...options, columnMapping: { ...effectiveMapping } })}
              >
                Confirm column roles
              </button>
            </p>
          ) : null}
        </section>
      ) : null}

      <section aria-labelledby="intake-options-title" className="cv-intake-section">
        <h5 id="intake-options-title">2. Sourcing options</h5>
        <label className="cv-intake-check">
          <input
            type="checkbox"
            checked={options.supplierSpecific}
            disabled={busy}
            onChange={(event) => onChange({ ...options, supplierSpecific: event.target.checked })}
          />
          <span>
            I need supplier-specific sourcing
            <small>
              Supplier is optional by default. Turn this on only if each line must name a supplier.
            </small>
          </span>
        </label>
        {options.supplierSpecific ? (
          <label className="cv-field cv-intake-supplier">
            <span>Supplier for rows that do not name one (optional)</span>
            <input
              value={options.defaultSupplier}
              disabled={busy}
              maxLength={120}
              placeholder="e.g. the distributor you will buy from"
              onChange={(event) => onChange({ ...options, defaultSupplier: event.target.value })}
            />
          </label>
        ) : null}
        {(counts.rows_with_errors ?? 0) > 0 || options.excludeInvalidRows ? (
          <label className="cv-intake-check">
            <input
              type="checkbox"
              checked={options.excludeInvalidRows}
              disabled={busy}
              onChange={(event) => onChange({ ...options, excludeInvalidRows: event.target.checked })}
            />
            <span>
              Leave out rows that still have errors
              <small>
                They are not analyzed and are listed, with the reason, in the saved report. Otherwise
                fix them below.
              </small>
            </span>
          </label>
        ) : null}
      </section>

      {validation.errors.length ? (
        <div className="cv-error" role="alert">
          <strong>Fix before analysis</strong>
          <ul>
            {validation.errors.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {validation.warnings.length ? (
        <div className="cv-bom-validation-warnings" role="status">
          <strong>Review these</strong>
          <ul>
            {validation.warnings.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {rows.length ? (
        <section aria-labelledby="intake-rows-title" className="cv-intake-section">
          <div className="cv-intake-rows-head">
            <h5 id="intake-rows-title">3. Review rows</h5>
            <div role="group" aria-label="Which rows to show" className="cv-intake-filter">
              <button
                type="button"
                className={`cv-button small${filter === "attention" ? " primary" : ""}`}
                aria-pressed={filter === "attention"}
                onClick={() => setFilter("attention")}
              >
                Needs attention ({rows.filter((row) => row.status !== "ok").length})
              </button>
              <button
                type="button"
                className={`cv-button small${filter === "all" ? " primary" : ""}`}
                aria-pressed={filter === "all"}
                onClick={() => setFilter("all")}
              >
                All shown rows ({rows.length})
              </button>
            </div>
          </div>
          <p className="cv-small-note">
            “As uploaded” is exactly what your file says. “Used” is what analysis will use. Edit a value
            to correct it; your original stays on record.
            {validation.rows_truncated
              ? ` Showing ${validation.rows_shown ?? rows.length} of ${validation.rows_total ?? rows.length} rows, flagged rows first.`
              : ""}
          </p>
          {visibleRows.length ? (
            <div className="cv-table-wrap">
              <table className="cv-table cv-intake-table cv-intake-rows">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Status</th>
                    {rowFields.map((field) => (
                      <th key={field.id}>{field.label}</th>
                    ))}
                    <th>Flags</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row) => {
                    const forRow = options.rowCorrections[String(row.row_number)] || {};
                    const open =
                      editing.has(row.row_number) ||
                      row.status === "error" ||
                      Object.keys(forRow).length > 0;
                    return (
                      <tr key={row.row_number} className={`cv-intake-row cv-intake-row--${row.status}`}>
                        <td data-label="Row">{row.row_number}</td>
                        <td data-label="Status">
                          <strong>{ROW_STATUS_LABEL[row.status]}</strong>
                          {row.corrections && Object.keys(row.corrections).length ? (
                            <small>Corrected by you</small>
                          ) : null}
                          {row.status !== "error" ? (
                            <button
                              type="button"
                              className="cv-button small"
                              aria-expanded={open}
                              onClick={() => toggleEditing(row.row_number)}
                            >
                              {open ? "Hide edit" : "Edit"}
                            </button>
                          ) : null}
                        </td>
                        {rowFields.map((field) => {
                          const raw = row.raw[field.id];
                          const used = row.normalized[field.id];
                          const mapped = raw !== undefined || used !== undefined;
                          const editable = ["mpn", "quantity", "manufacturer", "supplier"].includes(field.id);
                          return (
                            <td key={field.id} data-label={field.label}>
                              {mapped || editable ? (
                                <div className="cv-intake-pair">
                                  <div>
                                    <small>As uploaded</small>
                                    <span>{raw === undefined ? "— (no column)" : shown(raw)}</span>
                                  </div>
                                  <div>
                                    <small>Used</small>
                                    <span>{shown(used)}</span>
                                  </div>
                                </div>
                              ) : (
                                "—"
                              )}
                              {open && editable ? (
                                <input
                                  className="cv-intake-edit"
                                  aria-label={`${field.label}, row ${row.row_number}: corrected value`}
                                  placeholder="Corrected value"
                                  value={forRow[field.id] ?? ""}
                                  disabled={busy}
                                  onChange={(event) => setCorrection(row, field.id, event.target.value)}
                                />
                              ) : null}
                            </td>
                          );
                        })}
                        <td data-label="Flags">
                          {row.issues.length ? (
                            <ul className="cv-intake-flags">
                              {row.issues.map((issue, index) => (
                                <li key={`${issue.code}-${index}`}>
                                  <strong>{SEVERITY_LABEL[issue.severity]}:</strong> {issue.message}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            "No flags"
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="cv-small-note">No rows need attention.</p>
          )}
        </section>
      ) : null}

      {notes.length ? (
        <details className="cv-intake-notes">
          <summary>File notes ({notes.length})</summary>
          <ul>
            {notes.map((note, index) => (
              <li key={`${note.code}-${index}`}>{note.message}</li>
            ))}
          </ul>
        </details>
      ) : null}

      {dirty ? (
        <div className="cv-intake-apply" role="status">
          <p>
            You changed the mapping, options, or {pendingCorrections ? `${pendingCorrections} value(s)` : "values"}.
            Re-check the file to see the effect. Analysis stays off until you do.
          </p>
          <button type="button" className="cv-button primary" disabled={busy} onClick={onApply}>
            Re-check with my changes
          </button>
        </div>
      ) : null}
    </div>
  );
}
