import "./globals.css";

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

const appTitle = "Wardn AI";
const appDescription = "MCP operations for home-lab workspaces.";

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
      { url: "/favicon.ico", sizes: "any" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
    shortcut: ["/favicon.ico"],
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
  themeColor: "#0f172a",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
