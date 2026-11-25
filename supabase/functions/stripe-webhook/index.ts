import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import Stripe from "https://esm.sh/stripe@16.12.0?target=deno";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";
import {
  WebhookConfigurationError,
  asId,
  billingDecision,
} from "./billing.ts";
import { oneTimeBOMAction } from "./one_time_bom_event.ts";

// Versioned webhook source. JWT verification is disabled in
// supabase/config.toml because Stripe signs the raw request instead.
// Apply both billing migrations and prove a sandbox destination before
// replacing the live destination. The one-time product stays off until then.

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, {
  apiVersion: "2024-06-20",
});

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

const askCadivorCreditPacks = [
  { id: "ask_100", credits: 100, amount: 999 },
  { id: "ask_500", credits: 500, amount: 3999 },
  { id: "ask_1500", credits: 1500, amount: 9999 },
] as const;

const LEASE_SECONDS = 120;

function priceIds(): Record<string, string | string[] | undefined> {
  return {
    Starter: [Deno.env.get("STRIPE_STARTER_PRICE_ID"), Deno.env.get("STRIPE_STARTER_ANNUAL_PRICE_ID")].filter(Boolean) as string[],
    Professional: [Deno.env.get("STRIPE_PRO_PRICE_ID"), Deno.env.get("STRIPE_PRO_ANNUAL_PRICE_ID")].filter(Boolean) as string[],
    Business: [Deno.env.get("STRIPE_BUSINESS_PRICE_ID"), Deno.env.get("STRIPE_BUSINESS_ANNUAL_PRICE_ID")].filter(Boolean) as string[],
  };
}

function asIso(unixSeconds: number | null | undefined): string | null {
  return typeof unixSeconds === "number"
    ? new Date(unixSeconds * 1000).toISOString()
    : null;
}

async function claimEvent(event: Stripe.Event): Promise<"claimed" | "duplicate" | "busy"> {
  const { data, error } = await supabase.rpc("cadivor_claim_stripe_webhook_event", {
    p_event_id: event.id,
    p_event_type: event.type,
    p_livemode: event.livemode,
    p_event_created: new Date(event.created * 1000).toISOString(),
    p_lease_seconds: LEASE_SECONDS,
  });
  if (error) throw new Error("Unable to claim webhook event.");
  if (data === "claimed" || data === "duplicate" || data === "busy") return data;
  throw new Error("Unexpected webhook claim result.");
}

async function completeEvent(
  eventId: string,
  userId: string | null,
  customerId: string | null,
  subscriptionId: string | null,
  outcome: string,
): Promise<void> {
  const { error } = await supabase.rpc("cadivor_complete_stripe_webhook_event", {
    p_event_id: eventId,
    p_user_id: userId,
    p_stripe_customer_id: customerId,
    p_stripe_subscription_id: subscriptionId,
    p_outcome: outcome,
  });
  if (error) throw new Error("Unable to complete webhook event.");
}

async function releaseEvent(eventId: string, message: string): Promise<void> {
  const { error } = await supabase.rpc("cadivor_release_stripe_webhook_event", {
    p_event_id: eventId,
    p_error: message,
  });
  if (error) throw new Error("Unable to release webhook event lease.");
}

async function applySnapshot(
  event: Stripe.Event,
  subscription: Stripe.Subscription,
): Promise<string> {
  const userId = String(subscription.metadata?.user_id || "").trim();
  if (!userId) {
    throw new WebhookConfigurationError("Subscription is missing Cadivor user metadata.");
  }
  const decision = billingDecision(subscription, priceIds());
  const { data, error } = await supabase.rpc("cadivor_apply_stripe_billing_snapshot", {
    p_user_id: userId,
    p_event_id: event.id,
    p_event_created: new Date(event.created * 1000).toISOString(),
    p_stripe_customer_id: asId(subscription.customer),
    p_stripe_subscription_id: subscription.id,
    p_stripe_subscription_status: subscription.status,
    p_stripe_price_id: decision.priceId,
    p_stripe_current_period_end: asIso(subscription.current_period_end),
    p_stripe_cancel_at_period_end: subscription.cancel_at_period_end,
    p_set_plan: decision.setPlan,
    p_plan: decision.plan,
  });
  if (error) throw new Error("Unable to update Cadivor billing status.");
  if (data === "not_found") {
    throw new WebhookConfigurationError("Cadivor user was not found.");
  }
  if (
    data === "applied" ||
    data === "skipped_stale" ||
    data === "admin_untouched"
  ) {
    await applyMonitoredPartsAddonSnapshot(event, subscription, userId, decision.plan);
    return data;
  }
  throw new Error("Unexpected billing snapshot result.");
}

