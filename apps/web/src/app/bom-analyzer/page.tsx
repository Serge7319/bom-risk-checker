"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Shell } from "@/components/Shell";
import {
  analyzeBom,
  getSession,
  type AnalyzeSummary,
  type Session,
} from "@/lib/api";

export default function BomAnalyzerPage() {
  const router = useRouter();
  const [session, setLocalSession] = useState<Session | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState<AnalyzeSummary | null>(null);

  useEffect(() => {
    const current = getSession();
    if (!current) {
      router.replace("/login");
      return;
    }
    setLocalSession(current);
  }, [router]);

  async function onAnalyze() {
    if (!session || !file) return;
    setBusy(true);
    setError("");
    setSummary(null);
    try {
      const result = await analyzeBom(file, session.access_token);
      setSummary(result);
      router.push(`/reports/${result.analysis_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analyze failed");
      setBusy(false);
    }
  }

  if (!session) return null;

  return (
    <Shell session={session}>
      <section className="cv-hero cv-card">
        <h1>BOM Analyzer</h1>
        <p>
          Upload a synthetic BOM CSV, run the existing Python parse/risk/health
          path through the migration API, and open the report. Distributors,
          Stripe, and email stay disabled.
        </p>
      </section>

      <section className="cv-card" style={{ marginTop: 16 }}>
        <h2 style={{ marginTop: 0, fontSize: 18 }}>New analysis</h2>
        <input
          type="file"
          accept=".csv,.xlsx"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
          <button
            type="button"
            className="cv-button"
            disabled={!file || busy}
            onClick={onAnalyze}
          >
            {busy ? "Analyzing…" : "Analyze"}
          </button>
        </div>
        {busy ? (
          <div>
            <div className="cv-progress" aria-hidden>
              <i />
            </div>
            <p style={{ color: "#64748b", fontSize: 13, marginTop: 10 }}>
              Running synthetic analysis with production risk and health modules…
            </p>
          </div>
        ) : null}
        {error ? <div className="cv-error">{error}</div> : null}
        {summary ? (
          <p style={{ marginTop: 12, fontSize: 13 }}>
            Prepared report {summary.analysis_id} · {summary.total_parts} parts
          </p>
        ) : null}
      </section>
    </Shell>
  );
}
