"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { fetchAuthConfig, getSession, login, setSession } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [signupEnabled, setSignupEnabled] = useState(false);

  useEffect(() => {
    if (getSession()) router.replace("/");
  }, [router]);

  useEffect(() => {
    fetchAuthConfig()
      .then((config) => setSignupEnabled(config.signup_enabled))
      .catch(() => setSignupEnabled(false));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = await login(email, password);
      setSession(session);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cv-login">
      <form className="cv-card cv-login-card" onSubmit={onSubmit}>
        <div className="cv-brand" style={{ marginBottom: 18, paddingBottom: 0 }}>
          <span className="cv-mark" aria-hidden>
            C
          </span>
          <div>
            <strong>Cadivor</strong>
            <small>Engineering Intelligence</small>
          </div>
        </div>
        <div className="cv-eyebrow">Cadivor Auth</div>
        <h1 style={{ margin: "0 0 6px", fontSize: 26, letterSpacing: "-0.03em" }}>
          Sign in
        </h1>
        <p className="cv-page-description" style={{ marginTop: 6 }}>
          Sign in with the account enabled for this migration test. Saved BOMs
          here are separate from existing Cadivor records. Supplier and billing
          connections are not enabled in this build.
        </p>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error ? <div className="cv-error">{error}</div> : null}
        <button
          className="cv-button primary"
          style={{ width: "100%", marginTop: 18 }}
          type="submit"
          disabled={busy}
        >
          {busy ? "Signing in…" : "Continue"}
        </button>
        {signupEnabled ? (
          <p className="cv-auth-switch">
            New to Cadivor? <Link href="/signup">Start a 14-day trial</Link>
          </p>
        ) : null}
      </form>
    </div>
  );
}
