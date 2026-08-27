"use client";

import { ChevronDown } from "lucide-react";
import { type ReactNode, useSyncExternalStore } from "react";

import { Card, CardContent, CardHeader } from "@/components/atoms/card";
import { cn } from "@/lib/utils";

const dashboardSectionPreferenceEvent = "wardn:dashboard-section-preference";
const fallbackPreferences = new Map<string, string>();

function readPreference(key: string) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return fallbackPreferences.get(key) ?? null;
  }
}

function subscribeToPreferences(onStoreChange: () => void) {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(dashboardSectionPreferenceEvent, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(dashboardSectionPreferenceEvent, onStoreChange);
  };
}

type DashboardSectionProps = {
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  defaultOpen: boolean;
  description: ReactNode;
  id: string;
  persistenceKey: string;
  summary: ReactNode;
  title: string;
};

export function DashboardSection({
  children,
  className,
  contentClassName,
  defaultOpen,
  description,
  id,
  persistenceKey,
  summary,
  title,
}: DashboardSectionProps) {
  const preference = useSyncExternalStore(
    subscribeToPreferences,
    () => readPreference(persistenceKey),
    () => null
  );
  const isOpen = preference === null ? defaultOpen : preference === "open";
  const contentId = `${id}-content`;
  const titleId = `${id}-title`;

  function toggleSection() {
    const nextPreference = isOpen ? "closed" : "open";
    fallbackPreferences.set(persistenceKey, nextPreference);
    try {
      window.localStorage.setItem(persistenceKey, nextPreference);
    } catch {
      // The in-memory preference keeps the control usable when storage is unavailable.
    }
    window.dispatchEvent(new Event(dashboardSectionPreferenceEvent));
  }

  return (
    <section
      aria-labelledby={titleId}
      className={cn("scroll-mt-56", className)}
      id={id}
    >
      <Card className="overflow-hidden">
        <CardHeader className="p-0">
          <h2 id={titleId}>
            <button
              aria-controls={contentId}
              aria-expanded={isOpen}
              aria-label={`${isOpen ? "Collapse" : "Expand"} ${title}`}
              className="flex w-full items-start justify-between gap-4 px-4 py-3 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-ring/20 focus-visible:ring-[3px]"
              onClick={toggleSection}
              type="button"
            >
              <span className="min-w-0">
                <span className="block text-sm font-semibold leading-5 text-foreground">
                  {title}
                </span>
                <span className="mt-0.5 block text-sm leading-5 text-muted-foreground">
                  {description}
                </span>
              </span>
              <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                <span className="hidden sm:inline">{summary}</span>
                <ChevronDown
                  aria-hidden="true"
                  className={cn("size-4 transition-transform", isOpen && "rotate-180")}
                />
              </span>
            </button>
          </h2>
        </CardHeader>
        {isOpen ? (
          <CardContent className={cn("p-4", contentClassName)} id={contentId}>
            {children}
          </CardContent>
        ) : null}
      </Card>
    </section>
  );
}
