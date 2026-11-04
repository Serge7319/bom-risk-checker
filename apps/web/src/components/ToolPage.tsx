"use client";

import { Shell } from "@/components/Shell";
import {
  CapabilityStub,
  PageHeader,
  PrimaryLink,
  SecondaryLink,
} from "@/components/PageHeader";
import type { PageMeta } from "@/lib/routes";
import { useRequireSession } from "@/lib/session";

export function ToolPage({
  meta,
  capability,
  children,
}: {
  meta: PageMeta;
  capability: string;
  children?: React.ReactNode;
}) {
  const session = useRequireSession();
  if (!session) return null;

  return (
    <Shell session={session}>
      <PageHeader
        meta={meta}
        actions={
          <>
            <PrimaryLink href="/bom-analyzer">BOM Analyzer</PrimaryLink>
            <SecondaryLink href="/">Home</SecondaryLink>
          </>
        }
      />
      {children}
      <CapabilityStub
        capability={capability}
        nextStep={<PrimaryLink href="/bom-analyzer">Run synthetic BOM analysis</PrimaryLink>}
      />
    </Shell>
  );
}
