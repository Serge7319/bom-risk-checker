"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearSession, type Session } from "@/lib/api";

const NAV = [
  { href: "/", label: "Home" },
  { href: "/bom-analyzer", label: "BOM Analyzer" },
];

export function Shell({
  session,
  children,
}: {
  session: Session;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <div className="cv-shell">
      <aside className="cv-rail" aria-label="Workspace navigation">
        <div className="cv-brand">
          <span className="cv-mark" aria-hidden>
            C
          </span>
          <div>
            <strong>Cadivor</strong>
            <small>ENGINEERING INTELLIGENCE</small>
          </div>
        </div>
        <div className="cv-workspace-card">
          <span>WORKSPACE</span>
          <strong>{session.workspace}</strong>
          <em>
            SUBSCRIPTION · {session.plan.toUpperCase()}
          </em>
        </div>
        <nav className="cv-nav">
          <p>WORKSPACE</p>
          {NAV.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
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
        </nav>
        <button
          type="button"
          className="cv-signout"
          onClick={() => {
            clearSession();
            router.replace("/login");
          }}
        >
          Sign out
        </button>
      </aside>
      <main className="cv-main">{children}</main>
    </div>
  );
}