function positiveCapacity(): number | null {
  const raw = String(Deno.env.get("CADIVOR_MONITORED_PARTS_ADDON_CAPACITY") || "").trim();
  if (!/^\d+$/.test(raw)) return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value > 0 && value <= 100_000 ? value : null;
}

async function applyMonitoredPartsAddonSnapshot(
  event: Stripe.Event,
  subscription: Stripe.Subscription,
  userId: string,
  currentPlan: string | null,
): Promise<void> {
  const monthlyPriceId = String(Deno.env.get("STRIPE_MONITORED_PARTS_MONTHLY_PRICE_ID") || "").trim();
  const annualPriceId = String(Deno.env.get("STRIPE_MONITORED_PARTS_ANNUAL_PRICE_ID") || "").trim();
  const configuredPriceIds = new Set([monthlyPriceId, annualPriceId].filter(Boolean));
  const items = subscription.items?.data || [];
  const addonItem = items.find((item) => configuredPriceIds.has(asId(item.price) || ""));
  const { data: existing, error: existingError } = await supabase
    .from("cadivor_monitored_parts_addons")
    .select("price_id,capacity")
    .eq("subscription_id", subscription.id)
    .maybeSingle();
  if (existingError) throw new Error("Monitored-parts subscription record could not be loaded.");

  const markedItem = items.find((item) =>
    String(item.metadata?.cadivor_addon || "") === "monitored_parts_capacity"
  );
  let selectedItem = addonItem || (markedItem && existing ? markedItem : null);
  if (selectedItem && ENTITLING_STATUSES.has(String(subscription.status || "").toLowerCase()) &&
      !["Starter", "Professional"].includes(String(currentPlan || ""))) {
    await stripe.subscriptionItems.del(selectedItem.id, { proration_behavior: "create_prorations" });
    selectedItem = null;
  }
  if (!selectedItem && !existing) return;

  const priceId = asId(selectedItem?.price) || String(existing?.price_id || "").trim();
  const capacity = positiveCapacity() || Number(existing?.capacity || 0);
  if (!priceId || !Number.isSafeInteger(capacity) || capacity <= 0) {
    throw new WebhookConfigurationError("Monitored-parts add-on capacity is not configured.");
  }
  if (selectedItem && !configuredPriceIds.has(priceId) && !(existing && markedItem === selectedItem)) {
    throw new WebhookConfigurationError("Monitored-parts add-on price is not mapped.");
  }
  const status = selectedItem
    ? subscription.status
    : ENTITLING_STATUSES.has(String(subscription.status || "").toLowerCase())
      ? "canceled"
      : subscription.status;
  const { data, error } = await supabase.rpc("cadivor_set_monitored_parts_addon", {
    p_user_id: userId,
    p_subscription_id: subscription.id,
    p_price_id: priceId,
    p_status: status,
    p_capacity: capacity,
    p_event_created: new Date(event.created * 1000).toISOString(),
  });
  if (error || (data !== "applied" && data !== "skipped_stale")) {
    throw new Error("Unable to update monitored-parts add-on status.");
  }
}

