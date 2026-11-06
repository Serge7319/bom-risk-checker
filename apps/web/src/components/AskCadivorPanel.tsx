"use client";

import { FormEvent, useState } from "react";
import { GapBanner } from "@/components/GapBanner";
import { askCadivor } from "@/lib/api";

export function AskCadivorPanel({
  token,
  analysisId,
}: {
  token: string;
  analysisId: string;
}) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [answer, setAnswer] = useState("");
  const [gap, setGap] = useState("");
  const [provider, setProvider] = useState("");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await askCadivor(token, {
        analysis_id: analysisId,
        question,
      });
      setAnswer(String(data.answer || ""));
      setGap(typeof data.gap === "string" ? data.gap : "");
      setProvider(String(data.provider || ""));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ask Cadivor failed");
      setAnswer("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cv-card pad" style={{ marginBottom: 14 }}>
      <div className="cv-eyebrow">Ask Cadivor</div>
      <h3 className="cv-card-title" style={{ marginTop: 8 }}>
        Engineering questions on this report
      </h3>
      <p className="cv-card-subtitle">
        Answers are grounded in the saved analysis evidence for this BOM.
      </p>
      <form onSubmit={onSubmit} style={{ marginTop: 12 }}>
        <div className="cv-field">
          <label htmlFor="ask-cadivor-q">Question</label>
          <textarea
            id="ask-cadivor-q"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={3}
            placeholder="What should we review before release?"
            required
          />
        </div>
        <div style={{ marginTop: 12 }}>
          <button className="cv-button primary" type="submit" disabled={busy}>
            {busy ? "Reviewing…" : "Ask Cadivor"}
          </button>
        </div>
      </form>
      {error ? <div className="cv-error">{error}</div> : null}
      {gap ? <GapBanner>{gap}</GapBanner> : null}
      {answer ? (
        <div className="cv-ask-answer">
          {provider ? (
            <div className="cv-small-note" style={{ marginBottom: 8 }}>
              Source: {provider}
            </div>
          ) : null}
          <div className="cv-ask-answer-body">{answer}</div>
        </div>
      ) : null}
    </section>
  );
}
