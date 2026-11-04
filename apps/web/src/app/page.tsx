"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Shell } from "@/components/Shell";
import { getSession, type Session } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const [session, setLocalSession] = useState<Session | null>(null);

  useEffect(() => {
    const current = getSession();
    if (!current) {
      router.replace("/login");
      return;
    }
    setLocalSession(current);
  }, [router]);

  if (!session) return null;

  return (
    <Shell session={session}>
      <section className="cv-hero cv-card">
        <h1>Home</h1>
        <p>
          Next.js migration preview of the Cadivor workspace shell. Production
          Streamlit remains live on app.cadivor.com. This preview uses synthetic
          smoke auth and offline BOM analysis only.
        </p>
        <div style={{ marginTop: 18 }}>
          <Link className="cv-button" href="/bom-analyzer">
            Open BOM Analyzer
          </Link>
        </div>
      </section>
    </Shell>
  );
}
