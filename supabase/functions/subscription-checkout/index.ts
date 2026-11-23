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
  { name: "Starter", token: "starter", env: "STRIPE_STARTER_PRICE_ID", annualEnv: "STRIPE_STARTER_ANNUAL_PRICE_ID", expected: 2900 },
  { name: "Professional", token: "professional", env: "STRIPE_PRO_PRICE_ID", annualEnv: "STRIPE_PRO_ANNUAL_PRICE_ID", expected: 9900 },
  { name: "Business", token: "business", env: "STRIPE_BUSINESS_PRICE_ID", annualEnv: "STRIPE_BUSINESS_ANNUAL_PRICE_ID", expected: 29900 },
] as const;

const internalActions = new Set([
  "developer_api_keys_list",
  "developer_api_key_create",
  "developer_api_key_revoke",
  "reserve_usage_credit",
  "finish_usage_credit",
  "allocate_monitored_part_credits",
]);

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

type StripeErrorSummary = {
  type?: string;
  code?: string;
  statusCode?: number;
  requestId?: string;
  param?: string;
  message?: string;
};

function stripeErrorSummary(error: unknown): StripeErrorSummary {
  if (!error || typeof error !== "object") return {};
  const value = error as Record<string, unknown>;
  return {
    type: typeof value.type === "string" ? value.type : undefined,
    code: typeof value.code === "string" ? value.code : undefined,
    statusCode: typeof value.statusCode === "number" ? value.statusCode : undefined,
    requestId: typeof value.requestId === "string" ? value.requestId : undefined,
    param: typeof value.param === "string" ? value.param : undefined,
    // Stripe messages are useful for support, but never sent to the browser.
    message: typeof value.message === "string" ? value.message.slice(0, 240) : undefined,
  };
}

function marketingAttribution(user: { user_metadata?: unknown }): Record<string, string> {
  const metadata = user.user_metadata && typeof user.user_metadata === "object"
    ? user.user_metadata as Record<string, unknown>
    : {};
  const supplied = metadata.cadivor_marketing_attribution && typeof metadata.cadivor_marketing_attribution === "object"
    ? metadata.cadivor_marketing_attribution as Record<string, unknown>
    : {};
  const result: Record<string, string> = {};
  for (const key of ["utm_source", "utm_medium", "utm_campaign", "utm_content"]) {
    const value = typeof supplied[key] === "string" ? supplied[key].trim().slice(0, 80) : "";
    if (value && !value.includes("@") && /^[\w .:+~/=-]{1,80}$/u.test(value)) result[key] = value;
  }
  return result;
}

function isMissingStripeCustomer(error: unknown): boolean {
  const summary = stripeErrorSummary(error);
  return summary.code === "resource_missing" && (
    summary.param === "customer" || /no such customer/i.test(summary.message || "")
  );
}

function isMissingStripeSubscription(error: unknown): boolean {
  const summary = stripeErrorSummary(error);
  return summary.code === "resource_missing" && (
    summary.param === "id" || /no such subscription/i.test(summary.message || "")
  );
}

function checkoutSessionParams(
  origin: string,
  userId: string,
  email: string,
  token: string,
  priceId: string,
  billingInterval: "month" | "year",
  customerId?: string,
  attribution: Record<string, string> = {},
) {
  const metadata = {
    user_id: userId,
    cadivor_plan: token,
    cadivor_billing_interval: billingInterval,
    ...attribution,
  };
  return {
    mode: "subscription" as const,
    ...(customerId ? { customer: customerId } : { customer_email: email }),
    line_items: [{ price: priceId, quantity: 1 }],
    success_url: `${origin}/settings?billing=success`,
    cancel_url: `${origin}/settings?billing=cancel`,
    client_reference_id: userId,
    metadata,
    subscription_data: { metadata },
  };
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

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0);
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined) throw new Error("Invalid internal action payload.");
  return encoded;
}

async function verifyInternalActionProof(
  action: string,
  userId: string,
  body: Record<string, unknown>,
): Promise<boolean> {
  try {
    const supplied = String(body._cadivor_internal_proof || "").trim();
    if (!/^[0-9a-f]{64}$/i.test(supplied)) return false;
    const payload = Object.fromEntries(
      Object.entries(body).filter(([key]) => key !== "action" && key !== "_cadivor_internal_proof"),
    );
    const workspaceId = String(payload.workspace_id || "").trim();
    if (!workspaceId) return false;
    const message = `${action}\n${userId}\n${workspaceId}\n${canonicalJson(payload)}`;
    const key = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(serviceRoleKey!),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["verify"],
    );
    const signature = Uint8Array.from(supplied.match(/.{2}/g) || [], (pair) => Number.parseInt(pair, 16));
    return await crypto.subtle.verify("HMAC", key, signature, new TextEncoder().encode(message));
  } catch {
    return false;
  }
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

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function accountIsSuspended(userId: string): Promise<boolean> {
  const [controls, profile, pending] = await Promise.all([
    supabase.from("admin_user_controls").select("account_status").eq("user_id", userId).maybeSingle(),
    supabase.from("users").select("id").eq("id", userId).maybeSingle(),
    supabase.from("admin_account_deletion_pending").select("user_id").eq("user_id", userId).maybeSingle(),
  ]);
  if (controls.error || profile.error || pending.error) {
    throw new Error("Account access could not be checked.");
  }
  return !profile.data ||
    Boolean(pending.data) ||
    String(controls.data?.account_status || "active").toLowerCase() === "suspended";
}

type AdminDeletionTarget = {
  ok: true;
  userId: string;
  email: string;
  role: string;
  authUser: { id: string; email?: string } | null;
  pending: boolean;
};

