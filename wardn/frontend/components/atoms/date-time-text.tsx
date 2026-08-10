"use client";

import { useSyncExternalStore } from "react";

import { formatUserDateTime, userDateTimeOptions } from "@/lib/date-time";

type DateTimeTextProps = {
  className?: string;
  fallback?: string;
  locale?: string | string[];
  options?: Intl.DateTimeFormatOptions;
  value?: string | null;
};

function subscribe() {
  return () => {};
}

function browserTimeZone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
}

function serverTimeZone() {
  return null;
}

export function DateTimeText({
  className,
  fallback = "Not set",
  locale,
  options = userDateTimeOptions,
  value,
}: DateTimeTextProps) {
  const timeZone = useSyncExternalStore(subscribe, browserTimeZone, serverTimeZone);

  const formatted = formatUserDateTime(
    value,
    fallback,
    timeZone ? { ...options, timeZone } : options,
    locale
  );

  return (
    <span className={className} suppressHydrationWarning>
      {formatted}
    </span>
  );
}
