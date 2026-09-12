import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import Stripe from "https://esm.sh/stripe@16.12.0?target=deno";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";
import {
  WebhookConfigurationError,
  asId,
  billingDecision,
} from "./billing.ts";

// Versioned replacement for the exported deployed function.
// Not deployed. JWT verification is disabled only in supabase/config.toml
// because Stripe cannot send a Supabase JWT. Do not deploy until
// 20260912_stripe_webhook_event_lease.sql is approved and the handler is
// proven against a sandbox destination. Do not change the Active Live
// webhook destination from this file.

const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, {
  apiVersion: "2024-06-20",
});

const supabase = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

const LEASE_SECONDS = 120;

function priceIds(): Record<string, string | undefined> {
  return {
    Starter: Deno.env.get("STRIPE_STARTER_PRICE_ID"),
    Professional: Deno.env.get("STRIPE_PRO_PRICE_ID"),
    Business: Deno.env.get("STRIPE_BUSINESS_PRICE_ID"),
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
    return data;
  }
  throw new Error("Unexpected billing snapshot result.");
}

async function subscriptionForEvent(event: Stripe.Event): Promise<Stripe.Subscription | null> {
  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
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

    const subscription = await subscriptionForEvent(event);
    if (!subscription) {
      await completeEvent(event.id, null, null, null, "ignored");
      return Response.json({ received: true, outcome: "ignored" });
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
