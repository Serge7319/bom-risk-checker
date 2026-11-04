"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Shell } from "@/components/Shell";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { analyzeBom, type AnalyzeSummary } from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { rememberAnalysis, useRequireSession } from "@/lib/session";

const STAGES = [
  "Received",
  "Validating",
  "Analyzing",
  "Risks",
  "Evidence",
  "Decision",
  "Monitor",
] as const;

export default function BomAnalyzerPage() {
  const router = useRouter();
  const session = useRequireSession();
  const [file, setFile] = useState<File | null>(null);
  const [projectName, setProjectName] = useState("Demo Product Line");
  const [bomName, setBomName] = useState("");
  const [revision, setRevision] = useState("A");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [summary, setSummary] = useState<AnalyzeSummary | null>(null);

  async function onAnalyze() {
    if (!session || !file) return;
    setBusy(true);
    setError("");
    setSummary(null);
    try {
      const result = await analyzeBom(file, session.access_token, {
        projectName: projectName.trim() || undefined,
        bomName: bomName.trim() || file.name.replace(/\.(csv|xlsx)$/i, ""),
        revision: revision.trim() || "A",
      });
      rememberAnalysis({ ...result, filename: file.name });
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
      <PageHeader
        meta={PAGE_META.bom}
        actions={
          <>
            <button
              type="button"
              className="cv-button primary"
              disabled={!file || busy}
              onClick={onAnalyze}
            >
              {busy ? "Analyzing…" : "Run analysis"}
            </button>
            <SecondaryLink href="/reports">Saved analyses</SecondaryLink>
          </>
        }
      />

      <section className="cv-card pad" style={{ marginBottom: 16 }}>
        <div className="cv-eyebrow">Persistent workflow · migration API</div>
        <h3 className="cv-card-title" style={{ fontSize: 18 }}>
          {file ? file.name : "Upload a BOM to begin"}
        </h3>
        <p className="cv-card-subtitle">
          Saves project, BOM, revision, and analysis in the migration workspace
          store. Nested Parent MPN rows roll risk to assemblies. Distributors,
          Stripe, and email stay disabled.
        </p>

        <div className="cv-bom-stages" style={{ marginTop: 14 }}>
          {STAGES.map((stage) => (
            <span
              key={stage}
              className={`cv-bom-stage${busy && stage === "Analyzing" ? " active" : ""}${!busy && !summary && stage === "Received" ? " active" : ""}${summary && stage === "Decision" ? " active" : ""}`}
            >
              {stage}
            </span>
          ))}
        </div>
        <div className="cv-bom-progress" aria-hidden>
          <i style={{ width: busy ? "55%" : summary ? "85%" : "12%" }} />
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 12,
            marginTop: 16,
          }}
        >
          <label className="cv-field">
            <span>Project</span>
            <input
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="Project name"
            />
          </label>
          <label className="cv-field">
            <span>BOM name</span>
            <input
              value={bomName}
              onChange={(e) => setBomName(e.target.value)}
              placeholder="Defaults to filename"
            />
          </label>
          <label className="cv-field">
            <span>Revision</span>
            <input
              value={revision}
              onChange={(e) => setRevision(e.target.value)}
              placeholder="A"
            />
          </label>
        </div>

        <div className="cv-upload-zone">
          <h3>New analysis</h3>
          <p>
            Flat BOMs still work. For roll-up, include Parent MPN and Line Type
            (assembly|part) columns.
          </p>
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
          <div
            style={{
              display: "flex",
              gap: 10,
              justifyContent: "center",
              marginTop: 14,
            }}
          >
            <button
              type="button"
              className="cv-button primary"
              disabled={!file || busy}
              onClick={onAnalyze}
            >
              {busy ? "Analyzing…" : "Analyze BOM"}
            </button>
            <PrimaryLink href="/">Back to Home</PrimaryLink>
          </div>
        </div>

        {busy ? (
          <div className="cv-loading" style={{ marginTop: 14 }}>
            Running synthetic analysis and saving to workspace store…
            <div className="cv-progress" aria-hidden>
              <i />
            </div>
          </div>
        ) : null}
        {error ? <div className="cv-error">{error}</div> : null}
        {summary ? (
          <p className="cv-small-note" style={{ marginTop: 12 }}>
            Saved {summary.project_name || summary.analysis_id}
            {summary.has_hierarchy
              ? ` · assembly roll-up ${summary.top_rolled_risk || "n/a"}`
              : ""}{" "}
            · {summary.total_parts} parts · health {summary.health_score ?? "—"}
          </p>
        ) : null}
      </section>
    </Shell>
  );
}
