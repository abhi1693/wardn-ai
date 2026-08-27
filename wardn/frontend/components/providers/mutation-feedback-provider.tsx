"use client";

import { Copy, RefreshCw, X } from "lucide-react";
import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/atoms/button";
import { AsyncFeedback } from "@/components/molecules/async-feedback";
import { ApiError } from "@/lib/api/errors";
import {
  type MutationFeedbackEvent,
  subscribeMutationFeedback,
} from "@/lib/api/mutation-feedback-events";

type FailedMutation = Extract<MutationFeedbackEvent, { type: "error" }>;

const MutationFeedbackContext = createContext<{
  failure: FailedMutation | null;
  setFailure: (failure: FailedMutation | null) => void;
} | null>(null);

export function MutationFeedbackProvider({ children }: { children: ReactNode }) {
  const [failure, setFailure] = useState<FailedMutation | null>(null);

  useEffect(
    () =>
      subscribeMutationFeedback((event) => {
        if (event.type === "pending") {
          toast.loading(event.message, { id: event.id });
          setFailure(null);
          return;
        }
        if (event.type === "success") {
          toast.success(event.message, { id: event.id });
          setFailure(null);
          return;
        }
        toast.error(event.message, {
          description: event.error.requestId
            ? `Request ID: ${event.error.requestId}`
            : "Diagnostics are available below.",
          id: event.id,
        });
        setFailure(event);
      }),
    []
  );

  return (
    <MutationFeedbackContext.Provider value={{ failure, setFailure }}>
      {children}
    </MutationFeedbackContext.Provider>
  );
}

function diagnosticsFor(error: Error) {
  if (error instanceof ApiError) {
    return error.diagnostics();
  }
  return [
    "Wardn UI error",
    `Time: ${new Date().toISOString()}`,
    "Request ID: Unavailable",
    `Message: ${error.message}`,
  ].join("\n");
}

export function MutationErrorDetails({
  compact = false,
  error,
  announceAs,
  onDismiss,
  onRetry,
}: {
  compact?: boolean;
  error: Error;
  announceAs?: "alert" | "status";
  onDismiss?: () => void;
  onRetry?: () => Promise<unknown> | unknown;
}) {
  const [retrying, setRetrying] = useState(false);
  const requestId = error instanceof ApiError ? error.requestId : undefined;

  async function copyDiagnostics() {
    try {
      await navigator.clipboard.writeText(diagnosticsFor(error));
      toast.success("Diagnostics copied.");
    } catch {
      toast.error("Diagnostics could not be copied.");
    }
  }

  async function retry() {
    if (!onRetry) {
      return;
    }
    setRetrying(true);
    try {
      await onRetry();
    } catch {
      // The retried request publishes its own actionable error feedback.
    } finally {
      setRetrying(false);
    }
  }

  return (
    <AsyncFeedback announceAs={announceAs} className="space-y-2" variant="error">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium">
            {compact ? "Diagnostics for the error shown on this page" : error.message}
          </p>
          <p className="mt-1 text-xs opacity-80">
            {requestId ? `Request ID: ${requestId}` : "No request ID was returned."}
          </p>
        </div>
        {onDismiss ? (
          <Button
            aria-label="Dismiss error"
            className="-mr-1 -mt-1"
            onClick={onDismiss}
            size="icon"
            type="button"
            variant="ghost"
          >
            <X />
          </Button>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        {onRetry ? (
          <Button disabled={retrying} onClick={() => void retry()} size="sm" type="button" variant="outline">
            <RefreshCw className={retrying ? "animate-spin" : undefined} />
            {retrying ? "Retrying..." : "Retry"}
          </Button>
        ) : null}
        <Button onClick={() => void copyDiagnostics()} size="sm" type="button" variant="outline">
          <Copy />
          Copy diagnostics
        </Button>
      </div>
    </AsyncFeedback>
  );
}

export function MutationFeedbackOutlet() {
  const context = useContext(MutationFeedbackContext);
  const [matchingLocalError, setMatchingLocalError] = useState(false);
  const failure = context?.failure ?? null;

  useEffect(() => {
    if (!failure) {
      return;
    }
    const checkForLocalError = () => {
      const matchingAlert = Array.from(document.querySelectorAll<HTMLElement>('[role="alert"]'))
        .filter((element) => !element.closest("[data-mutation-feedback-outlet]"))
        .filter((element) => !element.closest("[data-sonner-toaster]"))
        .some((element) => element.textContent?.includes(failure.error.message));
      setMatchingLocalError(matchingAlert);
    };
    checkForLocalError();
    const observer = new MutationObserver(checkForLocalError);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [failure]);

  if (!context?.failure) {
    return null;
  }
  return (
    <div data-mutation-feedback-outlet>
      <MutationErrorDetails
        announceAs="status"
        compact={matchingLocalError}
        error={context.failure.error}
        onDismiss={() => context.setFailure(null)}
        onRetry={
          context.failure.retry
            ? async () => {
                context.setFailure(null);
                await failure?.retry?.();
              }
            : undefined
        }
      />
    </div>
  );
}
