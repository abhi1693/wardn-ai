export type FrontendMetric = {
  detail?: Record<string, boolean | number | string>;
  kind: "api" | "navigation" | "web-vital";
  name: string;
  path?: string;
  value: number;
};

type PendingNavigation = {
  path: string;
  startedAt: number;
};

let pendingNavigation: PendingNavigation | null = null;

function sampleRate() {
  if (process.env.NODE_ENV !== "production") {
    return 1;
  }
  const configured = Number(process.env.NEXT_PUBLIC_FRONTEND_TELEMETRY_SAMPLE_RATE ?? "0.1");
  return Number.isFinite(configured) ? Math.min(1, Math.max(0, configured)) : 0.1;
}

export function telemetryPath(value: string) {
  try {
    const url = new URL(value, window.location.origin);
    return url.pathname
      .replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, ":id")
      .replace(/\/(run|conversation|provider|installation)-[^/]+/gi, "/$1-:id");
  } catch {
    return value.split("?", 1)[0];
  }
}

export function reportFrontendMetric(metric: FrontendMetric) {
  if (typeof window === "undefined" || Math.random() > sampleRate()) {
    return;
  }
  const body = JSON.stringify({
    ...metric,
    path: metric.path ? telemetryPath(metric.path) : telemetryPath(window.location.pathname),
    recordedAt: new Date().toISOString(),
  });
  if (navigator.sendBeacon?.("/api/frontend-telemetry", body)) {
    return;
  }
  void fetch("/api/frontend-telemetry", {
    body,
    headers: { "content-type": "application/json" },
    keepalive: true,
    method: "POST",
  }).catch(() => undefined);
}

export function markNavigationStart(path: string) {
  if (typeof window === "undefined") {
    return;
  }
  pendingNavigation = { path: telemetryPath(path), startedAt: performance.now() };
}

export function reportNavigationComplete(path: string) {
  if (
    typeof window === "undefined" ||
    !pendingNavigation ||
    pendingNavigation.path !== telemetryPath(path)
  ) {
    return;
  }
  reportFrontendMetric({
    kind: "navigation",
    name: "route-transition",
    path,
    value: Math.max(0, performance.now() - pendingNavigation.startedAt),
  });
  pendingNavigation = null;
}
