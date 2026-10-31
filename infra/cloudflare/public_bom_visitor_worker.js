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
    const upstream = await fetch(new Request(request, { headers }));
    // Keep upload CORS aligned with the HTTPS browser Origin when Streamlit
    // (behind TLS termination) emits http://app.cadivor.com:443. Do not log
    // cookie values, bodies, or secrets.
    const out = new Headers(upstream.headers);
    const acao = out.get("Access-Control-Allow-Origin");
    if (
      acao &&
      /app\.cadivor\.com/i.test(acao) &&
      acao !== "https://app.cadivor.com"
    ) {
      out.set("Access-Control-Allow-Origin", "https://app.cadivor.com");
    }
    const setCookies = typeof out.getSetCookie === "function" ? out.getSetCookie() : [];
    if (setCookies.length) {
      out.delete("Set-Cookie");
      for (const cookie of setCookies) {
        let next = cookie;
        if (
          cookie.startsWith("_streamlit_xsrf=") &&
          !/;\s*Secure\b/i.test(cookie)
        ) {
          next = `${cookie}; Secure`;
        }
        out.append("Set-Cookie", next);
      }
    }
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: out,
    });
  },
};
