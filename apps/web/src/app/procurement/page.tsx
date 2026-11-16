"use client";

import { Suspense, useEffect, useMemo, useState, type FormEvent } from "react";
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
  fetchProcurement,
  listProcurementQuotes,
  listReports,
  type ProcurementQuote,
} from "@/lib/api";
import { evidenceSourceLabel } from "@/lib/display";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function analysisLabel(row: Record<string, unknown>) {
  const project = String(row.project_name || "").trim();
  const bom = String(row.bom_name || row.filename || "").trim();
  const revision = String(row.revision || "").trim();
  const title = [project, bom].filter(Boolean).join(" · ") || "Saved analysis";
  return revision ? `${title} (rev ${revision})` : title;
}

function withAnalysisId(href: string, analysisId: string) {
  if (!analysisId) return href;
  const joiner = href.includes("?") ? "&" : "?";
  return `${href}${joiner}analysis_id=${encodeURIComponent(analysisId)}`;
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

function partKey(part: Record<string, unknown>) {
  return `${String(part.mpn || "").trim().toLowerCase()}\u0000${String(part.manufacturer || "").trim().toLowerCase()}`;
}

function optionalNumber(value: unknown): number | null {
  if (value === null || value === undefined || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
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

  const requestedAnalysisId = useMemo(
    () => (searchParams.get("analysis_id") || "").trim(),
    [searchParams],
  );

  useEffect(() => {
    if (!session) return;
    let active = true;
    const last = readLastAnalysis(session);
    const preferredId = requestedAnalysisId || last?.analysis_id || "";
    setSelectedAnalysisId("");
    setBusy(true);
    setError("");
    setData(null);
    listReports(session.access_token)
      .catch(() => ({ reports: [] as Array<Record<string, unknown>> }))
      .then((reportPayload) => {
        if (!active) return;
        const visibleReports = (reportPayload.reports || []) as Array<Record<string, unknown>>;
        setReports(visibleReports);
        const availableIds = new Set(
          visibleReports.map((row) => String(row.id || "").trim()).filter(Boolean),
        );
        const safeAnalysisId = availableIds.has(preferredId)
          ? preferredId
          : String(visibleReports[0]?.id || "").trim();
        setSelectedAnalysisId(safeAnalysisId);
        if (safeAnalysisId !== requestedAnalysisId) {
          router.replace(
            safeAnalysisId
              ? `/procurement?analysis_id=${encodeURIComponent(safeAnalysisId)}`
              : "/procurement",
          );
        }
        return fetchProcurement(session.access_token, safeAnalysisId || undefined).then(
          (procurement) => {
            if (!active) return;
            setData(procurement);
            if (procurement.ok === false) {
              setError(String(procurement.gap || "Procurement could not load that analysis."));
            }
          },
        );
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed");
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [session, requestedAnalysisId]);

  const allParts = useMemo(
    () => (((data?.parts || []) as Array<Record<string, unknown>>) || []),
    [data],
  );

  useEffect(() => {
    if (!allParts.length) {
      setSelectedPartKey("");
      return;
    }
    if (!allParts.some((part) => partKey(part) === selectedPartKey)) {
      setSelectedPartKey(partKey(allParts[0]));
      setQuoteForm(emptyQuoteForm(String(allParts[0].mpn || "")));
      setComparisonQuantity("");
    }
  }, [allParts, selectedPartKey]);

  useEffect(() => {
    if (!session || !selectedAnalysisId) {
      setSavedQuotes([]);
      return;
    }
    let active = true;
    setQuotesBusy(true);
    setSavedQuotes([]);
    setQuoteError("");
    setQuoteSaved("");
    listProcurementQuotes(session.access_token, selectedAnalysisId)
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
  }, [session, selectedAnalysisId]);

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
  const missingParts = Number(evidenceSummary.parts_without_verified_supplier_evidence || 0);
  const partsTotal = Number(evidenceSummary.parts_total || ((data?.parts as unknown[]) || []).length || 0);
  const sourcingBadgeParts = [
    liveParts ? `Live: ${liveParts}` : "",
    sampleParts ? `Synthetic estimates: ${sampleParts}` : "",
    missingParts ? `No supplier match: ${missingParts}` : "",
  ].filter(Boolean);
  const sourcingBadge = partsTotal
    ? `${sourcingBadgeParts.join("; ") || `${partsTotal} parts`} (of ${partsTotal})`
    : "";
  const activeAnalysisId = String(data?.analysis_id || selectedAnalysisId || "").trim();
  const selectedPart =
    allParts.find((part) => partKey(part) === selectedPartKey) || allParts[0] || null;
  const contextLabel = [
    String(data?.project_name || "").trim(),
    String(data?.bom_name || data?.filename || "").trim(),
    data?.revision ? `rev ${String(data.revision)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const display = (value: unknown, fallback = "Not recorded") => {
    if (value === null || value === undefined || String(value).trim() === "") return fallback;
    return String(value);
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
    const catalogRows: ComparisonRow[] = offers.map((offer, index) => {
      const offeredMpn = String(offer.offered_mpn || "").trim();
      const offeredManufacturer = String(offer.offered_manufacturer || "").trim();
      const breaks = Array.isArray(offer.price_breaks)
        ? offer.price_breaks.flatMap((raw) => {
            if (!raw || typeof raw !== "object") return [];
            const row = raw as Record<string, unknown>;
            const quantity = optionalNumber(row.quantity);
            const unitPrice = optionalNumber(row.unit_price);
            return quantity !== null && unitPrice !== null ? [{ quantity, unit_price: unitPrice }] : [];
          })
        : [];
      const priceBreakQuantity = optionalNumber(offer.price_break_quantity);
      const unitPrice = optionalNumber(offer.unit_price);
      const normalizedBreaks = breaks.length
        ? breaks
        : priceBreakQuantity !== null && unitPrice !== null
          ? [{ quantity: priceBreakQuantity, unit_price: unitPrice }]
          : [];
      return {
        id: `offer-${index}-${String(offer.supplier || "supplier")}`,
        kind: `Saved catalog offer${liveCatalogEvidence ? " · live evidence" : " · not verified live"}`,
        supplier: String(offer.supplier || "Supplier not recorded"),
        quoteReference: String(offer.quote_reference || ""),
        offeredMpn,
        offeredManufacturer,
        identityStatus: describeCatalogIdentity(targetMpn, targetManufacturer, offeredMpn, offeredManufacturer),
        exactPart: describeCatalogIdentity(targetMpn, targetManufacturer, offeredMpn, offeredManufacturer) === "Exact MPN and manufacturer",
        currency: String(offer.currency || "").toUpperCase(),
        unitPrice,
        priceBreakQuantity,
        priceBreaks: normalizedBreaks,
        minimumOrderQuantity: optionalNumber(offer.minimum_order_quantity),
        packQuantity: optionalNumber(offer.pack_quantity),
        leadTimeWeeks: optionalNumber(offer.lead_time_weeks),
        stock: optionalNumber(offer.stock),
        validUntil: String(offer.valid_until || ""),
        sourceUrl: String(offer.product_url || ""),
        sourceTime: String(offer.retrieved_at || ""),
        notes: [String(offer.region || ""), ...(!liveCatalogEvidence ? ["Saved analysis does not confirm this as a live supplier quote."] : [])].filter(Boolean).join(" · "),
        canPriceCompare: liveCatalogEvidence,
      };
    });
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
    return [...catalogRows, ...enteredRows];
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

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.procurement}
        actions={
          <div className="cv-page-head-actions">
            <PrimaryLink href="/bom-analyzer">Run new BOM analysis</PrimaryLink>
            <SecondaryLink href={withAnalysisId("/cost-optimization", activeAnalysisId)}>Cost optimization</SecondaryLink>
            <SecondaryLink href={withAnalysisId("/compare-parts", activeAnalysisId)}>Compare alternatives</SecondaryLink>
          </div>
        }
      />
      {<EvidenceNotice gap={data?.gap} />}
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
                    ? `Showing ${contextLabel}${activeAnalysisId ? ` · ${activeAnalysisId}` : ""}`
                    : activeAnalysisId
                      ? `Showing analysis ${activeAnalysisId}`
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
                      <th>MPN</th>
                      <th>Manufacturer</th>
                      <th>Recommended action</th>
                      <th>Required quantity</th>
                      <th>Lifecycle</th>
                      <th>Risk</th>
                      <th>Supplier coverage</th>
                      <th>Stock</th>
                      <th>Unit price</th>
                      <th>Lead time</th>
                      <th>Evidence source</th>
                      <th>Offers</th>
                    </tr>
                  </thead>
                  <tbody>
                    {parts.map((p, i) => (
                      <tr key={`${String(p.mpn || "part")}-${i}`}>
                        <td>
                          <div className="cv-part-cell">
                            <PartThumbnail part={p} />
                            <div>
                              <strong>{display(p.mpn, "MPN not recorded")}</strong>
                              {p.description ? <small className="cv-procurement-description">{String(p.description)}</small> : null}
                              {p.category ? <small className="cv-procurement-description">Category: {String(p.category)}</small> : null}
                            </div>
                          </div>
                        </td>
                        <td>{display(p.manufacturer, "Not provided")}</td>
                        <td className="cv-procurement-recommendation">
                          <strong>{display(p.recommendation, "Check an authorized source")}</strong>
                          {p.next_step ? <small>{String(p.next_step)}</small> : null}
                        </td>
                        <td>{display(p.quantity)}</td>
                        <td>{display(p.lifecycle, "Unknown")}</td>
                        <td>{display(p.risk_level, "Needs verification")}</td>
                        <td>
                          <strong>{display(p.supplier, "No primary supplier recorded")}</strong>
                          <small className="cv-procurement-description">
                            {p.supplier_count == null
                              ? "Supplier count not reported"
                              : String(p.supplier_count) + " source" + (Number(p.supplier_count) === 1 ? "" : "s")}
                          </small>
                        </td>
                        <td>{display(p.stock, "Not reported")}</td>
                        <td>
                          {p.unit_price == null
                            ? "Price absent"
                            : `${String(p.unit_price)}${p.currency ? ` ${String(p.currency)}` : " (currency not recorded)"}`}
                          {p.price_type ? (
                            <small className="cv-procurement-description">Type: {String(p.price_type)}</small>
                          ) : null}
                        </td>
                        <td>{p.lead_time_weeks == null ? "Not reported" : `${String(p.lead_time_weeks)} weeks`}</td>
                        <td>
                          <span className="cv-badge gray">
                            {evidenceSourceLabel(p.price_source, "Not recorded")}
                          </span>
                          {p.identity_source ? (
                            <small className="cv-procurement-description">
                              Identity: {evidenceSourceLabel(p.identity_source, "Not recorded")}
                            </small>
                          ) : null}
                          {p.price_retrieved_at || p.retrieved_at ? (
                            <small className="cv-procurement-timestamp">
                              {String(p.price_retrieved_at || p.retrieved_at)}
                            </small>
                          ) : null}
                        </td>
                        <td>
                          {Array.isArray(p.supplier_offers) && p.supplier_offers.length ? (
                            <details className="cv-procurement-offers">
                              <summary>{p.supplier_offers.length} saved offer{p.supplier_offers.length === 1 ? "" : "s"}</summary>
                              <div className="cv-procurement-offer-list">
                                {p.supplier_offers.map((rawOffer, offerIndex) => {
                                  const offer = rawOffer as Record<string, unknown>;
                                  const supplierName = display(offer.supplier, "Supplier not recorded");
                                  const productUrl = String(offer.product_url || "");
                                  return (
                                    <div className="cv-procurement-offer" key={`${supplierName}-${offerIndex}`}>
                                      <strong>{supplierName}</strong>
                                      <span>
                                        {offer.unit_price == null
                                          ? "Price not reported"
                                          : `${String(offer.unit_price)}${offer.currency ? ` ${String(offer.currency)}` : " (currency not recorded)"}`}
                                      </span>
                                      <span>Stock: {display(offer.stock, "Not reported")}</span>
                                      <span>Lead: {offer.lead_time_weeks == null ? "Not reported" : `${String(offer.lead_time_weeks)} weeks`}</span>
                                      <span>
                                        Qty break:{" "}
                                        {offer.price_break_quantity == null
                                          ? "Not recorded"
                                          : String(offer.price_break_quantity)}
                                      </span>
                                      {offer.region ? <span>Region: {String(offer.region)}</span> : null}
                                      {offer.retrieved_at ? <span>Retrieved: {String(offer.retrieved_at)}</span> : null}
                                      {productUrl.startsWith("https://") || productUrl.startsWith("http://") ? (
                                        <a href={productUrl} target="_blank" rel="noreferrer">Supplier listing</a>
                                      ) : null}
                                    </div>
                                  );
                                })}
                              </div>
                            </details>
                          ) : (
                            <span>{display(p.coverage, "No saved offers")}</span>
                          )}
                        </td>
                      </tr>
                    ))}
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
                  Compare saved distributor offers and quotes entered for this exact BOM revision.
                </p>
                <p className="cv-small-note" style={{ marginTop: 7 }}>
                  Missing terms stay marked as unknown. A different MPN needs engineering review; an unconfirmed manufacturer stays unverified. Unit prices exclude costs not shown in the source.
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
                  <div className="cv-quote-price-summary" role="status">
                    <strong>Lowest recorded exact-part price tier</strong>
                    {comparisonSummaries.length ? (
                      <ul>
                        {comparisonSummaries.map((summary) => (
                          <li key={summary.currency}>
                            At {comparisonQuantity} units, the lowest recorded tier is {summary.currency} {summary.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })} per unit from {summary.supplier}{summary.reference ? ` (${summary.reference})` : ""}.
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>No live or user-entered exact-part price tier covers this quantity with the recorded MOQ and pack terms.</p>
                    )}
                    <small>Only exact-identity live offers and user-entered quotes are compared; synthetic preview data is excluded. Unknown MOQ, pack, stock, validity, freight, duty/tax, or qualification terms still need confirmation before a purchase decision.</small>
                  </div>
                ) : null}

                <div className="cv-table-wrap cv-quote-table-wrap">
                  <table className="cv-table cv-quote-table">
                    <thead>
                      <tr>
                        <th>Supplier / reference</th>
                        <th>Part identity</th>
                        <th>Unit price / breaks</th>
                        <th>MOQ</th>
                        <th>Pack quantity</th>
                        <th>Lead time</th>
                        <th>Stock</th>
                        <th>Quote validity</th>
                        <th>Source / time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparisonRows.map((row) => {
                        const today = new Date().toISOString().slice(0, 10);
                        const requestedMpn = String(selectedPart?.mpn || "");
                        const requestedManufacturer = String(selectedPart?.manufacturer || "");
                        const needsEngineeringComparison = Boolean(row.offeredMpn)
                          && row.offeredMpn.trim().toLowerCase() !== requestedMpn.trim().toLowerCase();
        const validity = row.validUntil
                          ? row.validUntil < today ? `Expired ${row.validUntil}` : `Through ${row.validUntil}`
          : row.kind.startsWith("Saved catalog offer") ? "Not reported" : "Not stated";
                        const priceLabel = row.priceBreaks.length
                          ? row.priceBreaks.map((priceBreak) => `${priceBreak.quantity}+ units: ${row.currency || "Currency unknown"} ${priceBreak.unit_price}`).join(" · ")
                          : row.unitPrice === null
                            ? "Price not reported"
                            : `${row.currency || "Currency unknown"} ${row.unitPrice} · break quantity not reported`;
                        return (
                          <tr key={row.id}>
                            <td>
                              <strong>{row.supplier}</strong>
                              <small className="cv-procurement-description">{row.kind}{row.quoteReference ? ` · ${row.quoteReference}` : ""}</small>
                            </td>
                            <td>
                              <span className={`cv-badge ${row.exactPart ? "green" : "amber"}`}>
                                {row.identityStatus}
                              </span>
                              <small className="cv-procurement-description">
                                Quoted: {row.offeredMpn || "MPN not recorded"}{row.offeredManufacturer ? ` · ${row.offeredManufacturer}` : " · manufacturer not reported"}
                              </small>
                              {needsEngineeringComparison ? (
                                <Link className="cv-quote-review-link" href={engineeringComparisonHref(
                                  activeAnalysisId,
                                  requestedMpn,
                                  requestedManufacturer,
                                  row.offeredMpn,
                                  row.offeredManufacturer,
                                )}>
                                  Open engineering comparison
                                </Link>
                              ) : null}
                            </td>
                            <td>{priceLabel}</td>
                            <td>{row.minimumOrderQuantity === null ? "Unknown" : row.minimumOrderQuantity}</td>
                            <td>{row.packQuantity === null ? "Unknown" : row.packQuantity}</td>
                            <td>{row.leadTimeWeeks === null ? "Unknown" : `${row.leadTimeWeeks} weeks`}</td>
                            <td>{row.stock === null ? "Unknown" : row.stock.toLocaleString()}</td>
                            <td>{validity}</td>
                            <td>
                              {row.sourceUrl.startsWith("https://") || row.sourceUrl.startsWith("http://") ? (
                                <a href={row.sourceUrl} target="_blank" rel="noreferrer">Open source</a>
                              ) : <span>{row.kind === "User-entered quote" ? "No source link recorded" : "Supplier page not recorded"}</span>}
                              <small className="cv-procurement-timestamp">
                                {row.sourceTime
                                  ? `${row.kind === "User-entered quote" ? "Recorded" : "Retrieved"}: ${row.sourceTime}`
                                  : "Time not recorded"}
                              </small>
                              {row.notes ? <small className="cv-procurement-description">{row.notes}</small> : null}
                            </td>
                          </tr>
                        );
                      })}
                      {!comparisonRows.length ? (
                        <tr><td colSpan={9}>No saved offers or entered quotes for this BOM part yet. Record a supplier quote below.</td></tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
                {quotesBusy ? <p className="cv-small-note" aria-live="polite">Loading saved quotes…</p> : null}

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

