"use client";

import { useMemo, useState, type FormEvent } from "react";
import {
  createProcurementQuoteGroup,
  type ProcurementQuote,
} from "@/lib/api";

type BomPart = Record<string, unknown>;
type PriceBreakInput = { quantity: string; unit_price: string };
type QuoteLineInput = {
  requested_mpn: string;
  requested_manufacturer: string;
  offered_mpn: string;
  offered_manufacturer: string;
  price_breaks: PriceBreakInput[];
  minimum_order_quantity: string;
  pack_quantity: string;
  lead_time_weeks: string;
  stock: string;
};

type QuoteHeader = {
  supplier: string;
  quote_reference: string;
  currency: string;
  valid_until: string;
  source_url: string;
  notes: string;
};

type Props = {
  accessToken: string;
  analysisId: string;
  parts: BomPart[];
  selectedPartKey: string;
  onSaved: (quotes: ProcurementQuote[]) => void;
};

function valueFrom(part: BomPart, ...keys: string[]) {
  for (const key of keys) {
    const value = part[key];
    if (value !== undefined && value !== null && String(value).trim()) return String(value).trim();
  }
  return "";
}

function partKey(part: BomPart) {
  return valueFrom(part, "mpn", "MPN", "Part Number", "part_number").toLowerCase()
    + "\u0000"
    + valueFrom(part, "manufacturer", "Manufacturer").toLowerCase();
}

function lineFor(part: BomPart): QuoteLineInput {
  const mpn = valueFrom(part, "mpn", "MPN", "Part Number", "part_number");
  const manufacturer = valueFrom(part, "manufacturer", "Manufacturer");
  return {
    requested_mpn: mpn,
    requested_manufacturer: manufacturer,
    offered_mpn: mpn,
    offered_manufacturer: "",
    price_breaks: [{ quantity: "", unit_price: "" }],
    minimum_order_quantity: "",
    pack_quantity: "",
    lead_time_weeks: "",
    stock: "",
  };
}

function emptyHeader(): QuoteHeader {
  return {
    supplier: "",
    quote_reference: "",
    currency: "USD",
    valid_until: "",
    source_url: "",
    notes: "",
  };
}

function optionalNumber(value: string) {
  return value.trim() ? Number(value) : null;
}