async function applyProfessionalApiAddonSnapshot(
  event: Stripe.Event,
  subscription: Stripe.Subscription,
): Promise<{ userId: string; customerId: string | null; outcome: string }> {
  const userId = String(subscription.metadata?.user_id || "").trim();
  const expectedPriceId = String(Deno.env.get("STRIPE_PROFESSIONAL_API_ADDON_PRICE_ID") || "").trim();
  const currentPriceId = asId(subscription.items?.data?.[0]?.price);
  if (!userId || !expectedPriceId || currentPriceId !== expectedPriceId) {
    throw new WebhookConfigurationError("Professional API add-on subscription is not mapped.");
  }
  const { data, error } = await supabase.rpc("cadivor_set_professional_api_addon", {
    p_user_id: userId,
    p_subscription_id: subscription.id,
    p_price_id: currentPriceId,
    p_status: subscription.status,
  });
  if (error || data !== "applied") throw new Error("Unable to update Professional API add-on status.");
  return {
    userId,
    customerId: asId(subscription.customer),
    outcome: ENTITLING_STATUSES.has(String(subscription.status || "").toLowerCase()) ? "applied" : "updated",
  };
}

async function usageOverageEvent(event: Stripe.Event): Promise<{
  userId: string | null; customerId: string | null; outcome: string;
} | null> {
  if (![
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "checkout.session.expired",
  ].includes(event.type)) return null;
  const session = event.data.object as Stripe.Checkout.Session;
  if (session.mode !== "payment" || session.metadata?.cadivor_addon !== "usage_overage") return null;
  const userId = String(session.metadata?.user_id || "").trim();
  const kind = String(session.metadata?.cadivor_credit_kind || "").trim();
  const creditsRaw = String(session.metadata?.cadivor_credit_units || "").trim();
  const units = /^\d+$/.test(creditsRaw) ? Number(creditsRaw) : 0;
  const packId = String(session.metadata?.cadivor_credit_pack_id || "").trim();
  const askPack = kind === "ask_cadivor"
    ? askCadivorCreditPacks.find((pack) => pack.id === packId)
    : null;
  const env = kind === "bom_analysis"
    ? { price: "STRIPE_BOM_ANALYSIS_OVERAGE_PRICE_ID", credits: "CADIVOR_BOM_ANALYSIS_OVERAGE_CREDITS" }
    : kind === "monitored_part"
      ? { price: "STRIPE_MONITORED_PARTS_OVERAGE_PRICE_ID", credits: "CADIVOR_MONITORED_PARTS_OVERAGE_CREDITS" }
      : null;
  const expectedUnits = askPack ? askPack.credits : env ? Number(Deno.env.get(env.credits) || 0) : 0;
  if (!userId || (!env && !askPack) || !Number.isSafeInteger(units) || units <= 0 ||
      units !== expectedUnits) {
    throw new WebhookConfigurationError("Usage overage checkout metadata is invalid.");
  }
  const expectedPriceId = env ? String(Deno.env.get(env.price) || "").trim() : "";
  if (env && !expectedPriceId) throw new WebhookConfigurationError("Usage overage price is not configured.");

  if (event.type === "checkout.session.expired" || event.type === "checkout.session.async_payment_failed") {
    return { userId, customerId: asId(session.customer), outcome: "closed" };
  }
  if (session.payment_status !== "paid") {
    return { userId, customerId: asId(session.customer), outcome: "pending" };
  }
  const paymentIntent = asId(session.payment_intent);
  const items = await stripe.checkout.sessions.listLineItems(session.id, { limit: 2 });
  const item = items.data[0];
  const priceId = asId(item?.price);
  if (!paymentIntent || items.data.length !== 1 || item?.quantity !== 1 ||
      (expectedPriceId && priceId !== expectedPriceId)) {
    throw new WebhookConfigurationError("Usage overage checkout has invalid payment or line items.");
  }
  if (askPack) {
    const price = priceId ? await stripe.prices.retrieve(priceId) : null;
    if (!price || !price.active || price.currency !== "usd" || price.recurring ||
        price.unit_amount !== askPack.amount || session.currency !== "usd") {
      throw new WebhookConfigurationError("Ask Cadivor credit pack amount could not be verified.");
    }
  }
  const { data, error } = await supabase.rpc("cadivor_grant_usage_credits", {
    p_checkout_session_id: session.id,
    p_user_id: userId,
    p_payment_intent_id: paymentIntent,
    p_price_id: priceId,
    p_credit_kind: kind,
    p_credits: units,
  });
  if (error || (data !== "applied" && data !== "duplicate")) {
    throw new Error("Unable to grant purchased usage credits.");
  }
  return {
    userId,
    customerId: asId(session.customer),
    outcome: data === "applied" ? "applied" : "duplicate",
  };
}