async function validateAdminDeletionTarget(
  actorId: string,
  body: Record<string, unknown>,
): Promise<AdminDeletionTarget | { ok: false; status: number; detail: string }> {
  const actorProfile = await profileFor(actorId);
  if (String(actorProfile.role || "").trim().toLowerCase() !== "admin") {
    return { ok: false, status: 403, detail: "Platform administrator access is required." };
  }
  const userId = String(body.target_user_id || "").trim();
  if (!UUID_PATTERN.test(userId)) {
    return { ok: false, status: 400, detail: "Choose a valid account." };
  }
  if (userId === actorId) {
    return { ok: false, status: 409, detail: "Administrators cannot delete their own account." };
  }
  const confirmationEmail = String(body.confirmation_email || "").trim().toLowerCase();
  const { data: targetProfile, error: profileError } = await supabase
    .from("users")
    .select("email,role")
    .eq("id", userId)
    .maybeSingle();
  if (profileError) throw new Error("Account could not be checked.");
  if (!targetProfile) return { ok: false, status: 404, detail: "Account not found." };

  const { data: authResult, error: authError } = await supabase.auth.admin.getUserById(userId);
  const authUser = authResult?.user
    ? { id: authResult.user.id, email: authResult.user.email || undefined }
    : null;
  const status = Number((authError as unknown as Record<string, unknown> | null)?.status || 0);
  const missingAuthUser = Boolean(authError && status === 404);
  if (authError && !missingAuthUser) throw new Error("Account authentication could not be checked.");

  const { data: pendingMarker, error: controlsError } = await supabase
    .from("admin_account_deletion_pending")
    .select("user_id")
    .eq("user_id", userId)
    .maybeSingle();
  if (controlsError) throw new Error("Account status could not be checked.");
  const pending = !authUser && Boolean(pendingMarker);
  if (!authUser && !pending) {
    return { ok: false, status: 404, detail: "Account not found." };
  }

  const email = String(authUser?.email || targetProfile.email || "").trim().toLowerCase();
  if (!email || !confirmationEmail || confirmationEmail !== email) {
    return { ok: false, status: 409, detail: "Type the account’s exact email address to confirm deletion." };
  }
  const role = String(targetProfile.role || "").trim().toLowerCase();
  if (role === "admin") {
    const { data: adminProfiles, error: adminError } = await supabase
      .from("users")
      .select("id")
      .ilike("role", "admin");
    if (adminError) throw new Error("Administrator access could not be checked.");
    const adminIds = (adminProfiles || []).map((row) => String(row.id));
    if (adminIds.includes(userId)) {
      const [controlsResult, pendingResult] = await Promise.all([
        supabase.from("admin_user_controls").select("user_id,account_status").in("user_id", adminIds),
        supabase.from("admin_account_deletion_pending").select("user_id").in("user_id", adminIds),
      ]);
      if (controlsResult.error || pendingResult.error) {
        throw new Error("Administrator access could not be checked.");
      }
      const controlsById = new Map<string, string>(
        (controlsResult.data || []).map((row): [string, string] => [
          String(row.user_id),
          String(row.account_status || "active").toLowerCase(),
        ]),
      );
      const pendingIds = new Set<string>((pendingResult.data || []).map((row) => String(row.user_id)));
      const targetIsActiveAdmin = !pendingIds.has(userId) &&
        (controlsById.get(userId) || "active") === "active";
      const otherActiveAdmins = adminIds.filter((adminId) => adminId !== userId &&
        !pendingIds.has(adminId) && (controlsById.get(adminId) || "active") === "active");
      if (targetIsActiveAdmin && otherActiveAdmins.length === 0) {
        return { ok: false, status: 409, detail: "Cadivor must retain at least one active administrator." };
      }
    }
  }
  return { ok: true, userId, email, role, authUser, pending };
}

function clearedStripeMetadata(metadata: Record<string, string> | null | undefined) {
  const result: Record<string, string> = {};
  for (const key of Object.keys(metadata || {})) result[key] = "";
  result.cadivor_deleted_account = "true";
  return result;
}

async function cancelAndAnonymizeBilling(targetUserId: string, profile: Record<string, unknown>) {
  const { data: addon, error: addonError } = await supabase
    .from("cadivor_professional_api_addons")
    .select("subscription_id")
    .eq("user_id", targetUserId)
    .maybeSingle();
  if (addonError) throw new Error("Subscription records could not be loaded.");

  const subscriptionIds = new Set<string>();
  for (const value of [profile.stripe_subscription_id, addon?.subscription_id]) {
    const id = String(value || "").trim();
    if (id) subscriptionIds.add(id);
  }
  for (const id of subscriptionIds) {
    try {
      const subscription = await stripe.subscriptions.retrieve(id);
      await stripe.subscriptions.update(id, {
        metadata: clearedStripeMetadata(subscription.metadata),
      });
      if (!['canceled', 'incomplete_expired'].includes(subscription.status)) {
        await stripe.subscriptions.cancel(id);
      }
    } catch (error) {
      const summary = stripeErrorSummary(error);
      if (summary.code === "resource_missing") continue;
      throw error;
    }
  }

  const customerId = String(profile.stripe_customer_id || "").trim();
  if (customerId) {
    try {
      const customer = await stripe.customers.retrieve(customerId);
      if (!("deleted" in customer && customer.deleted)) {
        await stripe.customers.update(customerId, {
          email: "",
          name: "",
          phone: "",
          description: "",
          address: { city: "", country: "", line1: "", line2: "", postal_code: "", state: "" },
          metadata: clearedStripeMetadata(customer.metadata),
        });
      }
    } catch (error) {
      const summary = stripeErrorSummary(error);
      if (summary.code !== "resource_missing") throw error;
    }
  }
}


function positiveUnits(name: string): number | null {
  const raw = String(Deno.env.get(name) || "").trim();
  if (!/^\d+$/.test(raw)) return null;
  const units = Number(raw);
  return Number.isSafeInteger(units) && units > 0 && units <= 100_000 ? units : null;
}

async function configuredPrice(
  envName: string,
  type: "one_time" | "recurring",
  interval?: "month",
): Promise<{ configured: boolean; enabled: boolean; amount: number | null; currency: string | null; interval: string | null }> {
  const id = String(Deno.env.get(envName) || "").trim();
  const empty = { configured: Boolean(id), enabled: false, amount: null, currency: null, interval: null };
  if (!id) return empty;
  try {
    const price = await stripe.prices.retrieve(id);
    const valid = price.active && price.currency === "usd" &&
      typeof price.unit_amount === "number" && price.unit_amount > 0 &&
      (type === "one_time"
        ? !price.recurring
        : Boolean(price.recurring && price.recurring.interval === interval));
    return {
      configured: true,
      enabled: valid,
      amount: valid ? price.unit_amount : null,
      currency: valid ? price.currency : null,
      interval: valid ? (price.recurring?.interval || "one_time") : null,
    };
  } catch {
    return empty;
  }
}

