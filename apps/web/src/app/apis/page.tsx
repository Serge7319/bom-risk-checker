"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { LoadingCard } from "@/components/GapBanner";
import { PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import {
  ApiError,
  createDeveloperApiKey,
  fetchDeveloperApiKeys,
  revokeDeveloperApiKey,
  type DeveloperApiKey,
} from "@/lib/api";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";
import { cleanUserText } from "@/lib/display";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = String(error.payload.detail || error.message);
    if (/not active/i.test(detail)) {
      return "Developer API access is not active for this workspace. Review the plan or ask the workspace owner to enable access.";
    }
    if (/only workspace owners and admins/i.test(detail)) {
      return "Only workspace owners and admins can create or revoke API keys. Ask a workspace owner or admin to manage keys.";
    }
    return detail;
  }
  if (error instanceof Error && /failed to fetch|networkerror/i.test(error.message)) {
    return "Cadivor could not be reached. Check your connection and try again.";
  }
  return error instanceof Error ? error.message : "API keys could not be loaded.";
}

export default function APIsPage() {
  const session = useRequireSession();
  const [keys, setKeys] = useState<DeveloperApiKey[]>([]);
  const [keyName, setKeyName] = useState("");
  const [secret, setSecret] = useState("");
  const [secretKeyId, setSecretKeyId] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState("");
  const [confirmingRevoke, setConfirmingRevoke] = useState("");

  const loadKeys = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError("");
    try {
      const result = await fetchDeveloperApiKeys(session.access_token);
      setKeys(result.keys || []);
    } catch (err) {
      setKeys([]);
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  async function handleCreateKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !keyName.trim()) return;
    setAction("create");
    setError("");
    setNotice("");
    setSecret("");
    try {
      const result = await createDeveloperApiKey(session.access_token, keyName.trim());
      const { secret: newSecret, ...key } = result.key;
      setKeys((current) => [key, ...current]);
      setKeyName("");
      setSecret(newSecret);
      setSecretKeyId(key.id);
      setNotice("Copy this secret now. Cadivor cannot display it again.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setAction("");
    }
  }

  async function handleRevoke(keyId: string) {
    if (!session) return;
    setAction(`revoke:${keyId}`);
    setError("");
    setNotice("");
    try {
      await revokeDeveloperApiKey(session.access_token, keyId);
      setKeys((current) => current.filter((key) => key.id !== keyId));
      if (secretKeyId === keyId) {
        setSecret("");
        setSecretKeyId("");
      }
      setConfirmingRevoke("");
      setNotice("API key revoked. Requests using it will stop working immediately.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setAction("");
    }
  }

  async function copySecret() {
    if (!secret) return;
    try {
      await navigator.clipboard.writeText(secret);
      setNotice("API key copied. Store it in the integration’s secure credential store.");
    } catch {
      setError("Clipboard access is unavailable. Select and copy the key manually.");
    }
  }

  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.apis}
        actions={
          <>
            <PrimaryLink href="https://www.cadivor.com/downloads/cadivor-kicad-plugin.zip">
              Download KiCad plugin
            </PrimaryLink>
            <SecondaryLink href="https://www.cadivor.com/developers/">
              API guide
            </SecondaryLink>
          </>
        }
      />

      <div className="cv-api-page-grid">
        <section className="cv-card pad" aria-labelledby="api-keys-title">
          <div className="cv-api-section-heading">
            <div>
              <h2 className="cv-card-title" id="api-keys-title">Workspace API keys</h2>
              <p className="cv-card-subtitle">
                Keys let approved integrations submit BOMs and read reports in this workspace.
                The full secret appears once, when created.
              </p>
            </div>
            <button className="cv-button" type="button" onClick={() => void loadKeys()} disabled={loading || Boolean(action)}>
              {loading ? "Refreshing…" : "Refresh keys"}
            </button>
          </div>

          <div className="cv-api-key-note">
            <strong>For KiCad</strong>
            <p>
              Create a key here, then paste it into the Cadivor KiCad action the first time you run it.
              The plugin saves the key in your computer’s credential manager, so you do not need to
              recreate it for each analysis or after signing out of the website.
            </p>
            <a href="https://www.cadivor.com/developers/#kicad">See macOS, Windows, and Linux setup steps →</a>
          </div>

          <form className="cv-api-create-form" onSubmit={(event) => void handleCreateKey(event)}>
            <div className="cv-field">
              <label htmlFor="api-key-name">Key name</label>
              <input
                id="api-key-name"
                value={keyName}
                maxLength={80}
                onChange={(event) => setKeyName(event.target.value)}
                placeholder="e.g. KiCad on my workstation"
                required
              />
            </div>
            <button className="cv-button primary" type="submit" disabled={Boolean(action) || !keyName.trim()}>
              {action === "create" ? "Creating key…" : "Create API key"}
            </button>
          </form>

          {secret ? (
            <div className="cv-api-key-secret" role="status">
              <strong>Copy your new API key now</strong>
              <code>{secret}</code>
              <button className="cv-button small" type="button" onClick={() => void copySecret()}>Copy key</button>
            </div>
          ) : null}
          {notice ? <p className="cv-api-notice" role="status">{notice}</p> : null}
          {error ? (
            <div className="cv-error" role="alert">
              {error}
              {/not active/i.test(error) ? <> <a href="/settings">Review workspace plan and billing</a>.</> : null}
            </div>
          ) : null}

          {loading ? <LoadingCard label="Loading workspace API keys…" /> : null}
          {!loading && !error && keys.length === 0 ? (
            <div className="cv-api-empty">
              <strong>No API keys yet</strong>
              <span>Create a key above to connect KiCad or another approved integration.</span>
            </div>
          ) : null}
          {!loading && keys.length > 0 ? (
            <ul className="cv-api-key-list">
              {keys.map((key) => (
                <li key={key.id}>
                  <span>
                    <strong>{cleanUserText(key.name || "API key")}</strong>
                    <small>
                      <code>{key.key_prefix}…</code>
                      {" · Created "}{key.created_at ? new Date(key.created_at).toLocaleDateString() : "—"}
                      {key.last_used_at ? ` · Used ${new Date(key.last_used_at).toLocaleDateString()}` : " · Not used yet"}
                    </small>
                  </span>
                  {confirmingRevoke === key.id ? (
                    <span className="cv-api-revoke-confirm">
                      <span>Stop this key immediately?</span>
                      <button className="cv-button small" type="button" onClick={() => setConfirmingRevoke("")} disabled={Boolean(action)}>Cancel</button>
                      <button className="cv-button small cv-api-danger" type="button" onClick={() => void handleRevoke(key.id)} disabled={Boolean(action)}>
                        {action === `revoke:${key.id}` ? "Revoking…" : "Confirm revoke"}
                      </button>
                    </span>
                  ) : (
                    <button className="cv-button small" type="button" onClick={() => setConfirmingRevoke(key.id)} disabled={Boolean(action)}>Revoke</button>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
        </section>

        <aside className="cv-card pad cv-api-guidance">
          <span className="cv-api-guidance-label">How key security works</span>
          <h2 className="cv-card-title">One workspace. Scoped access.</h2>
          <ul>
            <li>Keys apply only to the active workspace and stop working if access or membership ends.</li>
            <li>Cadivor stores a hash of each key. The secret cannot be recovered after the creation screen closes.</li>
            <li>To rotate a key, create and install its replacement first, confirm it works, then revoke the old key.</li>
          </ul>
          <p>
            KiCad sends component fields for analysis and opens the saved report. It does not upload
            the PCB layout, schematic, nets, or routing.
          </p>
          <a href="https://www.cadivor.com/developers/">Read API endpoints, limits, and integration details →</a>
        </aside>
      </div>
    </Shell>
  );
}
