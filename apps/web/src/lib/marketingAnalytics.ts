"use client";

const SESSION_KEY = "cadivor_analytics_session_v1";
const UTM_KEY = "cadivor_analytics_utm_v1";
const UTM_FIELDS = ["utm_source", "utm_medium", "utm_campaign", "utm_content"] as const;
const CONSENT_KEY = "cadivor_analytics_consent_v1";
export type MarketingEvent =
  | "page_view" | "cta_click" | "free_audit_started" | "free_audit_completed"
  | "signup_started" | "signup_completed" | "bom_uploaded"
  | "first_analysis_completed" | "trial_started" | "upgrade_clicked"
  | "checkout_started" | "subscription_created" | "demo_requested"
  | "one_time_report_purchased";

export function marketingAnalyticsAllowed(): boolean {
  if (typeof window === "undefined") return false;
  try { return localStorage.getItem(CONSENT_KEY) === "accepted"; } catch { return false; }
}

function safeParams(): URLSearchParams {
  if (typeof window === "undefined") return new URLSearchParams();
  const params = new URLSearchParams(window.location.search);
  const hashQuery = window.location.hash.match(/\?([^#]+)/)?.[1] || "";
  new URLSearchParams(hashQuery).forEach((value, key) => {
    if (!params.has(key)) params.set(key, value);
  });
  return params;
}

export function captureMarketingAttribution(): Record<string, string> {
  if (typeof window === "undefined") return {};
  if (!marketingAnalyticsAllowed()) return {};
  const current = safeParams();
  const values: Record<string, string> = {};
  for (const field of UTM_FIELDS) {
    const value = (current.get(field) || "").trim().slice(0, 80);
    if (value) values[field] = value;
  }
  if (Object.keys(values).length) {
    try { sessionStorage.setItem(UTM_KEY, JSON.stringify(values)); } catch { /* storage may be disabled */ }
    return values;
  }
  try {
    const stored = JSON.parse(sessionStorage.getItem(UTM_KEY) || "{}");
    return stored && typeof stored === "object" ? stored as Record<string, string> : {};
  } catch {
    return {};
  }
}

export function analyticsSessionId(): string {
  if (typeof window === "undefined") return "";
  if (!marketingAnalyticsAllowed()) return "";
  try {
    const params = safeParams();
    const incoming = params.get("cadivor_visit_id") || "";
    const stored = sessionStorage.getItem(SESSION_KEY) || "";
    const candidate = incoming || stored;
    if (/^[0-9a-f-]{36}$/i.test(candidate)) {
      sessionStorage.setItem(SESSION_KEY, candidate);
      return candidate;
    }
    const generated = typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
          const random = Math.random() * 16 | 0;
          return (char === "x" ? random : (random & 0x3 | 0x8)).toString(16);
        });
    sessionStorage.setItem(SESSION_KEY, generated);
    return generated;
  } catch {
    return "";
  }
}

export function trackMarketingEvent(
  event: MarketingEvent,
  properties: Record<string, string> = {},
  page?: string,
): void {
  if (typeof window === "undefined" || !marketingAnalyticsAllowed()) return;
  const payload = {
    event,
    source: "app",
    page: page || window.location.pathname,
    session_id: analyticsSessionId(),
    utm: captureMarketingAttribution(),
    properties,
  };
  void fetch("/api/public/analytics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => undefined);
}

export function trackMarketingEventOnce(
  event: MarketingEvent,
  dedupeKey: string,
  properties: Record<string, string> = {},
  page?: string,
): void {
  if (typeof window === "undefined" || !marketingAnalyticsAllowed()) return;
  const key = `cadivor_analytics_once:${dedupeKey.slice(0, 120)}`;
  try { if (localStorage.getItem(key)) return; } catch { /* continue without browser storage */ }
  const payload = {
    event,
    source: "app",
    page: page || window.location.pathname,
    session_id: analyticsSessionId(),
    utm: captureMarketingAttribution(),
    properties,
  };
  void fetch("/api/public/analytics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).then((response) => {
    if (response.ok) {
      try { localStorage.setItem(key, "1"); } catch { /* still record this session */ }
    }
  }).catch(() => undefined);
}
