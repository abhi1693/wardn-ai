"use client";

import { useEffect, useRef } from "react";

type VisibilityPollingOptions = {
  enabled?: boolean;
  immediate?: boolean;
  intervalMs: number;
  maxIntervalMs?: number;
  onError?: (error: unknown) => void;
  poll: (signal: AbortSignal) => Promise<void>;
};

export function useVisibilityPolling({
  enabled = true,
  immediate = true,
  intervalMs,
  maxIntervalMs = intervalMs * 8,
  onError,
  poll,
}: VisibilityPollingOptions) {
  const pollRef = useRef(poll);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    pollRef.current = poll;
  }, [poll]);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let activeController: AbortController | null = null;
    let stopped = false;
    let timeoutId: number | undefined;
    let nextDelayMs = intervalMs;

    function clearScheduledPoll() {
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
        timeoutId = undefined;
      }
    }

    function schedulePoll(delayMs: number) {
      clearScheduledPoll();
      if (stopped || document.visibilityState === "hidden") {
        return;
      }
      timeoutId = window.setTimeout(() => {
        void runPoll();
      }, delayMs);
    }

    async function runPoll() {
      if (stopped || activeController || document.visibilityState === "hidden") {
        return;
      }

      const controller = new AbortController();
      activeController = controller;
      try {
        await pollRef.current(controller.signal);
        nextDelayMs = intervalMs;
      } catch (error) {
        if (!controller.signal.aborted) {
          onErrorRef.current?.(error);
          nextDelayMs = Math.min(Math.max(intervalMs, nextDelayMs * 2), maxIntervalMs);
        }
      } finally {
        if (activeController === controller) {
          activeController = null;
        }
      }

      if (!controller.signal.aborted) {
        schedulePoll(nextDelayMs);
      }
    }

    function handleVisibilityChange() {
      clearScheduledPoll();
      if (document.visibilityState === "hidden") {
        activeController?.abort();
        return;
      }
      nextDelayMs = intervalMs;
      void runPoll();
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    if (immediate) {
      void runPoll();
    } else {
      schedulePoll(intervalMs);
    }

    return () => {
      stopped = true;
      clearScheduledPoll();
      activeController?.abort();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [enabled, immediate, intervalMs, maxIntervalMs]);
}
