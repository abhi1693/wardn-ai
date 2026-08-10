"use client";

import { useCallback, useEffect } from "react";

const defaultMessage = "You have unsaved changes. Leave this page?";

export function useUnsavedChanges(isDirty: boolean, message = defaultMessage) {
  useEffect(() => {
    if (!isDirty) {
      return;
    }
    function preventUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = message;
    }
    window.addEventListener("beforeunload", preventUnload);
    return () => window.removeEventListener("beforeunload", preventUnload);
  }, [isDirty, message]);

  return useCallback(() => !isDirty || window.confirm(message), [isDirty, message]);
}