async function addonCatalog() {
  const analysisCredits = positiveUnits("CADIVOR_BOM_ANALYSIS_OVERAGE_CREDITS");
  const monitoredParts = positiveUnits("CADIVOR_MONITORED_PARTS_OVERAGE_CREDITS");
  const [analysisPrice, monitoredPrice, apiPrice] = await Promise.all([
    configuredPrice("STRIPE_BOM_ANALYSIS_OVERAGE_PRICE_ID", "one_time"),
    configuredPrice("STRIPE_MONITORED_PARTS_OVERAGE_PRICE_ID", "one_time"),
    configuredPrice("STRIPE_PROFESSIONAL_API_ADDON_PRICE_ID", "recurring", "month"),
  ]);
  return {
    bom_analysis: { ...analysisPrice, enabled: analysisPrice.enabled && analysisCredits !== null, credits: analysisCredits },
    monitored_parts: { ...monitoredPrice, enabled: monitoredPrice.enabled && monitoredParts !== null, credits: monitoredParts },
    professional_api: apiPrice,
  };
}

async function apiAddonFor(userId: string) {
  const { data, error } = await supabase
    .from("cadivor_professional_api_addons")
    .select("subscription_id,status,price_id")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) throw new Error("API add-on status could not be loaded.");
  const active = ["active", "trialing"].includes(String(data?.status || "").toLowerCase());
  return { active, subscription_id: active ? data?.subscription_id || null : null };
}

async function apiAccessEnabled(userId: string, profile: Record<string, unknown>): Promise<boolean> {
  const { data: override, error } = await supabase
    .from("cadivor_api_access_overrides")
    .select("enabled")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) throw new Error("API access entitlement could not be loaded.");
  if (typeof override?.enabled === "boolean") return override.enabled;
  const plan = effectivePlan(profile).plan;
  if (["Trial", "Business", "Enterprise"].includes(plan)) return true;
  if (plan === "Professional") return (await apiAddonFor(userId)).active;
  return false;
}

function newDeveloperApiKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const base64 = btoa(String.fromCharCode(...bytes))
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
  return `cdv_live_${base64}`;
}

async function hashDeveloperApiKey(apiKey: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(apiKey));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function resolveDeveloperApiKey(apiKey: string) {
  if (!apiKey.startsWith("cdv_live_") || apiKey.length < 48 || apiKey.length > 100) {
    return response({ ok: false, detail: "API key is invalid or revoked." }, 401);
  }
  const keyHash = await hashDeveloperApiKey(apiKey);
  const { data, error } = await supabase
    .from("cadivor_developer_api_keys")
    .select("id,user_id,workspace_id,revoked_at")
    .eq("key_hash", keyHash)
    .is("revoked_at", null)
    .maybeSingle();
  if (error) throw new Error("Developer API key could not be checked.");
  if (!data?.user_id || !data?.workspace_id) {
    return response({ ok: false, detail: "API key is invalid or revoked." }, 401);
  }
  const profile = await profileFor(String(data.user_id));
  if (!(await apiAccessEnabled(String(data.user_id), profile))) {
    return response({ ok: false, detail: "Developer API access is not active for this account." }, 403);
  }
  const effective = effectivePlan(profile);
  const apiAddon = await apiAddonFor(String(data.user_id));
  const { error: touchError } = await supabase
    .from("cadivor_developer_api_keys")
    .update({ last_used_at: new Date().toISOString() })
    .eq("id", data.id)
    .is("revoked_at", null);
  if (touchError) throw new Error("Developer API key usage could not be recorded.");
  return response({
    ok: true,
    key_id: data.id,
    user_id: data.user_id,
    workspace_id: data.workspace_id,
    plan: effective.plan,
    trial_status: effective.trial_status,
    api_access_addon_active: apiAddon.active,
  });
}

