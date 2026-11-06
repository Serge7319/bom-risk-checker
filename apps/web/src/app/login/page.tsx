"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { clearSession, fetchAuthConfig, getSession, login, setSession } from "@/lib/api";
import { getSupabaseBrowserClient } from "@/lib/supabase";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [signupEnabled, setSignupEnabled] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("reason") === "session-refresh") {
      setSessionExpired(true);
    }

    const savedSession = getSession();
    if (!savedSession) return;

    const client = getSupabaseBrowserClient();
    if (!client) {
      router.replace("/");
      return;
    }

    let active = true;
    void client.auth.getSession().then(({ data, error: sessionError }) => {
      if (!active) return;
      const authUser = data.session?.user;
      const matchesSavedUser = Boolean(
        authUser &&
          (savedSession.user_id
            ? savedSession.user_id === authUser.id
            : savedSession.email.trim().toLowerCase() ===
              (authUser.email || "").trim().toLowerCase()),
      );
      if (!sessionError && data.session && matchesSavedUser) {
        router.replace("/");
      } else {
        clearSession();
        setSessionExpired(true);
      }
    }).catch(() => {
      if (!active) return;
      clearSession();
      setSessionExpired(true);
    });

    return () => {
      active = false;
    };
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
      await setSession(session);
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
          Sign in to your Cadivor workspace. Supplier evidence uses sample data;
          live supplier, billing, and automated alert email connections are not
          connected.
        </p>
        {sessionExpired ? (
          <div className="cv-error" role="status">
            Your saved sign-in expired. Sign in again to continue; your saved analyses remain in your workspace.
          </div>
        ) : null}
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
