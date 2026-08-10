"use client";

import { usePathname } from "next/navigation";
import { useReportWebVitals } from "next/web-vitals";
import { useEffect } from "react";

import {
  markNavigationStart,
  reportFrontendMetric,
  reportNavigationComplete,
} from "@/lib/frontend-telemetry";

export function FrontendTelemetry() {
  const pathname = usePathname();

  useReportWebVitals((metric) => {
    reportFrontendMetric({
      detail: { id: metric.id, rating: metric.rating },
      kind: "web-vital",
      name: metric.name,
      value: metric.value,
    });
  });

  useEffect(() => {
    function handleDocumentClick(event: MouseEvent) {
      const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(target instanceof HTMLAnchorElement) || target.origin !== window.location.origin) {
        return;
      }
      if (target.pathname !== window.location.pathname) {
        markNavigationStart(target.pathname);
      }
    }

    function handlePopState() {
      markNavigationStart(window.location.pathname);
    }

    document.addEventListener("click", handleDocumentClick, { capture: true });
    window.addEventListener("popstate", handlePopState);
    return () => {
      document.removeEventListener("click", handleDocumentClick, { capture: true });
      window.removeEventListener("popstate", handlePopState);
    };
  }, []);

  useEffect(() => {
    reportNavigationComplete(pathname);
  }, [pathname]);

  return null;
}
