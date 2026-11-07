import {
  classifyEvidenceNotice,
  compactContextLabel,
  type EvidenceNoticeTone,
} from "@/lib/evidenceNotice";

export function GapBanner({
  children,
  tone = "critical",
}: {
  children: React.ReactNode;
  tone?: Exclude<EvidenceNoticeTone, "hide" | "service">;
}) {
  if (tone === "context") {
    return (
      <p className="cv-evidence-context" role="note">
        {children}
      </p>
    );
  }
  return (
    <div className="cv-decision-banner" role="note">
      <div>
        <strong>Evidence note</strong>
        <span>{children}</span>
      </div>
    </div>
  );
}

/** Auto-classify gap text: critical stays amber, routine becomes a compact note, service gaps are omitted. */
export function EvidenceNotice({
  gap,
  forceTone,
}: {
  gap: unknown;
  forceTone?: Exclude<EvidenceNoticeTone, "hide" | "service">;
}) {
  const text = typeof gap === "string" ? gap.trim() : "";
  if (!text) return null;
  const tone = forceTone || classifyEvidenceNotice(text);
  if (tone === "hide" || tone === "service") return null;
  if (tone === "context") {
    return <GapBanner tone="context">{compactContextLabel(text)}</GapBanner>;
  }
  return <GapBanner tone="critical">{text}</GapBanner>;
}

export function LoadingCard({ label }: { label: string }) {
  return (
    <section className="cv-loading">
      {label}
      <div className="cv-progress" aria-hidden>
        <i />
      </div>
    </section>
  );
}