async function usageCreditsFor(userId: string) {
  const { data, error } = await supabase
    .from("cadivor_usage_credit_balances")
    .select("credit_kind,credits")
    .eq("user_id", userId);
  if (error) throw new Error("Usage credits could not be loaded.");
  const credits = { bom_analysis: 0, monitored_part: 0 };
  for (const row of data || []) {
    if (row.credit_kind === "bom_analysis" || row.credit_kind === "monitored_part") {
      credits[row.credit_kind] = Math.max(0, Number(row.credits) || 0);
    }
  }
  return credits;
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

async function entitlementSnapshot(userId: string, profile: Record<string, unknown>) {
  const effective = effectivePlan(profile);
  const [apiAddon, usageCredits] = await Promise.all([
    apiAddonFor(userId),
    usageCreditsFor(userId),
  ]);
  return {
    ok: true,
    plan: effective.plan,
    role: String(profile.role || "user"),
    trial_started_at: effective.plan === "Trial" ? profile.trial_started_at || null : null,
    trial_ends_at: effective.plan === "Trial" ? profile.trial_ends_at || null : null,
    trial_status: effective.trial_status,
    trial_days_remaining: effective.trial_days_remaining,
    api_access_addon_active: apiAddon.active,
    usage_credits: usageCredits,
  };
}

async function priceCatalog() {
  const rows: Array<Record<string, unknown>> = [];
  for (const plan of planPrices) {
    const id = String(Deno.env.get(plan.env) || "").trim();
    let monthly: Record<string, unknown> = {
      configured: Boolean(id),
      enabled: false,
      amount: null,
      currency: null,
      interval: null,
      price_matches_catalog: false,
    };
    let expectedMonthly: number | null = null;
    try {
      if (!id) throw new Error("monthly price not configured");
      const price = await stripe.prices.retrieve(id);
      const valid = Boolean(
        price.active &&
          price.currency === "usd" &&
          price.recurring?.interval === "month" &&
          typeof price.unit_amount === "number" &&
          price.unit_amount > 0,
      );
      expectedMonthly = valid && price.unit_amount === plan.expected ? price.unit_amount : null;
      monthly = {
        configured: true,
        enabled: valid && price.unit_amount === plan.expected,
        price_matches_catalog: valid && price.unit_amount === plan.expected,
        amount: valid ? price.unit_amount : null,
        currency: valid ? price.currency : null,
        interval: valid ? price.recurring?.interval : null,
      };
    } catch {
      monthly = { ...monthly, configured: Boolean(id) };
    }

    const annualId = String(Deno.env.get(plan.annualEnv) || "").trim();
    let annual: Record<string, unknown> = {
      configured: Boolean(annualId), enabled: false, amount: null,
      currency: null, interval: null, discount_percent: null,
    };
    try {
      if (!annualId) throw new Error("annual price not configured");
      const price = await stripe.prices.retrieve(annualId);
      const valid = Boolean(
        price.active && price.currency === "usd" &&
          price.recurring?.interval === "year" &&
          typeof price.unit_amount === "number" && price.unit_amount > 0,
      );
      const discounted = Boolean(
        valid && expectedMonthly !== null &&
          price.unit_amount! < expectedMonthly * 12,
      );
      annual = {
        configured: true,
        enabled: discounted,
        amount: valid ? price.unit_amount : null,
        currency: valid ? price.currency : null,
        interval: valid ? price.recurring?.interval : null,
        discount_percent: discounted
          ? Math.round((1 - price.unit_amount! / (expectedMonthly! * 12)) * 1000) / 10
          : null,
      };
    } catch {
      annual = { ...annual, configured: Boolean(annualId) };
    }
    rows.push({
      name: plan.name,
      token: plan.token,
      ...monthly,
      annual,
    });
  }
  return rows;
}

async function createPortal(
  profile: Record<string, unknown>,
  userId: string,
  origin: string,
  supportReference: string,
) {
  const savedSubscriptionId = String(profile.stripe_subscription_id || "").trim();
  const returnUrl = `${origin}/settings?billing=returned`;
  const failure = (code: string, detail: string) => ({
    ok: false,
    code,
    detail,
    support_reference: supportReference,
  });
  const customerIdFor = (subscription: Stripe.Subscription) =>
    typeof subscription.customer === "string"
      ? subscription.customer
      : subscription.customer?.id || "";
  const isManageableSubscription = (subscription: Stripe.Subscription | null) =>
    Boolean(
      subscription &&
      String(subscription.metadata?.user_id || "").trim() === userId &&
      ["active", "trialing"].includes(subscription.status) &&
      customerIdFor(subscription),
    );
  const createPortalSession = async (customerId: string) => {
    const session = await stripe.billingPortal.sessions.create({
      customer: customerId,
      return_url: returnUrl,
    });
    return { ok: true, checkout: { state: "open", url: session.url } };
  };

  let subscription: Stripe.Subscription | null = null;
  if (savedSubscriptionId) {
    try {
      subscription = await stripe.subscriptions.retrieve(savedSubscriptionId);
    } catch (error) {
      const summary = stripeErrorSummary(error);
      if (!isMissingStripeSubscription(error)) {
        console.error("billing_portal_subscription_recovery_failed", {
          reference: supportReference,
          error_type: summary.type,
          error_code: summary.code,
          error_status: summary.statusCode,
          error_param: summary.param,
          stripe_request_id: summary.requestId,
        });
        return failure(
          "billing_subscription_unverified",
          "Cadivor couldn't verify the subscription linked to this account. No billing changes were made. Contact support and provide this reference.",
        );
      }
      console.warn("billing_portal_saved_subscription_missing", {
        reference: supportReference,
        error_code: summary.code,
        error_param: summary.param,
        stripe_request_id: summary.requestId,
      });
    }
  }

  if (!isManageableSubscription(subscription)) {
    const matches: Stripe.Subscription[] = [];
    try {
      for (const status of ["active", "trialing"] as const) {
        const result = await stripe.subscriptions.search({
          query: "status:'" + status + "' AND metadata['user_id']:'" + userId + "'",
          limit: 2,
        });
        matches.push(...result.data);
        if (matches.length > 1) break;
      }
    } catch (error) {
      const summary = stripeErrorSummary(error);
      console.error("billing_portal_subscription_search_failed", {
        reference: supportReference,
        error_type: summary.type,
        error_code: summary.code,
        error_status: summary.statusCode,
        error_param: summary.param,
        stripe_request_id: summary.requestId,
      });
      return failure(
        "billing_subscription_unverified",
        "Cadivor couldn't verify the subscription linked to this account. No billing changes were made. Contact support and provide this reference.",
      );
    }

    const uniqueMatches = [...new Map(matches.map((item) => [item.id, item])).values()];
    if (uniqueMatches.length === 0) {
      console.error("billing_portal_active_subscription_not_found", {
        reference: supportReference,
        saved_subscription_missing: Boolean(savedSubscriptionId),
      });
      return failure(
        "billing_subscription_not_found",
        "Stripe couldn't find an active subscription for this account. Cadivor hasn't started a replacement subscription or changed billing. Contact support and provide this reference.",
      );
    }
    if (uniqueMatches.length !== 1 || !isManageableSubscription(uniqueMatches[0])) {
      console.error("billing_portal_subscription_search_ambiguous", {
        reference: supportReference,
        match_count: uniqueMatches.length,
      });
      return failure(
        "billing_subscription_ambiguous",
        "Stripe found multiple or unverified subscriptions for this account. Cadivor hasn't changed billing. Contact support and provide this reference.",
      );
    }
    subscription = uniqueMatches[0];
    console.info("billing_portal_subscription_recovered_by_user_metadata", {
      reference: supportReference,
      subscription_status: subscription.status,
    });
  }

  if (!subscription || !isManageableSubscription(subscription)) {
    console.error("billing_portal_subscription_recovery_rejected", {
      reference: supportReference,
      owner_matches: Boolean(subscription && String(subscription.metadata?.user_id || "").trim() === userId),
      subscription_status: subscription?.status || null,
      has_customer: Boolean(subscription && customerIdFor(subscription)),
    });
    return failure(
      "billing_subscription_unverified",
      "Cadivor couldn't verify the active subscription linked to this account. No billing changes were made. Contact support and provide this reference.",
    );
  }

  const recoveredCustomer = customerIdFor(subscription);
  let portal;
  try {
    portal = await createPortalSession(recoveredCustomer);
  } catch (error) {
    if (!isMissingStripeCustomer(error)) throw error;
    console.error("billing_portal_recovered_customer_missing", {
      reference: supportReference,
      stripe_request_id: stripeErrorSummary(error).requestId,
    });
    return failure(
      "billing_customer_link_invalid",
      "Stripe couldn't find the customer attached to this active subscription. Cadivor hasn't changed billing. Contact support and provide this reference.",
    );
  }

  const { data: repairedProfile, error: repairError } = await supabase
    .from("users")
    .update({
      stripe_customer_id: recoveredCustomer,
      stripe_subscription_id: subscription.id,
      stripe_subscription_status: subscription.status,
    })
    .eq("id", userId)
    .eq("stripe_subscription_id", savedSubscriptionId)
    .select("id")
    .maybeSingle();
  if (repairError || !repairedProfile) {
    console.error("billing_portal_customer_link_repair_failed", {
      reference: supportReference,
      error_code: repairError?.code || null,
      profile_matched: Boolean(repairedProfile),
    });
  } else {
    console.info("billing_portal_customer_link_repaired", {
      reference: supportReference,
      recovered_subscription: subscription.id !== savedSubscriptionId,
    });
  }
  return portal;
}

serve(async (request) => {
  const origin = siteOrigin(request);
  if (request.method === "OPTIONS") return response({ ok: true }, 200, origin);
  if (request.method !== "POST") return response({ ok: false, detail: "Method not allowed." }, 405, origin);

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch {
    return response({ ok: false, detail: "Invalid request." }, 400, origin);
  }
  const action = String(body.action || "").trim().toLowerCase();

  // Marketing pages may read the public price catalog without an account.
  // It contains only active prices and plan labels, never Stripe IDs or keys.
  if (action === "catalog") {
    try {
      return response({ ok: true, plans: await priceCatalog() }, 200, origin);
    } catch {
      return response({ ok: false, detail: "Pricing is temporarily unavailable." }, 503, origin);
    }
  }
  if (action === "addons_catalog") {
    try {
      return response({ ok: true, addons: await addonCatalog() }, 200, origin);
    } catch {
      return response({ ok: false, detail: "Add-on pricing is temporarily unavailable." }, 503, origin);
    }
  }
  if (action === "developer_api_key_resolve") {
    try {
      return await resolveDeveloperApiKey(String(body.api_key || ""));
    } catch {
      return response({ ok: false, detail: "Developer API authentication is temporarily unavailable." }, 503, origin);
    }
  }

  const auth = await verifiedUser(request);
  if (!auth.user) return response({ ok: false, detail: "Sign in with a verified Cadivor account." }, auth.status, origin);
  try {
    if (await accountIsSuspended(auth.user.id)) {
      return response({ ok: false, detail: "This account is suspended. Contact Cadivor support for help." }, 403, origin);
    }
  } catch {
    return response({ ok: false, detail: "Account access could not be verified." }, 503, origin);
  }
  if (internalActions.has(action) && !(await verifyInternalActionProof(action, auth.user.id, body))) {
    return response({ ok: false, detail: "This billing operation must be requested through Cadivor." }, 403, origin);
  }

  let planToken = "unknown";
  const supportReference = crypto.randomUUID();
  try {
    const profile = await profileFor(auth.user.id);

    if (action === "admin_sync_account_status") {
      if (String(profile.role || "").trim().toLowerCase() !== "admin") {
        return response({ ok: false, detail: "Platform administrator access is required." }, 403, origin);
      }
      const targetUserId = String(body.target_user_id || "").trim();
      const nextStatus = String(body.status || "").trim().toLowerCase();
      if (!UUID_PATTERN.test(targetUserId) || targetUserId === auth.user.id ||
          !["active", "suspended"].includes(nextStatus)) {
        return response({ ok: false, detail: "Invalid account status update." }, 400, origin);
      }
      const targetProfile = await profileFor(targetUserId);
      if (!targetProfile.role) return response({ ok: false, detail: "Account not found." }, 404, origin);
      const { data: targetControls, error: targetControlsError } = await supabase
        .from("admin_user_controls")
        .select("account_status,suspended_reason")
        .eq("user_id", targetUserId)
        .maybeSingle();
      const { data: pendingMarker, error: pendingError } = await supabase
        .from("admin_account_deletion_pending")
        .select("user_id")
        .eq("user_id", targetUserId)
        .maybeSingle();
      if (targetControlsError || pendingError) throw new Error("Account status could not be loaded.");
      if (pendingMarker || targetControls?.suspended_reason === "Account deletion pending") {
        return response({ ok: false, detail: "Account deletion is pending; retry deletion to finish it." }, 409, origin);
      }
      const storedStatus = String(targetControls?.account_status || "active").toLowerCase();
      if (storedStatus !== nextStatus) {
        return response({ ok: false, detail: "The account status change was not saved. Retry the update." }, 409, origin);
      }
      const { error } = await supabase.auth.admin.updateUserById(targetUserId, {
        ban_duration: nextStatus === "suspended" ? "876000h" : "none",
      });
      if (error) throw new Error("Auth account status could not be synchronized.");
      return response({ ok: true, account_status: nextStatus }, 200, origin);
    }

    if (action === "admin_validate_account_deletion") {
      const target = await validateAdminDeletionTarget(auth.user.id, body);
      if (!target.ok) return response({ ok: false, detail: target.detail }, target.status, origin);
      return response({
        ok: true,
        account: { id: target.userId, email: target.email, role: target.role },
      }, 200, origin);
    }

    if (action === "admin_prepare_account_deletion") {
      const target = await validateAdminDeletionTarget(auth.user.id, body);
      if (!target.ok) return response({ ok: false, detail: target.detail }, target.status, origin);
      const { error: prepareError } = await supabase.rpc("cadivor_admin_prepare_account_deletion", {
        p_target_user_id: target.userId,
        p_actor_user_id: auth.user.id,
      });
      if (prepareError) {
        const message = String(prepareError.message || "").toLowerCase();
        const conflict = message.includes("active member to receive ownership") ||
          message.includes("must retain at least one administrator") ||
          message.includes("must retain at least one active administrator");
        return response({
          ok: false,
          detail: conflict
            ? "Deletion needs attention: preserve shared workspace ownership and retry."
            : "Account cleanup could not be prepared. The account was not removed.",
        }, conflict ? 409 : 503, origin);
      }
      if (target.authUser) {
        const { error: banError } = await supabase.auth.admin.updateUserById(target.userId, {
          ban_duration: "876000h",
        });
        if (banError) {
          return response({
            ok: false,
            detail: "The account is marked for deletion, but sign-in could not be blocked. Retry deletion.",
          }, 503, origin);
        }
      }
      return response({ ok: true, prepared: true }, 200, origin);
    }

    if (action === "admin_delete_account") {
      const target = await validateAdminDeletionTarget(auth.user.id, body);
      if (!target.ok) return response({ ok: false, detail: target.detail }, target.status, origin);

      const { error: prepareError } = await supabase.rpc("cadivor_admin_prepare_account_deletion", {
        p_target_user_id: target.userId,
        p_actor_user_id: auth.user.id,
      });
      if (prepareError) {
        const message = String(prepareError.message || "").toLowerCase();
        const conflict = message.includes("active member to receive ownership") ||
          message.includes("must retain at least one administrator") ||
          message.includes("must retain at least one active administrator");
        return response({
          ok: false,
          detail: conflict
            ? "Deletion needs attention: preserve shared workspace ownership and retry."
            : "Account cleanup could not be prepared. The account was not removed.",
        }, conflict ? 409 : 503, origin);
      }

      const targetBillingProfile = await profileFor(target.userId);
      if (target.authUser) {
        const { error: banError } = await supabase.auth.admin.updateUserById(target.userId, {
          ban_duration: "876000h",
        });
        if (banError) {
          return response({ ok: false, detail: "The account is marked for deletion, but sign-in could not be blocked. Retry deletion." }, 503, origin);
        }
      }
      try {
        await cancelAndAnonymizeBilling(target.userId, targetBillingProfile);
      } catch {
        return response({
          ok: false,
          detail: "The account is marked for deletion, but billing cleanup did not finish. Retry deletion.",
        }, 503, origin);
      }

      if (target.authUser) {
        const { error: deleteError } = await supabase.auth.admin.deleteUser(target.userId, false);
        if (deleteError) {
          return response({ ok: false, detail: "The account is marked for deletion, but Auth removal did not finish. Retry deletion." }, 503, origin);
        }
      }

      const { error: finalizeError } = await supabase.rpc("cadivor_admin_finalize_account_deletion", {
        p_target_user_id: target.userId,
        p_actor_user_id: auth.user.id,
      });
      if (finalizeError) {
        return response({ ok: false, detail: "Auth removal finished, but account cleanup needs a retry." }, 503, origin);
      }
      return response({ ok: true, deleted: true }, 200, origin);
    }


    if (action === "entitlements") {
      return response(await entitlementSnapshot(auth.user.id, profile), 200, origin);
    }

    if (action === "developer_api_access_override_sync") {
      if (String(profile.role || "").trim().toLowerCase() !== "admin") {
        return response({ ok: false, detail: "Platform administrator access is required." }, 403, origin);
      }
      const targetUserId = String(body.target_user_id || "").trim();
      const enabled = body.enabled === null ? null : body.enabled;
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(targetUserId) ||
          (enabled !== null && typeof enabled !== "boolean")) {
        return response({ ok: false, detail: "Invalid API entitlement override." }, 400, origin);
      }
      if (enabled === null) {
        const { error } = await supabase
          .from("cadivor_api_access_overrides")
          .delete()
          .eq("user_id", targetUserId);
        if (error) throw new Error("API access override could not be updated.");
      } else {
        const { error } = await supabase
          .from("cadivor_api_access_overrides")
          .upsert({ user_id: targetUserId, enabled, updated_at: new Date().toISOString() });
        if (error) throw new Error("API access override could not be updated.");
      }
      return response({ ok: true, synced: true }, 200, origin);
    }

    if (action === "developer_api_keys_list") {
      const workspaceId = String(body.workspace_id || "").trim();
      if (!workspaceId || workspaceId.length > 180) {
        return response({ ok: false, detail: "Workspace is required." }, 400, origin);
      }
      if (!(await apiAccessEnabled(auth.user.id, profile))) {
        return response({ ok: false, detail: "Developer API access is not active for this account." }, 403, origin);
      }
      const { data, error } = await supabase
        .from("cadivor_developer_api_keys")
        .select("id,name,key_prefix,created_at,last_used_at,revoked_at")
        .eq("user_id", auth.user.id)
        .eq("workspace_id", workspaceId)
        .is("revoked_at", null)
        .order("created_at", { ascending: false });
      if (error) throw new Error("Developer API keys could not be loaded.");
      return response({ ok: true, keys: data || [] }, 200, origin);
    }

    if (action === "developer_api_key_create") {
      const workspaceId = String(body.workspace_id || "").trim();
      const name = String(body.name || "").trim().replace(/\s+/g, " ");
      if (!workspaceId || workspaceId.length > 180 || !name || name.length > 80) {
        return response({ ok: false, detail: "Enter a key name of 1 to 80 characters." }, 400, origin);
      }
      if (!(await apiAccessEnabled(auth.user.id, profile))) {
        return response({ ok: false, detail: "Developer API access is not active for this account." }, 403, origin);
      }
      const { count, error: countError } = await supabase
        .from("cadivor_developer_api_keys")
        .select("id", { count: "exact", head: true })
        .eq("user_id", auth.user.id)
        .eq("workspace_id", workspaceId)
        .is("revoked_at", null);
      if (countError) throw new Error("Developer API key limit could not be checked.");
      if ((count || 0) >= 10) {
        return response({ ok: false, detail: "This workspace can have up to 10 active API keys." }, 409, origin);
      }
      const apiKey = newDeveloperApiKey();
      const id = crypto.randomUUID();
      const keyHash = await hashDeveloperApiKey(apiKey);
      const { error } = await supabase.from("cadivor_developer_api_keys").insert({
        id,
        user_id: auth.user.id,
        workspace_id: workspaceId,
        name,
        key_prefix: apiKey.slice(0, 18),
        key_hash: keyHash,
      });
      if (error) throw new Error("Developer API key could not be created.");
      return response({ ok: true, key: { id, name, key_prefix: apiKey.slice(0, 18), created_at: new Date().toISOString(), secret: apiKey } }, 201, origin);
    }

    if (action === "developer_api_key_revoke") {
      const workspaceId = String(body.workspace_id || "").trim();
      const keyId = String(body.key_id || "").trim();
      if (!workspaceId || workspaceId.length > 180 || !keyId || keyId.length > 100) {
        return response({ ok: false, detail: "API key was not found." }, 400, origin);
      }
      const { data, error } = await supabase
        .from("cadivor_developer_api_keys")
        .update({ revoked_at: new Date().toISOString() })
        .eq("id", keyId)
        .eq("user_id", auth.user.id)
        .eq("workspace_id", workspaceId)
        .is("revoked_at", null)
        .select("id")
        .maybeSingle();
      if (error) throw new Error("Developer API key could not be revoked.");
      if (!data) return response({ ok: false, detail: "API key was not found or was already revoked." }, 404, origin);
      return response({ ok: true, revoked: true }, 200, origin);
    }

    if (action === "status") {
      const plans = await priceCatalog();
      const checkoutEnabled = plans.some((plan) =>
        plan.enabled === true || (
          Boolean(plan.annual) &&
          (plan.annual as Record<string, unknown>).enabled === true
        )
      );
      const active = ["active", "trialing"].includes(String(profile.stripe_subscription_status || "").toLowerCase());
      return response({
        ok: true,
        current_plan: effectivePlan(profile).plan,
        checkout_enabled: checkoutEnabled,
        stripe_mode: stripeSecret.startsWith("sk_live_") ? "live" : stripeSecret.startsWith("sk_test_") ? "test" : "unknown",
        charges_created: false,
        subscription_status: profile.stripe_subscription_status || null,
        has_active_subscription: active,
        can_manage_billing: Boolean(active && (profile.stripe_customer_id || profile.stripe_subscription_id)),
        plans,
        addons: await addonCatalog(),
        usage_credits: await usageCreditsFor(auth.user.id),
        api_access_addon_active: (await apiAddonFor(auth.user.id)).active,
      }, 200, origin);
    }

    if (String(profile.role || "").toLowerCase() === "admin") {
      return response({ ok: false, detail: "Workspace administrators cannot purchase an individual subscription." }, 403, origin);
    }

    if (action === "portal") {
      const portal = await createPortal(profile, auth.user.id, origin, supportReference);
      return response(portal, portal.ok ? 200 : 409, origin);
    }

    if (action === "professional_api_addon_checkout") {
      const currentPlan = effectivePlan(profile).plan;
      const currentStatus = String(profile.stripe_subscription_status || "").toLowerCase();
      if (currentPlan !== "Professional" || !["active", "trialing"].includes(currentStatus)) {
        return response({ ok: false, detail: "The Professional API add-on requires an active Professional subscription." }, 409, origin);
      }
      const existing = await apiAddonFor(auth.user.id);
      if (existing.active) {
        return response({ ok: false, code: "addon_already_active", detail: "Professional API access is already active." }, 409, origin);
      }
      const priceId = String(Deno.env.get("STRIPE_PROFESSIONAL_API_ADDON_PRICE_ID") || "").trim();
      if (!priceId) return response({ ok: false, detail: "The Professional API add-on is not configured for purchase yet." }, 503, origin);
      const price = await stripe.prices.retrieve(priceId);
      if (!price.active || price.currency !== "usd" || !price.recurring ||
          price.recurring.interval !== "month" || typeof price.unit_amount !== "number" || price.unit_amount <= 0) {
        return response({ ok: false, detail: "The Professional API add-on billing details need review." }, 503, origin);
      }
      const customerId = String(profile.stripe_customer_id || "").trim();
      const metadata = { user_id: auth.user.id, cadivor_addon: "professional_api" };
      const session = await stripe.checkout.sessions.create({
        mode: "subscription",
        ...(customerId ? { customer: customerId } : { customer_email: auth.user.email! }),
        line_items: [{ price: priceId, quantity: 1 }],
        success_url: origin + "/settings?billing=api-addon-success",
        cancel_url: origin + "/settings?billing=api-addon-cancel",
        client_reference_id: auth.user.id,
        metadata,
        subscription_data: { metadata },
      }, { idempotencyKey: "cadivor_api_addon_" + auth.user.id + "_" + supportReference });
      if (!session.url) throw new Error("Stripe did not return a checkout link.");
      return response({ ok: true, checkout: { state: "open", url: session.url } }, 200, origin);
    }

    if (action === "usage_overage_checkout") {
      const currentPlan = effectivePlan(profile).plan;
      const currentStatus = String(profile.stripe_subscription_status || "").toLowerCase();
      if (!["Starter", "Professional", "Business"].includes(currentPlan) ||
          !["active", "trialing"].includes(currentStatus)) {
        return response({ ok: false, detail: "Usage overage packs require an active paid subscription." }, 409, origin);
      }
      const kind = String(body.credit_kind || "").trim();
      const item = kind === "bom_analysis"
        ? { priceEnv: "STRIPE_BOM_ANALYSIS_OVERAGE_PRICE_ID", unitsEnv: "CADIVOR_BOM_ANALYSIS_OVERAGE_CREDITS" }
        : kind === "monitored_part"
          ? { priceEnv: "STRIPE_MONITORED_PARTS_OVERAGE_PRICE_ID", unitsEnv: "CADIVOR_MONITORED_PARTS_OVERAGE_CREDITS" }
          : null;
      if (!item) return response({ ok: false, detail: "Choose a supported usage pack." }, 400, origin);
      const priceId = String(Deno.env.get(item.priceEnv) || "").trim();
      const credits = positiveUnits(item.unitsEnv);
      if (!priceId || !credits) return response({ ok: false, detail: "This usage pack is not configured for purchase yet." }, 503, origin);
      const price = await stripe.prices.retrieve(priceId);
      if (!price.active || price.currency !== "usd" || price.recurring ||
          typeof price.unit_amount !== "number" || price.unit_amount <= 0) {
        return response({ ok: false, detail: "This usage pack billing details need review." }, 503, origin);
      }
      const customerId = String(profile.stripe_customer_id || "").trim();
      const metadata = {
        user_id: auth.user.id,
        cadivor_addon: "usage_overage",
        cadivor_credit_kind: kind,
        cadivor_credit_units: String(credits),
      };
      const idempotencyKey = "cadivor_usage_pack_" + auth.user.id + "_" + kind + "_" + supportReference;
      let session: Stripe.Checkout.Session;
      try {
        session = await stripe.checkout.sessions.create({
          mode: "payment",
          ...(customerId ? { customer: customerId } : { customer_email: auth.user.email! }),
          line_items: [{ price: priceId, quantity: 1 }],
          success_url: origin + "/settings?billing=usage-pack-success",
          cancel_url: origin + "/settings?billing=usage-pack-cancel",
          client_reference_id: auth.user.id,
          metadata,
          payment_intent_data: { metadata },
        }, { idempotencyKey });
      } catch (error) {
        if (!customerId || !isMissingStripeCustomer(error)) throw error;
        // One-time packs can use a fresh email-based Checkout Session when a
        // stored customer belongs to a retired Stripe mode or account. This
        // does not create or alter a recurring subscription.
        session = await stripe.checkout.sessions.create({
          mode: "payment",
          customer_email: auth.user.email!,
          line_items: [{ price: priceId, quantity: 1 }],
          success_url: origin + "/settings?billing=usage-pack-success",
          cancel_url: origin + "/settings?billing=usage-pack-cancel",
          client_reference_id: auth.user.id,
          metadata,
          payment_intent_data: { metadata },
        }, { idempotencyKey: idempotencyKey + "_fresh_customer" });
      }
      if (!session.url) throw new Error("Stripe did not return a checkout link.");
      return response({ ok: true, checkout: { state: "open", url: session.url } }, 200, origin);
    }

    if (action === "reserve_usage_credit") {
      const kind = String(body.credit_kind || "").trim();
      const reservationId = String(body.reservation_id || "").trim();
      if (kind !== "bom_analysis" || !reservationId || reservationId.length > 100) {
        return response({ ok: false, detail: "Invalid usage credit reservation." }, 400, origin);
      }
      const { data, error } = await supabase.rpc("cadivor_reserve_bom_analysis_credit", {
        p_user_id: auth.user.id,
        p_reservation_id: reservationId,
      });
      if (error) throw new Error("Usage credit could not be reserved.");
      return response({ ok: true, reserved: data === true }, 200, origin);
    }

    if (action === "finish_usage_credit") {
      const reservationId = String(body.reservation_id || "").trim();
      const commit = body.commit === true;
      if (!reservationId || reservationId.length > 100) {
        return response({ ok: false, detail: "Invalid usage credit reservation." }, 400, origin);
      }
      const { data, error } = await supabase.rpc("cadivor_finish_bom_analysis_credit", {
        p_user_id: auth.user.id,
        p_reservation_id: reservationId,
        p_commit: commit,
      });
      if (error) throw new Error("Usage credit could not be reconciled.");
      return response({ ok: true, finished: data === true }, 200, origin);
    }

    if (action === "allocate_monitored_part_credits") {
      const workspaceId = String(body.workspace_id || "").trim();
      const requiredCredits = Number(body.required_credits);
      if (!workspaceId || workspaceId.length > 180 ||
          !Number.isSafeInteger(requiredCredits) || requiredCredits < 0 || requiredCredits > 100_000) {
        return response({ ok: false, detail: "Invalid monitored part allocation." }, 400, origin);
      }
      const { data, error } = await supabase.rpc("cadivor_allocate_monitored_part_credits", {
        p_user_id: auth.user.id,
        p_workspace_id: workspaceId,
        p_required_credits: requiredCredits,
      });
      if (error) throw new Error("Monitoring credits could not be allocated.");
      return response({ ok: true, allocated: data === true }, 200, origin);
    }

    if (action !== "checkout") return response({ ok: false, detail: "Unknown billing action." }, 400, origin);
    const token = String(body.plan || "").trim().toLowerCase();
    const billingInterval = body.billing_interval === "year" ? "year" : "month";
    planToken = token || "unknown";
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

    const priceEnv = billingInterval === "year" ? plan.annualEnv : plan.env;
    const priceId = String(Deno.env.get(priceEnv) || "").trim();
    if (!priceId) return response({ ok: false, detail: "This plan is temporarily unavailable for purchase." }, 503, origin);
    const price = await stripe.prices.retrieve(priceId);
    const monthlyValid = billingInterval === "month" && price.recurring?.interval === "month" && price.unit_amount === plan.expected;
    const annualDiscounted = billingInterval === "year" && price.recurring?.interval === "year" &&
      typeof price.unit_amount === "number" && price.unit_amount > 0 && price.unit_amount < plan.expected * 12;
    if (!price.active || price.currency !== "usd" || (!monthlyValid && !annualDiscounted)) {
      return response({ ok: false, detail: "This plan's billing details need review. Contact Cadivor support." }, 503, origin);
    }

    const customerId = String(profile.stripe_customer_id || "").trim();
    const idempotencyKey = `cadivor_subscription_${auth.user.id}_${token}_${supportReference}`;
    let session: Stripe.Checkout.Session;
    try {
      session = await stripe.checkout.sessions.create(
        checkoutSessionParams(
          origin,
          auth.user.id,
          auth.user.email!,
          token,
          priceId,
          billingInterval,
          customerId || undefined,
          marketingAttribution(auth.user),
        ),
        { idempotencyKey },
      );
    } catch (error) {
      // A deleted or mode-mismatched Stripe customer must not strand a canceled
      // user. Retry only that precise failure by asking Checkout to create a
      // new subscription customer from the verified account email.
      if (!customerId || !isMissingStripeCustomer(error)) throw error;
      session = await stripe.checkout.sessions.create(
        checkoutSessionParams(
          origin,
          auth.user.id,
          auth.user.email!,
          token,
          priceId,
          billingInterval,
          undefined,
          marketingAttribution(auth.user),
        ),
        { idempotencyKey: `${idempotencyKey}_fresh_customer` },
      );
    }
    if (!session.url) throw new Error("Stripe did not return a checkout link.");
    return response({ ok: true, checkout: { state: "open", url: session.url } }, 200, origin);
  } catch (error) {
    const summary = stripeErrorSummary(error);
    // Do not log customer email, access tokens, request bodies, or secrets.
    console.error("subscription_checkout_failed", {
      reference: supportReference,
      action,
      plan: planToken,
      error_type: summary.type,
      error_code: summary.code,
      error_status: summary.statusCode,
      error_param: summary.param,
      stripe_request_id: summary.requestId,
    });
    return response({
      ok: false,
      code: "checkout_unavailable",
      detail: "Billing could not be started. Please try again or contact support.",
      support_reference: supportReference,
    }, 503, origin);
  }
});
