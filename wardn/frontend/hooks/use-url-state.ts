"use client";

import { useEffect, useState } from "react";

const storagePrefix = "wardn:url-state:v1";

function storageKey(key: string) {
  return `${storagePrefix}:${window.location.pathname}:${key}`;
}

function initialValue<T extends string>(key: string, defaultValue: T) {
  if (typeof window === "undefined") {
    return defaultValue;
  }
  const explicitValue = new URLSearchParams(window.location.search).get(key);
  if (explicitValue !== null) {
    return explicitValue as T;
  }
  try {
    return (window.sessionStorage.getItem(storageKey(key)) as T | null) ?? defaultValue;
  } catch {
    return defaultValue;
  }
}

export function useUrlState<T extends string = string>(key: string, defaultValue = "") {
  const [value, setValue] = useState<T>(() => {
    if (typeof window === "undefined") {
      return defaultValue as T;
    }
    return initialValue(key, defaultValue as T);
  });

  useEffect(() => {
    try {
      window.sessionStorage.setItem(storageKey(key), value);
    } catch {
      // URL state remains functional when session storage is unavailable.
    }
    const params = new URLSearchParams(window.location.search);
    if (value && value !== defaultValue) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
    const nextUrl = `${window.location.pathname}${params.size ? `?${params}` : ""}${window.location.hash}`;
    window.history.replaceState(window.history.state, "", nextUrl);
  }, [defaultValue, key, value]);

  return [value, setValue] as const;
}
