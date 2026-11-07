"use client";

import { useId, useState } from "react";
import {
  PRIVACY_URL,
  PUBLISHED_PRIVACY,
  PUBLISHED_TERMS,
  TERMS_URL,
} from "@/lib/legalTerms";

type Props = {
  checked: boolean;
  onChange: (accepted: boolean) => void;
  disabled?: boolean;
};

export function TermsAcceptance({ checked, onChange, disabled = false }: Props) {
  const checkboxId = useId();
  const [open, setOpen] = useState<"terms" | "privacy" | null>(null);

  return (
    <div className="cv-terms">
      <label className="cv-terms-check" htmlFor={checkboxId}>
        <input
          id={checkboxId}
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          required
        />
        <span>
          I agree to the{" "}
          <a href={TERMS_URL} target="_blank" rel="noopener noreferrer">
            Terms of Service
          </a>{" "}
          and{" "}
          <a href={PRIVACY_URL} target="_blank" rel="noopener noreferrer">
            Privacy Policy
          </a>
          .
        </span>
      </label>
      <div className="cv-terms-actions">
        <button
          type="button"
          className="cv-terms-toggle"
          aria-expanded={open === "terms"}
          onClick={() => setOpen((value) => (value === "terms" ? null : "terms"))}
        >
          {open === "terms" ? "Hide Terms of Service" : "View Terms of Service"}
        </button>
        <button
          type="button"
          className="cv-terms-toggle"
          aria-expanded={open === "privacy"}
          onClick={() =>
            setOpen((value) => (value === "privacy" ? null : "privacy"))
          }
        >
          {open === "privacy" ? "Hide Privacy Policy" : "View Privacy Policy"}
        </button>
      </div>
      {open === "terms" ? (
        <div className="cv-terms-full" role="region" aria-label="Terms of Service">
          <h3>{PUBLISHED_TERMS.title}</h3>
          <p className="cv-terms-meta">{PUBLISHED_TERMS.subtitle}</p>
          {PUBLISHED_TERMS.sections.map((section) => (
            <section key={section.title}>
              <h4>{section.title}</h4>
              <p>{section.body}</p>
            </section>
          ))}
        </div>
      ) : null}
      {open === "privacy" ? (
        <div className="cv-terms-full" role="region" aria-label="Privacy Policy">
          <h3>{PUBLISHED_PRIVACY.title}</h3>
          <p className="cv-terms-meta">{PUBLISHED_PRIVACY.subtitle}</p>
          {PUBLISHED_PRIVACY.sections.map((section) => (
            <section key={section.title}>
              <h4>{section.title}</h4>
              <p>{section.body}</p>
            </section>
          ))}
        </div>
      ) : null}
    </div>
  );
}
