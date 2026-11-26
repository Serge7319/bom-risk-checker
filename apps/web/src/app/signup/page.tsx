"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { fetchAuthConfig, signup } from "@/lib/api";
import { TermsAcceptance } from "@/components/TermsAcceptance";
import { BrandLink } from "@/components/BrandLink";
import { PRIVACY_VERSION, TERMS_VERSION } from "@/lib/legalTerms";
import { cleanUserText } from "@/lib/display";
import { captureMarketingAttribution, trackMarketingEvent } from "@/lib/marketingAnalytics";

const MIN_PASSWORD_LENGTH = 12;

export default function SignupPage() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [workspaceName, setWorkspaceName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const passwordCharacterCount = Array.from(password).length;
  const passwordMeetsMinimum = passwordCharacterCount >= MIN_PASSWORD_LENGTH;

  useEffect(() => {
    fetchAuthConfig()
      .then((config) => setEnabled(config.signup_enabled))
      .catch(() => setEnabled(false));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setMessage("");
    if (!passwordMeetsMinimum) {
      setError(`Use a password with at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (password !== confirmPassword) {
      setError("The passwords do not match.");
      return;
    }
    if (!acceptedTerms) {
      setError("Agree to the Terms of Service and Privacy Policy to continue.");
      return;
    }
    setBusy(true);
    trackMarketingEvent("signup_started", { intent: "trial" }, "/signup");
    try {
      const result = await signup(email, password, workspaceName, undefined, true, {
        terms_version: TERMS_VERSION,
        privacy_version: PRIVACY_VERSION,
      }, captureMarketingAttribution());
      setMessage(cleanUserText(result.message));
      setPassword("");
      setConfirmPassword("");
      setAcceptedTerms(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup could not be started.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cv-login">
      <form className="cv-card cv-login-card" onSubmit={onSubmit}>
        <BrandLink href="https://www.cadivor.com/" ariaLabel="Cadivor homepage" compact />
        <div className="cv-eyebrow">14-day evaluation</div>
        <h1 style={{ margin: "0 0 6px", fontSize: 26, letterSpacing: "-0.03em" }}>
          Create your workspace
        </h1>
        <p className="cv-page-description" style={{ marginTop: 6 }}>
          Verify your email to activate the workspace. Your trial starts after
          you verify and sign in. No payment details are requested here.
        </p>
        {enabled === null ? (
          <div className="cv-empty" role="status">Checking account setup…</div>
        ) : !enabled ? (
          <div className="cv-empty" role="status">
            Self-serve signup is not enabled yet. You can still sign in to an
            existing account.
          </div>
        ) : message ? (
          <div className="cv-card pad cv-signup-success" role="status">
            <strong>Check your email</strong>
            <p>{message}</p>
            <p>Your workspace and trial will be created after email verification and sign-in.</p>
          </div>
        ) : (
          <>
            <label htmlFor="workspace-name">Workspace name</label>
            <input
              id="workspace-name"
              autoComplete="organization"
              maxLength={80}
              value={workspaceName}
              onChange={(event) => setWorkspaceName(event.target.value)}
              required
            />
            <label htmlFor="signup-email">Work email</label>
            <input
              id="signup-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            <label htmlFor="signup-password">Password</label>
            <input
              id="signup-password"
              type="password"
              autoComplete="new-password"
              minLength={MIN_PASSWORD_LENGTH}
              aria-describedby="signup-password-requirements"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setError("");
              }}
              required
            />
            <div
              id="signup-password-requirements"
              className="cv-small-note"
              style={{ display: "flex", alignItems: "center", gap: 8, marginTop: -5, marginBottom: 14 }}
            >
              <span aria-hidden="true" style={{ color: passwordMeetsMinimum ? "#0f9f6e" : "#8291a7", fontWeight: 800 }}>
                {passwordMeetsMinimum ? "✓" : "○"}
              </span>
              <span>At least {MIN_PASSWORD_LENGTH} characters</span>
              <span aria-hidden="true" style={{ marginLeft: "auto" }}>
                {passwordCharacterCount}/{MIN_PASSWORD_LENGTH}
              </span>
              <span role="status" aria-live="polite" style={{ position: "absolute", width: 1, height: 1, padding: 0, margin: -1, overflow: "hidden", clip: "rect(0, 0, 0, 0)", whiteSpace: "nowrap", border: 0 }}>
                {passwordMeetsMinimum
                  ? `Password meets the ${MIN_PASSWORD_LENGTH}-character minimum.`
                  : `Password does not yet meet the ${MIN_PASSWORD_LENGTH}-character minimum.`}
              </span>
            </div>
            <label htmlFor="confirm-password">Confirm password</label>
            <input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => {
                setConfirmPassword(event.target.value);
                setError("");
              }}
              required
            />
            <TermsAcceptance
              checked={acceptedTerms}
              onChange={setAcceptedTerms}
              disabled={busy}
            />
            {error ? <div className="cv-error" role="alert">{error}</div> : null}
            <button
              className="cv-button primary"
              style={{ width: "100%", marginTop: 18 }}
              type="submit"
              disabled={busy || !acceptedTerms}
            >
              {busy ? "Sending verification…" : "Create workspace"}
            </button>
          </>
        )}
        <p className="cv-auth-switch">
          Already have an account? <Link href="/login">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
