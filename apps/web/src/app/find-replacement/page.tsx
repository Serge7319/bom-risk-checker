"use client";

import { ToolPage } from "@/components/ToolPage";
import { PAGE_META } from "@/lib/routes";

export default function Page() {
  return (
    <ToolPage
      meta={PAGE_META.replacement}
      capability="Candidate search and fit evidence scoring are not exposed by the migration API yet."
    >
    </ToolPage>
  );
}
