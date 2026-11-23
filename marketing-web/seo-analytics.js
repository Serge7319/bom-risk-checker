(() => {
  const APP_ORIGIN = "https://app.cadivor.com";
  const CONSENT_KEY = "cadivor_analytics_consent_v1";
  const SESSION_KEY = "cadivor_analytics_session_v1";
  const UTM_KEY = "cadivor_analytics_utm_v1";

  function allowed() {
    try { return localStorage.getItem(CONSENT_KEY) === "accepted"; } catch { return false; }
  }

  function sessionId() {
    if (!allowed()) return "";
    try {
      const existing = sessionStorage.getItem(SESSION_KEY) || "";
      if (/^[0-9a-f-]{36}$/i.test(existing)) return existing;
      const generated = crypto.randomUUID();
      sessionStorage.setItem(SESSION_KEY, generated);
      return generated;
    } catch { return ""; }
  }

  function utm() {
    if (!allowed()) return {};
    const result = {};
    const query = new URLSearchParams(location.search);
    for (const key of ["utm_source", "utm_medium", "utm_campaign", "utm_content"]) {
      const value = (query.get(key) || "").trim().slice(0, 80);
      if (value) result[key] = value;
    }
    if (Object.keys(result).length) {
      try { sessionStorage.setItem(UTM_KEY, JSON.stringify(result)); } catch {}
      return result;
    }
    try { return JSON.parse(sessionStorage.getItem(UTM_KEY) || "{}"); } catch { return {}; }
  }

  function track(event, properties = {}) {
    if (!allowed()) return;
    fetch(`${APP_ORIGIN}/api/public/analytics`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ event, source: "marketing", page: location.pathname, session_id: sessionId(), utm: utm(), properties }),
      keepalive: true,
      cache: "no-store",
    }).catch(() => undefined);
  }

  // Direct marketing pages reuse the same consent-gated sender without
  // passing form content or contact details.
  window.cadivorTrackMarketingEvent = track;

  function decorateAppLinks() {
    if (!allowed()) return;
    const params = utm();
    const visitId = sessionId();
    document.querySelectorAll('a[href^="https://app.cadivor.com/"]').forEach((anchor) => {
      try {
        const url = new URL(anchor.href);
        for (const [key, value] of Object.entries(params)) if (!url.searchParams.has(key)) url.searchParams.set(key, value);
        if (visitId) url.searchParams.set("cadivor_visit_id", visitId);
        anchor.href = url.toString();
      } catch {}
    });
  }

  const auditFrame = document.getElementById("freeAuditFrame");
  function analyticsChoice() {
    try {
      const value = localStorage.getItem(CONSENT_KEY) || "";
      return value === "accepted" || value === "rejected" ? value : "";
    } catch { return ""; }
  }

  function notifyAuditConsent() {
    const choice = analyticsChoice();
    if (!choice || !(auditFrame instanceof HTMLIFrameElement) || !auditFrame.contentWindow) return;
    auditFrame.contentWindow.postMessage(
      { type: "cadivor:marketing-analytics-consent", choice },
      APP_ORIGIN,
    );
  }

  function loadAuditEmbed() {
    if (!(auditFrame instanceof HTMLIFrameElement) || auditFrame.hasAttribute("src")) return;
    const params = new URLSearchParams({ embed: "true", source: "free-audit-page" });
    const choice = analyticsChoice();
    if (choice) params.set("analytics_consent", choice);
    if (allowed()) {
      for (const [key, value] of Object.entries(utm())) params.set(key, value);
      const visitId = sessionId();
      if (visitId) params.set("cadivor_visit_id", visitId);
    }
    auditFrame.src = `${APP_ORIGIN}/public-bom-audit?${params.toString()}`;
  }

  if (auditFrame instanceof HTMLIFrameElement) {
    window.addEventListener("message", (event) => {
      if (event.origin !== APP_ORIGIN || event.source !== auditFrame.contentWindow) return;
      const message = event.data;
      if (!message || message.type !== "cadivor:public-bom-audit:resize") return;
      const height = Number(message.height);
      if (!Number.isFinite(height)) return;
      auditFrame.style.height = `${Math.min(4200, Math.max(360, Math.ceil(height)))}px`;
    });
    auditFrame.addEventListener("load", notifyAuditConsent);
    loadAuditEmbed();
  }

  const banner = document.getElementById("seoAnalyticsConsent");
  const manage = document.getElementById("seoPrivacyChoices");
  const applyChoice = () => {
    let choice = "";
    try { choice = localStorage.getItem(CONSENT_KEY) || ""; } catch { choice = "rejected"; }
    if (banner) banner.hidden = Boolean(choice);
    if (manage) manage.hidden = choice !== "rejected" && choice !== "accepted";
  };
  banner?.querySelectorAll("[data-seo-consent]").forEach((button) => {
    button.addEventListener("click", () => {
      const choice = button.dataset.seoConsent === "accepted" ? "accepted" : "rejected";
      try { localStorage.setItem(CONSENT_KEY, choice); } catch {}
      applyChoice();
      decorateAppLinks();
      loadAuditEmbed();
      notifyAuditConsent();
      if (choice === "accepted") track("page_view");
    });
  });
  manage?.addEventListener("click", () => { if (banner) banner.hidden = false; manage.hidden = true; });
  applyChoice();
  decorateAppLinks();
  track("page_view");

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    const cta = target?.closest(".seo-button, .seo-actions a");
    if (!cta) return;
    const section = cta.closest("section, header, article");
    const label = (cta.textContent || cta.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim().slice(0, 80);
    track("cta_click", { location: section?.id || "page", cta: label });
    if (/one-time|report/i.test(cta.href || "")) track("upgrade_clicked", { intent: "one-time-report" });
  }, true);
})();
