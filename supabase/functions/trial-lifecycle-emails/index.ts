import { serve } from "https://deno.land/std@0.224.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
const cronToken = Deno.env.get("CADIVOR_TRIAL_EMAIL_CRON_TOKEN") || "";
const resendKey = Deno.env.get("RESEND_API_KEY") || "";
const fromEmail = Deno.env.get("TRANSACTIONAL_FROM_EMAIL") || Deno.env.get("CADIVOR_FROM_EMAIL") || "";
const enabled = String(Deno.env.get("CADIVOR_TRIAL_EMAIL_SEQUENCE_ENABLED") || "")
  .trim().toLowerCase() === "true";
const launchAtRaw = String(Deno.env.get("CADIVOR_TRIAL_EMAIL_SEQUENCE_LAUNCH_AT") || "").trim();

if (!supabaseUrl || !serviceRoleKey) {
  throw new Error("Trial email service configuration is incomplete.");
}

const supabase = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});

const milestones = [
  {
    key: "day_0",
    day: 0,
    subject: "Welcome to Cadivor — start with a BOM",
    title: "Find your first blocker",
    body: "Upload a BOM or load the sample BOM in Cadivor. Review the first high-priority finding, then follow the evidence to decide what needs attention.",
    cta: "Open BOM Analyzer",
  },
  {
    key: "day_2",
    day: 2,
    subject: "A sample BOM is ready if you need one",
    title: "Try the workflow with a sample",
    body: "You can explore Cadivor without preparing a file first. Load the sample BOM, review its highest-priority finding, and ask Cadivor a question about the evidence.",
    cta: "Load the sample BOM",
  },
  {
    key: "day_7",
    day: 7,
    subject: "Turn a BOM finding into a decision",
    title: "Keep the reasoning with the report",
    body: "Create a decision record to capture the action, owner, and evidence behind a release choice. Then opt a BOM into monitoring if you need to watch for later changes.",
    cta: "Continue in Cadivor",
  },
  {
    key: "day_12",
    day: 12,
    subject: "Your Cadivor trial ends in two days",
    title: "Keep your engineering work moving",
    body: "Your 14-day trial is nearing its end. Review your saved analyses and choose a plan if you want to keep using the full workflow and optional monitoring.",
    cta: "Review plans and billing",
  },
] as const;

