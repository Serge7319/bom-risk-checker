/**
 * Cloudflare Worker route: app.cadivor.com/* (including /_stcore/stream).
 * Bind CADIVOR_PUBLIC_BOM_HMAC_SECRET as a Worker secret and use the same value
 * in Railway. This Worker must run on every request, including WebSocket upgrades.
 * Never derive public-upload limits from a browser-supplied X-Forwarded-For value.
 */
export default {
  async fetch(request, env) {
    const ip = request.headers.get("CF-Connecting-IP");
    if (!ip || !env.CADIVOR_PUBLIC_BOM_HMAC_SECRET) {
      return new Response("Cadivor ingress unavailable", { status: 503 });
    }
    const timestamp = String(Math.floor(Date.now() / 1000));
    const message = `v1|${timestamp}|${ip}`;
    const key = await crypto.subtle.importKey(
      "raw", new TextEncoder().encode(env.CADIVOR_PUBLIC_BOM_HMAC_SECRET),
      { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
    );
    const signature = Array.from(new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message))))
      .map(byte => byte.toString(16).padStart(2, "0")).join("");
    const headers = new Headers(request.headers);
    headers.delete("X-Cadivor-Visitor");
    headers.set("X-Cadivor-Visitor", `v1;${timestamp};${ip};${signature}`);
    return fetch(new Request(request, { headers }));
  },
};
