"use client";

import { Suspense, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Shell } from "@/components/Shell";
import { EmptyState } from "@/components/EmptyState";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { Icon } from "@/components/Icons";
import { PartThumbnail } from "@/components/PartThumbnail";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import {
  createProcurementQuote,
  createProcurementQuotesBulk,
  fetchProcurement,
  listProcurementQuotes,
  listReports,
  type ProcurementQuote,
} from "@/lib/api";
import { cleanUserText, evidenceSourceLabel, userFacingLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function analysisLabel(row: Record<string, unknown>) {
  const project = userFacingLabel(row.project_name, "");
  const bom = userFacingLabel(row.bom_name || row.filename, "");
  const revision = userFacingLabel(row.revision, "");
  const title = [project, bom].filter(Boolean).join(" · ") || "Saved analysis";
  return revision ? `${title} (rev ${revision})` : title;
}

function withAnalysisId(href: string, analysisId: string) {
  if (!analysisId) return href;
  const joiner = href.includes("?") ? "&" : "?";
  return `${href}${joiner}analysis_id=${encodeURIComponent(analysisId)}`;
}

function savedBomAnalysisHref(analysisId: string) {
  return analysisId
    ? `/bom-analyzer?source_analysis_id=${encodeURIComponent(analysisId)}`
    : "/bom-analyzer";
}

function supplierRefreshHref(analysisId: string, partNumber: string) {
  const query = new URLSearchParams({ analysis_id: analysisId, part_number: partNumber });
  return `/monitoring?${query.toString()}#supplier-refresh`;
}

function engineeringComparisonHref(
  analysisId: string,
  requestedMpn: string,
  requestedManufacturer: string,
  offeredMpn: string,
  offeredManufacturer: string,
) {
  if (!offeredMpn.trim()) return withAnalysisId("/compare-parts", analysisId);
  const query = new URLSearchParams({
    analysis_id: analysisId,
    part_a: requestedMpn,
    part_b: offeredMpn,
  });
  if (requestedManufacturer) query.set("manufacturer_a", requestedManufacturer);
  if (offeredManufacturer) query.set("manufacturer_b", offeredManufacturer);
  return `/compare-parts?${query.toString()}`;
}

type QuoteFormState = {
  supplier: string;
  quote_reference: string;
  offered_mpn: string;
  offered_manufacturer: string;
  currency: string;
  price_breaks: Array<{ quantity: string; unit_price: string }>;
  minimum_order_quantity: string;
  pack_quantity: string;
  lead_time_weeks: string;
  stock: string;
  valid_until: string;
  source_url: string;
  notes: string;
};

type ComparisonRow = {
  id: string;
  kind: string;
  supplier: string;
  quoteReference: string;
  offeredMpn: string;
  offeredManufacturer: string;
  identityStatus: string;
  exactPart: boolean;
  currency: string;
  unitPrice: number | null;
  priceBreakQuantity: number | null;
  priceBreaks: Array<{ quantity: number; unit_price: number }>;
  minimumOrderQuantity: number | null;
  packQuantity: number | null;
  leadTimeWeeks: number | null;
  stock: number | null;
  validUntil: string;
  sourceUrl: string;
  sourceTime: string;
  notes: string;
  canPriceCompare: boolean;
};

type PriceImportSourceRow = {
  line: number;
  partNumber: string;
  unitPrice: string;
  minimumQuantity: string;
  supplier: string;
  manufacturer: string;
  currency: string;
  quoteReference: string;
  priceDate: string;
  validUntil: string;
  sourceUrl: string;
};

type PriceImportRow = PriceImportSourceRow & {
  matchedPart: Record<string, unknown> | null;
  unitPriceValue: number | null;
  minimumQuantityValue: number | null;
  supplierValue: string;
  currencyValue: string;
  status: "ready" | "issue" | "saved" | "failed";
  message: string;
};

function partKey(part: Record<string, unknown>) {
  return `${String(part.mpn || part.MPN || "").trim().toLowerCase()}\u0000${String(part.manufacturer || "").trim().toLowerCase()}`;
}

function optionalNumber(value: unknown): number | null {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function riskBadgeClass(value: unknown) {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized.includes("high")) return "red";
  if (normalized.includes("medium") || normalized.includes("verification") || normalized.includes("conflict")) return "amber";
  if (normalized.includes("low")) return "green";
  return "gray";
}

function describeCatalogIdentity(
  targetMpn: string,
  targetManufacturer: string,
  offerMpn: string,
  offerManufacturer: string,
) {
  if (!offerMpn) return "Offered MPN not recorded — verify identity";
  if (offerMpn.trim().toLowerCase() !== targetMpn.trim().toLowerCase()) {
    return "Alternate candidate — engineering review required";
  }
  if (!targetManufacturer || !offerManufacturer) {
    return "MPN matches; manufacturer unconfirmed";
  }
  if (offerManufacturer.trim().toLowerCase() !== targetManufacturer.trim().toLowerCase()) {
    return "Manufacturer differs — engineering review required";
  }
  return "Exact MPN and manufacturer";
}

function emptyQuoteForm(mpn = ""): QuoteFormState {
  return {
    supplier: "",
    quote_reference: "",
    offered_mpn: mpn,
    offered_manufacturer: "",
    currency: "USD",
    price_breaks: [{ quantity: "", unit_price: "" }],
    minimum_order_quantity: "",
    pack_quantity: "",
    lead_time_weeks: "",
    stock: "",
    valid_until: "",
    source_url: "",
    notes: "",
  };
}

function parseDelimitedRows(text: string): string[][] {
  const source = text.replace(/^\uFEFF/, "");
  const firstLine = source.split(/\r\n|\n|\r/, 1)[0] || "";
  const delimiters = [",", ";", "\t"];
  const counts = delimiters.map((delimiter) => {
    let count = 0;
    let quoted = false;
    for (let index = 0; index < firstLine.length; index += 1) {
      const character = firstLine[index];
      if (character === '"') {
        if (quoted && firstLine[index + 1] === '"') index += 1;
        else quoted = !quoted;
      } else if (character === delimiter && !quoted) count += 1;
    }
    return count;
  });
  const delimiter = delimiters[counts.indexOf(Math.max(...counts))] || ",";
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (character === '"') {
      if (quoted && source[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === delimiter && !quoted) {
      row.push(cell);
      cell = "";
    } else if ((character === "\n" || character === "\r") && !quoted) {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      if (character === "\r" && source[index + 1] === "\n") index += 1;
    } else {
      cell += character;
    }
  }
  row.push(cell);
  if (row.length || cell.length) rows.push(row);
  return rows;
}

function importHeaderKind(value: unknown): string {
  const header = String(value || "").trim().toLowerCase().replace(/[^a-z0-9]/g, "");
  const aliases: Record<string, string[]> = {
    partNumber: ["partnumber", "partno", "mpn", "manufacturerpartnumber", "manufacturerpartno", "catalognumber"],
    unitPrice: ["unitprice", "priceperunit", "unitcost", "price"],
    minimumQuantity: ["minimumquantity", "minquantity", "minqty", "minimumorderquantity", "minimumorderqty", "moq", "pricebreakquantity"],
    supplier: ["supplier", "vendor", "distributor"],
    manufacturer: ["manufacturer", "mfr", "make"],
    currency: ["currency", "currencycode", "ccy"],
    quoteReference: ["quotereference", "quoteref", "reference", "quoteid"],
    priceDate: ["pricedate", "quotedate", "datequoted", "priceasof"],
    validUntil: ["validuntil", "expirationdate", "expires", "expiry"],
    sourceUrl: ["sourceurl", "quoteurl", "listingurl", "supplierurl"],
  };
  return Object.entries(aliases).find(([, names]) => names.includes(header))?.[0] || "";
}

function spreadsheetCellText(value: unknown): string {
  if (value instanceof Date && Number.isFinite(value.getTime())) return value.toISOString().slice(0, 10);
  return value === null || value === undefined ? "" : String(value).trim();
}

function parsePriceImportTable(table: unknown[][]): PriceImportSourceRow[] {
  const headerRowIndex = table.findIndex((row) => row.some((value) => spreadsheetCellText(value)));
  if (headerRowIndex < 0) throw new Error("The file needs a header row and at least one price row.");
  const headers = table[headerRowIndex].map(importHeaderKind);
  const indexes = new Map<string, number>();
  headers.forEach((header, index) => {
    if (header && !indexes.has(header)) indexes.set(header, index);
  });
  if (!indexes.has("partNumber") || !indexes.has("unitPrice")) {
    throw new Error("Add part_number and unit_price columns to the first row. Download the template for the supported columns.");
  }
  const dataRows = table
    .slice(headerRowIndex + 1)
    .map((row, offset) => ({ row, line: headerRowIndex + offset + 2 }))
    .filter(({ row }) => row.some((value) => spreadsheetCellText(value)));
  if (dataRows.length > 1000) throw new Error("This import supports up to 1,000 price rows at a time.");
  const get = (row: unknown[], name: string) => {
    const column = indexes.get(name);
    return column === undefined ? "" : spreadsheetCellText(row[column]);
  };
  return dataRows.map(({ row, line }) => ({
    line,
    partNumber: get(row, "partNumber"),
    unitPrice: get(row, "unitPrice"),
    minimumQuantity: get(row, "minimumQuantity"),
    supplier: get(row, "supplier"),
    manufacturer: get(row, "manufacturer"),
    currency: get(row, "currency"),
    quoteReference: get(row, "quoteReference"),
    priceDate: get(row, "priceDate"),
    validUntil: get(row, "validUntil"),
    sourceUrl: get(row, "sourceUrl"),
  }));
}

function parseImportedPrice(value: string): number | null {
  let normalized = value.trim().replace(/^(USD|CAD|AUD|EUR|GBP|JPY)\s*/i, "").replace(/[$€£¥\s]/g, "");
  if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(normalized)) normalized = normalized.replace(/,/g, "");
  if (!/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(normalized)) return null;
  const amount = Number(normalized);
  return Number.isFinite(amount) && amount > 0 ? amount : null;
}

function parseImportedPositiveInteger(value: string): number | null {
  if (!value.trim()) return 1;
  const normalized = value.trim();
  const grouped = /^\d{1,3}(,\d{3})+$/.test(normalized) ? normalized.replace(/,/g, "") : normalized;
  if (!/^\d+$/.test(grouped)) return null;
  const quantity = Number(grouped);
  return Number.isSafeInteger(quantity) && quantity > 0 ? quantity : null;
}

function parseImportedDate(value: string): string | null {
  if (!value.trim()) return "";
  const dateOnly = value.trim().match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
  if (dateOnly) {
    const year = Number(dateOnly[1]);
    const month = Number(dateOnly[2]);
    const day = Number(dateOnly[3]);
    const check = new Date(Date.UTC(year, month - 1, day));
    if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return null;
    return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString().slice(0, 10) : null;
}

function preparePriceImport(
  sourceRows: PriceImportSourceRow[],
  parts: Array<Record<string, unknown>>,
  defaultSupplier: string,
  defaultCurrency: string,
): PriceImportRow[] {
  return sourceRows.map((row) => {
    const issues: string[] = [];
    const warnings: string[] = [];
    const unitPriceValue = parseImportedPrice(row.unitPrice);
    const minimumQuantityValue = parseImportedPositiveInteger(row.minimumQuantity);
    const supplierValue = row.supplier.trim() || defaultSupplier.trim();
    const symbolCurrency = row.unitPrice.includes("€") ? "EUR"
      : row.unitPrice.includes("£") ? "GBP"
        : row.unitPrice.includes("¥") ? "JPY"
          : "";
    const currencyValue = (row.currency.trim() || symbolCurrency || defaultCurrency.trim() || "USD").toUpperCase();
    const partMatches = parts.filter((part) =>
      String(part.mpn || part.MPN || "").trim().toLowerCase() === row.partNumber.trim().toLowerCase(),
    );
    const manufacturerMatches = row.manufacturer.trim()
      ? partMatches.filter((part) => String(part.manufacturer || "").trim().toLowerCase() === row.manufacturer.trim().toLowerCase())
      : partMatches;
    const uniqueMatches = Array.from(new Map(manufacturerMatches.map((part) => [partKey(part), part])).values());
    const matchedPart: Record<string, unknown> | null = uniqueMatches.length === 1
      ? uniqueMatches[0]
      : null;

    if (!row.partNumber.trim()) issues.push("Part number is blank.");
    else if (!partMatches.length) issues.push("Part number is not in this saved BOM.");
    else if (!manufacturerMatches.length) issues.push("Manufacturer does not match this saved BOM.");
    else if (uniqueMatches.length > 1) issues.push("Part number is ambiguous; add a manufacturer column.");
    if (unitPriceValue === null) issues.push("Enter a unit price greater than zero.");
    if (!supplierValue) issues.push("Enter a default supplier or add a supplier column.");
    if (!/^[A-Z]{3}$/.test(currencyValue)) issues.push("Currency must be a three-letter code, such as USD.");
    if (minimumQuantityValue === null) issues.push("Minimum quantity must be a positive whole number.");
    const validUntil = parseImportedDate(row.validUntil);
    if (validUntil === null) issues.push("Valid-until date could not be read.");
    if (row.sourceUrl && !/^https?:\/\//i.test(row.sourceUrl.trim())) issues.push("Source URL must start with http:// or https://.");
    if (!row.manufacturer.trim() && matchedPart) {
      warnings.push("Manufacturer comes from the matched BOM row; confirm the supplier listing is for that maker.");
    }
    if (!row.minimumQuantity.trim() && unitPriceValue !== null) {
      warnings.push("No minimum quantity supplied; this price tier starts at quantity 1.");
    }
    const priceDate = parseImportedDate(row.priceDate);
    if (priceDate === null) issues.push("Price date could not be read.");
    else if (!row.priceDate.trim()) warnings.push("No source price date supplied; Cadivor will show when this row was imported.");
    return {
      ...row,
      matchedPart,
      unitPriceValue,
      minimumQuantityValue,
      supplierValue,
      currencyValue,
      status: issues.length ? "issue" : "ready",
      message: issues.length ? issues.join(" ") : warnings.join(" "),
    };
  });
}

function ProcurementPageInner() {
  const session = useRequireSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [reports, setReports] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [filter, setFilter] = useState("");
  const [selectedAnalysisId, setSelectedAnalysisId] = useState("");
  const [selectedPartKey, setSelectedPartKey] = useState("");
  const [comparisonQuantity, setComparisonQuantity] = useState("");
  const [savedQuotes, setSavedQuotes] = useState<ProcurementQuote[]>([]);
  const [quotesBusy, setQuotesBusy] = useState(false);
  const [quoteForm, setQuoteForm] = useState<QuoteFormState>(() => emptyQuoteForm());
  const [quoteSaving, setQuoteSaving] = useState(false);
  const [quoteError, setQuoteError] = useState("");
  const [quoteSaved, setQuoteSaved] = useState("");
  const [bulkDefaultSupplier, setBulkDefaultSupplier] = useState("User price sheet");
  const [bulkDefaultCurrency, setBulkDefaultCurrency] = useState("USD");
  const [bulkFileName, setBulkFileName] = useState("");
  const [bulkImportBatchId, setBulkImportBatchId] = useState("");
  const [bulkSourceRows, setBulkSourceRows] = useState<PriceImportSourceRow[]>([]);
  const [bulkPreviewRows, setBulkPreviewRows] = useState<PriceImportRow[]>([]);
  const [bulkImportError, setBulkImportError] = useState("");
  const [bulkImportResult, setBulkImportResult] = useState("");
  const [bulkImportBusy, setBulkImportBusy] = useState(false);
  const [offersDialogPart, setOffersDialogPart] = useState<Record<string, unknown> | null>(null);
  const procurementCacheRef = useRef(new Map<string, Record<string, unknown>>());

  const requestedAnalysisId = useMemo(
    () => (searchParams.get("analysis_id") || "").trim(),
    [searchParams],
  );
  const requestedPartNumber = useMemo(
    () => (searchParams.get("part_number") || searchParams.get("mpn") || "").trim(),
    [searchParams],
  );

  useEffect(() => {
    if (!session) return;
    let active = true;
    let loadVersion = 0;
    let reportsResolved = false;
    let pendingProcurementError = "";
    const accessToken = session.access_token;
    const last = readLastAnalysis(session);
    const preferredId = requestedAnalysisId || last?.analysis_id || "";
    const cache = procurementCacheRef.current;

    setSelectedAnalysisId(preferredId);
    setError("");
    const cached = preferredId ? cache.get(preferredId) : undefined;
    setData(cached || null);
    setBusy(!cached);

    const remember = (analysisId: string, procurement: Record<string, unknown>) => {
      if (!analysisId) return;
      cache.set(analysisId, procurement);
      if (cache.size > 5) {
        const oldest = cache.keys().next().value;
        if (typeof oldest === "string") cache.delete(oldest);
      }
    };

    const loadAnalysis = async (analysisId: string) => {
      const id = analysisId.trim();
      const requestVersion = ++loadVersion;
      if (!id) {
        setData(null);
        setBusy(false);
        return;
      }
      const cachedForId = cache.get(id);
      if (cachedForId) {
        setData(cachedForId);
        setError(cachedForId.ok === false ? String(cachedForId.gap || "Procurement could not load that analysis.") : "");
        setBusy(false);
      } else {
        setData(null);
        setError("");
        setBusy(true);
      }

      try {
        const procurement = await fetchProcurement(accessToken, id);
        if (!active || requestVersion !== loadVersion) return;
        remember(id, procurement);
        setData(procurement);
        setError(
          procurement.ok === false
            ? String(procurement.gap || "Procurement could not load that analysis.")
            : "",
        );
      } catch (err) {
        if (!active || requestVersion !== loadVersion) return;
        const message = err instanceof Error ? err.message : "Procurement data could not be loaded.";
        if (cachedForId) {
          setData(cachedForId);
        } else {
          setData(null);
        }
        if (reportsResolved) setError(message);
        else pendingProcurementError = message;
      } finally {
        if (active && requestVersion === loadVersion) setBusy(false);
      }
    };

    // Start the selected analysis immediately. Reports load independently, so
    // the slower directory request cannot hold the main Procurement view.
    if (preferredId) void loadAnalysis(preferredId);
    else setBusy(true);

    void listReports(accessToken)
      .then(({ reports: reportRows }) => {
        if (!active) return;
        reportsResolved = true;
        const visibleReports = (reportRows || []) as Array<Record<string, unknown>>;
        setReports(visibleReports);
        const availableIds = new Set(
          visibleReports.map((row) => String(row.id || "").trim()).filter(Boolean),
        );
        const safeAnalysisId = availableIds.has(preferredId)
          ? preferredId
          : String(visibleReports[0]?.id || "").trim();

        if (safeAnalysisId !== preferredId) {
          setSelectedAnalysisId(safeAnalysisId);
          router.replace(
            safeAnalysisId
              ? `/procurement?analysis_id=${encodeURIComponent(safeAnalysisId)}`
              : "/procurement",
          );
          if (!safeAnalysisId) {
            setData(null);
            setBusy(false);
            setError("");
          }
          return;
        }

        setSelectedAnalysisId(safeAnalysisId);
        if (pendingProcurementError) setError(pendingProcurementError);
        if (!safeAnalysisId) {
          setData(null);
          setBusy(false);
          setError("");
        }
      })
      .catch((err) => {
        if (!active) return;
        reportsResolved = true;
        setReports([]);
        if (!preferredId) {
          setBusy(false);
          setError(err instanceof Error ? err.message : "Saved analyses could not be loaded.");
        } else if (pendingProcurementError) {
          setError(pendingProcurementError);
        }
      });

    return () => {
      active = false;
      loadVersion += 1;
    };
  }, [session, requestedAnalysisId, router]);

  const allParts = useMemo(
    () => (((data?.parts || []) as Array<Record<string, unknown>>) || []),
    [data],
  );

  useEffect(() => {
    if (!allParts.length) {
      setSelectedPartKey("");
      return;
    }
    const requestedKey = requestedPartNumber.trim().toLowerCase();
    const requestedPart = requestedKey
      ? allParts.find((part) => String(part.mpn || part.MPN || "").trim().toLowerCase() === requestedKey)
      : undefined;
    const chosen = requestedPart || allParts.find((part) => partKey(part) === selectedPartKey) || allParts[0];
    if (partKey(chosen) !== selectedPartKey) {
      setSelectedPartKey(partKey(chosen));
      setQuoteForm(emptyQuoteForm(String(chosen.mpn || chosen.MPN || "")));
      setComparisonQuantity("");
    }
  }, [allParts, selectedPartKey, requestedPartNumber]);

  const quoteAnalysisId = requestedAnalysisId || selectedAnalysisId;

  useEffect(() => {
    if (!session || !quoteAnalysisId) {
      setSavedQuotes([]);
      return;
    }
    let active = true;
    setQuotesBusy(true);
    setSavedQuotes([]);
    setQuoteError("");
    setQuoteSaved("");
    listProcurementQuotes(session.access_token, quoteAnalysisId)
      .then(({ quotes }) => {
        if (active) setSavedQuotes(quotes || []);
      })
      .catch((err) => {
        if (active) setQuoteError(err instanceof Error ? err.message : "Unable to load saved quotes.");
      })
      .finally(() => {
        if (active) setQuotesBusy(false);
      });
    return () => {
      active = false;
    };
  }, [session, quoteAnalysisId]);

  useEffect(() => {
    if (!offersDialogPart) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOffersDialogPart(null);
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [offersDialogPart]);

  const parts = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return allParts;
    return allParts.filter((p) =>
      [p.mpn, p.manufacturer, p.category, p.supplier, p.recommendation, p.lifecycle, p.coverage]
        .map((v) => String(v || "").toLowerCase())
        .some((v) => v.includes(q)),
    );
  }, [allParts, filter]);

  const evidenceSummary = (data?.evidence_summary || {}) as Record<string, unknown>;
  const liveParts = Number(evidenceSummary.live_parts || 0);
  const sampleParts = Number(evidenceSummary.sample_parts || 0);
  const unverifiedParts = Number(evidenceSummary.unverified_parts || 0);
  const unmatchedParts = Number(evidenceSummary.parts_without_supplier_match || 0);
  const partsTotal = Number(evidenceSummary.parts_total || ((data?.parts as unknown[]) || []).length || 0);
  const sourcingBadgeParts = [
    liveParts ? `Live: ${liveParts}` : "",
    sampleParts ? `Synthetic estimates: ${sampleParts}` : "",
    unverifiedParts ? `Needs supplier verification: ${unverifiedParts}` : "",
    unmatchedParts ? `No supplier match: ${unmatchedParts}` : "",
  ].filter(Boolean);
  const sourcingBadge = partsTotal
    ? `${sourcingBadgeParts.join("; ") || `${partsTotal} parts`} (of ${partsTotal})`
    : "";
  const activeAnalysisId = String(data?.analysis_id || selectedAnalysisId || "").trim();
  const selectedPart =
    allParts.find((part) => partKey(part) === selectedPartKey) || allParts[0] || null;
  const contextLabel = [
    userFacingLabel(data?.project_name, ""),
    userFacingLabel(data?.bom_name || data?.filename, ""),
    data?.revision ? `rev ${userFacingLabel(data.revision, "—")}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const display = (value: unknown, fallback = "Not recorded") => {
    if (value === null || value === undefined || String(value).trim() === "") return fallback;
    return cleanUserText(String(value));
  };

  const comparisonRows: ComparisonRow[] = useMemo(() => {
    if (!selectedPart) return [];
    const targetMpn = String(selectedPart.mpn || "").trim();
    const targetManufacturer = String(selectedPart.manufacturer || "").trim();
    const evidenceClass = String(selectedPart.evidence_class || "").trim().toLowerCase();
    const liveCatalogEvidence = evidenceClass === "live-authorized-supplier" || evidenceClass.startsWith("live-");
    const offers = Array.isArray(selectedPart.supplier_offers)
      ? selectedPart.supplier_offers as Array<Record<string, unknown>>
      : [];
    const offerGroups = new Map<string, Array<Record<string, unknown>>>();
    for (const offer of offers) {
      const groupKey = [
        offer.supplier,
        offer.offered_mpn,
        offer.offered_manufacturer,
        offer.currency,
        offer.product_url,
        offer.retrieved_at,
        offer.stock,
        offer.region,
        offer.quote_reference,
      ].map((value) => String(value || "").trim().toLowerCase()).join("\u0000");
      offerGroups.set(groupKey, [...(offerGroups.get(groupKey) || []), offer]);
    }
    const catalogRows: ComparisonRow[] = Array.from(offerGroups.entries()).map(
      ([groupKey, groupOffers], index) => {
        const offer = groupOffers[0] || {};
        const offeredMpn = String(offer.offered_mpn || "").trim();
        const offeredManufacturer = String(offer.offered_manufacturer || "").trim();
        const identityStatus = describeCatalogIdentity(
          targetMpn,
          targetManufacturer,
          offeredMpn,
          offeredManufacturer,
        );
        const normalizedBreaks = groupOffers.flatMap((groupOffer) => {
          const breaks = Array.isArray(groupOffer.price_breaks)
            ? groupOffer.price_breaks.flatMap((raw) => {
                if (!raw || typeof raw !== "object") return [];
                const row = raw as Record<string, unknown>;
                const quantity = optionalNumber(row.quantity);
                const unitPrice = optionalNumber(row.unit_price);
                return quantity !== null && unitPrice !== null ? [{ quantity, unit_price: unitPrice }] : [];
              })
            : [];
          const breakQuantity = optionalNumber(groupOffer.price_break_quantity);
          const unitPrice = optionalNumber(groupOffer.unit_price);
          if (!breaks.length && breakQuantity !== null && unitPrice !== null) {
            breaks.push({ quantity: breakQuantity, unit_price: unitPrice });
          }
          return breaks;
        });
        const priceBreaks = Array.from(
          new Map(normalizedBreaks.map((priceBreak) => [priceBreak.quantity, priceBreak])).values(),
        ).sort((a, b) => a.quantity - b.quantity);
        const priceBreakQuantity = optionalNumber(offer.price_break_quantity);
        const unitPrice = optionalNumber(offer.unit_price);
        return {
          id: "offer-" + index + "-" + String(offer.supplier || groupKey),
          kind: "Saved catalog offer" + (liveCatalogEvidence ? " · live evidence" : " · not verified live"),
          supplier: String(offer.supplier || "Supplier not recorded"),
          quoteReference: String(offer.quote_reference || ""),
          offeredMpn,
          offeredManufacturer,
          identityStatus,
          exactPart: identityStatus === "Exact MPN and manufacturer",
          currency: String(offer.currency || "").toUpperCase(),
          unitPrice: unitPrice ?? priceBreaks[0]?.unit_price ?? null,
          priceBreakQuantity: priceBreakQuantity ?? priceBreaks[0]?.quantity ?? null,
          priceBreaks,
          minimumOrderQuantity: optionalNumber(offer.minimum_order_quantity),
          packQuantity: optionalNumber(offer.pack_quantity),
          leadTimeWeeks: optionalNumber(offer.lead_time_weeks),
          stock: optionalNumber(offer.stock),
          validUntil: String(offer.valid_until || ""),
          sourceUrl: String(offer.product_url || ""),
          sourceTime: String(offer.retrieved_at || ""),
          notes: [
            String(offer.region || ""),
            ...(!liveCatalogEvidence ? ["Saved analysis does not confirm this as a live supplier quote."] : []),
          ].filter(Boolean).join(" · "),
          canPriceCompare: liveCatalogEvidence,
        };
      },
    );
    const enteredRows: ComparisonRow[] = savedQuotes
      .filter((quote) =>
        quote.requested_mpn.trim().toLowerCase() === targetMpn.toLowerCase()
        && String(quote.requested_manufacturer || "").trim().toLowerCase() === targetManufacturer.toLowerCase(),
      )
      .map((quote) => ({
        id: quote.quote_id || quote.id,
        kind: "User-entered quote",
        supplier: quote.supplier,
        quoteReference: quote.quote_reference || "",
        offeredMpn: quote.offered_mpn,
        offeredManufacturer: quote.offered_manufacturer || "",
        identityStatus: quote.identity_status === "exact_part"
          ? "Exact MPN and manufacturer"
          : quote.identity_status === "manufacturer_unconfirmed"
            ? "MPN matches; manufacturer unconfirmed"
            : "Alternate candidate — engineering review required",
        exactPart: quote.identity_status === "exact_part",
        currency: String(quote.currency || "").toUpperCase(),
        unitPrice: optionalNumber(quote.unit_price),
        priceBreakQuantity: optionalNumber(quote.price_break_quantity),
        priceBreaks: (quote.price_breaks || []).map((row) => ({
          quantity: Number(row.quantity), unit_price: Number(row.unit_price),
        })),
        minimumOrderQuantity: optionalNumber(quote.minimum_order_quantity),
        packQuantity: optionalNumber(quote.pack_quantity),
        leadTimeWeeks: optionalNumber(quote.lead_time_weeks),
        stock: optionalNumber(quote.stock),
        validUntil: quote.valid_until || "",
        sourceUrl: quote.source_url || "",
        sourceTime: quote.created_at || "",
        notes: quote.notes || "",
        canPriceCompare: true,
      }));
    return [...catalogRows, ...enteredRows].sort((a, b) => Number(b.exactPart) - Number(a.exactPart));
  }, [savedQuotes, selectedPart]);

  const comparisonSummaries = useMemo(() => {
    const quantity = Number(comparisonQuantity);
    if (!Number.isSafeInteger(quantity) || quantity <= 0) return [];
    const today = new Date().toISOString().slice(0, 10);
    const candidates = comparisonRows.flatMap((row) => {
      if (!row.canPriceCompare || !row.exactPart || !row.currency || (row.validUntil && row.validUntil < today)) return [];
      if (row.minimumOrderQuantity !== null && (row.minimumOrderQuantity <= 0 || quantity < row.minimumOrderQuantity)) return [];
      if (row.packQuantity !== null && (row.packQuantity <= 0 || quantity % row.packQuantity !== 0)) return [];
      const tier = [...row.priceBreaks]
        .filter((priceBreak) => priceBreak.quantity <= quantity)
        .sort((a, b) => b.quantity - a.quantity)[0];
      return tier ? [{ row, price: tier.unit_price }] : [];
    });
    const currencies = Array.from(new Set(candidates.map(({ row }) => row.currency)));
    return currencies.map((currency) => {
      const matching = candidates.filter(({ row }) => row.currency === currency);
      const lowest = [...matching].sort((a, b) => a.price - b.price)[0];
      return { currency, price: lowest.price, supplier: lowest.row.supplier, reference: lowest.row.quoteReference };
    });
  }, [comparisonQuantity, comparisonRows]);

  async function saveQuote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !selectedPart || !activeAnalysisId) return;
    const hasPartialPriceBreak = quoteForm.price_breaks.some(
      (row) => Boolean(row.quantity.trim()) !== Boolean(row.unit_price.trim()),
    );
    if (hasPartialPriceBreak) {
      setQuoteError("Enter both a quantity and unit price for each price break, or leave both blank.");
      return;
    }
    setQuoteSaving(true);
    setQuoteError("");
    setQuoteSaved("");
    try {
      const priceBreaks = quoteForm.price_breaks
        .filter((row) => row.quantity.trim() || row.unit_price.trim())
        .map((row) => ({ quantity: Number(row.quantity), unit_price: Number(row.unit_price) }));
      const result = await createProcurementQuote(session.access_token, {
        analysis_id: activeAnalysisId,
        requested_mpn: String(selectedPart.mpn || ""),
        requested_manufacturer: String(selectedPart.manufacturer || ""),
        supplier: quoteForm.supplier.trim(),
        quote_reference: quoteForm.quote_reference.trim(),
        offered_mpn: quoteForm.offered_mpn.trim(),
        offered_manufacturer: quoteForm.offered_manufacturer.trim(),
        currency: quoteForm.currency.trim(),
        price_breaks: priceBreaks,
        minimum_order_quantity: quoteForm.minimum_order_quantity.trim() ? Number(quoteForm.minimum_order_quantity) : null,
        pack_quantity: quoteForm.pack_quantity.trim() ? Number(quoteForm.pack_quantity) : null,
        lead_time_weeks: quoteForm.lead_time_weeks.trim() ? Number(quoteForm.lead_time_weeks) : null,
        stock: quoteForm.stock.trim() ? Number(quoteForm.stock) : null,
        valid_until: quoteForm.valid_until,
        source_url: quoteForm.source_url.trim(),
        notes: quoteForm.notes.trim(),
      });
      setSavedQuotes((current) => [result.quote, ...current]);
      setQuoteSaved("Quote saved to this BOM revision. User-entered terms are not supplier-verified by Cadivor.");
      setQuoteForm(emptyQuoteForm(String(selectedPart.mpn || "")));
    } catch (err) {
      setQuoteError(err instanceof Error ? err.message : "Unable to save this quote.");
    } finally {
      setQuoteSaving(false);
    }
  }

  async function handlePriceImportFile(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    setBulkImportError("");
    setBulkImportResult("");
    setBulkSourceRows([]);
    setBulkPreviewRows([]);
    setBulkFileName("");
    setBulkImportBatchId("");
    try {
      const lowerName = file.name.toLowerCase();
      if (!lowerName.endsWith(".csv") && !lowerName.endsWith(".xlsx")) {
        throw new Error("Choose a .csv or .xlsx file. Save older .xls workbooks as .xlsx first.");
      }
      if (file.size > 5 * 1024 * 1024) throw new Error("Price files must be 5 MB or smaller.");
      let table: unknown[][];
      if (lowerName.endsWith(".csv")) {
        table = parseDelimitedRows(await file.text());
      } else {
        const { readSheet } = await import("read-excel-file/browser");
        table = await readSheet(file);
      }
      const sourceRows = parsePriceImportTable(table);
      if (!sourceRows.length) throw new Error("No price rows were found below the header.");
      setBulkSourceRows(sourceRows);
      setBulkFileName(file.name);
      setBulkImportBatchId(window.crypto.randomUUID());
      setBulkImportResult(`${sourceRows.length} rows loaded from the first worksheet. Review the defaults, then preview the matches.`);
    } catch (err) {
      setBulkImportError(err instanceof Error ? err.message : "This file could not be read.");
    }
  }

  function downloadPriceImportTemplate() {
    const csv = "part_number,unit_price,minimum_quantity,currency,supplier,manufacturer,quote_reference,price_date,valid_until,source_url\r\n";
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "cadivor-price-import-template.csv";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function previewPriceImport() {
    if (!bulkSourceRows.length) return;
    setBulkPreviewRows(preparePriceImport(bulkSourceRows, allParts, bulkDefaultSupplier, bulkDefaultCurrency));
    setBulkImportError("");
    setBulkImportResult("");
  }

  async function saveBulkPriceImport() {
    if (!session || !activeAnalysisId || !bulkImportBatchId || bulkImportBusy) return;
    const rowsToSave = bulkPreviewRows.filter((row) => row.status === "ready" || row.status === "failed");
    if (!rowsToSave.length) return;
    setBulkImportBusy(true);
    setBulkImportError("");
    setBulkImportResult(`Saving ${rowsToSave.length} quote${rowsToSave.length === 1 ? "" : "s"} to this BOM revision…`);
    try {
      const quoteInputs = rowsToSave.flatMap((row) => {
        const matchedPart = row.matchedPart;
        if (!matchedPart || row.unitPriceValue === null || row.minimumQuantityValue === null) return [];
        const bomMpn = String(matchedPart.mpn || matchedPart.MPN || row.partNumber).trim();
        const bomManufacturer = String(matchedPart.manufacturer || "").trim();
        const parsedValidUntil = parseImportedDate(row.validUntil);
        const notes = [
          `Imported from ${bulkFileName}, row ${row.line}.`,
          !row.manufacturer.trim() ? "The uploaded row omitted the quoted manufacturer; verify that the supplier listing is for the saved BOM manufacturer." : "",
          !row.minimumQuantity.trim() ? "Minimum price-tier quantity defaulted to 1 from the upload." : "",
          !row.priceDate.trim() ? "The source sheet did not provide a price date; the import date is shown as the record date." : "",
        ].filter(Boolean).join(" ");
        return [{
          import_row_number: row.line,
          requested_mpn: bomMpn,
          requested_manufacturer: bomManufacturer,
          supplier: row.supplierValue,
          quote_reference: row.quoteReference.trim(),
          offered_mpn: bomMpn,
          offered_manufacturer: row.manufacturer.trim(),
          currency: row.currencyValue,
          price_breaks: [{ quantity: row.minimumQuantityValue, unit_price: row.unitPriceValue }],
          price_date: parseImportedDate(row.priceDate) || "",
          minimum_order_quantity: null,
          pack_quantity: null,
          valid_until: parsedValidUntil || "",
          source_url: row.sourceUrl.trim(),
          notes,
        }];
      });
      if (!quoteInputs.length) throw new Error("No valid matched rows are ready to import.");
      const result = await createProcurementQuotesBulk(
        session.access_token,
        activeAnalysisId,
        bulkImportBatchId,
        quoteInputs,
      );
      const savedLineNumbers = new Set(result.quotes.map((quote) => Number((quote as ProcurementQuote & { import_row_number?: number }).import_row_number)));
      setSavedQuotes((current) => [...result.quotes, ...current]);
      setBulkPreviewRows((current) => current.map((row) => savedLineNumbers.has(row.line)
        ? { ...row, status: "saved", message: "Saved to this BOM revision." }
        : row));
      setBulkImportResult(`${result.saved_count} quote${result.saved_count === 1 ? "" : "s"} saved to this BOM revision. Open Cost Optimization and select Recalculate to use these prices.`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to save this price import.";
      setBulkImportError(message);
      const pendingLines = new Set(rowsToSave.map((row) => row.line));
      setBulkPreviewRows((current) => current.map((row) => pendingLines.has(row.line)
        ? { ...row, status: "failed", message }
        : row));
      setBulkImportResult("No rows were saved. Resolve the issue or retry the same import.");
    } finally {
      setBulkImportBusy(false);
    }
  }

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.procurement}
        actions={
          <div className="cv-page-head-actions">
            <PrimaryLink href={savedBomAnalysisHref(activeAnalysisId)}>
              {activeAnalysisId ? "Analyze this BOM again" : "Run new BOM analysis"}
            </PrimaryLink>
            <SecondaryLink href={withAnalysisId("/cost-optimization", activeAnalysisId)}>Cost optimization</SecondaryLink>
            <SecondaryLink href={withAnalysisId("/compare-parts", activeAnalysisId)}>Compare alternatives</SecondaryLink>
          </div>
        }
      />
      {<EvidenceNotice gap={data?.gap} />}
      <section className="cv-card pad cv-procurement-guide" aria-labelledby="cv-procurement-guide-title">
        <div>
          <span className="cv-procurement-guide-eyebrow">How to use this page</span>
          <h2 id="cv-procurement-guide-title">Turn supplier evidence into a sourcing decision</h2>
          <p>
            Choose a saved BOM revision, review parts that need verification, then confirm the supplier listing or record a current quote.
            Cadivor does not place orders or create binding quotes.
          </p>
          <p className="cv-small-note">
            Offers stay with this report. Check each offer’s retrieval time for its age. To get a new Procurement snapshot, analyze this saved BOM again; Cadivor preloads its component list so you do not need to upload the file again. Monitoring refreshes update Monitoring evidence and alerts only.
          </p>
        </div>
        <ol>
          <li><strong>Pick the revision</strong><span>Keep the sourcing review tied to the BOM you intend to build.</span></li>
          <li><strong>Resolve the blockers</strong><span>Check exact part identity, availability, lead time, and missing terms.</span></li>
          <li><strong>Compare the evidence</strong><span>Use confirmed matches for price checks; ask the supplier about anything not reported.</span></li>
        </ol>
      </section>
      {busy ? <LoadingCard label="Loading procurement coverage…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {!busy && data ? (
        <>
          <section className="cv-card pad">
            <div className="cv-section-heading" style={{ marginTop: 0 }}>
              <div>
                <h2 className="cv-card-title" style={{ fontSize: 15 }}>
                  Supplier evidence
                </h2>
                <p className="cv-card-subtitle">
                  {String(data.recommendation_note || "Review sourcing coverage from the selected analysis.")}
                </p>
                <p className="cv-small-note" style={{ marginTop: 8 }} data-testid="procurement-context">
                  {contextLabel
                    ? `Showing ${contextLabel}`
                    : activeAnalysisId
                      ? "Showing the selected saved analysis"
                      : "No analysis selected — choose a saved BOM below."}
                </p>
              </div>
              {sourcingBadge ? (
                <span className="cv-badge gray" data-testid="procurement-evidence-summary">
                  {sourcingBadge}
                </span>
              ) : null}
            </div>

            <div className="cv-sourcing-controls">
              <select
                aria-label="Sourcing BOM context"
                value={selectedAnalysisId}
                onChange={(event) => {
                  const nextId = event.target.value;
                  setSelectedAnalysisId(nextId);
                  router.replace(nextId ? `/procurement?analysis_id=${encodeURIComponent(nextId)}` : "/procurement");
                }}
              >
                <option value="">Select a saved analysis</option>
                {reports.map((row) => {
                  const id = String(row.id || "").trim();
                  if (!id) return null;
                  return (
                    <option key={id} value={id}>
                      {analysisLabel(row)}
                    </option>
                  );
                })}
              </select>
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter by MPN or supplier"
                aria-label="Filter sourcing rows"
                style={{ width: 240 }}
              />
              <span style={{ flex: 1 }} />
            </div>

            {parts.length ? (
              <div className="cv-table-wrap">
                <table className="cv-table cv-procurement-table">
                  <thead>
                    <tr>
                      <th>Part</th>
                      <th>Next action</th>
                      <th>Risk and lifecycle</th>
                      <th>Supplier evidence</th>
                      <th>Recorded price and availability</th>
                      <th>Saved offers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {parts.map((p, i) => {
                      const offers = Array.isArray(p.supplier_offers)
                        ? p.supplier_offers as Array<Record<string, unknown>>
                        : [];
                      const risk = display(p.risk_level, "Needs verification");
                      return (
                        <tr key={String(p.mpn || "part") + "-" + i}>
                          <td>
                            <div className="cv-part-cell">
                              <PartThumbnail part={p} />
                              <div>
                                <strong>{display(p.mpn, "MPN not recorded")}</strong>
                                <small className="cv-procurement-description">
                                  {display(p.manufacturer, "Manufacturer not recorded")}
                                </small>
                                {p.description ? <small className="cv-procurement-description">{String(p.description)}</small> : null}
                                <small className="cv-procurement-description">
                                  Required quantity: {display(p.quantity, "Not provided")}
                                </small>
                              </div>
                            </div>
                          </td>
                          <td className="cv-procurement-recommendation">
                            <strong>{display(p.recommendation, "Verify with a configured supplier")}</strong>
                            <small>
                              {display(
                                p.next_step,
                                "Confirm exact identity, current stock, lead time, and price before ordering.",
                              )}
                            </small>
                          </td>
                          <td>
                            <span className={"cv-badge " + riskBadgeClass(risk)}>{risk}</span>
                            <small className="cv-procurement-description">
                              Lifecycle: {display(p.lifecycle, "Not provided by source")}
                            </small>
                          </td>
                          <td>
                            <strong>{display(p.supplier, "Supplier match not confirmed")}</strong>
                            <small className="cv-procurement-description">
                              {p.supplier_count == null
                                ? "Source count not provided"
                                : String(p.supplier_count) + " source" + (Number(p.supplier_count) === 1 ? "" : "s")}
                            </small>
                            <small className="cv-procurement-description">
                              {evidenceSourceLabel(p.price_source, "Source not recorded")}
                              {p.identity_source ? " · identity: " + evidenceSourceLabel(p.identity_source, "not recorded") : ""}
                            </small>
                            {p.price_retrieved_at || p.retrieved_at ? (
                              <small className="cv-procurement-timestamp">
                                Retrieved: {String(p.price_retrieved_at || p.retrieved_at)}
                              </small>
                            ) : null}
                          </td>
                          <td>
                            <strong>
                              {p.unit_price == null
                                ? "Price not provided"
                                : String(p.unit_price) + (p.currency ? " " + String(p.currency) : " · currency not recorded")}
                            </strong>
                            <small className="cv-procurement-description">
                              Stock: {display(p.stock, "Not provided")}
                            </small>
                            <small className="cv-procurement-description">
                              Lead time: {p.lead_time_weeks == null ? "Not provided" : String(p.lead_time_weeks) + " weeks"}
                            </small>
                            {p.price_type ? (
                              <small className="cv-procurement-description">Price basis: {String(p.price_type)}</small>
                            ) : null}
                          </td>
                          <td>
                            <div style={{ display: "grid", gap: 6, justifyItems: "start" }}>
                              {offers.length ? (
                                <button
                                  className="cv-procurement-offers-button"
                                  type="button"
                                  onClick={() => setOffersDialogPart(p)}
                                  aria-label={"View " + offers.length + " saved offers for " + display(p.mpn, "this part")}
                                  aria-haspopup="dialog"
                                >
                                  View {offers.length} offer{offers.length === 1 ? "" : "s"}
                                </button>
                              ) : (
                                <span className="cv-small-note">No saved offers</span>
                              )}
                              {activeAnalysisId && String(p.mpn || "").trim() ? (
                                <>
                                  <Link
                                    className="cv-button small"
                                    href={supplierRefreshHref(activeAnalysisId, String(p.mpn).trim())}
                                    aria-label={"Open Monitoring supplier refresh for " + display(p.mpn, "this part")}
                                    title="Opens Monitoring with this part selected"
                                  >
                                    Open part in Monitoring
                                  </Link>
                                  <small className="cv-procurement-description">
                                    Monitoring refresh does not change these offers.
                                  </small>
                                </>
                              ) : null}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState
                icon="procure"
                title={filter ? "No sourcing rows match this filter" : "No sourcing rows available"}
                body={filter ? "Try another part number, manufacturer, lifecycle, or coverage term." : "Analyze a BOM to review its available supplier coverage and source labels here."}
                action={<PrimaryLink href="/bom-analyzer">Open BOM Analyzer</PrimaryLink>}
              />
            )}
          </section>

          <section className="cv-card pad cv-quote-comparison" data-testid="procurement-quote-comparison">
            <div className="cv-section-heading" style={{ marginTop: 0 }}>
              <div>
                <h2 className="cv-card-title" style={{ fontSize: 16 }}>Quote comparison</h2>
                <p className="cv-card-subtitle">
                  Compare saved supplier snapshots and manually recorded quotes for this BOM part. A lower price is only a starting point: verify the exact part, current price, and order terms with the supplier.
                </p>
                <p className="cv-small-note" style={{ marginTop: 7 }}>
                  “Not provided” means the source did not report it; it does not mean zero or unavailable. Cadivor only applies recorded MOQ and pack rules, so confirm any missing terms before ordering.
                </p>
              </div>
              <span className="cv-badge gray">{contextLabel || "Saved BOM context required"}</span>
            </div>

            {activeAnalysisId && allParts.length ? (
              <>
                <div className="cv-quote-controls">
                  <label>
                    <span>BOM part</span>
                    <select
                      aria-label="BOM part for quote comparison"
                      value={selectedPart ? partKey(selectedPart) : ""}
                      onChange={(event) => {
                        const nextPart = allParts.find((part) => partKey(part) === event.target.value);
                        setSelectedPartKey(event.target.value);
                        setComparisonQuantity("");
                        setQuoteError("");
                        setQuoteSaved("");
                        setQuoteForm(emptyQuoteForm(String(nextPart?.mpn || "")));
                      }}
                    >
                      {allParts.map((part, index) => (
                        <option key={`${partKey(part)}-${index}`} value={partKey(part)}>
                          {String(part.mpn || "MPN not recorded")}{part.manufacturer ? ` · ${String(part.manufacturer)}` : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Planned order quantity</span>
                    <input
                      aria-label="Planned order quantity for price comparison"
                      type="number"
                      min="1"
                      step="1"
                      value={comparisonQuantity}
                      onChange={(event) => setComparisonQuantity(event.target.value)}
                      placeholder="Enter quantity to compare price breaks"
                    />
                  </label>
                </div>

                {comparisonQuantity.trim() ? (
                  <div
                    className={"cv-quote-price-summary " + (comparisonSummaries.length ? "is-ready" : "is-review")}
                    role="status"
                  >
                    <strong>Price check for {comparisonQuantity} units</strong>
                    {!Number.isSafeInteger(Number(comparisonQuantity)) || Number(comparisonQuantity) <= 0 ? (
                      <p>Enter a whole-number quantity greater than zero to compare price breaks.</p>
                    ) : comparisonSummaries.length ? (
                      <ul>
                        {comparisonSummaries.map((summary) => (
                          <li key={summary.currency}>
                            Lowest recorded tier that fits the known quantity rules: {summary.currency} {summary.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })} per unit from {summary.supplier}{summary.reference ? " (" + cleanUserText(summary.reference) + ")" : ""}. Confirm any missing order terms with the supplier.
                          </li>
                        ))}
                      </ul>
                    ) : comparisonRows.some((row) => row.canPriceCompare && row.exactPart) ? (
                      <p>
                        Exact-part prices were found, but none qualifies for this quantity. Check recorded price-break, minimum-order, pack, currency, or expiry details; confirm any missing terms with the supplier.
                      </p>
                    ) : comparisonRows.some((row) => row.canPriceCompare && !row.exactPart) ? (
                      <p>
                        Supplier listings were found, but the exact part identity is not confirmed. Verify the manufacturer and part listing before comparing its price.
                      </p>
                    ) : comparisonRows.length ? (
                      <p>
                        Saved records exist, but none is current, live evidence for an exact part match. Verify the supplier listing or record a current quote.
                      </p>
                    ) : (
                      <p>
                        No supplier offers or saved quotes are recorded for this part yet. Add a supplier quote below after you receive one.
                      </p>
                    )}
                    <small>
                      Only exact MPN and manufacturer matches can appear in the price ranking. Missing MOQ, pack, stock, validity, freight, duty/tax, and qualification details remain unconfirmed.
                    </small>
                  </div>
                ) : null}

                <div className="cv-table-wrap cv-quote-table-wrap">
                  <table className="cv-table cv-quote-table">
                    <thead>
                      <tr>
                        <th>Supplier</th>
                        <th>Part match</th>
                        <th>Price</th>
                        <th>Availability</th>
                        <th>Order terms</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparisonRows.map((row) => {
                        const today = new Date().toISOString().slice(0, 10);
                        const requestedMpn = String(selectedPart?.mpn || "");
                        const requestedManufacturer = String(selectedPart?.manufacturer || "");
                        const needsEngineeringComparison = Boolean(row.offeredMpn)
                          && row.offeredMpn.trim().toLowerCase() !== requestedMpn.trim().toLowerCase();
                        const quantity = Number(comparisonQuantity);
                        const validQuantity = Number.isSafeInteger(quantity) && quantity > 0;
                        const tier = validQuantity
                          ? [...row.priceBreaks]
                              .filter((priceBreak) => priceBreak.quantity <= quantity)
                              .sort((a, b) => b.quantity - a.quantity)[0]
                          : null;
                        const isExpired = Boolean(row.validUntil && row.validUntil < today);
                        const orderTermsAllowQuantity = validQuantity
                          && (row.minimumOrderQuantity === null || quantity >= row.minimumOrderQuantity)
                          && (row.packQuantity === null || (row.packQuantity > 0 && quantity % row.packQuantity === 0));
                        const canUsePrice = Boolean(
                          tier
                          && row.canPriceCompare
                          && row.exactPart
                          && row.currency
                          && !isExpired
                          && orderTermsAllowQuantity,
                        );
                        const priceLabel = validQuantity
                          ? canUsePrice
                            ? row.currency + " " + tier!.unit_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 }) + " / unit"
                            : row.exactPart
                              ? "No verified tier at this quantity"
                              : "Identity needs verification"
                          : row.priceBreaks.length
                            ? row.currency + " " + row.priceBreaks[0].unit_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 }) + " from " + row.priceBreaks[0].quantity.toLocaleString() + "+ units"
                            : row.unitPrice === null
                              ? "Price not provided"
                              : row.currency
                                ? row.currency + " " + row.unitPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 }) + " · break quantity not provided"
                                : "Currency not provided";
                        const missingTerms = [
                          row.minimumOrderQuantity === null ? "MOQ" : "",
                          row.packQuantity === null ? "pack size" : "",
                          row.leadTimeWeeks === null ? "lead time" : "",
                          row.stock === null ? "stock" : "",
                          !row.validUntil ? "validity" : "",
                        ].filter(Boolean);
                        const availability = [
                          row.stock === null ? "Stock not provided" : "Stock " + row.stock.toLocaleString(),
                          row.leadTimeWeeks === null ? "" : row.leadTimeWeeks + " week lead time",
                        ].filter(Boolean).join(" · ");
                        return (
                          <tr key={row.id}>
                            <td>
                              <strong>{row.supplier}</strong>
                              <small className="cv-procurement-description">
                                {cleanUserText(row.kind)}{row.quoteReference ? " · " + cleanUserText(row.quoteReference) : ""}
                              </small>
                            </td>
                            <td>
                              <span className={"cv-badge " + (row.exactPart ? "green" : "amber")}>
                                {row.identityStatus}
                              </span>
                              <small className="cv-procurement-description">
                                {row.offeredMpn || "MPN not recorded"}{row.offeredManufacturer ? " · " + row.offeredManufacturer : " · manufacturer not reported"}
                              </small>
                              {needsEngineeringComparison ? (
                                <Link className="cv-quote-review-link" href={engineeringComparisonHref(
                                  activeAnalysisId,
                                  requestedMpn,
                                  requestedManufacturer,
                                  row.offeredMpn,
                                  row.offeredManufacturer,
                                )}>
                                  Review alternate fit
                                </Link>
                              ) : null}
                            </td>
                            <td>
                              <strong>{priceLabel}</strong>
                              {validQuantity && tier && !canUsePrice ? (
                                <small className="cv-procurement-description">A required identity or order term is not confirmed.</small>
                              ) : !validQuantity && row.priceBreaks.length > 1 ? (
                                <small className="cv-procurement-description">{row.priceBreaks.length} price tiers · enter quantity to see applicable tier</small>
                              ) : null}
                            </td>
                            <td>{availability || "Availability not provided"}</td>
                            <td>
                              <span className={"cv-badge " + (missingTerms.length ? "amber" : "green")}>
                                {missingTerms.length ? missingTerms.length + " terms not provided" : "Key terms recorded"}
                              </span>
                              {missingTerms.length ? (
                                <small className="cv-procurement-description">Missing: {missingTerms.join(", ")}</small>
                              ) : null}
                              {row.validUntil && isExpired ? (
                                <small className="cv-procurement-description">Expired {row.validUntil}</small>
                              ) : null}
                            </td>
                            <td>
                              {row.sourceUrl.startsWith("https://") || row.sourceUrl.startsWith("http://") ? (
                                <a href={row.sourceUrl} target="_blank" rel="noreferrer">Open supplier listing</a>
                              ) : (
                                <span>{row.kind.startsWith("User-entered") ? "Quote source not linked" : "Supplier listing not linked"}</span>
                              )}
                              <small className="cv-procurement-timestamp">
                                {row.sourceTime
                                  ? (row.kind.startsWith("User-entered") ? "Recorded: " : "Retrieved: ") + row.sourceTime
                                  : "Source date not recorded"}
                              </small>
                              {!row.canPriceCompare ? (
                                <small className="cv-procurement-description">Saved snapshot; not confirmed as live evidence.</small>
                              ) : null}
                            </td>
                          </tr>
                        );
                      })}
                      {!comparisonRows.length ? (
                        <tr><td colSpan={6}>No offers are saved for this part yet. Record a supplier quote to compare it here.</td></tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
                {quotesBusy ? <p className="cv-small-note" aria-live="polite">Loading saved quotes…</p> : null}

                <section className="cv-price-import" aria-labelledby="cv-price-import-title">
                  <div>
                    <h3 id="cv-price-import-title">Import prices for this BOM</h3>
                    <p>
                      Upload one CSV or Excel workbook (.xlsx) to add prices for as many as 1,000 BOM parts in one import. Excel imports use the first worksheet. The first row must contain <code>part_number</code> and <code>unit_price</code>. Optional columns: <code>minimum_quantity</code>, <code>supplier</code>, <code>manufacturer</code>, <code>currency</code>, <code>quote_reference</code>, <code>price_date</code>, <code>valid_until</code>, and <code>source_url</code>.
                    </p>
                    <p className="cv-small-note">
                      Rows without a supplier are labeled “User price sheet” by default; enter a supplier name below or include a <code>supplier</code> column when you know it. Each accepted row becomes a quote record for this saved BOM revision. Uploading a newer sheet adds new records; it does not overwrite older quote history. Cadivor records the supplied prices but does not verify them with the supplier.
                    </p>
                    <p className="cv-small-note">
                      Cadivor matches part numbers to this saved BOM and uses the BOM manufacturer to identify the target part. If the file omits <code>manufacturer</code>, the saved quote is marked manufacturer unconfirmed so you can verify the supplier listing. Ambiguous part numbers are blocked. Include <code>manufacturer</code> to help resolve those matches. If <code>minimum_quantity</code> is omitted, the price tier starts at 1; include it when the price only applies above a specific order quantity. In Excel, format part-number cells as text to preserve leading zeros.
                    </p>
                  </div>

                  <div className="cv-quote-form-grid cv-price-import-fields">
                    <label>
                      <span>Default supplier (used when a row has none)</span>
                      <input
                        maxLength={120}
                        value={bulkDefaultSupplier}
                        onChange={(event) => setBulkDefaultSupplier(event.target.value)}
                        disabled={bulkImportBusy}
                        placeholder="e.g. DigiKey or Acme Electronics"
                      />
                    </label>
                    <label>
                      <span>Default currency</span>
                      <input
                        maxLength={3}
                        value={bulkDefaultCurrency}
                        onChange={(event) => setBulkDefaultCurrency(event.target.value.toUpperCase())}
                        disabled={bulkImportBusy}
                        placeholder="USD"
                      />
                    </label>
                    <label className="cv-quote-wide">
                      <span>Price file (.csv or .xlsx, up to 5 MB)</span>
                      <input
                        type="file"
                        accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        onChange={handlePriceImportFile}
                        disabled={bulkImportBusy}
                        aria-label="Choose a CSV or Excel price file"
                      />
                    </label>
                  </div>

                  <div className="cv-price-import-actions">
                    <button type="button" className="cv-quote-add-break" onClick={downloadPriceImportTemplate}>
                      Download CSV template
                    </button>
                    {bulkSourceRows.length ? (
                      <button type="button" className="cv-button" onClick={previewPriceImport} disabled={bulkImportBusy}>
                        {bulkPreviewRows.length ? "Refresh preview" : "Preview import"}
                      </button>
                    ) : null}
                    {bulkFileName ? <span>{bulkFileName}</span> : null}
                  </div>

                  {bulkImportError ? <div className="cv-error" role="alert">{bulkImportError}</div> : null}
                  {bulkImportResult ? <div className="cv-success" role="status" aria-live="polite">{bulkImportResult}</div> : null}

                  {bulkPreviewRows.length ? (
                    <div className="cv-price-import-preview">
                      <div className="cv-section-heading">
                        <div>
                          <h4>Review rows before saving</h4>
                          <p>
                            {bulkPreviewRows.filter((row) => row.status === "ready" || row.status === "saved" || row.status === "failed").length} matched rows · {bulkPreviewRows.filter((row) => row.status === "issue").length} rows need correction.
                          </p>
                        </div>
                      </div>
                      <div className="cv-table-wrap cv-price-import-table-wrap">
                        <table className="cv-table">
                          <thead>
                            <tr><th>File row</th><th>BOM part</th><th>Unit price</th><th>Supplier</th><th>Status / note</th></tr>
                          </thead>
                          <tbody>
                            {bulkPreviewRows.map((row) => (
                              <tr key={`import-row-${row.line}`}>
                                <td>{row.line}</td>
                                <td>{row.partNumber || "—"}{row.manufacturer ? <small className="cv-procurement-description">{row.manufacturer}</small> : null}</td>
                                <td>{row.unitPrice || "—"} {row.currencyValue || row.currency || bulkDefaultCurrency}</td>
                                <td>{row.supplierValue || row.supplier || "Supplier required"}</td>
                                <td>
                                  <span className={"cv-badge " + (row.status === "ready" || row.status === "saved" ? "green" : row.status === "failed" ? "red" : "amber")}>
                                    {row.status === "ready" ? "Ready" : row.status === "saved" ? "Saved" : row.status === "failed" ? "Retry needed" : "Not imported"}
                                  </span>
                                  {row.message ? <small className="cv-procurement-description">{row.message}</small> : null}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <button
                        type="button"
                        className="cv-button primary"
                        onClick={saveBulkPriceImport}
                        disabled={bulkImportBusy || !bulkPreviewRows.some((row) => row.status === "ready" || row.status === "failed")}
                      >
                        {bulkImportBusy
                          ? "Saving prices…"
                          : bulkPreviewRows.some((row) => row.status === "failed")
                            ? `Retry ${bulkPreviewRows.filter((row) => row.status === "failed").length} failed row${bulkPreviewRows.filter((row) => row.status === "failed").length === 1 ? "" : "s"}`
                            : `Save ${bulkPreviewRows.filter((row) => row.status === "ready").length} quotes to this BOM revision`}
                      </button>
                    </div>
                  ) : null}
                </section>

                <form className="cv-quote-entry" onSubmit={saveQuote}>
                  <div>
                    <h3>Record a supplier quote</h3>
                    <p>Save the terms against {String(selectedPart?.mpn || "the selected part")} in this saved BOM revision. Cadivor records your entry but does not independently verify the quote details.</p>
                  </div>
                  <div className="cv-quote-form-grid">
                    <label><span>Supplier *</span><input required maxLength={120} value={quoteForm.supplier} onChange={(event) => setQuoteForm({ ...quoteForm, supplier: event.target.value })} /></label>
                    <label><span>Quote reference</span><input maxLength={160} value={quoteForm.quote_reference} onChange={(event) => setQuoteForm({ ...quoteForm, quote_reference: event.target.value })} /></label>
                    <label><span>Quoted MPN *</span><input required maxLength={160} value={quoteForm.offered_mpn} onChange={(event) => setQuoteForm({ ...quoteForm, offered_mpn: event.target.value })} /></label>
                    <label><span>Quoted manufacturer</span><input maxLength={160} value={quoteForm.offered_manufacturer} onChange={(event) => setQuoteForm({ ...quoteForm, offered_manufacturer: event.target.value })} /></label>
                    <label><span>Currency</span><input maxLength={3} value={quoteForm.currency} onChange={(event) => setQuoteForm({ ...quoteForm, currency: event.target.value.toUpperCase() })} /></label>
                    <label><span>Valid until</span><input type="date" value={quoteForm.valid_until} onChange={(event) => setQuoteForm({ ...quoteForm, valid_until: event.target.value })} /></label>
                    <div className="cv-quote-breaks">
                      <strong>Price breaks</strong>
                      <span>Enter the minimum order quantity for each unit price.</span>
                      {quoteForm.price_breaks.map((priceBreak, index) => (
                        <div className="cv-quote-break-row" key={`break-${index}`}>
                          <label><span>Quantity</span><input aria-label={`Price break ${index + 1} quantity`} type="number" min="1" step="1" value={priceBreak.quantity} onChange={(event) => setQuoteForm({ ...quoteForm, price_breaks: quoteForm.price_breaks.map((row, rowIndex) => rowIndex === index ? { ...row, quantity: event.target.value } : row) })} /></label>
                          <label><span>Unit price</span><input aria-label={`Price break ${index + 1} unit price`} type="number" min="0.000001" step="any" value={priceBreak.unit_price} onChange={(event) => setQuoteForm({ ...quoteForm, price_breaks: quoteForm.price_breaks.map((row, rowIndex) => rowIndex === index ? { ...row, unit_price: event.target.value } : row) })} /></label>
                          {quoteForm.price_breaks.length > 1 ? <button className="cv-quote-remove-break" type="button" onClick={() => setQuoteForm({ ...quoteForm, price_breaks: quoteForm.price_breaks.filter((_, rowIndex) => rowIndex !== index) })}>Remove</button> : null}
                        </div>
                      ))}
                      {quoteForm.price_breaks.length < 20 ? <button className="cv-quote-add-break" type="button" onClick={() => setQuoteForm({ ...quoteForm, price_breaks: [...quoteForm.price_breaks, { quantity: "", unit_price: "" }] })}>Add price break</button> : null}
                    </div>
                    <label><span>Minimum order quantity</span><input type="number" min="1" step="1" value={quoteForm.minimum_order_quantity} onChange={(event) => setQuoteForm({ ...quoteForm, minimum_order_quantity: event.target.value })} /></label>
                    <label><span>Pack quantity / order multiple</span><input type="number" min="1" step="1" value={quoteForm.pack_quantity} onChange={(event) => setQuoteForm({ ...quoteForm, pack_quantity: event.target.value })} /></label>
                    <label><span>Lead time (weeks)</span><input type="number" min="0" step="any" value={quoteForm.lead_time_weeks} onChange={(event) => setQuoteForm({ ...quoteForm, lead_time_weeks: event.target.value })} /></label>
                    <label><span>Available stock</span><input type="number" min="0" step="1" value={quoteForm.stock} onChange={(event) => setQuoteForm({ ...quoteForm, stock: event.target.value })} /></label>
                    <label className="cv-quote-wide"><span>Supplier quote / listing URL</span><input type="url" maxLength={2048} placeholder="https://…" value={quoteForm.source_url} onChange={(event) => setQuoteForm({ ...quoteForm, source_url: event.target.value })} /></label>
                    <label className="cv-quote-wide"><span>Notes / assumptions</span><textarea maxLength={3000} rows={3} value={quoteForm.notes} onChange={(event) => setQuoteForm({ ...quoteForm, notes: event.target.value })} /></label>
                  </div>
                  {quoteError ? <div className="cv-error" role="alert">{quoteError}</div> : null}
                  {quoteSaved ? <div className="cv-success" role="status">{quoteSaved}</div> : null}
                  <button className="cv-button primary" type="submit" disabled={quoteSaving}>
                    {quoteSaving ? "Saving quote…" : "Save quote to this BOM revision"}
                  </button>
                </form>
              </>
            ) : (
              <EmptyState
                icon="procure"
                title="Select a saved BOM to compare quotes"
                body="Quote comparisons and saved quote records are tied to one exact analysis and revision."
                action={<PrimaryLink href="/reports">Choose a saved BOM</PrimaryLink>}
              />
            )}
          </section>

          <div className="cv-next-steps">
            <div className="cv-section-heading">
              <div>
                <h2>Next steps</h2>
                <p>
                  Keep sourcing signals connected to engineering qualification
                  and the release decision.
                </p>
              </div>
            </div>
            <div className="cv-next-steps-grid">
              <section className="cv-card pad">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <h3 className="cv-card-title">Review lifecycle concerns</h3>
                    <p className="cv-card-subtitle">
                      Open the detailed risk report for the current analysis.
                    </p>
                  </div>
                  <span className="cv-page-head-icon" aria-hidden>
                    <Icon name="risk" />
                  </span>
                </div>
                <div style={{ marginTop: 14 }}>
                  <SecondaryLink href={withAnalysisId("/detailed-risk-report", activeAnalysisId)}>Open risk report</SecondaryLink>
                </div>
              </section>
              <section className="cv-card pad">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <h3 className="cv-card-title">Compare an alternate</h3>
                    <p className="cv-card-subtitle">
                      Confirm package and electrical fit before substitution.
                    </p>
                  </div>
                  <span className="cv-page-head-icon" aria-hidden>
                    <Icon name="compare" />
                  </span>
                </div>
                <div style={{ marginTop: 14 }}>
                  <SecondaryLink href={withAnalysisId("/compare-parts", activeAnalysisId)}>Compare parts</SecondaryLink>
                </div>
              </section>
              <section className="cv-card pad">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div>
                    <h3 className="cv-card-title">Record sourcing decision</h3>
                    <p className="cv-card-subtitle">
                      Attach rationale to the selected BOM revision.
                    </p>
                  </div>
                  <span className="cv-page-head-icon" aria-hidden>
                    <Icon name="decisions" />
                  </span>
                </div>
                <div style={{ marginTop: 14 }}>
                  <Link className="cv-button" href={withAnalysisId("/engineering-decisions", activeAnalysisId)}>
                    Open decisions
                  </Link>
                </div>
              </section>
            </div>
          </div>
          {offersDialogPart ? (
            <div
              className="cv-procurement-modal-backdrop"
              role="presentation"
              onClick={() => setOffersDialogPart(null)}
            >
              <section
                className="cv-procurement-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="cv-procurement-offers-title"
                aria-describedby="cv-procurement-offers-description"
                onClick={(event) => event.stopPropagation()}
                tabIndex={-1}
              >
                <header className="cv-procurement-modal-header">
                  <div>
                    <span className="cv-procurement-guide-eyebrow">Supplier evidence</span>
                    <h2 id="cv-procurement-offers-title">
                      Saved offers for {display(offersDialogPart.mpn, "this part")}
                    </h2>
                    <p id="cv-procurement-offers-description">
                      These are saved supplier snapshots, not guaranteed current inventory or a binding quote. Confirm part identity, current price, stock, and order terms on the supplier listing before ordering.
                    </p>
                  </div>
                  <button
                    className="cv-button"
                    type="button"
                    autoFocus
                    onClick={() => setOffersDialogPart(null)}
                  >
                    Close
                  </button>
                </header>
                <div className="cv-procurement-modal-body">
                  <div
                    className="cv-procurement-refresh-options"
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                      gap: 10,
                      marginBottom: 12,
                    }}
                  >
                    <section className="cv-card pad" style={{ boxShadow: "none" }}>
                      <span className="cv-procurement-guide-eyebrow">Procurement offers</span>
                      <h3 className="cv-card-title" style={{ marginTop: 5 }}>Need new supplier offers?</h3>
                      <p className="cv-card-subtitle">
                        Cadivor will preload this saved BOM’s component list and project details. Review it, then analyze to create a new report and Procurement offer snapshot; this report stays unchanged.
                      </p>
                      <Link className="cv-button" href={savedBomAnalysisHref(activeAnalysisId)} style={{ marginTop: 10 }}>
                        Analyze this BOM again
                      </Link>
                    </section>
                    <section className="cv-card pad" style={{ boxShadow: "none" }}>
                      <span className="cv-procurement-guide-eyebrow">Monitoring only</span>
                      <h3 className="cv-card-title" style={{ marginTop: 5 }}>Need updated monitoring evidence?</h3>
                      <p className="cv-card-subtitle">
                        Refresh checks configured distributors for this exact MPN and saves verified results to Monitoring. It may update alerts, but these Procurement offers will not change.
                      </p>
                      {activeAnalysisId && String(offersDialogPart.mpn || "").trim() ? (
                        <Link
                          className="cv-button primary"
                          href={supplierRefreshHref(activeAnalysisId, String(offersDialogPart.mpn).trim())}
                          aria-label={"Open Monitoring for " + String(offersDialogPart.mpn).trim()}
                          style={{ marginTop: 10 }}
                        >
                          Open this part in Monitoring
                        </Link>
                      ) : (
                        <span className="cv-small-note">A saved MPN and BOM analysis are required for a part-specific Monitoring view.</span>
                      )}
                    </section>
                  </div>
                  {Array.isArray(offersDialogPart.supplier_offers) && offersDialogPart.supplier_offers.length ? (
                    offersDialogPart.supplier_offers.map((offer: Record<string, unknown>, index) => {
                      const identity = describeCatalogIdentity(
                        String(offersDialogPart.mpn || ""),
                        String(offersDialogPart.manufacturer || ""),
                        String(offer.offered_mpn || ""),
                        String(offer.offered_manufacturer || ""),
                      );
                      const productUrl = String(offer.product_url || "");
                      const priceBreaks = Array.isArray(offer.price_breaks)
                        ? offer.price_breaks.flatMap((raw) => {
                            if (!raw || typeof raw !== "object") return [];
                            const priceBreak = raw as Record<string, unknown>;
                            const quantity = optionalNumber(priceBreak.quantity);
                            const unitPrice = optionalNumber(priceBreak.unit_price);
                            return quantity !== null && unitPrice !== null
                              ? [quantity.toLocaleString() + "+ units: " + String(offer.currency || "") + " " + unitPrice]
                              : [];
                          })
                        : [];
                      return (
                        <article className="cv-procurement-offer-card" key={String(offer.supplier || "supplier") + "-" + index}>
                          <div className="cv-procurement-offer-card-heading">
                            <div>
                              <strong>{display(offer.supplier, "Supplier not recorded")}</strong>
                              <small>{identity}</small>
                            </div>
                            <span className={"cv-badge " + (identity === "Exact MPN and manufacturer" ? "green" : "amber")}>
                              {identity === "Exact MPN and manufacturer" ? "Identity matches" : "Verify part identity"}
                            </span>
                          </div>
                          <div className="cv-procurement-offer-facts">
                            <div><span>Offered part</span><strong>{display(offer.offered_mpn, "MPN not provided")}</strong></div>
                            <div><span>Unit price</span><strong>{offer.unit_price == null ? "Not provided" : String(offer.unit_price) + (offer.currency ? " " + String(offer.currency) : " · currency not provided")}</strong></div>
                            <div><span>Stock</span><strong>{display(offer.stock, "Not provided")}</strong></div>
                            <div><span>Lead time</span><strong>{offer.lead_time_weeks == null ? "Not provided" : String(offer.lead_time_weeks) + " weeks"}</strong></div>
                            <div><span>Minimum quantity</span><strong>{display(offer.minimum_order_quantity, "Not provided")}</strong></div>
                            <div><span>Pack multiple</span><strong>{display(offer.pack_quantity, "Not provided")}</strong></div>
                          </div>
                          {priceBreaks.length ? (
                            <p className="cv-procurement-offer-breaks"><strong>Price breaks:</strong> {priceBreaks.join(" · ")}</p>
                          ) : null}
                          <div className="cv-procurement-offer-footer">
                            <span>
                              {offer.retrieved_at ? "Retrieved " + String(offer.retrieved_at) : "Retrieval date not provided"}
                              {offer.region ? " · " + String(offer.region) : ""}
                            </span>
                            {productUrl.startsWith("https://") || productUrl.startsWith("http://") ? (
                              <a href={productUrl} target="_blank" rel="noreferrer">Open supplier listing</a>
                            ) : (
                              <span>Supplier listing not linked</span>
                            )}
                          </div>
                        </article>
                      );
                    })
                  ) : (
                    <p className="cv-small-note">No saved supplier offers are attached to this BOM part.</p>
                  )}
                </div>
              </section>
            </div>
          ) : null}
        </>
      ) : null}
    </Shell>
  );
}

export default function ProcurementPage() {
  return (
    <Suspense fallback={<LoadingCard label="Loading procurement…" />}>
      <ProcurementPageInner />
    </Suspense>
  );
}

