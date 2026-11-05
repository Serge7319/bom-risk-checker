export function GapBanner({ children }: { children: React.ReactNode }) {
  return (
    <div className="cv-decision-banner" role="note">
      <div>
        <strong>Capability note</strong>
        <span>{children}</span>
      </div>
    </div>
  );
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
