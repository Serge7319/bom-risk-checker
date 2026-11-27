"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Icon, NAV_ICONS } from "@/components/Icons";
import { BrandLink } from "@/components/BrandLink";
import { ServiceNotices } from "@/components/ServiceNotices";
import {
  clearSession,
  fetchPlanUsage,
  fetchRuntimeMaintenance,
  logout,
  type RuntimeMaintenanceStatus,
  type Session,
} from "@/lib/api";
import { workspaceDisplayName } from "@/lib/display";
import { NAV_GROUPS } from "@/lib/routes";

// Each page mounts its own Shell. Keep short-lived account-scoped snapshots so
// soft navigation does not repeat the same status requests on every route.
const MAINTENANCE_CACHE_MS = 5_000;
const PLAN_CACHE_MS = 15_000;
const runtimeMaintenanceByUser = new Map<
  string,
  { status: RuntimeMaintenanceStatus; fetchedAt: number }
>();
const planByWorkspace = new Map<string, { plan: string; fetchedAt: number }>();

function crumbTitle(pathname: string): string {
  if (pathname === "/") return "Home";
  if (pathname.startsWith("/reports/")) return "Saved report";
  if (pathname === "/detailed-risk-report") return "Risk evidence detail";
  if (pathname === "/engineering-intelligence") return "Latest report";
  if (pathname.startsWith("/admin/users")) return "User accounts";
  if (pathname.startsWith("/admin/entitlements")) return "Account entitlements";
  if (pathname.startsWith("/admin/marketing-analytics")) return "Growth analytics";
  if (pathname.startsWith("/admin/platform")) return "Maintenance mode";
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
  const maintenanceCacheKey = session.user_id || session.email.trim().toLowerCase();
  const planCacheKey = `${maintenanceCacheKey}:${session.workspace_id || session.workspace}`;
  const [navOpen, setNavOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [verifiedPlan, setVerifiedPlan] = useState<string | null>(() =>
    planByWorkspace.get(planCacheKey)?.plan || null,
  );
  const cachedMaintenance = runtimeMaintenanceByUser.get(maintenanceCacheKey);
  const [maintenanceSnapshot, setMaintenanceSnapshot] = useState(() => ({
    userKey: maintenanceCacheKey,
    status: cachedMaintenance?.status ?? null,
  }));
  const maintenanceStatus = maintenanceSnapshot.userKey === maintenanceCacheKey
    ? maintenanceSnapshot.status
    : null;
  const title = crumbTitle(pathname);
  const remainingDays = session.trial_ends_at
    ? Math.max(0, Math.ceil((Date.parse(session.trial_ends_at) - Date.now()) / 86400000))
    : session.trial_days_remaining;
  const planLabel = verifiedPlan || session.plan;
  const trialExpired = verifiedPlan
    ? verifiedPlan === "Trial expired" || verifiedPlan === "Subscription inactive"
    : session.trial_status === "trial_expired" ||
      (session.trial_status === "trialing" && remainingDays === 0);
  const subscriptionLabel = verifiedPlan === "Subscription inactive"
    ? "Subscription inactive · read only"
    : verifiedPlan === "Trial expired" || (!verifiedPlan && trialExpired)
      ? "Trial expired · read only"
      : (verifiedPlan === "Trial" || (!verifiedPlan && session.trial_status === "trialing")) && remainingDays != null
        ? `Trial · ${remainingDays} days remaining`
        : `Subscription · ${planLabel}`;

  const initials = useMemo(() => {
    const source = (session.email || "C").trim();
    const parts = source.split(/[\s@._-]+/).filter(Boolean);
    return ((parts[0]?.[0] || "C") + (parts[1]?.[0] || "")).toUpperCase();
  }, [session.email]);

  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    let current = true;
    const refreshAvailability = () => {
      const cached = runtimeMaintenanceByUser.get(maintenanceCacheKey);
      if (cached && Date.now() - cached.fetchedAt < MAINTENANCE_CACHE_MS) {
        setMaintenanceSnapshot({ userKey: maintenanceCacheKey, status: cached.status });
        return;
      }
      void fetchRuntimeMaintenance(session.access_token)
        .then((status) => {
          if (current) {
            runtimeMaintenanceByUser.set(maintenanceCacheKey, {
              status,
              fetchedAt: Date.now(),
            });
            setMaintenanceSnapshot({ userKey: maintenanceCacheKey, status });
          }
        })
        .catch(() => {
          // Keep the app usable if the status check itself has a transient error;
          // authenticated API routes still enforce maintenance server-side.
          if (current) {
            const fallbackStatus: RuntimeMaintenanceStatus = {
              maintenance_mode: false,
              maintenance_message: "",
              is_admin: session.platform_role === "admin",
              planned_maintenance_message: "",
              planned_maintenance_starts_at: null,
              planned_maintenance_ends_at: null,
            };
            runtimeMaintenanceByUser.set(maintenanceCacheKey, {
              status: fallbackStatus,
              fetchedAt: Date.now(),
            });
            setMaintenanceSnapshot({ userKey: maintenanceCacheKey, status: fallbackStatus });
          }
        });
    };
    refreshAvailability();
    const timer = window.setInterval(refreshAvailability, 30_000);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [session.access_token, session.platform_role, maintenanceCacheKey]);

  useEffect(() => {
    let current = true;
    const cached = planByWorkspace.get(planCacheKey);
    if (!cached) setVerifiedPlan(null);
    else setVerifiedPlan(cached.plan);
    if (cached && Date.now() - cached.fetchedAt < PLAN_CACHE_MS) {
      return () => {
        current = false;
      };
    }
    void fetchPlanUsage(session.access_token)
      .then((usage) => {
        const plan = String(usage.plan || "").trim();
        if (current && plan) {
          planByWorkspace.set(planCacheKey, { plan, fetchedAt: Date.now() });
          setVerifiedPlan(plan);
        }
      })
      .catch(() => {
        // Keep the sign-in snapshot if the usage endpoint is temporarily unavailable.
      });
    return () => {
      current = false;
    };
  }, [session.access_token, planCacheKey]);

  if (session.platform_role !== "admin" && maintenanceStatus?.maintenance_mode) {
    return (
      <main className="cv-maintenance-checking" role="main">
        <section className="cv-maintenance-card" aria-labelledby="cv-maintenance-heading">
          <span className="cv-maintenance-mark" aria-hidden="true">C</span>
          <p className="cv-eyebrow">Scheduled maintenance</p>
          <h1 id="cv-maintenance-heading">We’re improving Cadivor.</h1>
          <p className="cv-maintenance-message">
            {maintenanceStatus.maintenance_message || "Cadivor is undergoing scheduled maintenance. Please try again shortly."}
          </p>
          <div className="cv-maintenance-assurance">
            <strong>Your engineering data is safe.</strong>
            <span>Your workspace and saved analyses will be available again when service is restored.</span>
          </div>
          <p className="cv-maintenance-contact">
            Please check back shortly. For a launch blocker, contact{" "}
            <a href="mailto:beta@cadivor.com?subject=Cadivor%20Beta%20Blocker">beta@cadivor.com</a>.
          </p>
          <button
            type="button"
            className="cv-button"
            onClick={async () => {
              try {
                if (session.access_token) await logout(session.access_token);
              } catch {
                // Always clear local session even if revoke fails.
              }
              clearSession();
              router.replace("/login");
            }}
          >
            Sign out
          </button>
        </section>
      </main>
    );
  }

  function onSearch(event: FormEvent) {
    event.preventDefault();
    const q = search.trim();
    if (!q) return;
    router.push(`/find-replacement?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className="cv-shell">
      <aside className={`cv-rail${navOpen ? " is-open" : ""}`} aria-label="Workspace navigation">
        <BrandLink href="/" ariaLabel="Cadivor workspace home" />

        <div className="cv-workspace-card">
          <span>Workspace</span>
          <strong>{workspaceDisplayName(session.workspace)}</strong>
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
          {session.platform_role === "admin" ? (
            <div className="cv-nav-group">
              <div className="cv-nav-label">Platform</div>
              <Link
                href="/admin/users"
                className={pathname === "/admin/users" ? "active" : undefined}
                aria-current={pathname === "/admin/users" ? "page" : undefined}
                onClick={() => setNavOpen(false)}
              >
                <Icon name="shield" />
                <span>User accounts</span>
              </Link>
              <Link
                href="/admin/entitlements"
                className={pathname === "/admin/entitlements" ? "active" : undefined}
                aria-current={pathname === "/admin/entitlements" ? "page" : undefined}
                onClick={() => setNavOpen(false)}
              >
                <Icon name="settings" />
                <span>Account entitlements</span>
              </Link>
              <Link
                href="/admin/marketing-analytics"
                className={pathname === "/admin/marketing-analytics" ? "active" : undefined}
                aria-current={pathname === "/admin/marketing-analytics" ? "page" : undefined}
                onClick={() => setNavOpen(false)}
              >
                <Icon name="spark" />
                <span>Growth analytics</span>
              </Link>
              <Link
                href="/admin/platform"
                className={pathname === "/admin/platform" ? "active" : undefined}
                aria-current={pathname === "/admin/platform" ? "page" : undefined}
                onClick={() => setNavOpen(false)}
              >
                <Icon name="settings" />
                <span>Maintenance mode</span>
              </Link>
            </div>
          ) : null}
        </nav>

        <div className="cv-rail-bottom">
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
            <Link href="/monitoring" className="cv-icon-btn" aria-label="Open monitoring" title="Open monitoring">
              <Icon name="bell" />
            </Link>
            <div className="cv-user-chip" title={session.email}>
              <span className="cv-avatar" aria-hidden="true">
                {initials}
              </span>
              <span className="cv-user-copy">
                <strong>{session.email}</strong>
                <span>{planLabel === "Subscription inactive" ? planLabel : `${planLabel} plan`}</span>
              </span>
            </div>
          </div>
        </header>
        <main className="cv-main">
          <ServiceNotices
            status={maintenanceStatus ? {
              maintenance_mode: maintenanceStatus.maintenance_mode,
              maintenance_message: maintenanceStatus.maintenance_message,
              planned_maintenance_message: maintenanceStatus.planned_maintenance_message || "",
              planned_maintenance_starts_at: maintenanceStatus.planned_maintenance_starts_at || null,
              planned_maintenance_ends_at: maintenanceStatus.planned_maintenance_ends_at || null,
            } : null}
          />
          {children}
        </main>
      </div>
    </div>
  );
}

