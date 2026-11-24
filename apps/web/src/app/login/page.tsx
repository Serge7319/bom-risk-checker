"use client";

import { FormEvent, Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  clearSession,
  fetchAuthConfig,
  fetchMe,
  fetchPublicServiceStatus,
  getSession,
  login,
  completeMfaLogin,
  lookupInvitation,
  registerFromInvitation,
  setSession,
  stageSupabaseSession,
  type PendingMfaSession,
  type Session,
  type PublicServiceStatus,
} from "@/lib/api";
import { getSupabaseBrowserClient } from "@/lib/supabase";
import { cleanUserText, userFacingLabel } from "@/lib/display";
import { TermsAcceptance } from "@/components/TermsAcceptance";
import { BrandLink } from "@/components/BrandLink";
import { ServiceNotices } from "@/components/ServiceNotices";
import { PRIVACY_VERSION, TERMS_VERSION } from "@/lib/legalTerms";
import { marketingAnalyticsAllowed, trackMarketingEvent, trackMarketingEventOnce } from "@/lib/marketingAnalytics";
import {
  parseSignupConfirmParams,
  SIGNUP_CONFIRM_EXPIRED_MESSAGE,
  stressReportIdFromSearch,
  stressReportRequested,
  stripSignupConfirmParams,
  verifySignupEmail,
} from "@/lib/signupEmailConfirm";
import {
  consumeStressReportPending,
  markStressReportPending,
  reportsHandoffHref,
} from "@/lib/publicBomStress";

type InvitePreview = {
  email: string;
  workspace_name: string;
  role: string;
  expires_at?: string;
};

type ConfirmPhase = "none" | "ready" | "success" | "invalid";
type TotpFactorChoice = { id: string; friendly_name: string };

function isPendingMfaSession(
  session: Session | PendingMfaSession,
): session is PendingMfaSession {
  return (session as PendingMfaSession).mfa_required === true;
}

