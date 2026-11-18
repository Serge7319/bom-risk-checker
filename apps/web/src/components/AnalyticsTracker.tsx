"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { trackMarketingEvent } from "@/lib/marketingAnalytics";

export function AnalyticsTracker() {
  const pathname = usePathname();

  useEffect(() => {
    trackMarketingEvent("page_view", {}, pathname || "/");
  }, [pathname]);

  useEffect(() => {
    const onConsent = () => trackMarketingEvent("page_view", {}, pathname || "/");
    window.addEventListener("cadivor-analytics-consent", onConsent);
    return () => window.removeEventListener("cadivor-analytics-consent", onConsent);
  }, [pathname]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      const cta = target?.closest("a.cv-button, button.cv-button, [data-analytics-cta]");
      if (!cta) return;
      const region = cta.closest("section, main, header") as HTMLElement | null;
      const location = (region?.id || region?.dataset.analyticsLocation || "page").slice(0, 80);
      const label = (cta.getAttribute("data-analytics-cta") || cta.getAttribute("aria-label") || cta.textContent || "")
        .replace(/\s+/g, " ").trim().slice(0, 80);
      if (label) trackMarketingEvent("cta_click", { location, cta: label });
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  return null;
}
