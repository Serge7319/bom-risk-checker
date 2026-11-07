import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import Stripe from "https://esm.sh/stripe@16.12.0?target=deno";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

const stripeSecret = Deno.env.get("STRIPE_SECRET_KEY");
const supabaseUrl = Deno.env.get("SUPABASE_URL");
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
if (!stripeSecret || !supabaseUrl || !serviceRoleKey) {
  throw new Error("Subscription billing configuration is incomplete.");
}

const stripe = new Stripe(stripeSecret, { apiVersion: "2024-06-20" });
const supabase = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});

const planPrices = [
  { name: "Starter", token: "starter", env: "STRIPE_STARTER_PRICE_ID", expected: 2900 },
  { name: "Professional", token: "professional", env: "STRIPE_PRO_PRICE_ID", expected: 9900 },
  { name: "Business", token: "business", env: "STRIPE_BUSINESS_PRICE_ID", expected: 29900 },
] as const;

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

function siteOrigin(request: Request): string {
  const allowed = new Set([
    "https://app.cadivor.com",
    "https://cadivor.com",
    "https://www.cadivor.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
  ]);
  const supplied = request.headers.get("origin") || "";
  return allowed.has(supplied) ? supplied : "https://app.cadivor.com";
}

async function verifiedUser(request: Request) {
  const token = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "").trim();
  if (!token) return { user: null, status: 401 } as const;
  const { data, error } = await supabase.auth.getUser(token);
  if (error || !data.user?.id) return { user: null, status: 401 } as const;
  if (!data.user.email || !(data.user.email_confirmed_at || data.user.confirmed_at)) {
    return { user: null, status: 403 } as const;
  }
  return { user: data.user, status: 200 } as const;
}

async function profileFor(userId: string) {
  const { data, error } = await supabase
    .from("users")
    .select("plan,role,trial_started_at,trial_ends_at,plan_grandfather_source,stripe_customer_id,stripe_subscription_id,stripe_subscription_status")
    .eq("id", userId)
    .maybeSingle();
  if (error) throw new Error("Billing profile could not be loaded.");
  return data || {};
}

function effectivePlan(profile: Record<string, unknown>, now = new Date()): {
  plan: string;
  trial_status: string | null;
  trial_days_remaining: number | null;
} {
  const role = String(profile.role || "").trim().toLowerCase();
  const stored = String(profile.plan || "").trim().toLowerCase();
  const billingStatus = String(profile.stripe_subscription_status || "").trim().toLowerCase();
  const grandfathered = Boolean(String(profile.plan_grandfather_source || "").trim());

  if (role === "admin" || stored === "enterprise" || stored === "admin") {
    return { plan: "Enterprise", trial_status: null, trial_days_remaining: null };
  }
  if (stored === "student") {
    return { plan: "Student", trial_status: null, trial_days_remaining: null };
  }
  if (stored === "trial" || stored === "free trial") {
    const endValue = profile.trial_ends_at;
    const end = endValue ? new Date(String(endValue)) : null;
    if (end && !Number.isNaN(end.getTime()) && end <= now) {
      return { plan: "Trial expired", trial_status: "trial_expired", trial_days_remaining: 0 };
    }
    const days = end && !Number.isNaN(end.getTime())
      ? Math.max(0, Math.ceil((end.getTime() - now.getTime()) / 86_400_000))
      : null;
    return { plan: "Trial", trial_status: "trialing", trial_days_remaining: days };
  }
  if (stored === "trial expired" || stored === "expired trial") {
    return { plan: "Trial expired", trial_status: "trial_expired", trial_days_remaining: 0 };
  }
  const paidPlan = planPrices.find((item) => item.name.toLowerCase() === stored);
  if (paidPlan && ["active", "trialing"].includes(billingStatus)) {
    return { plan: paidPlan.name, trial_status: null, trial_days_remaining: null };
  }
  if (grandfathered && ["free", "beta", "beta access", "grandfathered", "grandfathered beta", "starter", "professional", "business"].includes(stored)) {
    return { plan: "Grandfathered beta", trial_status: null, trial_days_remaining: null };
  }
  return { plan: "Subscription inactive", trial_status: null, trial_days_remaining: null };
}

function entitlementSnapshot(profile: Record<string, unknown>) {
  const effective = effectivePlan(profile);
  return {
    ok: true,
    plan: effective.plan,
    role: String(profile.role || "user"),
    trial_started_at: effective.plan === "Trial" ? profile.trial_started_at || null : null,
    trial_ends_at: effective.plan === "Trial" ? profile.trial_ends_at || null : null,
    trial_status: effective.trial_status,
    trial_days_remaining: effective.trial_days_remaining,
  };
}

