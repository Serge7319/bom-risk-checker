import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import Stripe from "https://esm.sh/stripe@16.12.0?target=deno";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

// The checkout handler reuses the Stripe key and service-role client already
// used by the deployed stripe-webhook. The price id is recovered from an
// existing paid order; it is an identifier, not a credential.
const EXISTING_REPORT_PRICE_ID = "price_1UNfUxR9wj2HxwgvlDkE0YZt";
const REPORT_LIMIT = 100;

const stripeSecret = Deno.env.get("STRIPE_SECRET_KEY");
const supabaseUrl = Deno.env.get("SUPABASE_URL");
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
if (!stripeSecret || !supabaseUrl || !serviceRoleKey) {
  throw new Error("One-time report backend configuration is incomplete.");
}

const stripe = new Stripe(stripeSecret, { apiVersion: "2024-06-20" });
const supabase = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});

type Action = "status" | "checkout" | "reserve" | "release" | "consume";

function response(body: unknown, status = 200, origin = "") {
  const allowed = new Set([
    "https://app.cadivor.com",
    "https://cadivor.com",
    "https://www.cadivor.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
  ]);
  const corsOrigin = allowed.has(origin) ? origin : "https://app.cadivor.com";
  return Response.json(body, {
    status,
    headers: {
      "Access-Control-Allow-Origin": corsOrigin,
      "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Cache-Control": "no-store",
      "Vary": "Origin",
    },
  });
}

function salesEnabled(): boolean {
  const flag = String(Deno.env.get("CADIVOR_ONE_TIME_BOM_REPORT_ENABLED") || "").trim().toLowerCase();
  return !["0", "false", "no", "off"].includes(flag);
}

async function verifiedUser(req: Request) {
  const authorization = req.headers.get("authorization") || "";
  const token = authorization.replace(/^Bearer\s+/i, "").trim();
  if (!token) return { user: null, status: 401 } as const;
  const { data, error } = await supabase.auth.getUser(token);
  if (error || !data.user?.id) return { user: null, status: 401 } as const;
  const emailConfirmed = Boolean(data.user.email_confirmed_at || data.user.confirmed_at);
  if (!emailConfirmed || !data.user.email) return { user: null, status: 403 } as const;
  return { user: data.user, status: 200 } as const;
}

async function verifiedPrice() {
  const configuredPriceId = String(
    Deno.env.get("STRIPE_ONE_TIME_BOM_REPORT_PRICE_ID") || EXISTING_REPORT_PRICE_ID,
  ).trim();
  const price = await stripe.prices.retrieve(configuredPriceId);
  if (
    !price.active || price.recurring || price.currency !== "usd" ||
    typeof price.unit_amount !== "number" || price.unit_amount < 1
  ) {
    throw new Error("The existing one-time report price is not active or valid.");
  }
  return price;
}

async function existingCheckout(userId: string) {
  const { data, error } = await supabase
    .from("cadivor_one_time_bom_orders")
    .select("id,stripe_session_id")
    .eq("user_id", userId)
    .eq("status", "pending")
    .order("created_at", { ascending: false })
    .limit(10);
  if (error) throw new Error("One-time report order history is unavailable.");
  for (const order of data || []) {
    if (!order.stripe_session_id) continue;
    try {
      const session = await stripe.checkout.sessions.retrieve(order.stripe_session_id);
      if (session.status === "open" && session.url) {
        return { state: "open", url: session.url };
      }
      if (session.status === "expired") {
        await supabase
          .from("cadivor_one_time_bom_orders")
          .update({ status: "expired" })
          .eq("id", order.id)
          .eq("user_id", userId)
          .eq("status", "pending");
      } else {
        return { state: "processing", url: "" };
      }
    } catch {
      return { state: "processing", url: "" };
    }
  }
  return null;
}