export function QuoteGroupEntry({
  accessToken,
  analysisId,
  parts,
  selectedPartKey,
  onSaved,
}: Props) {
  const uniqueParts = useMemo(() => {
    const seen = new Set<string>();
    return parts.filter((part) => {
      const key = partKey(part);
      if (!key.split("\u0000")[0] || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [parts]);

  const [header, setHeader] = useState<QuoteHeader>(() => emptyHeader());
  const [lines, setLines] = useState<QuoteLineInput[]>(() => {
    const first = parts.find((part) => partKey(part) === selectedPartKey) || parts[0] || {};
    return [lineFor(first)];
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedMessage, setSavedMessage] = useState("");

  function updateLine(index: number, patch: Partial<QuoteLineInput>) {
    setLines((current) => current.map((line, lineIndex) =>
      lineIndex === index ? { ...line, ...patch } : line,
    ));
  }

  function updatePriceBreak(lineIndex: number, breakIndex: number, patch: Partial<PriceBreakInput>) {
    setLines((current) => current.map((line, index) => index === lineIndex
      ? {
          ...line,
          price_breaks: line.price_breaks.map((priceBreak, rowIndex) =>
            rowIndex === breakIndex ? { ...priceBreak, ...patch } : priceBreak,
          ),
        }
      : line,
    ));
  }

  function addLine() {
    const selected = new Set(lines.map((line) =>
      line.requested_mpn.trim().toLowerCase()
        + "\u0000"
        + line.requested_manufacturer.trim().toLowerCase(),
    ));
    const nextPart = uniqueParts.find((part) => !selected.has(partKey(part)));
    if (!nextPart) {
      setError("Every distinct BOM component is already included in this quote.");
      return;
    }
    setError("");
    setLines((current) => [...current, lineFor(nextPart)]);
  }

  async function saveGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSavedMessage("");

    const selectedKeys = lines.map((line) =>
      line.requested_mpn.trim().toLowerCase()
        + "\u0000"
        + line.requested_manufacturer.trim().toLowerCase(),
    );
    if (selectedKeys.some((key) => !key.split("\u0000")[0])) {
      setError("Choose a BOM component for every quote line.");
      return;
    }
    if (new Set(selectedKeys).size !== selectedKeys.length) {
      setError("Each BOM component can appear only once in a quote group.");
      return;
    }
    if (lines.some((line) => !line.offered_mpn.trim())) {
      setError("Enter the quoted MPN for every component.");
      return;
    }
    const partialBreak = lines.some((line) => line.price_breaks.some((row) =>
      Boolean(row.quantity.trim()) !== Boolean(row.unit_price.trim()),
    ));
    if (partialBreak) {
      setError("Enter both quantity and unit price for each price break, or leave both blank.");
      return;
    }

    setSaving(true);
    try {
      const payload = await createProcurementQuoteGroup(accessToken, {
        analysis_id: analysisId,
        supplier: header.supplier.trim(),
        quote_reference: header.quote_reference.trim(),
        currency: header.currency.trim().toUpperCase(),
        valid_until: header.valid_until,
        source_url: header.source_url.trim(),
        notes: header.notes.trim(),
        lines: lines.map((line) => ({
          requested_mpn: line.requested_mpn.trim(),
          requested_manufacturer: line.requested_manufacturer.trim(),
          offered_mpn: line.offered_mpn.trim(),
          offered_manufacturer: line.offered_manufacturer.trim(),
          price_breaks: line.price_breaks
            .filter((row) => row.quantity.trim() || row.unit_price.trim())
            .map((row) => ({ quantity: Number(row.quantity), unit_price: Number(row.unit_price) })),
          minimum_order_quantity: optionalNumber(line.minimum_order_quantity),
          pack_quantity: optionalNumber(line.pack_quantity),
          lead_time_weeks: optionalNumber(line.lead_time_weeks),
          stock: optionalNumber(line.stock),
        })),
      });
      onSaved(payload.quotes);
      setSavedMessage("Saved one supplier quote with " + payload.line_count
        + " BOM component" + (payload.line_count === 1 ? "" : "s") + ".");
      setHeader(emptyHeader());
      const initialPart = parts.find((part) => partKey(part) === selectedPartKey) || parts[0] || {};
      setLines([lineFor(initialPart)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save this supplier quote.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="cv-quote-entry" onSubmit={saveGroup} data-testid="procurement-quote-group-form">
      <div>
        <h3>Record a supplier quote</h3>
        <p>
          Enter the supplier and quote details once, then add every component covered by that quote.
          Cadivor records your evidence; it does not independently verify the supplier document.
        </p>
      </div>

      <div className="cv-quote-form-grid">
        <label><span>Supplier *</span><input required maxLength={120} value={header.supplier} onChange={(event) => setHeader({ ...header, supplier: event.target.value })} /></label>
        <label><span>Quote reference</span><input maxLength={160} value={header.quote_reference} onChange={(event) => setHeader({ ...header, quote_reference: event.target.value })} /></label>
        <label><span>Currency</span><input required maxLength={3} value={header.currency} onChange={(event) => setHeader({ ...header, currency: event.target.value.toUpperCase() })} /></label>
        <label><span>Valid until</span><input type="date" value={header.valid_until} onChange={(event) => setHeader({ ...header, valid_until: event.target.value })} /></label>
        <label className="cv-quote-wide"><span>Supplier quote / listing URL</span><input type="url" maxLength={2048} placeholder="https://…" value={header.source_url} onChange={(event) => setHeader({ ...header, source_url: event.target.value })} /></label>
        <label className="cv-quote-wide"><span>Quote notes / assumptions</span><textarea maxLength={3000} rows={3} value={header.notes} onChange={(event) => setHeader({ ...header, notes: event.target.value })} /></label>
      </div>

      <div className="cv-quote-group-lines">
        <div className="cv-quote-group-heading">
          <div>
            <h4>Components on this quote</h4>
            <p>Each line is linked to one part in the selected BOM revision.</p>
          </div>
          <button className="cv-quote-add-break" type="button" onClick={addLine}>Add BOM component</button>
        </div>
        {lines.map((line, lineIndex) => (
          <fieldset className="cv-quote-group-line" key={line.requested_mpn + "-" + line.requested_manufacturer + "-" + lineIndex}>
            <legend>Component {lineIndex + 1}</legend>
            <div className="cv-quote-form-grid">
              <label className="cv-quote-wide">
                <span>BOM component *</span>
                <select
                  required
                  value={line.requested_mpn.toLowerCase() + "\u0000" + line.requested_manufacturer.toLowerCase()}
                  onChange={(event) => {
                    const part = uniqueParts.find((row) => partKey(row) === event.target.value);
                    if (!part) return;
                    const next = lineFor(part);
                    updateLine(lineIndex, next);
                  }}
                >
                  {uniqueParts.map((part) => (
                    <option key={partKey(part)} value={partKey(part)}>
                      {valueFrom(part, "mpn", "MPN", "Part Number", "part_number")}
                      {valueFrom(part, "manufacturer", "Manufacturer") ? " · " + valueFrom(part, "manufacturer", "Manufacturer") : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label><span>Quoted MPN *</span><input required maxLength={160} value={line.offered_mpn} onChange={(event) => updateLine(lineIndex, { offered_mpn: event.target.value })} /></label>
              <label><span>Quoted manufacturer</span><input maxLength={160} value={line.offered_manufacturer} onChange={(event) => updateLine(lineIndex, { offered_manufacturer: event.target.value })} /></label>
              <div className="cv-quote-breaks">
                <strong>Price breaks</strong>
                <span>Enter the minimum quantity for each unit price.</span>
                {line.price_breaks.map((priceBreak, breakIndex) => (
                  <div className="cv-quote-break-row" key={"line-" + lineIndex + "-break-" + breakIndex}>
                    <label><span>Quantity</span><input aria-label={"Component " + (lineIndex + 1) + " price break " + (breakIndex + 1) + " quantity"} type="number" min="1" step="1" value={priceBreak.quantity} onChange={(event) => updatePriceBreak(lineIndex, breakIndex, { quantity: event.target.value })} /></label>
                    <label><span>Unit price</span><input aria-label={"Component " + (lineIndex + 1) + " price break " + (breakIndex + 1) + " unit price"} type="number" min="0.000001" step="any" value={priceBreak.unit_price} onChange={(event) => updatePriceBreak(lineIndex, breakIndex, { unit_price: event.target.value })} /></label>
                    {line.price_breaks.length > 1 ? <button className="cv-quote-remove-break" type="button" onClick={() => updateLine(lineIndex, { price_breaks: line.price_breaks.filter((_, index) => index !== breakIndex) })}>Remove</button> : null}
                  </div>
                ))}
                {line.price_breaks.length < 20 ? <button className="cv-quote-add-break" type="button" onClick={() => updateLine(lineIndex, { price_breaks: [...line.price_breaks, { quantity: "", unit_price: "" }] })}>Add price break</button> : null}
              </div>
              <label><span>Minimum order quantity</span><input type="number" min="1" step="1" value={line.minimum_order_quantity} onChange={(event) => updateLine(lineIndex, { minimum_order_quantity: event.target.value })} /></label>
              <label><span>Pack quantity / order multiple</span><input type="number" min="1" step="1" value={line.pack_quantity} onChange={(event) => updateLine(lineIndex, { pack_quantity: event.target.value })} /></label>
              <label><span>Lead time (weeks)</span><input type="number" min="0" step="any" value={line.lead_time_weeks} onChange={(event) => updateLine(lineIndex, { lead_time_weeks: event.target.value })} /></label>
              <label><span>Available stock</span><input type="number" min="0" step="1" value={line.stock} onChange={(event) => updateLine(lineIndex, { stock: event.target.value })} /></label>
            </div>
            {lines.length > 1 ? <button className="cv-quote-remove-break" type="button" onClick={() => setLines((current) => current.filter((_, index) => index !== lineIndex))}>Remove component</button> : null}
          </fieldset>
        ))}
      </div>

      {error ? <div className="cv-error" role="alert">{error}</div> : null}
      {savedMessage ? <div className="cv-success" role="status">{savedMessage}</div> : null}
      <button className="cv-button primary" type="submit" disabled={saving}>
        {saving ? "Saving quote…" : "Save quote for " + lines.length + " BOM component" + (lines.length === 1 ? "" : "s")}
      </button>
      <p className="cv-small-note">The quote header is shared. Price breaks, MOQ, pack, lead time, stock, and part identity are recorded separately for each line.</p>
    </form>
  );
}
