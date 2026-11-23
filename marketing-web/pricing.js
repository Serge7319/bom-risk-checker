(() => {
  const addonSection = document.querySelector("[data-addons-catalog-url]");
  const formatMoney = (cents, currency) => {
    const code = /^[A-Z]{3}$/.test(String(currency || "").toUpperCase())
      ? String(currency).toUpperCase()
      : "USD";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: code,
      maximumFractionDigits: 2,
      minimumFractionDigits: 0,
    }).format(cents / 100);
  };

  if (addonSection) {
    const addonCards = addonSection.querySelector("[data-addon-cards]");
    const addonStatus = addonSection.querySelector("[data-addon-status]");
    const addonDefinitions = [
      { key: "bom_analysis", title: "BOM analysis pack", unitLabel: "additional BOM analyses" },
      { key: "monitored_parts", title: "Monitored-parts pack", unitLabel: "additional monitored parts" },
    ];
    fetch(addonSection.dataset.addonsCatalogUrl, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    })
      .then((response) => {
        if (!response.ok) throw new Error("Usage packs unavailable");
        return response.json();
      })
      .then((catalog) => {
        if (!catalog || catalog.ok !== true || !catalog.addons) {
          throw new Error("Usage packs unavailable");
        }
        const available = addonDefinitions.filter(({ key }) => {
          const item = catalog.addons[key];
          return item && item.enabled === true && Number.isInteger(item.amount) &&
            item.amount > 0 && Number.isInteger(item.credits) && item.credits > 0;
        });
        addonCards.replaceChildren();
        for (const definition of available) {
          const item = catalog.addons[definition.key];
          const card = document.createElement("article");
          card.className = "seo-card seo-addon-card";
          const kicker = document.createElement("span");
          kicker.className = "seo-kicker";
          kicker.textContent = "ONE-TIME PURCHASE";
          const heading = document.createElement("h3");
          heading.textContent = definition.title;
          const price = document.createElement("p");
          price.className = "seo-addon-price";
          price.textContent = formatMoney(item.amount, item.currency);
          const units = document.createElement("p");
          units.textContent = `${Number(item.credits).toLocaleString()} ${definition.unitLabel}`;
          const note = document.createElement("p");
          note.textContent = "For eligible active paid workspaces. Sign in to review pack eligibility and purchase.";
          const link = document.createElement("a");
          link.className = "seo-button";
          link.href = "https://app.cadivor.com/settings?tab=billing";
          link.textContent = "View account billing";
          card.append(kicker, heading, price, units, note, link);
          addonCards.append(card);
        }
        addonStatus.textContent = available.length
          ? "Displayed prices and credit amounts come from the active billing catalog. Checkout verifies account eligibility."
          : "No usage packs are currently published for checkout. Available packs will appear here after the billing price and credit amount are configured.";
      })
      .catch(() => {
        addonCards.replaceChildren();
        addonStatus.textContent = "Published usage pack prices could not be refreshed. Check account billing for current availability.";
      });
  }

  const section = document.querySelector("[data-pricing-catalog-url]");
  if (!section) return;

  const annualButton = section.querySelector('[data-billing="year"]');
  const monthlyButton = section.querySelector('[data-billing="month"]');
  const status = section.querySelector("[data-pricing-status]");
  const cards = [...section.querySelectorAll("[data-plan-token]")];
  const plans = new Map();
  let billing = "month";

  const formatUsd = (cents) => new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
    minimumFractionDigits: 0,
  }).format(cents / 100);

  function render() {
    for (const card of cards) {
      const plan = plans.get(card.dataset.planToken);
      if (!plan) continue;
      const amount = card.querySelector("[data-price-amount]");
      const period = card.querySelector("[data-price-period]");
      const note = card.querySelector("[data-annual-note]");
      const annual = plan.annual && plan.annual.enabled === true && Number.isFinite(plan.annual.amount);
      const monthly = plan.enabled === true && Number.isFinite(plan.amount);

      if (billing === "year" && annual) {
        amount.textContent = formatUsd(plan.annual.amount);
        period.textContent = "/year";
        const discount = Number(plan.annual.discount_percent);
        note.textContent = discount > 0
          ? `Save ${discount}% compared with monthly billing.`
          : "Annual billing.";
        note.hidden = false;
      } else if (billing === "year") {
        if (monthly) amount.textContent = formatUsd(plan.amount);
        period.textContent = "/month";
        note.textContent = "Annual rate not available yet.";
        note.hidden = false;
      } else {
        if (monthly) amount.textContent = formatUsd(plan.amount);
        period.textContent = "/month";
        note.hidden = true;
      }
    }
    monthlyButton.classList.toggle("is-active", billing === "month");
    monthlyButton.setAttribute("aria-pressed", String(billing === "month"));
    annualButton.classList.toggle("is-active", billing === "year");
    annualButton.setAttribute("aria-pressed", String(billing === "year"));
    if (status) {
      status.textContent = billing === "year"
        ? "Annual prices below are billed once per year. Savings compare the annual amount with 12 monthly payments."
        : annualButton.disabled
          ? "Annual pricing will appear here when annual Stripe prices are configured."
          : "Annual pricing is available for selected plans. Choose Annual to compare rates.";
    }
  }

  annualButton.addEventListener("click", () => {
    if (!annualButton.disabled) {
      billing = "year";
      render();
    }
  });
  monthlyButton.addEventListener("click", () => {
    billing = "month";
    render();
  });

  fetch(section.dataset.pricingCatalogUrl, { headers: { Accept: "application/json" }, cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error("Price catalog unavailable");
      return response.json();
    })
    .then((catalog) => {
      if (!catalog || catalog.ok !== true || !Array.isArray(catalog.plans)) {
        throw new Error("Price catalog unavailable");
      }
      for (const plan of catalog.plans) {
        if (plan && typeof plan.token === "string") plans.set(plan.token, plan);
      }
      const annualAvailable = [...plans.values()].some((plan) =>
        plan.annual && plan.annual.enabled === true && Number.isFinite(plan.annual.amount),
      );
      annualButton.disabled = !annualAvailable;
      if (status && annualAvailable) {
        status.textContent = "Annual pricing is available for selected plans. Choose Annual to compare rates.";
      }
      render();
    })
    .catch(() => {
      annualButton.disabled = true;
      if (status) status.textContent = "Monthly prices are shown. Annual pricing could not be refreshed.";
    });
})();
