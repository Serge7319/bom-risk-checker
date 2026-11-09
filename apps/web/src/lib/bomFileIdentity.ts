/** Content-based BOM file identity (no path aliases — safe for Node test runner). */

export type ScopeSession = {
  user_id?: string;
  email?: string;
  workspace_id?: string;
};

const META_KEY = "cadivor_bom_analyzer_draft_meta";
const FILE_ID = "current";

/** Scope key: authenticated identity AND workspace. */
export function scopeIdentityKey(session?: ScopeSession): string {
  const identity = session?.user_id || session?.email?.trim().toLowerCase() || "anonymous";
  const workspace = session?.workspace_id?.trim() || "no-workspace";
  return `${identity}::${workspace}`;
}

export function draftMetaStorageKey(session?: ScopeSession): string {
  return `${META_KEY}:${scopeIdentityKey(session)}`;
}

export function draftFileRecordId(session?: ScopeSession): string {
  return `${FILE_ID}:${scopeIdentityKey(session)}`;
}

function bytesToHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** SHA-256 digest of file bytes (Web Crypto — available in modern browsers and Node 20+). */
export async function fileContentDigest(file: Blob): Promise<string> {
  const buffer = await file.arrayBuffer();
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new Error("Web Crypto SHA-256 is required to identify BOM file contents.");
  }
  const digest = await subtle.digest("SHA-256", buffer);
  return bytesToHex(digest);
}

/**
 * Clone the selected File into memory so validation/analyze keep working even if the
 * original picker handle later throws NotFoundError (or IndexedDB persistence fails).
 */
export async function materializeBomFile(file: File): Promise<{ file: File; identityKey: string }> {
  const buffer = await file.arrayBuffer();
  const cloned = new File([buffer], file.name, {
    type: file.type || "application/octet-stream",
    lastModified: file.lastModified || Date.now(),
  });
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) {
    throw new Error("Web Crypto SHA-256 is required to identify BOM file contents.");
  }
  const digest = await subtle.digest("SHA-256", buffer);
  return { file: cloned, identityKey: `sha256:${bytesToHex(digest)}` };
}

/**
 * Validation/file identity based on content.
 * Distinguishes different bytes even when filename/size/lastModified match.
 */
export async function fileIdentityKey(file: File): Promise<string> {
  const digest = await fileContentDigest(file);
  return `sha256:${digest}`;
}
