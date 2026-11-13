/**
 * Signup email confirmation (token_hash + type=email).
 * Stage the hash in memory; call verifyOtp only after an explicit user click.
 * Never log or render the raw token_hash.
 */

export const SIGNUP_CONFIRM_TYPE = "email";
export const SIGNUP_CONFIRM_MARKER = "cadivor_signup_confirm";

export const SIGNUP_CONFIRM_EXPIRED_MESSAGE =
  "The confirmation link may have expired or already been used. Return to sign in, or create an account again if needed.";

const STRIP_PARAM_KEYS = [
  SIGNUP_CONFIRM_MARKER,
  "token_hash",
  "type",
  "email-confirmed",
  "error",
  "error_code",
  "error_description",
] as const;

export type SignupConfirmParse =
  | { kind: "none" }
  | { kind: "ready"; tokenHash: string }
  | { kind: "invalid" };

/** Read signup-confirm params. Ignores recovery and fragment access_token. */
export function parseSignupConfirmParams(
  search: URLSearchParams,
): SignupConfirmParse {
  const tokenHash = (search.get("token_hash") || "").trim();
  const type = (search.get("type") || "").trim().toLowerCase();
  const marker = (search.get(SIGNUP_CONFIRM_MARKER) || "").trim().toLowerCase();
  const markerPresent = marker === "1" || marker === "true" || marker === "yes";

  if (!tokenHash && !markerPresent) {
    return { kind: "none" };
  }

  // Recovery links use type=recovery — leave those to /reset-password.
  if (type === "recovery") {
    return { kind: "none" };
  }

  if (!tokenHash || type !== SIGNUP_CONFIRM_TYPE) {
    // Marker or token_hash without a valid email type → invalid surface.
    if (tokenHash || markerPresent) {
      return { kind: "invalid" };
    }
    return { kind: "none" };
  }

  return { kind: "ready", tokenHash };
}

/** Remove signup-confirm secrets from the address bar (never log the hash). */
export function stripSignupConfirmParams(href?: string): string {
  if (typeof window === "undefined") return "";
  const safeUrl = new URL(href || window.location.href);
  for (const key of STRIP_PARAM_KEYS) {
    safeUrl.searchParams.delete(key);
  }
  const next = `${safeUrl.pathname}${safeUrl.search}${safeUrl.hash}`;
  window.history.replaceState(window.history.state, "", next);
  return next;
}

export type VerifySignupEmailResult =
  | { ok: true; email?: string; sessionReady: boolean }
  | { ok: false; message: string };

type VerifyOtpClient = {
  auth: {
    verifyOtp: (args: {
      token_hash: string;
      type: "email";
    }) => Promise<{
      data: {
        user: { email?: string | null } | null;
        session: unknown;
      };
      error: { message?: string } | null;
    }>;
  };
};

/** Call verifyOtp once. Caller must strip the URL immediately before this. */
export async function verifySignupEmail(
  client: VerifyOtpClient,
  tokenHash: string,
): Promise<VerifySignupEmailResult> {
  const hash = String(tokenHash || "").trim();
  if (!hash) {
    return { ok: false, message: SIGNUP_CONFIRM_EXPIRED_MESSAGE };
  }
  try {
    const { data, error } = await client.auth.verifyOtp({
      token_hash: hash,
      type: SIGNUP_CONFIRM_TYPE,
    });
    if (error || !data.user) {
      return { ok: false, message: SIGNUP_CONFIRM_EXPIRED_MESSAGE };
    }
    return {
      ok: true,
      email: data.user.email || undefined,
      sessionReady: Boolean(data.session),
    };
  } catch {
    return { ok: false, message: SIGNUP_CONFIRM_EXPIRED_MESSAGE };
  }
}

/** True when the current URL looks like a signup-confirm callback (no verify). */
export function signupConfirmCallbackInUrl(search: URLSearchParams): boolean {
  const parsed = parseSignupConfirmParams(search);
  return parsed.kind === "ready" || parsed.kind === "invalid";
}