async function statusFor(userId: string) {
  const price = await verifiedPrice();
  const { data, error } = await supabase
    .from("cadivor_one_time_bom_orders")
    .select("id,status,created_at,paid_at,reserved_at,analysis_id")
    .eq("user_id", userId)
    .in("status", ["pending", "paid", "reserved", "consumed", "refunded"])
    .order("created_at", { ascending: false })
    .limit(10);
  if (error) throw new Error("One-time report order history is unavailable.");
  const orders = (data || []).map((order) => ({
    id: order.id,
    status: order.status,
    created_at: order.created_at,
    paid_at: order.paid_at,
    analysis_id: order.analysis_id,
  }));
  const availableCredit = orders.some((order) => order.status === "paid");
  const inProgress = orders.some((order) => order.status === "reserved");
  const openCheckout = await existingCheckout(userId);
  return {
    ok: true,
    enabled: salesEnabled(),
    price: { amount: price.unit_amount, currency: price.currency.toUpperCase() },
    available_credit: availableCredit,
    analysis_in_progress: inProgress,
    checkout: openCheckout,
    orders,
    max_components: REPORT_LIMIT,
  };
}

async function beginCheckout(user: { id: string; email: string }) {
  if (!salesEnabled()) return { status: 409, body: { ok: false, code: "checkout_disabled", detail: "One-time reports are temporarily unavailable." } };
  const open = await existingCheckout(user.id);
  if (open) return { status: 200, body: { ok: true, checkout: open } };

  const price = await verifiedPrice();
  const { data: created, error: insertError } = await supabase
    .from("cadivor_one_time_bom_orders")
    .insert({ user_id: user.id, price_id: price.id })
    .select("id")
    .single();
  if (insertError || !created?.id) {
    throw new Error("Could not create a secure one-time report order.");
  }

  let session: Stripe.Checkout.Session | null = null;
  try {
    const origin = "https://app.cadivor.com";
    session = await stripe.checkout.sessions.create(
      {
        mode: "payment",
        customer_email: user.email,
        customer_creation: "always",
        line_items: [{ price: price.id, quantity: 1 }],
        success_url: `${origin}/single-bom-report?checkout=success`,
        cancel_url: `${origin}/single-bom-report?checkout=cancel`,
        client_reference_id: created.id,
        metadata: {
          cadivor_product: "single_bom_report",
          cadivor_order_id: created.id,
          user_id: user.id,
        },
      },
      { idempotencyKey: `cadivor_single_bom_${created.id}` },
    );
    if (!session.id || !session.url) throw new Error("Stripe did not return a usable Checkout session.");
    const { data: linked, error: linkError } = await supabase
      .from("cadivor_one_time_bom_orders")
      .update({ stripe_session_id: session.id })
      .eq("id", created.id)
      .eq("user_id", user.id)
      .eq("status", "pending")
      .select("id");
    if (linkError || !linked?.length) throw new Error("Checkout could not be linked to its order.");
    return { status: 200, body: { ok: true, checkout: { state: "open", url: session.url } } };
  } catch {
    if (session?.id) {
      try { await stripe.checkout.sessions.expire(session.id); } catch { /* retain the primary error */ }
    }
    await supabase
      .from("cadivor_one_time_bom_orders")
      .update({ status: "expired" })
      .eq("id", created.id)
      .eq("user_id", user.id)
      .eq("status", "pending");
    throw new Error("Could not prepare secure checkout. No payment was taken. Please retry shortly.");
  }
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

async function reserveCredit(userId: string, analysisId: unknown) {
  if (!isUuid(analysisId)) return { status: 400, body: { ok: false, detail: "Analysis id must be a UUID." } };
  // v2 only recycles a stale reservation that never received an analysis id.
  // The older RPC checks the legacy Streamlit database for a saved analysis;
  // Next reports live in Railway Postgres, so that check would be unsafe here.
  const { data: orderId, error } = await supabase.rpc("cadivor_reserve_one_time_bom_order_v2", { p_user_id: userId });
  if (error || !orderId) return { status: 402, body: { ok: false, code: "payment_not_confirmed", detail: "No confirmed one-time report credit is available." } };
  const { data: attached, error: attachError } = await supabase.rpc("cadivor_attach_one_time_bom_analysis", {
    p_user_id: userId, p_order_id: orderId, p_analysis_id: analysisId,
  });
  if (attachError || attached !== true) {
    await supabase.rpc("cadivor_release_one_time_bom_order", { p_user_id: userId, p_order_id: orderId });
    return { status: 409, body: { ok: false, detail: "The paid report could not be reserved. Your credit remains available." } };
  }
  return { status: 200, body: { ok: true, order_id: orderId } };
}

async function releaseCredit(userId: string, orderId: unknown) {
  if (!isUuid(orderId)) return { status: 400, body: { ok: false, detail: "Order id must be a UUID." } };
  const { data, error } = await supabase.rpc("cadivor_release_one_time_bom_order", {
    p_user_id: userId, p_order_id: orderId,
  });
  return error || data !== true
    ? { status: 409, body: { ok: false, detail: "The report reservation could not be released." } }
    : { status: 200, body: { ok: true } };
}

async function consumeCredit(userId: string, orderId: unknown, analysisId: unknown) {
  if (!isUuid(orderId) || !isUuid(analysisId)) {
    return { status: 400, body: { ok: false, detail: "Order and analysis ids must be UUIDs." } };
  }
  // The Next API calls this only after its workspace-scoped report save
  // succeeds. The user JWT limits the operation to the caller's own order.
  const { data, error } = await supabase
    .from("cadivor_one_time_bom_orders")
    .update({ status: "consumed", analysis_id: analysisId, consumed_at: new Date().toISOString() })
    .eq("id", orderId)
    .eq("user_id", userId)
    .eq("status", "reserved")
    .eq("analysis_id", analysisId)
    .select("id");
  if (error) return { status: 503, body: { ok: false, detail: "The saved report needs payment reconciliation." } };
  if (data?.length) return { status: 200, body: { ok: true } };
  const { data: prior, error: priorError } = await supabase
    .from("cadivor_one_time_bom_orders")
    .select("id")
    .eq("id", orderId)
    .eq("user_id", userId)
    .eq("status", "consumed")
    .eq("analysis_id", analysisId)
    .limit(1);
  return !priorError && prior?.length
    ? { status: 200, body: { ok: true, duplicate: true } }
    : { status: 409, body: { ok: false, detail: "The paid report reservation does not match this analysis." } };
}

serve(async (req) => {
  const origin = req.headers.get("origin") || "";
  if (req.method === "OPTIONS") return response({}, 200, origin);
  if (req.method !== "POST") return response({ detail: "Method not allowed." }, 405, origin);

  const auth = await verifiedUser(req);
  if (!auth.user) {
    return response({ detail: auth.status === 403 ? "Verify your email before purchasing a report." : "Unauthorized." }, auth.status, origin);
  }
  let body: { action?: Action; [key: string]: unknown };
  try {
    body = await req.json();
  } catch {
    return response({ detail: "Invalid JSON." }, 400, origin);
  }

  try {
    if (body.action === "status") return response(await statusFor(auth.user.id), 200, origin);
    if (body.action === "checkout") {
      const result = await beginCheckout({ id: auth.user.id, email: auth.user.email! });
      return response(result.body, result.status, origin);
    }
    if (body.action === "reserve") {
      const result = await reserveCredit(auth.user.id, body.analysis_id);
      return response(result.body, result.status, origin);
    }
    if (body.action === "release") {
      const result = await releaseCredit(auth.user.id, body.order_id);
      return response(result.body, result.status, origin);
    }
    if (body.action === "consume") {
      const result = await consumeCredit(auth.user.id, body.order_id, body.analysis_id);
      return response(result.body, result.status, origin);
    }
    return response({ detail: "Unknown one-time report action." }, 400, origin);
  } catch (error) {
    console.error("One-time report action failed", {
      action: String(body.action || "unknown"),
      errorType: error instanceof Error ? error.name : "unknown",
    });
    return response({ ok: false, detail: "One-time report service is temporarily unavailable." }, 503, origin);
  }
});
