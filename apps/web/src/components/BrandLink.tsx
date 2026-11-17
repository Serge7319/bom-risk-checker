import Link from "next/link";

export function BrandLink({
  href,
  ariaLabel,
  compact = false,
}: {
  href: string;
  ariaLabel: string;
  compact?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`cv-brand${compact ? " cv-brand-auth" : ""}`}
      aria-label={ariaLabel}
      style={compact ? { marginBottom: 18, paddingBottom: 0 } : undefined}
    >
      <span className="cv-mark" aria-hidden>
        C
      </span>
      <span>
        <strong>Cadivor</strong>
        <small>Engineering Intelligence</small>
      </span>
    </Link>
  );
}
