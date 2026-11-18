import type { Metadata } from "next";
import "./globals.css";
import { AnalyticsTracker } from "@/components/AnalyticsTracker";
import { AnalyticsConsent } from "@/components/AnalyticsConsent";

export const metadata: Metadata = {
  title: "Cadivor",
  description: "Cadivor engineering intelligence and BOM analysis platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <AnalyticsTracker />
        <AnalyticsConsent />
        {children}
      </body>
    </html>
  );
}
