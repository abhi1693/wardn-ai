"use client";

import { useEffect, useState } from "react";

export function useUrlState(key: string, defaultValue = "") {
  const [value, setValue] = useState(() => {
    if (typeof window === "undefined") {
      return defaultValue;
    }
    return new URLSearchParams(window.location.search).get(key) ?? defaultValue;
  });

  useEffect(() => {
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