async function subscriptionForEvent(event: Stripe.Event): Promise<Stripe.Subscription | null> {
  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
    if (session.mode === "payment") return null;
    const subscriptionId = asId(session.subscription);
    if (!subscriptionId) {
      throw new WebhookConfigurationError("Completed checkout has no subscription.");
    }
    return await stripe.subscriptions.retrieve(subscriptionId);
  }
  if (
    event.type === "customer.subscription.created" ||
    event.type === "customer.subscription.updated" ||
    event.type === "customer.subscription.deleted"
  ) {
    return event.data.object as Stripe.Subscription;
  }
  if (event.type === "invoice.payment_failed" || event.type === "invoice.paid") {
    const invoice = event.data.object as Stripe.Invoice;
    const subscriptionId = asId(invoice.subscription);
    if (!subscriptionId) return null;
    return await stripe.subscriptions.retrieve(subscriptionId);
  }
  return null;
}

async function oneTimeBOMEvent(event: Stripe.Event): Promise<{
  userId: string | null; customerId: string | null; outcome: string;
} | null> {
  const session = event.data.object as Stripe.Checkout.Session;
  const action = oneTimeBOMAction(event.type, session);
  if (!action) return null;
  if (action === "ignore") {
    return { userId: null, customerId: null, outcome: "ignored" };
  }
  const orderId = String(session.metadata?.cadivor_order_id || "");
  const userId = String(session.metadata?.user_id || "");
  const customerId = asId(session.customer);
  if (action === "close") {
    const { data, error } = await supabase.rpc("cadivor_close_one_time_bom_checkout", {
      p_order_id: orderId, p_session_id: session.id,
    });
    if (error || data === "not_found") throw new Error("Unable to close one-time BOM order.");
    return { userId, customerId, outcome: data === "applied" ? "applied" : "skipped_stale" };
  }
  // Checkout completion can precede delayed-payment settlement. Never grant
  // an analysis credit for an unpaid Session or for a browser redirect.
  if (action === "pending") {
    return { userId, customerId, outcome: "ignored" };
  }
  const paymentIntent = asId(session.payment_intent);
  const items = await stripe.checkout.sessions.listLineItems(session.id, { limit: 2 });
  const item = items.data[0];
  if (!paymentIntent || items.data.length !== 1 || item.quantity !== 1) {
    throw new WebhookConfigurationError("One-time checkout has invalid payment or line items.");
  }
  const priceId = asId(item.price);
  if (!priceId) throw new WebhookConfigurationError("One-time checkout has no price.");
  const { data, error } = await supabase.rpc("cadivor_fulfill_one_time_bom_order", {
    p_order_id: orderId,
    p_user_id: userId,
    p_session_id: session.id,
    p_price_id: priceId,
    p_payment_intent_id: paymentIntent,
  });
  if (error || data === "not_found") throw new Error("Unable to fulfill one-time BOM order.");
  if (data !== "applied" && data !== "already_paid") {
    throw new Error("Unexpected one-time BOM fulfillment outcome.");
  }
  return { userId, customerId, outcome: data === "applied" ? "applied" : "skipped_stale" };
}

