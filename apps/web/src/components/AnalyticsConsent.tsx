"use client";

import { useEffect, useState } from "react";

const CONSENT_KEY = "cadivor_analytics_consent_v1";

export function AnalyticsConsent() {
  const [choice, setChoice] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [embedded, setEmbedded] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const isTrustedMarketingOrigin = (origin: string) =>
      origin === "https://cadivor.com" ||
      origin === "https://www.cadivor.com" ||
      /^https:\/\/[a-z0-9-]+\.cadivor\.pages\.dev$/i.test(origin);
    let parentOrigin = "";
    try { parentOrigin = new URL(document.referrer).origin; } catch { /* no referrer */ }
    const isEmbeddedAudit =
      window.parent !== window &&
      ["1", "true"].includes((params.get("embed") || "").toLowerCase()) &&
      isTrustedMarketingOrigin(parentOrigin);

    if (isEmbeddedAudit) {
      setEmbedded(true);
      const applyEmbeddedChoice = (value: string | null) => {
        if (value !== "accepted" && value !== "rejected") return;
        try { localStorage.setItem(CONSENT_KEY, value); } catch { /* default to no tracking */ }
        setChoice(value);
        if (value === "accepted") window.dispatchEvent(new Event("cadivor-analytics-consent"));
      };
      applyEmbeddedChoice(params.get("analytics_consent"));
      const onParentMessage = (event: MessageEvent) => {
        if (event.source !== window.parent || !isTrustedMarketingOrigin(event.origin)) return;
        if (event.data?.type !== "cadivor:marketing-analytics-consent") return;
        applyEmbeddedChoice(event.data.choice);
      };
      window.addEventListener("message", onParentMessage);
      setReady(true);
      return () => window.removeEventListener("message", onParentMessage);
    }

    try { setChoice(localStorage.getItem(CONSENT_KEY)); } catch { setChoice("rejected"); }
    setReady(true);
  }, []);

  function choose(value: "accepted" | "rejected") {
    try { localStorage.setItem(CONSENT_KEY, value); } catch { /* default to no tracking */ }
    setChoice(value);
    setOpen(false);
    if (value === "accepted") window.dispatchEvent(new Event("cadivor-analytics-consent"));
  }

  if (!ready || embedded) return null;

  if (choice !== null && !open) {
    return (
      <button className="cv-privacy-choice-link" type="button" onClick={() => setOpen(true)}>
        Privacy choices
      </button>
    );
  }

  if (choice === null) {
    return (
      <aside className="cv-analytics-consent" aria-label="Optional analytics choice">
        <div><strong>Help improve Cadivor</strong><p>Allow anonymous first-party usage events to measure which workflows help people reach a useful result. BOM contents and part numbers are not collected.</p></div>
        <div className="cv-analytics-consent-actions">
          <button type="button" onClick={() => choose("rejected")}>Essential only</button>
          <button type="button" className="primary" onClick={() => choose("accepted")}>Allow analytics</button>
        </div>
      </aside>
    );
  }

  return (
    <aside className="cv-analytics-consent" aria-label="Optional analytics choice">
      <div><strong>Privacy choices</strong><p>Anonymous first-party usage analytics are currently {choice === "accepted" ? "on" : "off"}. You can change this choice at any time.</p></div>
      <div className="cv-analytics-consent-actions">
        <button type="button" onClick={() => choose("rejected")}>Keep off</button>
        <button type="button" className="primary" onClick={() => choose("accepted")}>Allow analytics</button>
      </div>
    </aside>
  );
}
