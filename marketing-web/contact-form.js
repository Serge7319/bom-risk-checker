(() => {
  const form = document.getElementById("cadivorContactForm");
  if (!form) return;

  const card = document.getElementById("contactFormCard");
  const success = document.getElementById("contactSuccess");
  const successMessage = document.getElementById("contactSuccessMessage");
  const status = document.getElementById("contactStatus");
  const submit = document.getElementById("contactSubmit");
  const reset = document.getElementById("contactReset");
  const endpoint = "https://app.cadivor.com/api/public/contact";
  const inboxByTopic = { security: "security@cadivor.com", legal: "legal@cadivor.com", billing: "billing@cadivor.com" };
  let started = false;

  function track(event, properties) {
    if (typeof window.cadivorTrackMarketingEvent === "function") {
      window.cadivorTrackMarketingEvent(event, properties);
    }
  }

  function safeTopic(value) {
    const allowed = new Set(["demo", "general", "student", "beta", "blocker", "support", "single-report", "billing", "security", "legal"]);
    const topic = String(value || "demo").trim().toLowerCase();
    return allowed.has(topic) ? topic : "demo";
  }

  function queryAttribution() {
    const query = new URLSearchParams(window.location.search);
    const result = {};
    try {
      if (window.localStorage.getItem("cadivor_analytics_consent_v1") !== "accepted") return result;
    } catch {
      return result;
    }
    for (const key of ["utm_source", "utm_medium", "utm_campaign", "utm_content"]) {
      const value = (query.get(key) || "").trim().slice(0, 80);
      if (value) result[key] = value;
    }
    return result;
  }

  form.addEventListener("focusin", () => {
    if (started) return;
    started = true;
    track("contact_form_started", { intent: safeTopic(new URLSearchParams(window.location.search).get("intent") || form.elements.topic.value), location: "contact-form" });
  }, { once: true });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const name = String(data.get("name") || "").trim();
    const email = String(data.get("email") || "").trim();
    const message = String(data.get("message") || "").trim();
    if (!name || !email || !message || data.get("consent") !== "true") {
      status.textContent = "Complete the required fields and consent before submitting.";
      status.setAttribute("role", "alert");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      status.textContent = "Enter a valid email address.";
      status.setAttribute("role", "alert");
      return;
    }

    const query = new URLSearchParams(window.location.search);
    const topic = safeTopic(query.get("intent") || data.get("topic"));
    const payload = {
      name,
      email,
      company: String(data.get("company") || "").trim(),
      role: String(data.get("role") || "").trim(),
      team_size: String(data.get("team_size") || "").trim(),
      bom_volume: String(data.get("bom_volume") || "").trim(),
      topic,
      plan_interest: query.get("plan") || "",
      message,
      consent: true,
      website: String(data.get("website") || "").trim(),
      source: "marketing-contact",
      utm: queryAttribution(),
    };
    submit.disabled = true;
    status.setAttribute("role", "status");
    status.textContent = "Sending your request…";
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
        cache: "no-store",
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok !== true) {
        throw new Error(result.detail || "Your request could not be sent. Please try again.");
      }
      track("contact_form_completed", { intent: topic, location: "contact-form" });
      if (topic === "demo") track("demo_requested", { intent: "demo", location: "contact-form" });
      form.hidden = true;
      success.hidden = false;
      const inbox = inboxByTopic[topic] || "info@cadivor.com";
      if (result.notification_status === "sent") {
        successMessage.textContent = "Your request was sent to Cadivor. We aim to follow up within one business day.";
      } else {
        successMessage.textContent = result.notification_status === "not_configured"
          ? `Your request was saved, but email delivery is not active yet. Email ${inbox} for a timely reply.`
          : `Your request was saved, but Cadivor could not be notified. Email ${inbox} so we can respond.`;
        const link = document.createElement("a");
        link.href = `mailto:${inbox}?subject=${encodeURIComponent("Cadivor request follow-up")}`;
        link.textContent = `Email ${inbox}`;
        successMessage.append(document.createElement("br"), link);
      }
      card.classList.add("is-success");
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : "Your request could not be sent. Please try again.";
      status.setAttribute("role", "alert");
      submit.disabled = false;
    }
  });

  reset?.addEventListener("click", () => {
    form.reset();
    form.hidden = false;
    success.hidden = true;
    submit.disabled = false;
    status.textContent = "Your request is stored for follow-up. We will tell you if email notification is unavailable.";
    status.setAttribute("role", "status");
    card.classList.remove("is-success");
    started = false;
  });
})();
