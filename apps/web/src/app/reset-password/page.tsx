"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { completePasswordReset, requestPasswordReset } from "@/lib/api";

function readRecoveryAccessToken(search: URLSearchParams): string {
  const fromQuery =
    (search.get("access_token") || search.get("token") || "").trim();
  if (fromQuery) return fromQuery;
  if (typeof window === "undefined") return "";
  const hash = window.location.hash.replace(/^#/, "");
  if (!hash) return "";
  const params = new URLSearchParams(hash);
  const type = (params.get("type") || "").toLowerCase();
  const token = (params.get("access_token") || "").trim();
  if (token && (!type || type === "recovery")) return token;
  return token;
}

function ResetPasswordInner() {
  const search = useSearchParams();
  const [recoveryToken, setRecoveryToken] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setRecoveryToken(readRecoveryAccessToken(search));
  }, [search]);

  async function onRequest(event: FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    setBusy(true);
    try {
      const result = await requestPasswordReset(email);
      setNotice(
        result.message ||
          "If an account exists for this address, a reset link will arrive by email.",
      );
      setEmail("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset email could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  async function onComplete(event: FormEvent) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (password !== confirmPassword) {
      setError("The passwords do not match.");
      return;
    }
    if (!recoveryToken) {
      setError("This reset link is invalid or has expired.");
      return;
    }
    setBusy(true);
    try {
      const result = await completePasswordReset(recoveryToken, password);
      setNotice(
        result.message || "Your password was updated. Sign in with the new password.",
      );
      setPassword("");
      setConfirmPassword("");
      setRecoveryToken("");
      if (typeof window !== "undefined" && window.location.hash) {
        window.history.replaceState(null, "", window.location.pathname);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Password could not be updated.",
      );
    } finally {
      setBusy(false);
    }
  }

  const completing = Boolean(recoveryToken);

  return (
    <div className="cv-login">
      <form
        className="cv-card cv-login-card"
        onSubmit={completing ? onComplete : onRequest}
      >
        <div className="cv-brand" style={{ marginBottom: 18, paddingBottom: 0 }}>
          <span className="cv-mark" aria-hidden>
            C
          </span>
          <div>
            <strong>Cadivor</strong>
            <small>Engineering Intelligence</small>
          </div>
        </div>
        <div className="cv-eyebrow">Secure account recovery</div>
        <h1 style={{ margin: "0 0 6px", fontSize: 26, letterSpacing: "-0.03em" }}>
          {completing ? "Choose a new password" : "Reset your password"}
        </h1>
        <p className="cv-page-description" style={{ marginTop: 6 }}>
          {completing
            ? "Your recovery link is active. Choose a secure new password to restore access."
            : "Enter the email for your Cadivor workspace. If an account exists, we will send recovery instructions."}
        </p>

        {notice ? (
          <div className="cv-card pad" style={{ marginBottom: 14, padding: 12 }} role="status">
            {notice}
            {completing || notice.toLowerCase().includes("updated") ? (
              <p style={{ marginTop: 8 }}>
                <Link href="/login">Return to sign in</Link>
              </p>
            ) : null}
          </div>
        ) : null}

        {!notice && completing ? (
          <>
            <label htmlFor="new-password">New password</label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <label htmlFor="confirm-new-password">Confirm password</label>
            <input
              id="confirm-new-password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
          </>
        ) : null}

        {!notice && !completing ? (
          <>
            <label htmlFor="reset-email">Email</label>
            <input
              id="reset-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </>
        ) : null}

        {error ? (
          <div className="cv-error" role="alert">
            {error}
          </div>
        ) : null}

        {!notice ? (
          <button
            className="cv-button primary"
            style={{ width: "100%", marginTop: 18 }}
            type="submit"
            disabled={busy}
          >
            {busy
              ? completing
                ? "Updating…"
                : "Sending…"
              : completing
                ? "Update password"
                : "Send recovery email"}
          </button>
        ) : null}

        <p className="cv-auth-switch">
          <Link href="/login">Back to sign in</Link>
        </p>
      </form>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordInner />
    </Suspense>
  );
}
