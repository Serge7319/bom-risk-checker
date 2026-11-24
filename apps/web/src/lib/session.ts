"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getSession,
  LEGACY_SESSION_KEY,
  SESSION_KEY,
  type AnalyzeSummary,
  type Session,
} from "@/lib/api";
import { getSupabaseBrowserClient } from "@/lib/supabase";

const LAST_ANALYSIS_KEY = "cadivor_next_last_analysis";

function lastAnalysisKey(session?: Pick<Session, "user_id" | "email">): string {
  const identity = session?.user_id || session?.email?.trim().toLowerCase();
  return identity ? `${LAST_ANALYSIS_KEY}:${identity}` : LAST_ANALYSIS_KEY;
}

export function useRequireSession(): Session | null {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    const current = getSession();
    if (!current) {
      router.replace("/login");
      return;
    }
    setSession(current);
  }, [router]);

  useEffect(() => {
    function syncSessionAcrossTabs(event: StorageEvent) {
      if (
        event.key !== null &&
        event.key !== SESSION_KEY &&
        event.key !== LEGACY_SESSION_KEY
      ) {
        return;
      }
      const current = getSession();
      setSession(current);
      if (!current) router.replace("/login");
    }
    window.addEventListener("storage", syncSessionAcrossTabs);
    return () => window.removeEventListener("storage", syncSessionAcrossTabs);
  }, [router]);

  useEffect(() => {
    const client = getSupabaseBrowserClient();
    if (!client) return;
    const { data } = client.auth.onAuthStateChange((_event, authSession) => {
      // The app's display session and Supabase's refresh-token session are
      // stored separately. If a second tab changes accounts, discard the old
      // app snapshot instead of rendering admin controls for a different JWT.
      window.setTimeout(() => {
        const current = getSession();
        if (!current) {
          setSession(null);
          router.replace("/login");
          return;
        }

        const authUser = authSession?.user;
        const matches = Boolean(
          authUser &&
            (current.user_id
              ? current.user_id === authUser.id
              : current.email.trim().toLowerCase() ===
                (authUser.email || "").trim().toLowerCase()),
        );
        if (matches) return;

        // Keep Supabase's newly selected account intact so the user can sign
        // in again; remove only Cadivor's stale UI snapshot.
        window.localStorage.removeItem(SESSION_KEY);
        window.localStorage.removeItem(LEGACY_SESSION_KEY);
        setSession(null);
        router.replace("/login?reason=session-refresh");
      }, 0);
    });
    return () => data.subscription.unsubscribe();
  }, [router]);

  return session;
}

export function rememberAnalysis(
  summary: AnalyzeSummary & { filename?: string },
  session?: Pick<Session, "user_id" | "email">,
) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(
    lastAnalysisKey(session),
    JSON.stringify({ ...summary, saved_at: new Date().toISOString() }),
  );
}

export function readLastAnalysis(session?: Pick<Session, "user_id" | "email">):
  | (AnalyzeSummary & { filename?: string; saved_at?: string })
  | null {
  if (typeof window === "undefined") return null;
  try {
    // Never reuse a previous account's report context after switching accounts.
    // The unscoped key is read only for legacy callers without an active session.
    const raw = window.localStorage.getItem(lastAnalysisKey(session));
    return raw
      ? (JSON.parse(raw) as AnalyzeSummary & {
          filename?: string;
          saved_at?: string;
        })
      : null;
  } catch {
    return null;
  }
}