async function manualPlanInvoiceEvent(event: Stripe.Event): Promise<{
  userId: string | null; customerId: string | null; outcome: string;
} | null> {
  if (event.type !== "invoice.paid") return null;
  const invoice = event.data.object as Stripe.Invoice;
  const invoiceRecordId = String(invoice.metadata?.cadivor_manual_plan_invoice_id || "").trim();
  if (!invoiceRecordId) return null;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(invoiceRecordId)) {
    throw new WebhookConfigurationError("Manual Cadivor invoice metadata is invalid.");
  }
  if (invoice.status !== "paid" || invoice.subscription || typeof invoice.amount_paid !== "number" ||
      !invoice.currency || !invoice.status_transitions?.paid_at) {
    throw new WebhookConfigurationError("Paid manual invoice is incomplete or linked to a subscription.");
  }
  const { data: record, error: recordError } = await supabase
    .from("cadivor_manual_plan_invoices")
    .select("id,user_id,stripe_invoice_id")
    .eq("id", invoiceRecordId)
    .maybeSingle();
  if (recordError || !record || record.stripe_invoice_id !== invoice.id) {
    throw new WebhookConfigurationError("Paid manual invoice does not match a Cadivor billing record.");
  }
  const { data, error } = await supabase.rpc("cadivor_apply_manual_plan_invoice_paid", {
    p_invoice_id: invoiceRecordId,
    p_stripe_invoice_id: invoice.id,
    p_stripe_event_id: event.id,
    p_amount_paid: invoice.amount_paid,
    p_currency: invoice.currency,
    p_paid_at: new Date(invoice.status_transitions.paid_at * 1000).toISOString(),
    p_paid_out_of_band: invoice.paid_out_of_band === true,
  });
  if (error) throw new Error("Paid manual invoice could not be applied.");
  const result = (data || {}) as Record<string, unknown>;
  if (result.ok !== true || !["applied", "already_paid", "account_deleted", "account_unavailable"].includes(String(result.outcome || ""))) {
    throw new WebhookConfigurationError("Manual invoice payment did not pass Cadivor validation.");
  }
  return {
    userId: record.user_id ? String(record.user_id) : null,
    customerId: asId(invoice.customer),
    outcome: String(result.outcome),
  };
}

serve(async (req) => {
  const signature = req.headers.get("stripe-signature");
  if (!signature) {
    return new Response("Missing Stripe signature", { status: 400 });
  }

  const body = await req.text();
  let event: Stripe.Event;
  try {
    event = await stripe.webhooks.constructEventAsync(
      body,
      signature,
      Deno.env.get("STRIPE_WEBHOOK_SECRET")!,
    );
  } catch {
    return new Response("Webhook signature verification failed", { status: 400 });
  }

  let claimed = false;
  try {
    const claim = await claimEvent(event);
    if (claim === "duplicate") {
      return Response.json({ received: true, duplicate: true });
    }
    if (claim === "busy") {
      return new Response("Webhook event is already being processed", { status: 500 });
    }
    claimed = true;

    const usageOverage = await usageOverageEvent(event);
    if (usageOverage) {
      await completeEvent(event.id, usageOverage.userId, usageOverage.customerId, null, usageOverage.outcome);
      return Response.json({ received: true, outcome: usageOverage.outcome });
    }

    const oneTime = await oneTimeBOMEvent(event);
    if (oneTime) {
      await completeEvent(event.id, oneTime.userId, oneTime.customerId, null, oneTime.outcome);
      return Response.json({ received: true, outcome: oneTime.outcome });
    }

    const manualInvoice = await manualPlanInvoiceEvent(event);
    if (manualInvoice) {
      await completeEvent(event.id, manualInvoice.userId, manualInvoice.customerId, null, manualInvoice.outcome);
      return Response.json({ received: true, outcome: manualInvoice.outcome });
    }

    const subscription = await subscriptionForEvent(event);
    if (!subscription) {
      await completeEvent(event.id, null, null, null, "ignored");
      return Response.json({ received: true, outcome: "ignored" });
    }

    if (String(subscription.metadata?.cadivor_addon || "") === "professional_api") {
      const addon = await applyProfessionalApiAddonSnapshot(event, subscription);
      await completeEvent(event.id, addon.userId, addon.customerId, subscription.id, addon.outcome);
      return Response.json({ received: true, outcome: addon.outcome });
    }

    const outcome = await applySnapshot(event, subscription);
    await completeEvent(
      event.id,
      String(subscription.metadata?.user_id || "").trim() || null,
      asId(subscription.customer),
      subscription.id,
      outcome,
    );
    return Response.json({ received: true, outcome });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    if (claimed) {
      try {
        await releaseEvent(event.id, message);
      } catch (releaseError) {
        console.error("Stripe webhook lease release failed", {
          eventId: event.id,
          message: releaseError instanceof Error ? releaseError.message : "Unknown error",
        });
      }
    }
    console.error("Stripe webhook processing failed", {
      eventId: event.id,
      eventType: event.type,
      message,
    });
    return new Response("Webhook processing failed", { status: 500 });
  }
});
