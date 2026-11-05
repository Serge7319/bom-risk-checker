"use client";

import { Shell } from "@/components/Shell";
import { CapabilityStub, PageHeader, PrimaryLink, SecondaryLink } from "@/components/PageHeader";
import { PAGE_META } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

export default function Page() {
  const session = useRequireSession();
  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={PAGE_META.settings}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">BOM Analyzer</PrimaryLink>
            <SecondaryLink href="/">Home</SecondaryLink>
          </>
        }
      />
      <section className="cv-card pad" style={{ marginBottom: 14 }}>
        <div className="cv-form-grid">
          <div className="cv-field">
            <label htmlFor="workspace-name">Workspace name</label>
            <input id="workspace-name" value={session.workspace} readOnly />
          </div>
          <div className="cv-field">
            <label htmlFor="plan">Plan</label>
            <input id="plan" value={session.plan} readOnly />
          </div>
          <div className="cv-field">
            <label htmlFor="email">Signed-in email</label>
            <input id="email" value={session.email} readOnly />
          </div>
        </div>
        <p className="cv-small-note" style={{ marginTop: 12 }}>
          Workspace and plan details are read-only in this test build. Changes
          are not saved here.
        </p>
      </section>
      <CapabilityStub
        capability="Workspace admin, evidence-source preferences, and billing settings stay on Streamlit production for now."
        nextStep={<PrimaryLink href="/bom-analyzer">Run synthetic BOM analysis</PrimaryLink>}
      />
    </Shell>
  );
}