function LoginInner() {
  const router = useRouter();
  const search = useSearchParams();
  const inviteToken = (search.get("invite") || "").trim();
  const emailAlreadyConfirmed = search.get("email-confirmed") === "1";

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
  const [serviceStatus, setServiceStatus] = useState<PublicServiceStatus | null>(null);
  const [mfaPendingSession, setMfaPendingSession] = useState<PendingMfaSession | null>(null);
  const [mfaFactors, setMfaFactors] = useState<TotpFactorChoice[]>([]);
  const [mfaSelectedFactor, setMfaSelectedFactor] = useState("");
  const [mfaCode, setMfaCode] = useState("");

  // Signup email confirmation: stage hash in memory; never verifyOtp in an effect.
  const stagedTokenHash = useRef<string | null>(null);
  const stagedOnce = useRef(false);
  const [confirmPhase, setConfirmPhase] = useState<ConfirmPhase>("none");
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmMessage, setConfirmMessage] = useState("");

  useEffect(() => {
    if (stagedOnce.current) return;
    stagedOnce.current = true;

    const params = new URLSearchParams(window.location.search);
    // Stage before stripping so OTP redirects keep the public-audit unlock intent
    // and the specific report_id selector from the verification email link.
    if (stressReportRequested(params)) {
      markStressReportPending(stressReportIdFromSearch(params));
    }
    const parsed = parseSignupConfirmParams(params);
    if (parsed.kind === "ready") {
      stagedTokenHash.current = parsed.tokenHash;
      setConfirmPhase("ready");
      return;
    }
    if (parsed.kind === "invalid") {
      stagedTokenHash.current = null;
      setConfirmPhase("invalid");
      setConfirmMessage(SIGNUP_CONFIRM_EXPIRED_MESSAGE);
      stripSignupConfirmParams();
      return;
    }
    if (emailAlreadyConfirmed) {
      setNotice(
        "Email confirmed. Sign in with this address to finish activating your workspace.",
      );
    }
  }, [emailAlreadyConfirmed]);

  useEffect(() => {
    // Do not redirect away while a confirmation surface is active.
    if (confirmPhase !== "none" || stagedTokenHash.current) return;

    if (
      new URLSearchParams(window.location.search).get("reason") ===
      "session-refresh"
    ) {
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
    void client.auth
      .getSession()
      .then(({ data, error: sessionError }) => {
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
      })
      .catch(() => {
        if (!active) return;
        clearSession();
        setSessionExpired(true);
      });

    return () => {
      active = false;
    };
  }, [confirmPhase, router]);

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
    let current = true;
    void fetchPublicServiceStatus()
      .then((status) => {
        if (current) setServiceStatus(status);
      })
      .catch(() => {
        if (current) setServiceStatus(null);
      });
    return () => {
      current = false;
    };
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

  async function onConfirmEmail() {
    const tokenHash = stagedTokenHash.current;
    if (!tokenHash || confirmBusy) return;

    // Strip the one-time credential from the address bar immediately before verify.
    stripSignupConfirmParams();
    stagedTokenHash.current = null;

    const client = getSupabaseBrowserClient();
    if (!client) {
      setConfirmPhase("invalid");
      setConfirmMessage(SIGNUP_CONFIRM_EXPIRED_MESSAGE);
      return;
    }

    setConfirmBusy(true);
    setConfirmMessage("");
    setError("");
    try {
      const result = await verifySignupEmail(client, tokenHash);
      if (!result.ok) {
        setConfirmPhase("invalid");
        setConfirmMessage(cleanUserText(result.message));
        return;
      }
      trackMarketingEvent("signup_completed", { intent: "trial" }, "/login");
      if (marketingAnalyticsAllowed()) {
        try { sessionStorage.setItem("cadivor_signup_confirmed_pending", "1"); } catch { /* analytics is optional */ }
      }
      if (result.email) setEmail(result.email);

      const stressHandoff = consumeStressReportPending();
      if (stressHandoff.pending && result.sessionReady && result.accessToken) {
        try {
          const me = await fetchMe(result.accessToken);
          const session: Session = {
            access_token: result.accessToken,
            refresh_token: result.refreshToken,
            email: me.email || result.email || "",
            workspace: me.workspace,
            workspace_id: me.workspace_id,
            user_id: me.user_id,
            plan: me.plan,
            mode: me.mode,
            platform_role: me.platform_role,
            trial_started_at: me.trial_started_at,
            trial_ends_at: me.trial_ends_at,
            trial_status: me.trial_status,
            trial_days_remaining: me.trial_days_remaining,
          };
          await setSession(session);
          if (session.trial_status === "trialing") {
            trackMarketingEventOnce(
              "trial_started",
              `trial_started:${session.user_id || ""}`,
              { intent: "trial" },
              "/login",
            );
          }
          router.replace(reportsHandoffHref(stressHandoff.reportId));
          return;
        } catch {
          // Fall through to sign-in handoff if session bootstrap fails.
          markStressReportPending(stressHandoff.reportId);
        }
      } else if (stressHandoff.pending) {
        markStressReportPending(stressHandoff.reportId);
      }

      setConfirmPhase("success");
      setConfirmMessage(
        stressHandoff.pending
          ? "Your email has been confirmed. Sign in to open your complete BOM audit in Reports."
          : "Your email has been confirmed successfully. Sign in to access your workspace.",
      );
      setNotice(
        stressHandoff.pending
          ? "Email confirmed. Sign in to unlock your free BOM audit in Reports."
          : "Email confirmed. Sign in with this address to finish activating your workspace.",
      );
    } finally {
      setConfirmBusy(false);
    }
  }

  function dismissConfirmToSignIn() {
    stagedTokenHash.current = null;
    setConfirmPhase("none");
    setConfirmMessage("");
    setMode("signin");
  }

  async function showMfaChallenge(result: PendingMfaSession) {
    const client = getSupabaseBrowserClient();
    if (!client) throw new Error("Authenticator verification is unavailable. Please try again.");
    const listed = await client.auth.mfa.listFactors();
    if (listed.error) throw listed.error;
    const factors = listed.data.totp
      .filter((factor) => factor.status === "verified")
      .map((factor) => ({
        id: factor.id,
        friendly_name: factor.friendly_name || "Authenticator app",
      }));
    if (!factors.length) {
      throw new Error("No verified authenticator was found. Contact Cadivor support before continuing.");
    }
    const serverFactorIds = new Set(result.mfa_factors.map((factor) => factor.id));
    const firstFactor = factors.find((factor) => serverFactorIds.has(factor.id)) || factors[0];
    setEmail(result.email);
    setMfaPendingSession(result);
    setMfaFactors(factors);
    setMfaSelectedFactor(firstFactor.id);
    setPassword("");
  }

  async function cancelMfaSignIn() {
    const client = getSupabaseBrowserClient();
    if (client) await client.auth.signOut({ scope: "local" }).catch(() => undefined);
    setMfaPendingSession(null);
    setMfaFactors([]);
    setMfaSelectedFactor("");
    setMfaCode("");
    setError("");
  }

  async function enterWorkspace(session: Session) {
    await setSession(session);
    let newlyConfirmed = false;
    try {
      newlyConfirmed = marketingAnalyticsAllowed() && sessionStorage.getItem("cadivor_signup_confirmed_pending") === "1";
      if (newlyConfirmed) sessionStorage.removeItem("cadivor_signup_confirmed_pending");
    } catch { /* analytics is optional */ }
    if (newlyConfirmed && session.trial_status === "trialing") {
      trackMarketingEventOnce(
        "trial_started",
        `trial_started:${session.user_id || ""}`,
        { intent: "trial" },
        "/login",
      );
    }
    const stressHandoff = consumeStressReportPending();
    router.replace(
      stressHandoff.pending
        ? reportsHandoffHref(stressHandoff.reportId)
        : "/",
    );
  }

  async function onSignIn(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    let stagedAuthSession = false;
    try {
      const result = await login(email, password, inviteToken || undefined);
      if (isPendingMfaSession(result)) {
        await stageSupabaseSession(result);
        stagedAuthSession = true;
        await showMfaChallenge(result);
        return;
      }
      await enterWorkspace(result);
    } catch (err) {
      if (stagedAuthSession) {
        const client = getSupabaseBrowserClient();
        if (client) await client.auth.signOut({ scope: "local" }).catch(() => undefined);
        setMfaPendingSession(null);
        setMfaFactors([]);
        setMfaSelectedFactor("");
      }
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  async function onPasskeySignIn() {
    const client = getSupabaseBrowserClient();
    if (!client) {
      setError("Passkey sign-in is unavailable in this environment.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    let authenticated = false;
    try {
      const { data, error: passkeyError } = await client.auth.signInWithPasskey();
      if (passkeyError) throw passkeyError;
      const authSession = data.session;
      if (!authSession) throw new Error("Passkey sign-in did not return an active session.");
      authenticated = true;
      const result = await completeMfaLogin(
        authSession.access_token,
        inviteToken || undefined,
      );
      if (isPendingMfaSession(result)) {
        await showMfaChallenge(result);
        return;
      }
      await enterWorkspace({
        ...result,
        access_token: authSession.access_token,
        refresh_token: authSession.refresh_token,
      });
    } catch (err) {
      if (authenticated) await client.auth.signOut({ scope: "local" }).catch(() => undefined);
      setMfaPendingSession(null);
      setMfaFactors([]);
      setMfaSelectedFactor("");
      const message = err instanceof Error ? err.message : "Passkey sign-in failed.";
      setError(/passkey_disabled/i.test(message)
        ? "Passkey sign-in is not available yet. Use your password or contact Cadivor support."
        : message);
    } finally {
      setBusy(false);
    }
  }

  async function onVerifyMfa(event: FormEvent) {
    event.preventDefault();
    if (!mfaPendingSession || !mfaSelectedFactor) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const client = getSupabaseBrowserClient();
      if (!client) throw new Error("Authenticator verification is unavailable. Please try again.");
      const challenge = await client.auth.mfa.challenge({ factorId: mfaSelectedFactor });
      if (challenge.error) throw challenge.error;
      const verified = await client.auth.mfa.verify({
        factorId: mfaSelectedFactor,
        challengeId: challenge.data.id,
        code: mfaCode.trim(),
      });
      if (verified.error) throw verified.error;
      const [{ data: authData, error: authError }, { data: aalData, error: aalError }] =
        await Promise.all([
          client.auth.getSession(),
          client.auth.mfa.getAuthenticatorAssuranceLevel(),
        ]);
      if (authError || !authData.session || aalError || aalData.currentLevel !== "aal2") {
        throw new Error("The authenticator code was not accepted. Check the current code and try again.");
      }
      const completed = await completeMfaLogin(
        authData.session.access_token,
        inviteToken || undefined,
      );
      if (isPendingMfaSession(completed)) {
        throw new Error("Authenticator verification did not complete. Please try the current code again.");
      }
      setMfaPendingSession(null);
      setMfaFactors([]);
      setMfaSelectedFactor("");
      setMfaCode("");
      await enterWorkspace({
        ...completed,
        access_token: authData.session.access_token,
        refresh_token: authData.session.refresh_token,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authenticator verification failed.");
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

  if (confirmPhase === "ready") {
    return (
      <div className="cv-login">
        <div className="cv-card cv-login-card" data-testid="signup-confirm-ready">
          <BrandLink href="https://www.cadivor.com/" ariaLabel="Cadivor homepage" compact />
          <div className="cv-eyebrow">Cadivor · Email confirmation</div>
          <p className="cv-small-note" role="status" style={{ marginTop: 0 }}>
            Email link ready
          </p>
          <h1 style={{ margin: "0 0 6px", fontSize: 26, letterSpacing: "-0.03em" }}>
            Confirm your email to continue
          </h1>
          <p className="cv-page-description" style={{ marginTop: 6 }}>
            Click below once to confirm this address. Email scanners that open the
            link alone will not consume it.
          </p>
          <button
            className="cv-button primary"
            style={{ width: "100%", marginTop: 18 }}
            type="button"
            data-testid="signup-confirm-submit"
            onClick={() => void onConfirmEmail()}
            disabled={confirmBusy}
          >
            {confirmBusy ? "Confirming email…" : "Confirm email"}
          </button>
        </div>
      </div>
    );
  }

  if (confirmPhase === "success") {
    return (
      <div className="cv-login">
        <div
          className="cv-card cv-login-card"
          data-testid="signup-confirm-success"
        >
          <BrandLink href="https://www.cadivor.com/" ariaLabel="Cadivor homepage" compact />
          <div className="cv-eyebrow">Email confirmed</div>
          <p className="cv-small-note" role="status" style={{ marginTop: 0 }}>
            Confirmation complete
          </p>
          <h1 style={{ margin: "0 0 6px", fontSize: 26, letterSpacing: "-0.03em" }}>
            Continue to Cadivor
          </h1>
          <p className="cv-page-description" style={{ marginTop: 6 }}>
            {confirmMessage ||
              "Your email has been confirmed. Sign in to access your workspace."}
          </p>
          <button
            className="cv-button primary"
            style={{ width: "100%", marginTop: 18 }}
            type="button"
            data-testid="signup-confirm-continue-login"
            onClick={dismissConfirmToSignIn}
          >
            Continue to sign in
          </button>
        </div>
      </div>
    );
  }

  if (confirmPhase === "invalid") {
    return (
      <div className="cv-login">
        <div
          className="cv-card cv-login-card"
          data-testid="signup-confirm-invalid"
        >
          <BrandLink href="https://www.cadivor.com/" ariaLabel="Cadivor homepage" compact />
          <div className="cv-eyebrow">Email confirmation</div>
          <p className="cv-small-note" role="status" style={{ marginTop: 0 }}>
            Confirmation link unavailable
          </p>
          <h1 style={{ margin: "0 0 6px", fontSize: 26, letterSpacing: "-0.03em" }}>
            This link can’t be used
          </h1>
          <p className="cv-page-description" style={{ marginTop: 6 }} role="alert">
            {confirmMessage || SIGNUP_CONFIRM_EXPIRED_MESSAGE}
          </p>
          <button
            className="cv-button primary"
            style={{ width: "100%", marginTop: 18 }}
            type="button"
            data-testid="signup-confirm-return-login"
            onClick={dismissConfirmToSignIn}
          >
            Return to sign in
          </button>
          <p className="cv-auth-switch">
            <Link href="/signup">Create Account</Link>
            {" · "}
            <Link href="/reset-password">Reset password</Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="cv-login">
      <form
        className="cv-card cv-login-card"
        onSubmit={
          mode === "create"
            ? onCreateFromInvite
            : mfaPendingSession
              ? onVerifyMfa
              : onSignIn
        }
      >
        <BrandLink href="https://www.cadivor.com/" ariaLabel="Cadivor homepage" compact />
        <div className="cv-eyebrow">Cadivor Auth</div>
        <h1 style={{ margin: "0 0 6px", fontSize: 26, letterSpacing: "-0.03em" }}>
          {mode === "create" ? "Create your account" : "Sign in"}
        </h1>
        <p className="cv-page-description" style={{ marginTop: 6 }}>
          {mode === "create"
            ? "Use the email address on your workspace invitation."
            : "Sign in to your Cadivor workspace. Supplier prices and availability may include sample estimates; check the source label before acting."}
        </p>

        <ServiceNotices status={serviceStatus} showUnavailable />

        {invite ? (
          <div className="cv-card pad" style={{ marginBottom: 14, padding: 12 }} role="status">
            <strong>Invitation</strong>
            <p className="cv-small-note" style={{ marginTop: 6 }}>
              Join <strong>{userFacingLabel(invite.workspace_name, "your workspace")}</strong> as{" "}
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

        {!mfaPendingSession && inviteToken && invitationsEnabled ? (
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

        {mfaPendingSession ? (
          <div className="cv-card pad" style={{ margin: "12px 0", padding: 14 }}>
            <div className="cv-eyebrow">Two-step verification</div>
            <p className="cv-page-description" style={{ margin: "6px 0 12px" }}>
              Enter the current code from your authenticator app to finish signing in as {email}.
            </p>
            {mfaFactors.length > 1 ? (
              <>
                <label htmlFor="mfa-factor">Authenticator</label>
                <select
                  id="mfa-factor"
                  value={mfaSelectedFactor}
                  onChange={(event) => {
                    const factorId = event.target.value;
                    setMfaSelectedFactor(factorId);
                    setMfaCode("");
                    setError("");
                  }}
                  disabled={busy}
                >
                  {mfaFactors.map((factor, index) => (
                    <option key={factor.id} value={factor.id}>
                      {factor.friendly_name || `Authenticator ${index + 1}`}
                    </option>
                  ))}
                </select>
              </>
            ) : null}
            <label htmlFor="mfa-code">Authenticator code</label>
            <input
              id="mfa-code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6,10}"
              maxLength={10}
              value={mfaCode}
              onChange={(event) => setMfaCode(event.target.value.replace(/\D/g, ""))}
              required
              aria-describedby="mfa-code-help"
            />
            <p id="mfa-code-help" className="cv-small-note" style={{ marginTop: 6 }}>
              Use the current code shown in your authenticator app.
            </p>
          </div>
        ) : (
          <>
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
            {mode === "signin" ? (
              <button
                className="cv-button"
                style={{ width: "100%", marginTop: 12 }}
                type="button"
                onClick={() => void onPasskeySignIn()}
                disabled={busy}
              >
                {busy ? "Waiting for passkey…" : "Sign in with a passkey"}
              </button>
            ) : null}
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
          </>
        )}
        {error ? <div className="cv-error" role="alert">{error}</div> : null}
        {mode === "signin" && !mfaPendingSession ? (
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
              : mfaPendingSession
                ? "Verifying code…"
                : "Signing in…"
            : mode === "create"
              ? "Create account and join workspace"
              : mfaPendingSession
                ? "Verify and continue"
                : "Continue"}
        </button>
        {mfaPendingSession ? (
          <button
            className="cv-button"
            style={{ width: "100%", marginTop: 10 }}
            type="button"
            onClick={() => void cancelMfaSignIn()}
            disabled={busy}
          >
            Cancel sign-in
          </button>
        ) : mode === "signin" && signupEnabled ? (
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
