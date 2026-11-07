"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { fetchAuthConfig, signup } from "@/lib/api";
import { TermsAcceptance } from "@/components/TermsAcceptance";

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

  useEffect(() => {
    fetchAuthConfig()
      .then((config) => setEnabled(config.signup_enabled))
      .catch(() => setEnabled(false));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setMessage("");
    if (password !== confirmPassword) {
      setError("The passwords do not match.");
      return;
    }
    if (!acceptedTerms) {
      setError("Agree to the Terms of Service and Privacy Policy to continue.");
      return;
    }
    setBusy(true);
    try {
      const result = await signup(email, password, workspaceName, undefined, true);
      setMessage(result.message);
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
        <div className="cv-brand" style={{ marginBottom: 18, paddingBottom: 0 }}>
          <span className="cv-mark" aria-hidden>C</span>
          <div><strong>Cadivor</strong><small>Engineering Intelligence</small></div>
        </div>
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
              minLength={12}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            <label htmlFor="confirm-password">Confirm password</label>
            <input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
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
