"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { askDatasheet, fetchReport } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { readLastAnalysis, useRequireSession } from "@/lib/session";

function DatasheetQaPageInner() {
  const session = useRequireSession();
  const searchParams = useSearchParams();
  const [file, setFile] = useState<File | null>(null);
  const [question, setQuestion] = useState(
    "What is the recommended operating supply voltage?",
  );
  const [mpn, setMpn] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [bomNote, setBomNote] = useState("");

  const queryMpn = useMemo(
    () => (searchParams.get("mpn") || searchParams.get("part") || "").trim(),
    [searchParams],
  );
  const queryMfr = useMemo(
    () => (searchParams.get("manufacturer") || searchParams.get("mfr") || "").trim(),
    [searchParams],
  );
  const queryAnalysisId = useMemo(
    () => (searchParams.get("analysis_id") || "").trim(),
    [searchParams],
  );

  useEffect(() => {
    if (!session) return;
    if (queryMpn) setMpn(queryMpn);
    if (queryMfr) setManufacturer(queryMfr);
    const analysisId =
      queryAnalysisId || readLastAnalysis(session)?.analysis_id || "";
    if (!analysisId || !queryMpn) {
      if (queryMpn) {
        setBomNote(
          `Selected part ${queryMpn}${queryMfr ? ` (${queryMfr})` : ""} — answers require a PDF that verifies this exact identity.`,
        );
      }
      return;
    }
    let active = true;
    fetchReport(analysisId, session.access_token)
      .then((report) => {
        if (!active) return;
        const payload = report as unknown as Record<string, unknown>;
        const parts = (payload.parts || payload.components || []) as Array<
          Record<string, unknown>
        >;
        const match = parts.find((row) => {
          const rowMpn = String(row.MPN || row.mpn || "").trim();
          return rowMpn.toLowerCase() === queryMpn.toLowerCase();
        });
        if (match) {
          const mfr = String(
            match.Manufacturer || match.manufacturer || queryMfr || "",
          ).trim();
          if (mfr) setManufacturer(mfr);
          setBomNote(
            `Bound to BOM analysis ${analysisId}: ${queryMpn}${mfr ? ` · ${mfr}` : ""}. The PDF must verify this exact part.`,
          );
        } else {
          setBomNote(
            `MPN ${queryMpn} is selected, but it was not found in analysis ${analysisId}. Enter manufacturer manually if needed.`,
          );
        }
      })
      .catch(() => {
        if (!active) return;
        setBomNote(
          `Selected part ${queryMpn}. Could not load analysis ${analysisId}; manufacturer may need to be entered manually.`,
        );
      });
    return () => {
      active = false;
    };
  }, [session, queryMpn, queryMfr, queryAnalysisId]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!session || !file) return;
    const selectedMpn = mpn.trim();
    if (!selectedMpn) {
      setError("Enter the exact MPN this datasheet must verify against.");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(
        await askDatasheet(session.access_token, file, question, {
          mpn: selectedMpn,
          manufacturer: manufacturer.trim() || null,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Q&A failed");
    } finally {
      setBusy(false);
    }
  }

  if (!session) return null;
  const evidence = (result?.evidence || []) as Array<Record<string, unknown>>;
  const citations = (result?.citations || []) as string[];
  const document = (result?.document || {}) as Record<string, unknown>;
  const sourceDocument = (result?.source_document || {}) as Record<string, unknown>;
  const answerKind = String(result?.answer_kind || "");

  return (
    <Shell session={session}>
      <PageHeader meta={PAGE_META.qa} actions={<PrimaryLink href="/">Home</PrimaryLink>} />
      <form className="cv-card pad" onSubmit={onSubmit}>
        <p className="cv-card-subtitle">
          Answers are bound to the exact MPN (and manufacturer when provided). If the
          uploaded PDF does not verify that identity, Cadivor returns Needs verification
          instead of citing the wrong document.
        </p>
        {bomNote ? (
          <p className="cv-evidence-context" role="note" style={{ marginTop: 8 }}>
            {bomNote}
          </p>
        ) : null}
        <div className="cv-field" style={{ marginTop: 12 }}>
          <label htmlFor="mpn">Exact MPN</label>
          <input
            id="mpn"
            value={mpn}
            onChange={(e) => setMpn(e.target.value)}
            placeholder="e.g. LM358DR"
            required
            autoComplete="off"
          />
        </div>
        <div className="cv-field" style={{ marginTop: 12 }}>
          <label htmlFor="manufacturer">Manufacturer</label>
          <input
            id="manufacturer"
            value={manufacturer}
            onChange={(e) => setManufacturer(e.target.value)}
            placeholder="e.g. Texas Instruments"
            autoComplete="organization"
          />
        </div>
        <div className="cv-field" style={{ marginTop: 12 }}>
          <label htmlFor="datasheet">Datasheet PDF</label>
          <input
            id="datasheet"
            type="file"
            accept=".pdf,application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            required
          />
        </div>
        <div className="cv-field" style={{ marginTop: 12 }}>
          <label htmlFor="question">Question</label>
          <textarea
            id="question"
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            required
          />
        </div>
        <button
          className="cv-button primary"
          style={{ marginTop: 14 }}
          type="submit"
          disabled={busy || !file || !mpn.trim()}
        >
          {busy ? "Reading datasheet…" : "Ask"}
        </button>
      </form>
      {busy ? <LoadingCard label="Extracting text and grounding an answer…" /> : null}
      {error ? <div className="cv-error">{error}</div> : null}
      {result ? (
        <>
          {<EvidenceNotice gap={result.gap} />}
          <section className="cv-card pad" style={{ marginTop: 14 }}>
            <h3 className="cv-card-title">Answer</h3>
            <p className="cv-card-subtitle">
              Provider · {String(result.provider || "local")}
              {answerKind ? ` · ${answerKind}` : ""}
              {document.bound === true
                ? ` · bound to ${String(document.requested_mpn || mpn)}`
                : document.requested_mpn
                  ? ` · identity not verified for ${String(document.requested_mpn)}`
                  : ""}
            </p>
            {sourceDocument.filename || sourceDocument.source_url ? (
              <p className="cv-small-note" style={{ marginTop: 6 }}>
                Source:{" "}
                {String(
                  sourceDocument.filename ||
                    sourceDocument.source_url ||
                    sourceDocument.name ||
                    "",
                )}
                {sourceDocument.requested_mpn
                  ? ` · part ${String(sourceDocument.requested_mpn)}`
                  : ""}
              </p>
            ) : null}
            <p style={{ marginTop: 12, lineHeight: 1.55 }}>
              {String(result.answer || result.error || "")}
            </p>
            {citations.length ? (
              <p className="cv-small-note" style={{ marginTop: 10 }}>
                Citations: {citations.join(", ")}
              </p>
            ) : null}
            {evidence.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead>
                    <tr>
                      <th>Page</th>
                      <th>Excerpt</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evidence.slice(0, 8).map((row, i) => (
                      <tr key={i}>
                        <td>{String(row.page || row.Page || "")}</td>
                        <td>
                          {String(row.excerpt || row.text || row.Evidence || "").slice(
                            0,
                            280,
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section>
        </>
      ) : null}
    </Shell>
  );
}

export default function DatasheetQaPage() {
  return (
    <Suspense fallback={<LoadingCard label="Loading Datasheet Q&A…" />}>
      <DatasheetQaPageInner />
    </Suspense>
  );
}
