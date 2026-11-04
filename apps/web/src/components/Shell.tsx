"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { API_BASE, clearSession, logout, type Session } from "@/lib/api";
import { NAV_GROUPS } from "@/lib/routes";

function crumbTitle(pathname: string): string {
  if (pathname === "/") return "Home";
  if (pathname.startsWith("/reports/")) return "Engineering Intelligence";
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      if (item.href === "/") continue;
      if (pathname === item.href || pathname.startsWith(`${item.href}/`)) {
        return item.label;
      }
    }
  }
  return "Workspace";
}

export function Shell({
  session,
  children,
}: {
  session: Session;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const title = crumbTitle(pathname);

  return (
    <div className="cv-shell">
      <aside className="cv-rail" aria-label="Workspace navigation">
        <div className="cv-brand">
          <span className="cv-mark" aria-hidden>
            C
          </span>
          <div>
            <strong>Cadivor</strong>
            <small>Engineering Intelligence</small>
          </div>
        </div>
        <div className="cv-workspace-card">
          <span>Workspace</span>
          <strong>{session.workspace}</strong>
          <em style={{ marginTop: 6 }}>Subscription · {session.plan}</em>
        </div>
        <nav className="cv-nav" aria-label="Primary">
          {NAV_GROUPS.map((group) => (
            <div className="cv-nav-group" key={group.label}>
              <div className="cv-nav-label">{group.label}</div>
              {group.items.map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname === item.href ||
                      pathname.startsWith(`${item.href}/`);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={active ? "active" : undefined}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="cv-rail-bottom">
          <div className="cv-plan-card">
            <div className="cv-plan-top">
              <span>Migration preview</span>
              <span className="cv-plan-chip">Sandbox</span>
            </div>
            <div className="cv-plan-copy">
              Sandbox JWT auth with membership-scoped workspaces. Production
              Streamlit on app.cadivor.com is untouched.
            </div>
          </div>
          <button
            type="button"
            className="cv-signout"
            onClick={async () => {
              try {
                if (session.access_token) {
                  await logout(session.access_token);
                }
              } catch {
                // Always clear local session even if revoke fails.
              }
              clearSession();
              router.replace("/login");
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <div className="cv-column">
        <header className="cv-topbar">
          <div className="cv-crumb">
            <span>Workspace</span>
            <span aria-hidden>·</span>
            <strong>{title}</strong>
          </div>
        </header>
        <main className="cv-main">
          <div className="cv-preview-banner" role="status">
            <span className="cv-preview-dot" aria-hidden />
            <strong>Next.js migration preview.</strong>
            <span>
              API target{" "}
              <code style={{ fontSize: 10 }}>{API_BASE}</code>
              . Real API where wired; unsupported pages are labeled. No live
              supplier, Stripe, or email calls.
            </span>
          </div>
          {children}
        </main>
      </div>
    </div>
  );
}
