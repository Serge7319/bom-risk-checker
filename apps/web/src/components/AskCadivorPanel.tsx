"use client";

import { type FormEvent, type ReactNode, useState } from "react";
import { EvidenceNotice } from "@/components/GapBanner";
import { askCadivor } from "@/lib/api";
import { cleanUserText } from "@/lib/display";

function renderInline(markdown: string): ReactNode[] {
  const parts = markdown.split(/(\*\*.+?\*\*|__.+?__|\x60[^\x60]+\x60|\*[^*]+\*)/g);
  return parts.filter(Boolean).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("__") && part.endsWith("__")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("\x60") && part.endsWith("\x60")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

export function formatCadivorAnswer(markdown: string): ReactNode[] {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let index = 0;
  let blockKey = 0;

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push(<p key={blockKey++}>{renderInline(paragraph.join(" "))}</p>);
      paragraph = [];
    }
  };

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      flushParagraph();
      index += 1;
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      const content = renderInline(heading[2]);
      const key = blockKey++;
      index += 1;
      if (heading[1].length === 1) blocks.push(<h2 key={key}>{content}</h2>);
      else if (heading[1].length === 2) blocks.push(<h3 key={key}>{content}</h3>);
      else blocks.push(<h4 key={key}>{content}</h4>);
      continue;
    }

    const unordered = line.match(/^[-*+]\s+(.+)$/);
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const listType = unordered ? "ul" : "ol";
      const items: string[] = [];
      while (index < lines.length) {
        const itemLine = lines[index].trim();
        const item = listType === "ul"
          ? itemLine.match(/^[-*+]\s+(.+)$/)
          : itemLine.match(/^\d+[.)]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      const children = items.map((item, itemIndex) => (
        <li key={itemIndex}>{renderInline(item)}</li>
      ));
      blocks.push(listType === "ul"
        ? <ul key={blockKey++}>{children}</ul>
        : <ol key={blockKey++}>{children}</ol>);
      continue;
    }

    paragraph.push(line);
    index += 1;
  }

  flushParagraph();
  return blocks;
}

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

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await askCadivor(token, {
        analysis_id: analysisId,
        question,
      });
      setAnswer(cleanUserText(data.answer));
      setGap(cleanUserText(data.gap));
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
      {<EvidenceNotice gap={gap} />}
      {answer ? (
        <div className="cv-ask-answer">
          <div className="cv-ask-answer-body">{formatCadivorAnswer(answer)}</div>
        </div>
      ) : null}
    </section>
  );
}
