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

function safeSupportMessage(message: string | undefined): string | undefined {
  if (!message) return undefined;
  return message
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[redacted-email]")
    .replace(/\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]+\b/gi, "[redacted-key]")
    .replace(/\bBearer\s+[^\s,]+/gi, "Bearer [redacted]")
    .slice(0, 240);
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
    .select("plan,role,trial_started_at,trial_ends_at,plan_grandfather_source,stripe_customer_id,stripe_subscription_id,stripe_subscription_status,stripe_current_period_end,stripe_price_id")
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
  const [
    { data: apiAddon, error: apiAddonError },
    { data: monitoredAddon, error: monitoredAddonError },
    { data: manualInvoices, error: manualInvoicesError },
  ] = await Promise.all([
    supabase
    .from("cadivor_professional_api_addons")
    .select("subscription_id")
    .eq("user_id", targetUserId)
    .maybeSingle(),
    supabase
      .from("cadivor_monitored_parts_addons")
      .select("subscription_id")
      .eq("user_id", targetUserId)
      .maybeSingle(),
    supabase
      .from("cadivor_manual_plan_invoices")
      .select("id,status,stripe_invoice_id,payment_method")
      .eq("user_id", targetUserId)
      .in("status", ["creating", "open", "payment_recorded"]),
  ]);
  if (apiAddonError || monitoredAddonError || manualInvoicesError) {
    throw new Error("Subscription records could not be loaded.");
  }

  for (const manualInvoice of manualInvoices || []) {
    const invoiceId = String(manualInvoice.stripe_invoice_id || "").trim();
    let nextStatus = "void";
    let paidAt: string | null = null;
    let paymentMethod: string | null = null;
    if (invoiceId) {
      try {
        const invoice = await stripe.invoices.retrieve(invoiceId);
        if (invoice.status === "paid") {
          nextStatus = "paid";
          paidAt = invoice.status_transitions?.paid_at
            ? new Date(invoice.status_transitions.paid_at * 1000).toISOString()
            : new Date().toISOString();
          paymentMethod = invoice.paid_out_of_band
            ? ["cash", "check"].includes(String(manualInvoice.payment_method || ""))
              ? String(manualInvoice.payment_method)
              : "offline_unclassified"
            : "stripe";
        } else if (invoice.status === "draft") {
          await stripe.invoices.del(invoiceId);
        } else if (invoice.status === "open") {
          await stripe.invoices.voidInvoice(invoiceId);
        } else if (invoice.status !== "void") {
          throw new Error("Unpaid invoice could not be safely closed.");
        }
      } catch (error) {
        const summary = stripeErrorSummary(error);
        if (summary.code !== "resource_missing") throw error;
      }
    }
    const { error: invoiceCloseError } = await supabase
      .from("cadivor_manual_plan_invoices")
      .update({
        status: nextStatus,
        ...(nextStatus === "paid" ? { paid_at: paidAt, payment_method: paymentMethod } : {}),
        hosted_invoice_url: null,
        invoice_pdf: null,
        updated_at: new Date().toISOString(),
      })
      .eq("id", manualInvoice.id)
      .in("status", ["creating", "open", "payment_recorded"]);
    if (invoiceCloseError) throw new Error("Manual invoice cleanup could not be saved.");
  }

  const subscriptionIds = new Set<string>();
  for (const value of [profile.stripe_subscription_id, apiAddon?.subscription_id, monitoredAddon?.subscription_id]) {
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
  interval?: "month" | "year",
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
  const monitoredPartsCapacity = positiveUnits("CADIVOR_MONITORED_PARTS_ADDON_CAPACITY");
  const [analysisPrice, monitoredMonthly, monitoredAnnual, apiPrice] = await Promise.all([
    configuredPrice("STRIPE_BOM_ANALYSIS_OVERAGE_PRICE_ID", "one_time"),
    configuredPrice("STRIPE_MONITORED_PARTS_MONTHLY_PRICE_ID", "recurring", "month"),
    configuredPrice("STRIPE_MONITORED_PARTS_ANNUAL_PRICE_ID", "recurring", "year"),
    configuredPrice("STRIPE_PROFESSIONAL_API_ADDON_PRICE_ID", "recurring", "month"),
  ]);
  const monitoredMonthlyMatches = monitoredMonthly.amount === 2900;
  const monitoredAnnualMatches = monitoredAnnual.amount === 29000;
  return {
    bom_analysis: { ...analysisPrice, enabled: analysisPrice.enabled && analysisCredits !== null, credits: analysisCredits },
    monitored_parts: {
      enabled: monitoredPartsCapacity !== null &&
        ((monitoredMonthly.enabled && monitoredMonthlyMatches) ||
          (monitoredAnnual.enabled && monitoredAnnualMatches)),
      capacity: monitoredPartsCapacity,
      monthly: {
        ...monitoredMonthly,
        enabled: monitoredMonthly.enabled && monitoredMonthlyMatches && monitoredPartsCapacity !== null,
        price_matches_catalog: monitoredMonthlyMatches,
      },
      annual: {
        ...monitoredAnnual,
        enabled: monitoredAnnual.enabled && monitoredAnnualMatches && monitoredPartsCapacity !== null,
        price_matches_catalog: monitoredAnnualMatches,
      },
    },
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

async function monitoredPartsAddonFor(userId: string) {
  const { data, error } = await supabase
    .from("cadivor_monitored_parts_addons")
    .select("subscription_id,status,price_id,capacity")
    .eq("user_id", userId)
    .in("status", ["active", "trialing"])
    .maybeSingle();
  if (error) throw new Error("Monitored-parts add-on status could not be loaded.");
  const active = ["active", "trialing"].includes(String(data?.status || "").toLowerCase());
  return {
    active,
    subscription_id: active ? data?.subscription_id || null : null,
    price_id: active ? data?.price_id || null : null,
    capacity: active ? Math.max(0, Number(data?.capacity) || 0) : 0,
  };
}

type ManualPlanGrant = {
  id: string;
  plan: string;
  billing_interval: string;
  grant_starts_at: string;
  grant_ends_at: string;
};

async function manualBillingStateFor(userId: string, now = new Date()) {
  const [grantResult, invoiceResult] = await Promise.all([
    supabase
      .from("cadivor_manual_plan_invoices")
      .select("id,plan,billing_interval,grant_starts_at,grant_ends_at")
      .eq("user_id", userId)
      .eq("status", "paid")
      .lte("grant_starts_at", now.toISOString())
      .gt("grant_ends_at", now.toISOString())
      .order("grant_ends_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
    supabase
      .from("cadivor_manual_plan_invoices")
      .select("id,status,hosted_invoice_url,invoice_pdf,invoice_sent_at,plan,billing_interval,amount_minor,currency,due_at,created_at")
      .eq("user_id", userId)
      .in("status", ["creating", "open", "payment_recorded"])
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle(),
  ]);
  if (grantResult.error || invoiceResult.error) {
    throw new Error("Manual billing status could not be loaded.");
  }
  return {
    activeGrant: (grantResult.data || null) as ManualPlanGrant | null,
    pendingInvoice: invoiceResult.data || null,
  };
}

async function effectivePlanFor(
  userId: string,
  profile: Record<string, unknown>,
  now = new Date(),
) {
  const manualBilling = await manualBillingStateFor(userId, now);
  if (manualBilling.activeGrant) {
    return {
      plan: String(manualBilling.activeGrant.plan),
      trial_status: null,
      trial_days_remaining: null,
      manual_grant: manualBilling.activeGrant,
    };
  }
  return { ...effectivePlan(profile, now), manual_grant: null };
}

async function applyOutOfBandManualInvoicePayment(invoiceRecordId: string, invoice: Stripe.Invoice) {
  if (invoice.status !== "paid" || !invoice.paid_out_of_band ||
      typeof invoice.amount_paid !== "number" || !invoice.status_transitions?.paid_at) {
    throw new Error("The offline invoice payment has not been confirmed.");
  }
  const { data, error } = await supabase.rpc("cadivor_apply_manual_plan_invoice_paid", {
    p_invoice_id: invoiceRecordId,
    p_stripe_invoice_id: invoice.id,
    p_stripe_event_id: null,
    p_amount_paid: invoice.amount_paid,
    p_currency: invoice.currency,
    p_paid_at: new Date(invoice.status_transitions.paid_at * 1000).toISOString(),
    p_paid_out_of_band: true,
  });
  if (error) throw new Error("Payment was confirmed, but Cadivor could not apply the paid plan term yet.");
  const result = (data || {}) as Record<string, unknown>;
  if (result.ok !== true) throw new Error("Payment was confirmed, but Cadivor could not apply the paid plan term yet.");
  return result;
}

async function apiAccessEnabled(userId: string, profile: Record<string, unknown>): Promise<boolean> {
  const { data: override, error } = await supabase
    .from("cadivor_api_access_overrides")
    .select("enabled")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) throw new Error("API access entitlement could not be loaded.");
  if (typeof override?.enabled === "boolean") return override.enabled;
  const plan = (await effectivePlanFor(userId, profile)).plan;
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
  const effective = await effectivePlanFor(String(data.user_id), profile);
  const apiAddon = await apiAddonFor(String(data.user_id));
  const monitoredAddon = await monitoredPartsAddonFor(String(data.user_id));
  const monitoredCapacity = hasCurrentPaidSubscription(profile) && monitoredAddon.active &&
      ["Starter", "Professional"].includes(effective.plan)
    ? monitoredAddon.capacity
    : 0;
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
    monitored_parts_addon_capacity: monitoredCapacity,
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

function hasCurrentPaidSubscription(profile: Record<string, unknown>, now = new Date()): boolean {
  const status = String(profile.stripe_subscription_status || "").trim().toLowerCase();
  if (!["active", "trialing"].includes(status)) return false;

  // Do not trust a stale `active` flag after the recorded paid period elapsed.
  // This can occur when an old test-mode subscription snapshot was retained in
  // production after the Stripe account switched to live mode.
  const periodEndValue = profile.stripe_current_period_end;
  if (!periodEndValue) return true;
  const periodEnd = new Date(String(periodEndValue));
  return !Number.isNaN(periodEnd.getTime()) && periodEnd > now;
}

function effectivePlan(profile: Record<string, unknown>, now = new Date()): {
  plan: string;
  trial_status: string | null;
  trial_days_remaining: number | null;
} {
  const role = String(profile.role || "").trim().toLowerCase();
  const stored = String(profile.plan || "").trim().toLowerCase();
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
  if (paidPlan && hasCurrentPaidSubscription(profile, now)) {
    return { plan: paidPlan.name, trial_status: null, trial_days_remaining: null };
  }
  if (grandfathered && ["free", "beta", "beta access", "grandfathered", "grandfathered beta", "starter", "professional", "business"].includes(stored)) {
    return { plan: "Grandfathered beta", trial_status: null, trial_days_remaining: null };
  }
  return { plan: "Subscription inactive", trial_status: null, trial_days_remaining: null };
}

async function entitlementSnapshot(userId: string, profile: Record<string, unknown>) {
  const manualBilling = await manualBillingStateFor(userId);
  const effective = manualBilling.activeGrant
    ? {
      plan: String(manualBilling.activeGrant.plan),
      trial_status: null,
      trial_days_remaining: null,
    }
    : effectivePlan(profile);
  const [apiAddon, monitoredAddon, usageCredits] = await Promise.all([
    apiAddonFor(userId),
    monitoredPartsAddonFor(userId),
    usageCreditsFor(userId),
  ]);
  const monitoredPartsAddonCapacity =
    hasCurrentPaidSubscription(profile) && monitoredAddon.active &&
      ["Starter", "Professional"].includes(effective.plan)
      ? monitoredAddon.capacity
      : 0;
  return {
    ok: true,
    plan: effective.plan,
    role: String(profile.role || "user"),
    trial_started_at: effective.plan === "Trial" ? profile.trial_started_at || null : null,
    trial_ends_at: effective.plan === "Trial" ? profile.trial_ends_at || null : null,
    trial_status: effective.trial_status,
    trial_days_remaining: effective.trial_days_remaining,
    api_access_addon_active: apiAddon.active,
    monitored_parts_addon_capacity: monitoredPartsAddonCapacity,
    usage_credits: usageCredits,
    manual_billing: {
      active: Boolean(manualBilling.activeGrant),
      access_ends_at: manualBilling.activeGrant?.grant_ends_at || null,
      invoice_pending: Boolean(manualBilling.pendingInvoice),
      invoice_status: manualBilling.pendingInvoice?.status || null,
      invoice_url: manualBilling.pendingInvoice?.hosted_invoice_url || null,
      invoice_pdf: manualBilling.pendingInvoice?.invoice_pdf || null,
    },
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
  let supportStage = "profile_lookup";
  try {
    const profile = await profileFor(auth.user.id);

    if (action.startsWith("admin_manual_plan_")) {
      if (String(profile.role || "").trim().toLowerCase() !== "admin") {
        return response({ ok: false, detail: "Platform administrator access is required." }, 403, origin);
      }
      const targetUserId = String(body.target_user_id || "").trim();
      if (!UUID_PATTERN.test(targetUserId) || targetUserId === auth.user.id) {
        return response({ ok: false, detail: "Choose a valid customer account." }, 400, origin);
      }

      if (action === "admin_manual_plan_billing_list") {
        const { data, error } = await supabase
          .from("cadivor_manual_plan_invoices")
          .select("id,plan,billing_interval,amount_minor,currency,status,due_days,hosted_invoice_url,invoice_pdf,invoice_sent_at,due_at,created_at,paid_at,payment_method,payment_reference,payment_recorded_at,grant_starts_at,grant_ends_at,stripe_invoice_id")
          .eq("user_id", targetUserId)
          .order("created_at", { ascending: false })
          .limit(30);
        if (error) throw new Error("Manual billing history could not be loaded.");
        return response({ ok: true, invoices: data || [] }, 200, origin);
      }

      const { data: targetProfile, error: targetProfileError } = await supabase
        .from("users")
        .select("role,email,full_name,stripe_customer_id,stripe_subscription_status,stripe_current_period_end")
        .eq("id", targetUserId)
        .maybeSingle();
      if (targetProfileError) throw new Error("Customer account could not be loaded.");
      if (!targetProfile) return response({ ok: false, detail: "Customer account was not found." }, 404, origin);

      if (action === "admin_manual_plan_invoice_create") {
        if (String(targetProfile.role || "user").trim().toLowerCase() === "admin") {
          return response({ ok: false, detail: "Platform administrator accounts cannot be billed through this flow." }, 409, origin);
        }
        if (await accountIsSuspended(targetUserId)) {
          return response({ ok: false, detail: "Restore the customer account before issuing an invoice." }, 409, origin);
        }
        supportStage = "manual_invoice_validate_plan";
        const planName = String(body.plan || "").trim();
        const billingInterval = String(body.billing_interval || "month").trim().toLowerCase();
        const rawDueDays = body.due_days == null ? 30 : Number(body.due_days);
        const selectedPlan = planPrices.find((item) => item.name === planName);
        if (!selectedPlan || !["month", "year"].includes(billingInterval) ||
            !Number.isSafeInteger(rawDueDays) || rawDueDays < 1 || rawDueDays > 90) {
          return response({ ok: false, detail: "Choose a valid plan, billing term, and due date." }, 400, origin);
        }
        planToken = selectedPlan.token;
        supportStage = "manual_invoice_verify_customer_email";
        const { data: authResult, error: authError } = await supabase.auth.admin.getUserById(targetUserId);
        if (authError || !authResult?.user?.email) {
          const status = Number((authError as unknown as Record<string, unknown> | null)?.status || 0);
          if (status === 404 || (!authError && !authResult?.user)) {
            return response({ ok: false, detail: "Customer account was not found." }, 404, origin);
          }
          throw new Error("Customer email could not be verified.");
        }
        const customerEmail = String(authResult.user.email).trim().toLowerCase();

        supportStage = "manual_invoice_check_subscription";
        const activeSubscriptions: Stripe.Subscription[] = [];
        for (const status of ["active", "trialing"] as const) {
          const result = await stripe.subscriptions.search({
            query: `status:'${status}' AND metadata['user_id']:'${targetUserId}'`,
            limit: 2,
          });
          activeSubscriptions.push(...result.data);
          if (activeSubscriptions.length > 1) break;
        }
        if (activeSubscriptions.length > 0 || (
          ["active", "trialing"].includes(String(targetProfile.stripe_subscription_status || "").toLowerCase()) &&
          (!targetProfile.stripe_current_period_end || new Date(String(targetProfile.stripe_current_period_end)) > new Date())
        )) {
          return response({ ok: false, detail: "This account has an active Stripe subscription. No manual invoice was created." }, 409, origin);
        }

        const priceEnv = billingInterval === "year" ? selectedPlan.annualEnv : selectedPlan.env;
        const priceId = String(Deno.env.get(priceEnv) || "").trim();
        if (!priceId) return response({ ok: false, detail: "This plan term has no configured Stripe price." }, 503, origin);
        supportStage = "manual_invoice_verify_price";
        const price = await stripe.prices.retrieve(priceId);
        const monthlyValid = billingInterval === "month" && price.recurring?.interval === "month" &&
          (price.recurring.interval_count || 1) === 1 && price.unit_amount === selectedPlan.expected;
        const annualValid = billingInterval === "year" && price.recurring?.interval === "year" &&
          (price.recurring.interval_count || 1) === 1 && typeof price.unit_amount === "number" &&
          price.unit_amount > 0 && price.unit_amount < selectedPlan.expected * 12;
        if (!price.active || price.currency !== "usd" || typeof price.unit_amount !== "number" ||
            (!monthlyValid && !annualValid)) {
          return response({ ok: false, detail: "This plan's configured price does not match Cadivor's billing catalog." }, 503, origin);
        }

        let stripeCustomerId = String(targetProfile.stripe_customer_id || "").trim();
        let customer: Stripe.Customer;
        supportStage = "manual_invoice_verify_or_create_customer";
        if (stripeCustomerId) {
          const existingCustomer = await stripe.customers.retrieve(stripeCustomerId);
          if ("deleted" in existingCustomer && existingCustomer.deleted) {
            return response({ ok: false, detail: "The saved Stripe customer record is unavailable. No invoice was created." }, 409, origin);
          }
          if (existingCustomer.metadata?.user_id && existingCustomer.metadata.user_id !== targetUserId) {
            return response({ ok: false, detail: "The saved Stripe customer does not belong to this Cadivor account." }, 409, origin);
          }
          if (existingCustomer.email && existingCustomer.email.trim().toLowerCase() !== customerEmail) {
            return response({ ok: false, detail: "The Stripe billing email does not match this account's verified email. Correct it in Stripe before issuing an invoice." }, 409, origin);
          }
          customer = existingCustomer.email && existingCustomer.metadata?.user_id === targetUserId
            ? existingCustomer
            : await stripe.customers.update(stripeCustomerId, {
              ...(existingCustomer.email ? {} : { email: customerEmail }),
              metadata: { ...existingCustomer.metadata, user_id: targetUserId },
            });
        } else {
          customer = await stripe.customers.create({
            email: customerEmail,
            ...(targetProfile.full_name ? { name: String(targetProfile.full_name).slice(0, 200) } : {}),
            metadata: { user_id: targetUserId, cadivor_billing_customer: "true" },
          }, { idempotencyKey: `cadivor_manual_customer_${targetUserId}` });
          stripeCustomerId = customer.id;
          const { error: customerLinkError } = await supabase
            .from("users")
            .update({ stripe_customer_id: stripeCustomerId })
            .eq("id", targetUserId);
          if (customerLinkError) throw new Error("Stripe customer was created, but Cadivor could not link it safely.");
        }
        stripeCustomerId = customer.id;

        supportStage = "manual_invoice_reserve_record";
        const invoiceRecordId = crypto.randomUUID();
        const { data: reserveData, error: reserveError } = await supabase.rpc("cadivor_admin_reserve_manual_plan_invoice", {
          p_invoice_id: invoiceRecordId,
          p_actor_user_id: auth.user.id,
          p_target_user_id: targetUserId,
          p_customer_email: customerEmail,
          p_plan: selectedPlan.name,
          p_billing_interval: billingInterval,
          p_price_id: priceId,
          p_amount_minor: price.unit_amount,
          p_currency: price.currency,
          p_due_days: rawDueDays,
          p_stripe_customer_id: stripeCustomerId,
        });
        if (reserveError) throw new Error("Invoice could not be safely reserved.");
        const reservation = (reserveData || {}) as Record<string, unknown>;
        if (reservation.ok !== true) {
          const code = String(reservation.code || "");
          const detail = code === "invoice_pending"
            ? "This account already has an unpaid manual invoice. Close it before creating another."
            : code === "stripe_subscription_active"
              ? "This account has an active Stripe subscription. No manual invoice was created."
              : code === "account_unavailable"
                ? "Restore the customer account before issuing an invoice."
                : code === "account_not_found"
                  ? "Customer account was not found."
                  : code === "admin_target"
                    ? "Platform administrator accounts cannot be billed through this flow."
                    : "Invoice details failed Cadivor's billing checks.";
          return response({ ok: false, detail, code }, code === "account_not_found" ? 404 : 409, origin);
        }
        const invoiceRecord = (reservation.invoice || {}) as Record<string, unknown>;
        const recordId = String(invoiceRecord.id || "").trim();
        if (!UUID_PATTERN.test(recordId)) throw new Error("Manual invoice record is invalid.");

        const invoiceMetadata = {
          cadivor_manual_plan_invoice_id: recordId,
          cadivor_user_id: targetUserId,
          cadivor_plan: selectedPlan.token,
          cadivor_interval: billingInterval,
        };
        let invoice: Stripe.Invoice;
        const linkedInvoiceId = String(invoiceRecord.stripe_invoice_id || "").trim();
        if (linkedInvoiceId) {
          supportStage = "manual_invoice_resume_stripe_invoice";
          invoice = await stripe.invoices.retrieve(linkedInvoiceId);
        } else {
          supportStage = "manual_invoice_create_stripe_invoice";
          invoice = await stripe.invoices.create({
            customer: stripeCustomerId,
            collection_method: "send_invoice",
            days_until_due: rawDueDays,
            auto_advance: false,
            description: `Cadivor ${selectedPlan.name} plan access - ${billingInterval === "year" ? "annual" : "monthly"} prepayment`,
            metadata: invoiceMetadata,
          }, { idempotencyKey: `cadivor_manual_invoice_${recordId}` });
          const { error: invoiceLinkError } = await supabase
            .from("cadivor_manual_plan_invoices")
            .update({ stripe_invoice_id: invoice.id, stripe_customer_id: stripeCustomerId, updated_at: new Date().toISOString() })
            .eq("id", recordId)
            .eq("status", "creating");
          if (invoiceLinkError) throw new Error("Stripe invoice was created, but Cadivor could not link it safely.");
        }
        if (asId(invoice.customer) !== stripeCustomerId || invoice.subscription ||
            invoice.metadata?.cadivor_manual_plan_invoice_id !== recordId) {
          return response({ ok: false, detail: "Stripe invoice ownership could not be verified. No access was changed." }, 409, origin);
        }
        if (invoice.status === "draft") {
          supportStage = "manual_invoice_check_draft_lines";
          const lines = await stripe.invoices.listLineItems(invoice.id, { limit: 5 });
          if (lines.data.length === 0) {
            supportStage = "manual_invoice_add_draft_line";
            await stripe.invoiceItems.create({
              customer: stripeCustomerId,
              invoice: invoice.id,
              currency: price.currency,
              amount: price.unit_amount,
              description: `Cadivor ${selectedPlan.name} plan access - ${billingInterval === "year" ? "12 months" : "1 month"} after payment`,
              metadata: { cadivor_manual_plan_invoice_id: recordId },
            }, { idempotencyKey: `cadivor_manual_invoice_line_${recordId}` });
          } else if (lines.data.length !== 1 || lines.data[0].amount !== price.unit_amount) {
            throw new Error("Draft invoice line items did not match the configured plan price.");
          }
          supportStage = "manual_invoice_finalize";
          invoice = await stripe.invoices.finalizeInvoice(invoice.id, { auto_advance: false });
        } else {
          supportStage = "manual_invoice_verify_existing_lines";
          const lines = await stripe.invoices.listLineItems(invoice.id, { limit: 5 });
          if (lines.data.length !== 1 || lines.data[0].amount !== price.unit_amount) {
            throw new Error("Invoice line items did not match the configured plan price.");
          }
        }
        if (invoice.status !== "open" || invoice.amount_due !== price.unit_amount || invoice.currency !== price.currency) {
          supportStage = "manual_invoice_close_amount_mismatch";
          if (invoice.status === "open") await stripe.invoices.voidInvoice(invoice.id);
          const { error: voidError } = await supabase.rpc("cadivor_admin_void_manual_plan_invoice", {
            p_actor_user_id: auth.user.id,
            p_invoice_id: recordId,
          });
          if (voidError) throw new Error("Invoice amount validation failed and the invoice could not be closed.");
          return response({ ok: false, detail: "Stripe added an amount or currency that differs from the configured plan price. The invoice was voided; review customer tax or balance settings." }, 409, origin);
        }
        supportStage = "manual_invoice_save_payment_link";
        const { error: saveInvoiceError } = await supabase
          .from("cadivor_manual_plan_invoices")
          .update({
            status: "open",
            stripe_invoice_id: invoice.id,
            stripe_customer_id: stripeCustomerId,
            hosted_invoice_url: invoice.hosted_invoice_url,
            invoice_pdf: invoice.invoice_pdf,
            due_at: invoice.due_date ? new Date(invoice.due_date * 1000).toISOString() : null,
            updated_at: new Date().toISOString(),
          })
          .eq("id", recordId)
          .eq("status", "creating");
        if (saveInvoiceError) throw new Error("Invoice was finalized, but Cadivor could not save its payment link.");
        return response({
          ok: true,
          invoice: {
            id: recordId,
            stripe_invoice_id: invoice.id,
            plan: selectedPlan.name,
            billing_interval: billingInterval,
            amount_minor: price.unit_amount,
            currency: price.currency,
            status: "open",
            hosted_invoice_url: invoice.hosted_invoice_url,
            invoice_pdf: invoice.invoice_pdf,
            due_at: invoice.due_date ? new Date(invoice.due_date * 1000).toISOString() : null,
            invoice_sent_at: null,
          },
        }, 200, origin);
      }

      const invoiceRecordId = String(body.invoice_id || "").trim();
      if (!UUID_PATTERN.test(invoiceRecordId)) {
        return response({ ok: false, detail: "Choose a valid manual invoice." }, 400, origin);
      }
      const { data: invoiceRecord, error: invoiceRecordError } = await supabase
        .from("cadivor_manual_plan_invoices")
        .select("id,user_id,plan,billing_interval,price_id,amount_minor,currency,status,payment_method,payment_reference,payment_recorded_at,payment_recorded_by,stripe_customer_id,stripe_invoice_id,hosted_invoice_url,invoice_pdf,invoice_sent_at,due_at,created_at,paid_at,grant_starts_at,grant_ends_at")
        .eq("id", invoiceRecordId)
        .eq("user_id", targetUserId)
        .maybeSingle();
      if (invoiceRecordError) throw new Error("Manual invoice could not be loaded.");
      if (!invoiceRecord) return response({ ok: false, detail: "Manual invoice was not found." }, 404, origin);

      if (action === "admin_manual_plan_invoice_send") {
        if (invoiceRecord.status !== "open" || !invoiceRecord.stripe_invoice_id) {
          return response({ ok: false, detail: "Only an open invoice can be sent." }, 409, origin);
        }
        if (invoiceRecord.invoice_sent_at) {
          return response({ ok: true, already_sent: true, invoice: invoiceRecord }, 200, origin);
        }
        const invoice = await stripe.invoices.retrieve(String(invoiceRecord.stripe_invoice_id));
        if (invoice.status !== "open" || invoice.subscription ||
            invoice.metadata?.cadivor_manual_plan_invoice_id !== invoiceRecordId ||
            asId(invoice.customer) !== invoiceRecord.stripe_customer_id) {
          return response({ ok: false, detail: "Stripe invoice ownership could not be verified. It was not sent." }, 409, origin);
        }
        const sentInvoice = await stripe.invoices.sendInvoice(invoice.id, {}, {
          idempotencyKey: `cadivor_manual_invoice_send_${invoiceRecordId}`,
        });
        const sentAt = new Date().toISOString();
        const { error: sentError } = await supabase
          .from("cadivor_manual_plan_invoices")
          .update({ invoice_sent_at: sentAt, hosted_invoice_url: sentInvoice.hosted_invoice_url, invoice_pdf: sentInvoice.invoice_pdf, updated_at: sentAt })
          .eq("id", invoiceRecordId)
          .eq("status", "open");
        if (sentError) throw new Error("Stripe sent the invoice, but Cadivor could not save the send record.");
        return response({ ok: true, invoice_sent_at: sentAt }, 200, origin);
      }

      if (action === "admin_manual_plan_payment_record") {
        const method = String(body.payment_method || "").trim().toLowerCase();
        const reference = String(body.payment_reference || "").replace(/[\r\n\t]/g, " ").replace(/\s+/g, " ").trim().slice(0, 120);
        if (!["cash", "check"].includes(method)) {
          return response({ ok: false, detail: "Choose cash or check as the received payment method." }, 400, origin);
        }
        if (!["open", "payment_recorded"].includes(String(invoiceRecord.status || "")) || !invoiceRecord.stripe_invoice_id) {
          return response({ ok: false, detail: "Only an open unpaid invoice can be recorded as paid offline." }, 409, origin);
        }
        const invoice = await stripe.invoices.retrieve(String(invoiceRecord.stripe_invoice_id));
        if (invoice.status === "paid") {
          if (invoiceRecord.status !== "payment_recorded" || !invoice.paid_out_of_band ||
              invoice.amount_paid !== invoiceRecord.amount_minor) {
            return response({ ok: false, detail: "This invoice is already paid. Refresh the account; no additional payment was recorded." }, 409, origin);
          }
          const grantResult = await applyOutOfBandManualInvoicePayment(invoiceRecordId, invoice);
          return response({
            ok: true,
            paid: true,
            outcome: grantResult.outcome,
            grant_starts_at: grantResult.grant_starts_at || null,
            grant_ends_at: grantResult.grant_ends_at || null,
          }, 200, origin);
        }
        if (invoice.status !== "open" || invoice.subscription ||
            invoice.metadata?.cadivor_manual_plan_invoice_id !== invoiceRecordId ||
            asId(invoice.customer) !== invoiceRecord.stripe_customer_id ||
            invoice.amount_remaining !== invoiceRecord.amount_minor || invoice.currency !== invoiceRecord.currency) {
          return response({ ok: false, detail: "Stripe invoice details no longer match Cadivor's invoice record." }, 409, origin);
        }
        const { data: paymentData, error: paymentRecordError } = await supabase.rpc("cadivor_admin_record_manual_plan_payment", {
          p_actor_user_id: auth.user.id,
          p_invoice_id: invoiceRecordId,
          p_payment_method: method,
          p_payment_reference: reference || null,
        });
        if (paymentRecordError) throw new Error("Offline payment details could not be recorded.");
        const paymentResult = (paymentData || {}) as Record<string, unknown>;
        if (paymentResult.ok !== true) {
          const code = String(paymentResult.code || "");
          const detail = code === "invoice_already_paid"
            ? "This invoice is already paid. Refresh the account."
            : code === "payment_already_recorded"
              ? "A different offline payment was already recorded for this invoice."
              : "This invoice cannot be marked paid in its current state.";
          return response({ ok: false, detail, code }, 409, origin);
        }
        const paidInvoice = await stripe.invoices.pay(invoice.id, { paid_out_of_band: true }, {
          idempotencyKey: `cadivor_manual_invoice_oob_payment_${invoiceRecordId}`,
        });
        if (paidInvoice.status !== "paid" || !paidInvoice.paid_out_of_band ||
            paidInvoice.amount_paid !== invoiceRecord.amount_minor) {
          return response({ ok: false, detail: "The payment was recorded, but Stripe has not confirmed the invoice as paid. Retry after checking Stripe." }, 503, origin);
        }
        const grantResult = await applyOutOfBandManualInvoicePayment(invoiceRecordId, paidInvoice);
        return response({
          ok: true,
          paid: true,
          outcome: grantResult.outcome,
          grant_starts_at: grantResult.grant_starts_at || null,
          grant_ends_at: grantResult.grant_ends_at || null,
        }, 200, origin);
      }

      if (action === "admin_manual_plan_invoice_void") {
        if (invoiceRecord.status !== "open") {
          return response({ ok: false, detail: "Only a finalized, unpaid invoice can be voided. A preparing invoice or recorded payment must be resolved first." }, 409, origin);
        }
        if (invoiceRecord.stripe_invoice_id) {
          const invoice = await stripe.invoices.retrieve(String(invoiceRecord.stripe_invoice_id));
          if (invoice.status === "paid") {
            return response({ ok: false, detail: "This invoice is already paid and cannot be voided." }, 409, origin);
          }
          if (invoice.metadata?.cadivor_manual_plan_invoice_id !== invoiceRecordId ||
              asId(invoice.customer) !== invoiceRecord.stripe_customer_id || invoice.subscription) {
            return response({ ok: false, detail: "Stripe invoice ownership could not be verified. It was not changed." }, 409, origin);
          }
          if (invoice.status === "draft") await stripe.invoices.del(invoice.id);
          else if (invoice.status === "open") await stripe.invoices.voidInvoice(invoice.id);
          else if (invoice.status !== "void") return response({ ok: false, detail: "This invoice can no longer be voided." }, 409, origin);
        }
        const { data: voidData, error: voidError } = await supabase.rpc("cadivor_admin_void_manual_plan_invoice", {
          p_actor_user_id: auth.user.id,
          p_invoice_id: invoiceRecordId,
        });
        if (voidError) throw new Error("Stripe invoice was closed, but Cadivor could not save the void record.");
        const voidResult = (voidData || {}) as Record<string, unknown>;
        if (voidResult.ok !== true) return response({ ok: false, detail: "This invoice can no longer be voided." }, 409, origin);
        return response({ ok: true, voided: true }, 200, origin);
      }

      return response({ ok: false, detail: "Unknown manual billing action." }, 400, origin);
    }

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
      const active = hasCurrentPaidSubscription(profile);
      const manualBilling = await manualBillingStateFor(auth.user.id);
      const effective = manualBilling.activeGrant
        ? { plan: String(manualBilling.activeGrant.plan), trial_status: null, trial_days_remaining: null }
        : effectivePlan(profile);
      const monitoredAddon = await monitoredPartsAddonFor(auth.user.id);
      const monitoredAddonCapacity = active && monitoredAddon.active &&
          ["Starter", "Professional"].includes(effective.plan)
        ? monitoredAddon.capacity
        : 0;
      const storedPriceId = String(profile.stripe_price_id || "").trim();
      const annualPlanPrices = ["STRIPE_STARTER_ANNUAL_PRICE_ID", "STRIPE_PRO_ANNUAL_PRICE_ID", "STRIPE_BUSINESS_ANNUAL_PRICE_ID"]
        .map((name) => String(Deno.env.get(name) || "").trim())
        .filter(Boolean);
      return response({
        ok: true,
        current_plan: effective.plan,
        manual_billing_mode: manualBilling.activeGrant ? "invoice" : manualBilling.pendingInvoice ? "invoice_pending" : null,
        manual_access_ends_at: manualBilling.activeGrant?.grant_ends_at || null,
        manual_invoice_pending: Boolean(manualBilling.pendingInvoice),
        manual_invoice_status: manualBilling.pendingInvoice?.status || null,
        manual_invoice_url: manualBilling.pendingInvoice?.hosted_invoice_url || null,
        manual_invoice_pdf: manualBilling.pendingInvoice?.invoice_pdf || null,
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
        monitored_parts_addon_active: monitoredAddonCapacity > 0,
        monitored_parts_addon_capacity: monitoredAddonCapacity,
        subscription_billing_interval: annualPlanPrices.includes(storedPriceId) ? "year" : "month",
      }, 200, origin);
    }

    if (String(profile.role || "").toLowerCase() === "admin") {
      return response({ ok: false, detail: "Workspace administrators cannot purchase an individual subscription." }, 403, origin);
    }

    if (action === "portal") {
      const manualBilling = await manualBillingStateFor(auth.user.id);
      if (manualBilling.activeGrant || manualBilling.pendingInvoice) {
        return response({
          ok: false,
          code: "manual_billing_mode",
          detail: "This account is billed through a Cadivor invoice. Contact Cadivor to change or renew the plan.",
        }, 409, origin);
      }
      const portal = await createPortal(profile, auth.user.id, origin, supportReference);
      return response(portal, portal.ok ? 200 : 409, origin);
    }

    if (action === "professional_api_addon_checkout") {
      const currentPlan = effectivePlan(profile).plan;
      if (currentPlan !== "Professional" || !hasCurrentPaidSubscription(profile)) {
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

    if (action === "monitored_parts_addon_checkout") {
      const currentPlan = effectivePlan(profile).plan;
      if (!["Starter", "Professional"].includes(currentPlan) || !hasCurrentPaidSubscription(profile)) {
        return response({ ok: false, detail: "The monitored-parts capacity add-on requires an active Starter or Professional subscription." }, 409, origin);
      }
      const interval = body.billing_interval === "year" ? "year" : body.billing_interval === "month" ? "month" : "";
      if (!interval) return response({ ok: false, detail: "Choose monthly or annual billing." }, 400, origin);
      const capacity = positiveUnits("CADIVOR_MONITORED_PARTS_ADDON_CAPACITY");
      const priceEnv = interval === "year"
        ? "STRIPE_MONITORED_PARTS_ANNUAL_PRICE_ID"
        : "STRIPE_MONITORED_PARTS_MONTHLY_PRICE_ID";
      const priceId = String(Deno.env.get(priceEnv) || "").trim();
      if (!capacity || !priceId) {
        return response({ ok: false, detail: "The monitored-parts capacity add-on is not configured for purchase yet." }, 503, origin);
      }
      const configured = await configuredPrice(priceEnv, "recurring", interval);
      const expectedAmount = interval === "year" ? 29000 : 2900;
      if (!configured.enabled || configured.amount !== expectedAmount) {
        return response({ ok: false, detail: "The monitored-parts add-on price needs review before purchase." }, 503, origin);
      }
      const existingAddon = await monitoredPartsAddonFor(auth.user.id);
      if (existingAddon.active) {
        return response({ ok: false, code: "addon_already_active", detail: "Monitored-parts capacity is already active on this account." }, 409, origin);
      }

      let subscription: Stripe.Subscription | null = null;
      const savedSubscriptionId = String(profile.stripe_subscription_id || "").trim();
      if (savedSubscriptionId) {
        try {
          subscription = await stripe.subscriptions.retrieve(savedSubscriptionId);
        } catch (error) {
          if (!isMissingStripeSubscription(error)) throw error;
        }
      }
      if (!subscription || String(subscription.metadata?.user_id || "").trim() !== auth.user.id ||
          subscription.status !== "active" || subscription.cancel_at_period_end) {
        return response({ ok: false, detail: "Cadivor could not verify an active, non-canceling subscription for this account. Open Manage subscription or contact support before adding capacity." }, 409, origin);
      }
      const configuredPlanPrices = planPrices.flatMap((item) => [
        { plan: item.name, interval: "month", price_id: String(Deno.env.get(item.env) || "").trim() },
        { plan: item.name, interval: "year", price_id: String(Deno.env.get(item.annualEnv) || "").trim() },
      ]).filter((item) => item.price_id);
      const planItem = subscription.items.data.find((item) => {
        const id = typeof item.price === "string" ? item.price : item.price.id;
        return configuredPlanPrices.some((candidate) => candidate.price_id === id);
      });
      if (!planItem) {
        return response({ ok: false, detail: "Cadivor could not identify the current plan price for this account. Contact support before changing billing." }, 409, origin);
      }
      const planPriceId = typeof planItem.price === "string" ? planItem.price : planItem.price.id;
      const planPrice = configuredPlanPrices.find((candidate) => candidate.price_id === planPriceId);
      if (!planPrice || planPrice.plan.toLowerCase() !== currentPlan.toLowerCase() || planPrice.interval !== interval) {
        return response({ ok: false, code: "billing_interval_mismatch", detail: "The add-on must renew on the same monthly or annual schedule as your current plan. Choose the matching billing option." }, 409, origin);
      }
      const currentAddonPrices = new Set([
        String(Deno.env.get("STRIPE_MONITORED_PARTS_MONTHLY_PRICE_ID") || "").trim(),
        String(Deno.env.get("STRIPE_MONITORED_PARTS_ANNUAL_PRICE_ID") || "").trim(),
      ].filter(Boolean));
      if (subscription.items.data.some((item) => {
        const id = typeof item.price === "string" ? item.price : item.price.id;
        return currentAddonPrices.has(id);
      })) {
        return response({ ok: false, code: "addon_already_active", detail: "Monitored-parts capacity is already included in this subscription." }, 409, origin);
      }

      const userId = auth.user.id;
      const item = await stripe.subscriptionItems.create({
        subscription: subscription.id,
        price: priceId,
        quantity: 1,
        proration_behavior: "create_prorations",
        metadata: { cadivor_addon: "monitored_parts_capacity", user_id: userId },
      }, { idempotencyKey: `cadivor_monitored_parts_${userId}_${subscription.id}_${priceId}_${supportReference}` });
      const { data: applied, error: applyError } = await supabase.rpc("cadivor_set_monitored_parts_addon", {
        p_user_id: userId,
        p_subscription_id: subscription.id,
        p_price_id: priceId,
        p_status: subscription.status,
        p_capacity: capacity,
        p_event_created: new Date().toISOString(),
      });
      if (applyError || applied !== "applied") {
        console.error("monitored_parts_addon_entitlement_sync_failed", {
          subscription_id: subscription.id,
          subscription_item_id: item.id,
          error_code: applyError?.code || null,
        });
        return response({ ok: false, detail: "The capacity add-on was added, but Cadivor could not confirm the entitlement yet. Refresh billing status or contact support." }, 503, origin);
      }
      return response({
        ok: true,
        addon_added: true,
        capacity,
        billing_interval: interval,
        detail: "Monitored-parts capacity is active. Any partial-period charge is included on your next subscription invoice.",
      }, 200, origin);
    }

    if (action === "monitored_parts_addon_remove") {
      const addon = await monitoredPartsAddonFor(auth.user.id);
      if (!addon.active || !addon.subscription_id || !addon.price_id) {
        return response({ ok: false, detail: "There is no active monitored-parts capacity add-on to remove." }, 409, origin);
      }
      const subscription = await stripe.subscriptions.retrieve(addon.subscription_id);
      if (String(subscription.metadata?.user_id || "").trim() !== auth.user.id ||
          !["active", "trialing"].includes(subscription.status)) {
        return response({ ok: false, detail: "Cadivor could not verify the subscription that owns this add-on. Contact support before changing billing." }, 409, origin);
      }
      const addonItem = subscription.items.data.find((item) => {
        const itemPriceId = typeof item.price === "string" ? item.price : item.price.id;
        return itemPriceId === addon.price_id || String(item.metadata?.cadivor_addon || "") === "monitored_parts_capacity";
      });
      if (!addonItem) {
        return response({ ok: false, detail: "The current subscription no longer lists this add-on. Refresh billing status or contact support." }, 409, origin);
      }
      await stripe.subscriptionItems.del(addonItem.id, { proration_behavior: "create_prorations" });
      const { data: removed, error: removeError } = await supabase.rpc("cadivor_set_monitored_parts_addon", {
        p_user_id: auth.user.id,
        p_subscription_id: subscription.id,
        p_price_id: addon.price_id,
        p_status: "canceled",
        p_capacity: addon.capacity,
        p_event_created: new Date().toISOString(),
      });
      if (removeError || removed !== "applied") {
        console.error("monitored_parts_addon_removal_sync_failed", {
          subscription_id: subscription.id,
          subscription_item_id: addonItem.id,
          error_code: removeError?.code || null,
        });
        return response({ ok: false, detail: "The add-on was removed, but Cadivor could not update its entitlement yet. Refresh billing status or contact support." }, 503, origin);
      }
      return response({
        ok: true,
        addon_removed: true,
        detail: "Monitored-parts capacity was removed. Any unused time is prorated on your next subscription invoice.",
      }, 200, origin);
    }

    if (action === "usage_overage_checkout") {
      const currentPlan = effectivePlan(profile).plan;
      if (!["Starter", "Professional", "Business"].includes(currentPlan) ||
          !hasCurrentPaidSubscription(profile)) {
        return response({ ok: false, detail: "Usage overage packs require an active paid subscription." }, 409, origin);
      }
      const kind = String(body.credit_kind || "").trim();
      const item = kind === "bom_analysis"
        ? { priceEnv: "STRIPE_BOM_ANALYSIS_OVERAGE_PRICE_ID", unitsEnv: "CADIVOR_BOM_ANALYSIS_OVERAGE_CREDITS" }
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
    const manualBilling = await manualBillingStateFor(auth.user.id);
    if (manualBilling.activeGrant || manualBilling.pendingInvoice) {
      return response({
        ok: false,
        code: "manual_billing_mode",
        detail: "This account has a Cadivor invoice or invoice-funded plan. Use the invoice link to pay, or contact Cadivor to change the plan.",
      }, 409, origin);
    }
    const token = String(body.plan || "").trim().toLowerCase();
    const billingInterval = body.billing_interval === "year" ? "year" : "month";
    planToken = token || "unknown";
    const plan = planPrices.find((item) => item.token === token);
    if (!plan) return response({ ok: false, detail: "Choose Starter, Professional, or Business." }, 400, origin);

    // A user's local profile can outlive the Stripe subscription it originally
    // described. Verify against the active Stripe account before blocking a
    // new purchase; do not let stale test-mode IDs strand a production account.
    const activeSubscriptions: Stripe.Subscription[] = [];
    try {
      for (const status of ["active", "trialing"] as const) {
        const result = await stripe.subscriptions.search({
          query: "status:'" + status + "' AND metadata['user_id']:'" + auth.user.id + "'",
          limit: 2,
        });
        activeSubscriptions.push(...result.data);
        if (activeSubscriptions.length > 1) break;
      }
    } catch (error) {
      const summary = stripeErrorSummary(error);
      console.error("subscription_checkout_existing_subscription_check_failed", {
        reference: supportReference,
        error_type: summary.type,
        error_code: summary.code,
        error_status: summary.statusCode,
        stripe_request_id: summary.requestId,
      });
      return response({
        ok: false,
        code: "billing_subscription_unverified",
        detail: "Cadivor couldn't verify whether this account already has a subscription. No new subscription was started. Please retry or contact support.",
        support_reference: supportReference,
      }, 503, origin);
    }
    const uniqueActiveSubscriptions = [...new Map(activeSubscriptions.map((item) => [item.id, item])).values()];
    if (uniqueActiveSubscriptions.length > 1) {
      return response({
        ok: false,
        code: "billing_subscription_ambiguous",
        detail: "More than one active subscription is linked to this account. No new subscription was started. Contact support.",
        support_reference: supportReference,
      }, 409, origin);
    }
    if (uniqueActiveSubscriptions.length === 1) {
      const existing = uniqueActiveSubscriptions[0];
      const customerId = typeof existing.customer === "string"
        ? existing.customer
        : existing.customer?.id || "";
      if (String(existing.metadata?.user_id || "").trim() !== auth.user.id || !customerId) {
        return response({
          ok: false,
          code: "billing_subscription_unverified",
          detail: "Cadivor couldn't verify the active subscription linked to this account. No new subscription was started. Contact support.",
          support_reference: supportReference,
        }, 409, origin);
      }
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
      stage: supportStage,
      error_name: error instanceof Error ? error.name : typeof error,
      error_type: summary.type,
      error_code: summary.code,
      error_status: summary.statusCode,
      error_param: summary.param,
      stripe_request_id: summary.requestId,
      error_message: safeSupportMessage(summary.message),
    });
    const detail = action === "admin_manual_plan_invoice_create"
      ? `Invoice setup did not finish. No access was granted or invoice email sent. Refresh this profile; if an incomplete invoice appears, use Resume invoice setup. Reference: ${supportReference}.`
      : "Billing could not be started. Please try again or contact support.";
    return response({
      ok: false,
      code: "checkout_unavailable",
      detail,
      support_reference: supportReference,
    }, 503, origin);
  }
});
