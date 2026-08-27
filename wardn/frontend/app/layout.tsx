import "./globals.css";

import type { Metadata, Viewport } from "next";
import Script from "next/script";
import type { ReactNode } from "react";

import { Toaster } from "@/components/atoms/sonner";
import { TooltipProvider } from "@/components/atoms/tooltip";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { FrontendTelemetry } from "@/components/providers/frontend-telemetry";
import { MutationFeedbackProvider } from "@/components/providers/mutation-feedback-provider";
import { NavigationStateRestoration } from "@/components/providers/navigation-state-restoration";

const appTitle = "Wardn AI";
const appDescription = "MCP operations for home-lab workspaces.";
const iconVersion = "brand-20260729";

function metadataBaseUrl() {
  const configuredUrl = process.env.NEXT_PUBLIC_SITE_URL ?? process.env.WARDN_FRONTEND_BASE_URL;
  try {
    return new URL(configuredUrl ?? "http://localhost:3000");
  } catch {
    return new URL("http://localhost:3000");
  }
}

export const metadata: Metadata = {
  metadataBase: metadataBaseUrl(),
  title: {
    default: appTitle,
    template: `%s | ${appTitle}`,
  },
  description: appDescription,
  applicationName: appTitle,
  manifest: "/site.webmanifest",
  icons: {
    icon: [
      { url: `/favicon.ico?v=${iconVersion}`, sizes: "any" },
      { url: `/favicon-16x16.png?v=${iconVersion}`, sizes: "16x16", type: "image/png" },
      { url: `/favicon-32x32.png?v=${iconVersion}`, sizes: "32x32", type: "image/png" },
    ],
    apple: [
      { url: `/apple-touch-icon.png?v=${iconVersion}`, sizes: "180x180", type: "image/png" },
    ],
    shortcut: [`/favicon.ico?v=${iconVersion}`],
  },
  openGraph: {
    title: appTitle,
    description: appDescription,
    siteName: appTitle,
    images: [{ url: "/og-image.png", width: 1200, height: 630, alt: appTitle }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: appTitle,
    description: appDescription,
    images: ["/og-image.png"],
  },
  other: {
    "msapplication-TileColor": "#0f172a",
    "msapplication-TileImage": "/mstile-150x150.png",
  },
};

export const viewport: Viewport = {
  themeColor: [
    { color: "#f6f7f9", media: "(prefers-color-scheme: light)" },
    { color: "#0b0f14", media: "(prefers-color-scheme: dark)" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <Script src="/wardn-config.js" strategy="beforeInteractive" />
      </head>
      <body>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          disableTransitionOnChange
          enableSystem
        >
          <TooltipProvider delayDuration={300}>
            <FrontendTelemetry />
            <NavigationStateRestoration />
            <MutationFeedbackProvider>{children}</MutationFeedbackProvider>
            <Toaster closeButton position="bottom-right" richColors />
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
