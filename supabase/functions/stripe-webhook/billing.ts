// Billing decisions shared by the Stripe webhook handler.
// Metadata wins. A configured price id is only the fallback. Disagreement
// and an entitling status with no mapped plan are retryable configuration
// errors: do not grant a paid plan and do not mark the event processed.
// Non-paying plan writes are applied in SQL from plan_grandfather_source.
// This module must not infer Beta access from plan text or Stripe ids, and
// must not set a paid plan for a non-entitling status.

export const PLAN_TOKENS: Record<string, string> = {
  starter: "Starter",
  professional: "Professional",
  business: "Business",
};

export const ENTITLING_STATUSES = new Set(["active", "trialing"]);

export class WebhookConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WebhookConfigurationError";
  }
}

export function asId(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (value && typeof value === "object" && "id" in value) {
    const id = (value as { id?: unknown }).id;
    return typeof id === "string" && id.trim() ? id.trim() : null;
  }
  return null;
}

export function priceIdOf(subscription: {
  items?: { data?: Array<{ price?: { id?: string | null } | string | null }> };
}): string | null {
  const price = subscription.items?.data?.[0]?.price;
  if (typeof price === "string") return price.trim() || null;
  const id = price && typeof price === "object" ? price.id : null;
  return typeof id === "string" && id.trim() ? id.trim() : null;
}

function planForPrice(
  priceId: string | null,
  priceIds: Record<string, string | undefined>,
): string | null {
  if (!priceId) return null;
  for (const planName of Object.values(PLAN_TOKENS)) {
    const configured = priceIds[planName];
    if (configured && configured.trim() === priceId) return planName;
  }
  return null;
}

export function resolvePaidPlan(
  metadata: Record<string, unknown> | null | undefined,
  priceId: string | null,
  priceIds: Record<string, string | undefined>,
): string | null {
  const token = String(metadata?.cadivor_plan || "").trim().toLowerCase();
  const metadataPlan = token ? PLAN_TOKENS[token] ?? null : null;
  const unknownToken = Boolean(token) && metadataPlan === null;
  const pricePlan = planForPrice(priceId, priceIds);
  if (unknownToken && pricePlan) {
    throw new WebhookConfigurationError(
      "cadivor_plan metadata and Stripe price id disagree.",
    );
  }
  if (metadataPlan && pricePlan && metadataPlan !== pricePlan) {
    throw new WebhookConfigurationError(
      "cadivor_plan metadata and Stripe price id disagree.",
    );
  }
  if (unknownToken) return null;
  return metadataPlan || pricePlan;
}

export function billingDecision(
  subscription: {
    status?: string | null;
    metadata?: Record<string, unknown> | null;
    items?: { data?: Array<{ price?: { id?: string | null } | string | null }> };
  },
  priceIds: Record<string, string | undefined>,
): { setPlan: boolean; plan: string | null; priceId: string | null } {
  const status = String(subscription.status || "").trim().toLowerCase();
  const mapped = resolvePaidPlan(
    subscription.metadata,
    priceIdOf(subscription),
    priceIds,
  );
  const entitling = ENTITLING_STATUSES.has(status);
  if (entitling && !mapped) {
    throw new WebhookConfigurationError(
      "Active subscription is not mapped to a Cadivor paid plan.",
    );
  }
  return {
    setPlan: Boolean(entitling && mapped),
    plan: entitling ? mapped : null,
    priceId: priceIdOf(subscription),
  };
}
