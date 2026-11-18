"use client";

import { useEffect, useState } from "react";

const CONSENT_KEY = "cadivor_analytics_consent_v1";

export function AnalyticsConsent() {
  const [choice, setChoice] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try { setChoice(localStorage.getItem(CONSENT_KEY)); } catch { setChoice("rejected"); }
  }, []);

  function choose(value: "accepted" | "rejected") {
    try { localStorage.setItem(CONSENT_KEY, value); } catch { /* default to no tracking */ }
    setChoice(value);
    setOpen(false);
    if (value === "accepted") window.dispatchEvent(new Event("cadivor-analytics-consent"));
  }

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
