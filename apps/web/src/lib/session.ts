"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getSession,
  type AnalyzeSummary,
  type Session,
} from "@/lib/api";

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

