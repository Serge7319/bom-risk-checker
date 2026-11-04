"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  getSession,
  type AnalyzeSummary,
  type Session,
} from "@/lib/api";

const LAST_ANALYSIS_KEY = "cadivor_next_last_analysis";

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

export function rememberAnalysis(summary: AnalyzeSummary & { filename?: string }) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(
    LAST_ANALYSIS_KEY,
    JSON.stringify({ ...summary, saved_at: new Date().toISOString() }),
  );
}

export function readLastAnalysis():
  | (AnalyzeSummary & { filename?: string; saved_at?: string })
  | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LAST_ANALYSIS_KEY);
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
