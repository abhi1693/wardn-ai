"use client";

import { useEffect, useState } from "react";

const storagePrefix = "wardn:session-state:v1";

function storageKey(key: string) {
  return `${storagePrefix}:${window.location.pathname}:${key}`;
}

export function useSessionState<T>(key: string, defaultValue: T) {
  const [value, setValue] = useState<T>(() => {
    if (typeof window === "undefined") {
      return defaultValue;
    }
    try {
      const stored = window.sessionStorage.getItem(storageKey(key));
      return stored === null ? defaultValue : (JSON.parse(stored) as T);
    } catch {
      return defaultValue;
    }
  });

  useEffect(() => {
    try {
      window.sessionStorage.setItem(storageKey(key), JSON.stringify(value));
    } catch {
      // The state remains usable for the current mount without session storage.
    }
  }, [key, value]);

  return [value, setValue] as const;
}
