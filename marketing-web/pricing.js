(() => {
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