function response(body: unknown, status = 200) {
  return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

function esc(value: string): string {
  return value.replace(/[&<>\"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[char] || char);
}

function launchDate(): Date | null {
  if (!launchAtRaw) return null;
  const parsed = new Date(launchAtRaw);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function htmlFor(item: typeof milestones[number]): string {
  const path = item.key === "day_12" ? "/settings?tab=billing" : "/bom-analyzer";
  const url = `https://app.cadivor.com${path}`;
  return `<div style="font-family:Arial,sans-serif;color:#14263d;line-height:1.6;max-width:620px;margin:auto">
    <p style="color:#526f94;font-size:12px;font-weight:700;letter-spacing:.12em">CADIVOR · TRIAL GUIDE</p>
    <h1 style="font-size:26px;line-height:1.25">${esc(item.title)}</h1>
    <p>${esc(item.body)}</p>
    <p style="margin:26px 0"><a href="${url}" style="background:#245fe8;color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:700">${esc(item.cta)}</a></p>
    <p style="font-size:12px;color:#66758a">These messages help you use your Cadivor trial. Manage your account and notification settings in Cadivor.</p>
  </div>`;
}

async function sendEmail(to: string, item: typeof milestones[number]): Promise<void> {
  if (!resendKey || !fromEmail) throw new Error("email_delivery_not_configured");
  const result = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${resendKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: fromEmail,
      to: [to],
      subject: item.subject,
      html: htmlFor(item),
      text: `${item.title}\n\n${item.body}\n\n${item.cta}: https://app.cadivor.com${item.key === "day_12" ? "/settings?tab=billing" : "/bom-analyzer"}`,
      reply_to: Deno.env.get("EMAIL_REPLY_TO") || "support@cadivor.com",
    }),
  });
  if (!result.ok) throw new Error(`email_provider_http_${result.status}`);
}

async function main() {
  if (!enabled) return response({ ok: true, status: "disabled", sent: 0, skipped: 0 });
  if (!cronToken || !resendKey || !fromEmail) {
    return response({ ok: false, status: "blocked", reason: "email_or_cron_configuration_missing" }, 503);
  }
  const launched = launchDate();
  if (!launched) {
    return response({ ok: false, status: "blocked", reason: "launch_timestamp_missing_or_invalid" }, 503);
  }

  let page = 1;
  let sent = 0;
  let skipped = 0;
  let failures = 0;
  const perPage = 200;
  const now = Date.now();

  while (page <= 100) {
    const { data: authPage, error: authError } = await supabase.auth.admin.listUsers({ page, perPage });
    if (authError) throw new Error("trial_user_list_failed");
    const authUsers = authPage.users || [];
    if (!authUsers.length) break;
    const ids = authUsers.map((user) => user.id);
    const { data: profiles, error: profileError } = await supabase
      .from("users")
      .select("id,plan,role,trial_started_at,trial_ends_at,stripe_subscription_status")
      .in("id", ids);
    if (profileError) throw new Error("trial_profile_read_failed");
    const profilesById = new Map((profiles || []).map((profile) => [profile.id, profile]));

    for (const user of authUsers) {
      const profile = profilesById.get(user.id);
      const email = String(user.email || "").trim();
      const confirmed = Boolean(user.email_confirmed_at || user.confirmed_at);
      const plan = String(profile?.plan || "").trim().toLowerCase();
      const status = String(profile?.stripe_subscription_status || "").trim().toLowerCase();
      const start = profile?.trial_started_at ? new Date(String(profile.trial_started_at)) : null;
      const end = profile?.trial_ends_at ? new Date(String(profile.trial_ends_at)) : null;
      if (!email || !confirmed || plan !== "trial" || String(profile?.role || "").toLowerCase() === "admin" ||
          !start || Number.isNaN(start.getTime()) || start < launched ||
          !end || Number.isNaN(end.getTime()) || now >= end.getTime() ||
          ["active", "trialing"].includes(status)) {
        skipped += 1;
        continue;
      }
      const ageDays = (now - start.getTime()) / 86_400_000;
      const due = [...milestones].reverse().find((item) => ageDays >= item.day);
      if (!due) {
        skipped += 1;
        continue;
      }
      const { data: claimed, error: claimError } = await supabase.rpc("cadivor_claim_trial_lifecycle_email", {
        p_user_id: user.id,
        p_milestone: due.key,
        p_lease_seconds: 900,
      });
      if (claimError) throw new Error("trial_email_claim_failed");
      if (claimed !== true) {
        skipped += 1;
        continue;
      }
      try {
        await sendEmail(email, due);
        const { error: finishError } = await supabase.rpc("cadivor_finish_trial_lifecycle_email", {
          p_user_id: user.id,
          p_milestone: due.key,
          p_delivered: true,
          p_error: null,
        });
        if (finishError) throw new Error("trial_email_delivery_record_failed");
        sent += 1;
      } catch (error) {
        await supabase.rpc("cadivor_finish_trial_lifecycle_email", {
          p_user_id: user.id,
          p_milestone: due.key,
          p_delivered: false,
          p_error: error instanceof Error ? error.message : "delivery_failed",
        });
        failures += 1;
      }
    }
    if (authUsers.length < perPage) break;
    page += 1;
  }
  return response({ ok: failures === 0, status: failures === 0 ? "complete" : "completed_with_failures", sent, skipped, failures });
}

serve(async (request) => {
  if (request.method !== "POST") return response({ ok: false, detail: "Method not allowed." }, 405);
  if (!cronToken || request.headers.get("x-cadivor-trial-cron-token") !== cronToken) {
    return response({ ok: false, detail: "Unauthorized." }, 401);
  }
  try {
    return await main();
  } catch {
    // Never log recipient addresses, provider responses, or configuration values.
    console.error("trial_lifecycle_email_run_failed");
    return response({ ok: false, status: "failed", reason: "trial_email_run_failed" }, 500);
  }
});