async function priceCatalog() {
  const rows = [];
  for (const plan of planPrices) {
    const id = String(Deno.env.get(plan.env) || "").trim();
    if (!id) {
      rows.push({ name: plan.name, token: plan.token, configured: false, enabled: false });
      continue;
    }
    try {
      const price = await stripe.prices.retrieve(id);
      const valid = Boolean(
        price.active &&
          price.currency === "usd" &&
          price.recurring?.interval === "month" &&
          typeof price.unit_amount === "number" &&
          price.unit_amount > 0,
      );
      rows.push({
        name: plan.name,
        token: plan.token,
        configured: true,
        enabled: valid && price.unit_amount === plan.expected,
        price_matches_catalog: valid && price.unit_amount === plan.expected,
        amount: valid ? price.unit_amount : null,
        currency: valid ? price.currency : null,
        interval: valid ? price.recurring?.interval : null,
      });
    } catch {
      rows.push({ name: plan.name, token: plan.token, configured: true, enabled: false, price_matches_catalog: false });
    }
  }
  return rows;
}

async function createPortal(profile: Record<string, unknown>, origin: string) {
  const customer = String(profile.stripe_customer_id || "").trim();
  if (!customer) return { ok: false, code: "billing_customer_missing", detail: "No subscription is linked to this account." };
  const session = await stripe.billingPortal.sessions.create({
    customer,
    return_url: `${origin}/settings?billing=returned`,
  });
  return { ok: true, checkout: { state: "open", url: session.url } };
}

serve(async (request) => {
  const origin = siteOrigin(request);
  if (request.method === "OPTIONS") return response({ ok: true }, 200, origin);
  if (request.method !== "POST") return response({ ok: false, detail: "Method not allowed." }, 405, origin);

  const auth = await verifiedUser(request);
  if (!auth.user) return response({ ok: false, detail: "Sign in with a verified Cadivor account." }, auth.status, origin);

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return response({ ok: false, detail: "Invalid request." }, 400, origin);
  }
  const action = String(body.action || "").trim().toLowerCase();
  try {
    const profile = await profileFor(auth.user.id);

    if (action === "entitlements") {
      return response(entitlementSnapshot(profile), 200, origin);
    }

    if (action === "status") {
      const plans = await priceCatalog();
      const checkoutEnabled = plans.some((plan) => plan.enabled);
      const active = ["active", "trialing"].includes(String(profile.stripe_subscription_status || "").toLowerCase());
      return response({
        ok: true,
        current_plan: effectivePlan(profile).plan,
        checkout_enabled: checkoutEnabled,
        stripe_mode: stripeSecret.startsWith("sk_live_") ? "live" : stripeSecret.startsWith("sk_test_") ? "test" : "unknown",
        charges_created: false,
        subscription_status: profile.stripe_subscription_status || null,
        has_active_subscription: active,
        can_manage_billing: Boolean(active && profile.stripe_customer_id),
        plans,
      }, 200, origin);
    }

    if (String(profile.role || "").toLowerCase() === "admin") {
      return response({ ok: false, detail: "Workspace administrators cannot purchase an individual subscription." }, 403, origin);
    }

    if (action === "portal") {
      const portal = await createPortal(profile, origin);
      return response(portal, portal.ok ? 200 : 409, origin);
    }

    if (action !== "checkout") return response({ ok: false, detail: "Unknown billing action." }, 400, origin);
    const token = String(body.plan || "").trim().toLowerCase();
    const plan = planPrices.find((item) => item.token === token);
    if (!plan) return response({ ok: false, detail: "Choose Starter, Professional, or Business." }, 400, origin);

    const status = String(profile.stripe_subscription_status || "").toLowerCase();
    if (["active", "trialing"].includes(status) && profile.stripe_customer_id) {
      return response({
        ok: false,
        code: "manage_existing_subscription",
        detail: "Manage or change your current plan through secure billing settings.",
      }, 409, origin);
    }

    const priceId = String(Deno.env.get(plan.env) || "").trim();
    if (!priceId) return response({ ok: false, detail: "This plan is temporarily unavailable for purchase." }, 503, origin);
    const price = await stripe.prices.retrieve(priceId);
    if (!price.active || price.currency !== "usd" || price.recurring?.interval !== "month" || price.unit_amount !== plan.expected) {
      return response({ ok: false, detail: "This plan's billing details need review. Contact Cadivor support." }, 503, origin);
    }

    const metadata = { user_id: auth.user.id, cadivor_plan: token };
    const customerId = String(profile.stripe_customer_id || "").trim();
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      ...(customerId ? { customer: customerId } : { customer_email: auth.user.email! }),
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: `${origin}/settings?billing=success`,
      cancel_url: `${origin}/settings?billing=cancel`,
      client_reference_id: auth.user.id,
      metadata,
      subscription_data: { metadata },
    });
    if (!session.url) throw new Error("Stripe did not return a checkout link.");
    return response({ ok: true, checkout: { state: "open", url: session.url } }, 200, origin);
  } catch {
    return response({ ok: false, detail: "Billing could not be started. Please try again or contact support." }, 503, origin);
  }
});
