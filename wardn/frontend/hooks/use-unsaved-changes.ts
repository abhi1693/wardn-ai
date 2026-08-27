"use client";

import { useCallback, useEffect, useState } from "react";

const defaultMessage = "You have unsaved changes. Leave this page?";
const activeDirtyForms = new Map<symbol, string>();

export function confirmActiveFormNavigation() {
  const message = activeDirtyForms.values().next().value;
  return typeof message !== "string" || window.confirm(message);
}

export function useUnsavedChanges(isDirty: boolean, message = defaultMessage) {
  const [registration] = useState(() => Symbol("wardn-dirty-form"));

  useEffect(() => {
    if (!isDirty) {
      return;
    }
    activeDirtyForms.set(registration, message);
    function preventUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = message;
    }
    function preventLinkNavigation(event: MouseEvent) {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }
      const target = event.target;
      const anchor = target instanceof Element ? target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!anchor || anchor.target === "_blank" || anchor.hasAttribute("download")) {
        return;
      }
      const destination = new URL(anchor.href, window.location.href);
      const current = new URL(window.location.href);
      if (
        destination.origin === current.origin &&
        destination.pathname === current.pathname &&
        destination.search === current.search
      ) {
        return;
      }
      if (!window.confirm(message)) {
        event.preventDefault();
        event.stopPropagation();
      }
    }
    window.addEventListener("beforeunload", preventUnload);
    document.addEventListener("click", preventLinkNavigation, true);
    return () => {
      activeDirtyForms.delete(registration);
      window.removeEventListener("beforeunload", preventUnload);
      document.removeEventListener("click", preventLinkNavigation, true);
    };
  }, [isDirty, message, registration]);

  return useCallback(() => !isDirty || window.confirm(message), [isDirty, message]);
}
