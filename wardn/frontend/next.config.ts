import type { NextConfig } from "next";

function connectSources() {
  const configured = [
    process.env.NEXT_PUBLIC_API_BASE_URL,
    ...(process.env.WARDN_CSP_CONNECT_SRC ?? "").split(/\s+/),
  ];
  const origins = configured.flatMap((value) => {
    if (!value?.trim()) {
      return [];
    }
    try {
      const url = new URL(value);
      return ["http:", "https:", "ws:", "wss:"].includes(url.protocol) ? [url.origin] : [];
    } catch {
      return [];
    }
  });
  return Array.from(new Set(["'self'", ...origins])).join(" ");
}

const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  `connect-src ${connectSources()}`,
  "font-src 'self' data:",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "img-src 'self' data: blob: https:",
  "manifest-src 'self'",
  "media-src 'self'",
  "object-src 'none'",
  `script-src 'self' 'unsafe-inline'${process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "worker-src 'self' blob:",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Permissions-Policy",
    value: "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
  },
];

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.1.101"],
  devIndicators: false,
  experimental: {
    authInterrupts: true,
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  output: "standalone",
};

export default nextConfig;
