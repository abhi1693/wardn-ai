"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";

type FormSafetyOptions = {
  currentValue: unknown;
  enabled?: boolean;
  formId: string;
  initialValue: unknown;
  isSaving?: boolean;
  message?: string;
};

function snapshot(value: unknown) {
  return JSON.stringify(value, (_key, item: unknown) => {
    if (item instanceof Set) {
      return Array.from(item).sort();
    }
    return item;
  });
}

export function useFormSafety({
  currentValue,
  enabled = true,
  formId,
  initialValue,
  isSaving = false,
  message,
}: FormSafetyOptions) {
  const initialSnapshot = useMemo(() => snapshot(initialValue), [initialValue]);
  const currentSnapshot = useMemo(() => snapshot(currentValue), [currentValue]);
  const [baseline, setBaseline] = useState(initialSnapshot);
  const isDirty = enabled && currentSnapshot !== baseline;
  const confirmNavigation = useUnsavedChanges(isDirty && !isSaving, message);

  useEffect(() => {
    function submitWithKeyboard(event: KeyboardEvent) {
      if (
        event.key.toLowerCase() !== "s" ||
        (!event.metaKey && !event.ctrlKey) ||
        event.altKey ||
        event.shiftKey
      ) {
        return;
      }
      const form = document.getElementById(formId);
      if (!(form instanceof HTMLFormElement)) {
        return;
      }
      event.preventDefault();
      if (!isSaving) {
        form.requestSubmit();
      }
    }

    document.addEventListener("keydown", submitWithKeyboard);
    return () => document.removeEventListener("keydown", submitWithKeyboard);
  }, [formId, isSaving]);

  const markSaved = useCallback(() => {
    setBaseline(currentSnapshot);
  }, [currentSnapshot]);

  return {
    confirmNavigation,
    isDirty,
    markSaved,
  };
}
