"use client";

import { FormEvent, useState } from "react";
import { Shell } from "@/components/Shell";
import { EvidenceNotice, LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink } from "@/components/PageHeader";
import { askDatasheet } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

export default function DatasheetQaPage() {
  const session = useRequireSession();
  const [file, setFile] = useState<File | null>(null);
  const [question, setQuestion] = useState("What is the absolute maximum supply voltage?");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!session || !file) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(await askDatasheet(session.access_token, file, question));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Q&A failed");
    } finally {
      setBusy(false);
    }
  }

  if (!session) return null;
  const evidence = (result?.evidence || []) as Array<Record<string, unknown>>;
  const citations = (result?.citations || []) as string[];

  return (
    <Shell session={session}>
      <PageHeader meta={PAGE_META.qa} actions={<PrimaryLink href="/">Home</PrimaryLink>} />
      <form className="cv-card pad" onSubmit={onSubmit}>
        <div className="cv-field">
          <label htmlFor="datasheet">Datasheet PDF</label>
          <input id="datasheet" type="file" accept=".pdf,application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} required />
        </div>
        <div className="cv-field" style={{ marginTop: 12 }}>
          <label htmlFor="question">Question</label>
          <textarea id="question" rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} required />
        </div>
        <button className="cv-button primary" style={{ marginTop: 14 }} type="submit" disabled={busy || !file}>
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
            <p className="cv-card-subtitle">Provider · {String(result.provider || "local")}</p>
            <p style={{ marginTop: 12, lineHeight: 1.55 }}>{String(result.answer || result.error || "")}</p>
            {citations.length ? (
              <p className="cv-small-note" style={{ marginTop: 10 }}>Citations: {citations.join(", ")}</p>
            ) : null}
            {evidence.length ? (
              <div className="cv-table-wrap" style={{ marginTop: 12 }}>
                <table className="cv-table">
                  <thead><tr><th>Page</th><th>Excerpt</th></tr></thead>
                  <tbody>
                    {evidence.slice(0, 8).map((row, i) => (
                      <tr key={i}>
                        <td>{String(row.page || row.Page || "")}</td>
                        <td>{String(row.excerpt || row.text || row.Evidence || "").slice(0, 280)}</td>
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
