"use client";

import { ToolPage } from "@/components/ToolPage";
import { PAGE_META } from "@/lib/routes";

export default function Page() {
  return (
    <ToolPage
      meta={PAGE_META.replacement}
      capability="Candidate search and evidence-backed fit scoring are not available here yet."
    >
    </ToolPage>
  );
}
