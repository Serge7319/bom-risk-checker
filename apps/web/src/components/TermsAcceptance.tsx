"use client";

import { useId, useState } from "react";
import {
  CADIVOR_TERMS_SECTIONS,
  PRIVACY_URL,
  TERMS_SUMMARY,
  TERMS_URL,
} from "@/lib/legalTerms";

type Props = {
  checked: boolean;
  onChange: (accepted: boolean) => void;
  disabled?: boolean;
};

export function TermsAcceptance({ checked, onChange, disabled = false }: Props) {
  const checkboxId = useId();
  const [open, setOpen] = useState(false);

  return (
    <div className="cv-terms">
      <div className="cv-terms-box" role="note">
        <strong>Terms summary:</strong> {TERMS_SUMMARY}
      </div>
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
      <button
        type="button"
        className="cv-terms-toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "Hide Terms of Service" : "View Terms of Service"}
      </button>
      {open ? (
        <div className="cv-terms-full" role="region" aria-label="Terms of Service">
          <p className="cv-terms-meta">
            Pre-launch version — Last updated July 25, 2026. By creating an
            account, checking the acceptance box during registration, or using
            Cadivor, you agree to these Terms and the Privacy Policy.
          </p>
          {CADIVOR_TERMS_SECTIONS.map((section) => (
            <section key={section.title}>
              <h3>{section.title}</h3>
              <p>{section.body}</p>
            </section>
          ))}
          <p className="cv-terms-meta">
            This pre-launch version requires review by qualified counsel and
            completion with Cadivor’s legal entity name, business address,
            governing law, payment and refund terms, dispute process, and
            enterprise-specific provisions before commercial launch.
          </p>
        </div>
      ) : null}
    </div>
  );
}
