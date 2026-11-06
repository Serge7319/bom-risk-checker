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
  const [projectName, setProjectName] = useState("");
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
      rememberAnalysis({ ...result, filename: file.name }, session);
      setSummary(result);
      router.push(`/reports/${result.analysis_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analyze failed");
      setBusy(false);
    }
  }

  if (!session) return null;

  const activeStage = busy
    ? "Analyzing"
    : summary
      ? "Decision"
      : file
        ? "Validating"
        : "Received";

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

      <section
        className="cv-bom-progress-sticky"
        aria-live="polite"
        aria-busy={busy}
      >
        <div className="cv-eyebrow">BOM progress</div>
        <div className="cv-bom-stages">
          {STAGES.map((stage) => (
            <span
              key={stage}
              className={`cv-bom-stage${stage === activeStage ? " active" : ""}`}
            >
              {stage}
            </span>
          ))}
        </div>
        <div className="cv-bom-progress" aria-hidden>
          <i style={{ width: busy ? "55%" : summary ? "85%" : file ? "28%" : "12%" }} />
        </div>
        {busy ? (
          <div className="cv-loading" style={{ marginTop: 12, border: 0, padding: "10px 0 0" }}>
            Analyzing the BOM with available evidence and saving it to your workspace…
          </div>
        ) : null}
        {error ? <div className="cv-error" style={{ marginTop: 10 }}>{error}</div> : null}
        {summary ? (
          <p className="cv-small-note" style={{ marginTop: 10 }}>
            Saved {summary.project_name || summary.analysis_id}
            {summary.has_hierarchy
              ? ` · assembly roll-up ${summary.top_rolled_risk || "n/a"}`
              : ""}{" "}
            · {summary.total_parts} parts · health {summary.health_score ?? "—"}
          </p>
        ) : null}
      </section>

      <section className="cv-card pad" style={{ marginBottom: 16 }}>
        <div className="cv-eyebrow">Persistent BOM workflow</div>
        <h3 className="cv-card-title" style={{ fontSize: 18 }}>
          {file ? file.name : "Upload a BOM to begin"}
        </h3>
        <p className="cv-card-subtitle">
          Each run saves a report you can reopen from Saved analyses. Parent MPN
          and Line Type columns enable assembly risk roll-up.
        </p>

        <div
          className="cv-bom-fields"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 12,
            marginTop: 16,
          }}
        >
          <label className="cv-field">
          <span>Project name</span>
            <input
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="e.g. Motor controller"
            />
          </label>
          <label className="cv-field">
            <span>BOM name</span>
            <input
              value={bomName}
              onChange={(e) => setBomName(e.target.value)}
              placeholder="Optional · defaults to filename"
            />
          </label>
          <label className="cv-field">
            <span>Revision</span>
            <input
              value={revision}
              onChange={(e) => setRevision(e.target.value)}
              placeholder="e.g. A"
            />
          </label>
        </div>

        <div className="cv-upload-zone cv-bom-upload-zone">
          <h3>New analysis</h3>
          <p>
            Upload a CSV or XLSX BOM. Add Parent MPN and Line Type columns when
            you want to roll component risk up to assemblies.
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
            <PrimaryLink href="/reports">Saved analyses</PrimaryLink>
          </div>
        </div>
      </section>
    </Shell>
  );
}

