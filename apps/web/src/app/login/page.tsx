"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  SMOKE_EMAIL,
  SMOKE_PASSWORD,
  getSession,
  setSession,
  smokeLogin,
} from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState(SMOKE_EMAIL);
  const [password, setPassword] = useState(SMOKE_PASSWORD);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (getSession()) router.replace("/");
  }, [router]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = await smokeLogin(email, password);
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
        <div className="cv-brand" style={{ marginBottom: 18 }}>
          <span className="cv-mark" aria-hidden>
            C
          </span>
          <div>
            <strong>Cadivor</strong>
            <small>NEXT.JS MIGRATION PREVIEW</small>
          </div>
        </div>
        <h1 style={{ margin: "0 0 6px", fontSize: 26, letterSpacing: "-0.03em" }}>
          Sign in
        </h1>
        <p style={{ margin: 0, color: "#64748b", fontSize: 13, lineHeight: 1.5 }}>
          Smoke credentials only. No Stripe charges, email, or live supplier
          calls.
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
          className="cv-button"
          style={{ width: "100%", marginTop: 18 }}
          type="submit"
          disabled={busy}
        >
          {busy ? "Signing in…" : "Continue"}
        </button>
      </form>
    </div>
  );
}
