"use client";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { signupConfirmCallbackInUrl } from "@/lib/signupEmailConfirm";

let browserClient: SupabaseClient | null = null;

/** Create one browser Auth client so refresh-token rotation stays coordinated. */
export function getSupabaseBrowserClient(): SupabaseClient | null {
  if (typeof window === "undefined") return null;

  const url = (process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
  const key = (
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
    ""
  ).trim();
  if (!url || !key) return null;

  if (!browserClient) {
    // Signup confirm links use token_hash in the query. Do not let the Auth
    // client auto-consume the URL on load — Cadivor verifies only after click.
    const detectSessionInUrl = !signupConfirmCallbackInUrl(
      new URLSearchParams(window.location.search),
    );
    browserClient = createClient(url, key, {
      auth: {
        autoRefreshToken: true,
        persistSession: true,
        detectSessionInUrl,
        flowType: "pkce",
      },
    });
  }

  return browserClient;
}
