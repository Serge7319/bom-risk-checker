import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Shared engineering decision | Cadivor",
  robots: { index: false, follow: false, noarchive: true },
  referrer: "no-referrer",
};

export default function DecisionShareLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
