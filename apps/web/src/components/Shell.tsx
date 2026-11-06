"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Icon, NAV_ICONS } from "@/components/Icons";
import { clearSession, logout, type Session } from "@/lib/api";
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
  const [navOpen, setNavOpen] = useState(false);
  const [search, setSearch] = useState("");
  const title = crumbTitle(pathname);
  const remainingDays = session.trial_ends_at
    ? Math.max(0, Math.ceil((Date.parse(session.trial_ends_at) - Date.now()) / 86400000))
    : session.trial_days_remaining;
  const trialExpired =
    session.trial_status === "trial_expired" ||
    (session.trial_status === "trialing" && remainingDays === 0);
  const subscriptionLabel = trialExpired
    ? "Trial expired · read only"
    : session.trial_status === "trialing" && remainingDays != null
      ? `Trial · ${remainingDays} days remaining`
      : `Subscription · ${session.plan}`;

  const initials = useMemo(() => {
    const source = (session.email || "C").trim();
    const parts = source.split(/[\s@._-]+/).filter(Boolean);
    return ((parts[0]?.[0] || "C") + (parts[1]?.[0] || "")).toUpperCase();
  }, [session.email]);

  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  function onSearch(event: FormEvent) {
    event.preventDefault();
    const q = search.trim();
    if (!q) return;
    router.push(`/find-replacement?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className="cv-shell">
      <aside className={`cv-rail${navOpen ? " is-open" : ""}`} aria-label="Workspace navigation">
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
          <em style={{ marginTop: 6 }}>{subscriptionLabel}</em>
        </div>

        <div className="cv-nav-create">
          <Link href="/bom-analyzer" className="cv-button primary cv-btn-block" onClick={() => setNavOpen(false)}>
            <Icon name="plus" />
            New BOM analysis
          </Link>
        </div>

        <nav className="cv-nav cv-nav-scroll" aria-label="Primary">
          {NAV_GROUPS.map((group) => (
            <div className="cv-nav-group" key={group.label}>
              <div className="cv-nav-label">{group.label}</div>
              {group.items.map((item) => {
                const active =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname === item.href || pathname.startsWith(`${item.href}/`);
                const icon = NAV_ICONS[item.id] || "spark";
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={active ? "active" : undefined}
                    aria-current={active ? "page" : undefined}
                    onClick={() => setNavOpen(false)}
                  >
                    <Icon name={icon} />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="cv-rail-bottom">
          <div className="cv-plan-card">
            <div className="cv-plan-top">
              <span>Workspace data</span>
              <span className="cv-plan-chip">This workspace</span>
            </div>
            <div className="cv-plan-copy">
              Supplier evidence shown here is labeled synthetic when live
              distributors are disconnected. Billing checkout and automated alert
              emails are not connected yet.
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

      {navOpen ? (
        <button
          type="button"
          className="cv-nav-scrim"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
        />
      ) : null}

      <div className="cv-column">
        <header className="cv-topbar">
          <button
            type="button"
            className="cv-button cv-nav-toggle"
            onClick={() => setNavOpen((v) => !v)}
            aria-label="Open navigation"
          >
            <Icon name="menu" />
          </button>
          <div className="cv-crumb">
            <span>Workspace</span>
            <span aria-hidden>·</span>
            <strong>{title}</strong>
          </div>
          <form className="cv-top-search" onSubmit={onSearch} role="search">
            <Icon name="search" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search parts, decisions, reports"
              aria-label="Search workspace"
            />
          </form>
          <div className="cv-topbar-actions">
            <span className="cv-icon-btn" aria-hidden="true" title="Notifications (not connected)">
              <Icon name="bell" />
            </span>
            <div className="cv-user-chip" title={session.email}>
              <span className="cv-avatar" aria-hidden="true">
                {initials}
              </span>
              <span className="cv-user-copy">
                <strong>{session.email}</strong>
                <span>{session.plan} plan</span>
              </span>
            </div>
          </div>
        </header>
        <main className="cv-main">
          <div className="cv-preview-banner" role="status">
            <span className="cv-preview-dot" aria-hidden />
            <strong>Evidence notice.</strong>
            <span>
              Supplier pricing, lifecycle, and availability shown here use sample
              evidence. Live supplier integrations, billing, and automated alert
              delivery are not connected.
            </span>
          </div>
          {children}
        </main>
      </div>
    </div>
  );
}
