"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  clearSession,
  fetchAuthConfig,
  getSession,
  login,
  lookupInvitation,
  registerFromInvitation,
  setSession,
} from "@/lib/api";
import { getSupabaseBrowserClient } from "@/lib/supabase";
import { TermsAcceptance } from "@/components/TermsAcceptance";
import { PRIVACY_VERSION, TERMS_VERSION } from "@/lib/legalTerms";

type InvitePreview = {
  email: string;
  workspace_name: string;
  role: string;
  expires_at?: string;
};

function LoginInner() {
  const router = useRouter();
  const search = useSearchParams();
  const inviteToken = (search.get("invite") || "").trim();

  const [mode, setMode] = useState<"signin" | "create">(
    inviteToken ? "create" : "signin",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [signupEnabled, setSignupEnabled] = useState(false);
  const [invitationsEnabled, setInvitationsEnabled] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [invite, setInvite] = useState<InvitePreview | null>(null);
  const [inviteError, setInviteError] = useState("");
  const [acceptedTerms, setAcceptedTerms] = useState(false);

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
      .then((config) => {
        setSignupEnabled(config.signup_enabled);
        setInvitationsEnabled(config.invitations_enabled !== false);
      })
      .catch(() => {
        setSignupEnabled(false);
        setInvitationsEnabled(true);
      });
  }, []);

  useEffect(() => {
    if (!inviteToken) {
      setInvite(null);
      setInviteError("");
      return;
    }
    let active = true;
    lookupInvitation(inviteToken)
      .then((preview) => {
        if (!active) return;
        setInvite(preview);
        setEmail(preview.email);
        setMode("create");
        setInviteError("");
      })
      .catch((err) => {
        if (!active) return;
        setInvite(null);
        setInviteError(
          err instanceof Error
            ? err.message
            : "This invitation is not valid or has expired.",
        );
      });
    return () => {
      active = false;
    };
  }, [inviteToken]);

  async function onSignIn(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
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

  async function onCreateFromInvite(event: FormEvent) {
    event.preventDefault();
    if (!inviteToken) {
      setError("Open the invitation link from your email to create an account.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (!acceptedTerms) {
      setError("Agree to the Terms of Service and Privacy Policy to continue.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await registerFromInvitation({
        token: inviteToken,
        email,
        password,
        accepted_terms: true,
        terms_version: TERMS_VERSION,
        privacy_version: PRIVACY_VERSION,
      });
      setNotice(
        result.message ||
          "Account created. Sign in with this email to open the invited workspace.",
      );
      setMode("signin");
      setPassword("");
      setConfirmPassword("");
      setAcceptedTerms(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="cv-login">
      <form
        className="cv-card cv-login-card"
        onSubmit={mode === "create" ? onCreateFromInvite : onSignIn}
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
        <div className="cv-eyebrow">Cadivor Auth</div>
        <h1 style={{ margin: "0 0 6px", fontSize: 26, letterSpacing: "-0.03em" }}>
          {mode === "create" ? "Create your account" : "Sign in"}
        </h1>
        <p className="cv-page-description" style={{ marginTop: 6 }}>
          {mode === "create"
            ? "Use the email address on your workspace invitation."
            : "Sign in to your Cadivor workspace. Supplier prices and availability may include sample estimates; check the source label before acting."}
        </p>

        {invite ? (
          <div className="cv-card pad" style={{ marginBottom: 14, padding: 12 }} role="status">
            <strong>Invitation</strong>
            <p className="cv-small-note" style={{ marginTop: 6 }}>
              Join <strong>{invite.workspace_name}</strong> as{" "}
              {invite.role.replace(/_/g, " ")}.
            </p>
          </div>
        ) : null}
        {inviteError ? <div className="cv-error" role="alert">{inviteError}</div> : null}
        {sessionExpired ? (
          <div className="cv-error" role="status">
            Your saved sign-in expired. Sign in again to continue; your saved analyses remain in your workspace.
          </div>
        ) : null}
        {notice ? (
          <div className="cv-card pad" style={{ marginBottom: 14, padding: 12 }} role="status">
            {notice}
          </div>
        ) : null}

        {inviteToken && invitationsEnabled ? (
          <div className="cv-segment" style={{ display: "flex", gap: 8, marginBottom: 14 }}>
            <button
              type="button"
              className={mode === "create" ? "cv-button primary" : "cv-button"}
              onClick={() => setMode("create")}
            >
              Create account
            </button>
            <button
              type="button"
              className={mode === "signin" ? "cv-button primary" : "cv-button"}
              onClick={() => setMode("signin")}
            >
              Sign in
            </button>
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
          readOnly={Boolean(invite)}
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete={mode === "create" ? "new-password" : "current-password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={mode === "create" ? 12 : undefined}
        />
        {mode === "create" ? (
          <>
            <label htmlFor="confirm-password">Confirm password</label>
            <input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={12}
            />
            <TermsAcceptance
              checked={acceptedTerms}
              onChange={setAcceptedTerms}
              disabled={busy}
            />
          </>
        ) : null}
        {error ? <div className="cv-error">{error}</div> : null}
        {mode === "signin" ? (
          <p className="cv-auth-switch" style={{ marginTop: 8, marginBottom: 0 }}>
            <Link href="/reset-password">Forgot password?</Link>
          </p>
        ) : null}
        <button
          className="cv-button primary"
          style={{ width: "100%", marginTop: 18 }}
          type="submit"
          disabled={
            busy ||
            (mode === "create" &&
              (!inviteToken || Boolean(inviteError) || !acceptedTerms))
          }
        >
          {busy
            ? mode === "create"
              ? "Creating account…"
              : "Signing in…"
            : mode === "create"
              ? "Create account and join workspace"
              : "Continue"}
        </button>
        {mode === "signin" && signupEnabled ? (
          <p className="cv-auth-switch">
            <Link href="/signup">Create an account · Start a 14-day trial</Link>
          </p>
        ) : mode === "signin" && inviteToken ? (
          <p className="cv-auth-switch">
            Already have an account? Use Sign in above after verifying your email.
          </p>
        ) : mode === "signin" && invitationsEnabled ? (
          <p className="cv-auth-switch">
            New teammates join through a workspace invitation link. Ask a workspace
            owner or admin to invite you, or contact{" "}
            <a href="mailto:support@cadivor.com?subject=Cadivor%20access%20request">
              Cadivor support
            </a>.
          </p>
        ) : mode === "signin" ? (
          <p className="cv-auth-switch">
            New account invitations are not available in this app yet. To request
            access, contact{" "}
            <a href="mailto:support@cadivor.com?subject=Cadivor%20access%20request">
              Cadivor support
            </a>.
          </p>
        ) : null}
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
