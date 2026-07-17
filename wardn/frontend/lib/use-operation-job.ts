"use client";

import { useCallback, useEffect, useRef } from "react";

import type { MCPOperationJobRead } from "@/lib/api/generated/model";

const DEFAULT_MAX_DURATION_MS = 10 * 60 * 1_000;
const INITIAL_POLL_INTERVAL_MS = 1_000;
const MAX_POLL_INTERVAL_MS = 15_000;
const POLL_BACKOFF_MULTIPLIER = 1.6;

type WaitForOperationJobOptions<Result> = {
  failureMessage: string;
  fetchJob: (jobId: string, signal: AbortSignal) => Promise<MCPOperationJobRead>;
  initialJob: MCPOperationJobRead;
  onProgress: (message: string) => void;
  pendingMessage: string;
  readResult: (job: MCPOperationJobRead) => Result;
  timeoutMessage: string;
  maxDurationMs?: number;
};

function abortError() {
  return new DOMException("Operation job polling was cancelled.", "AbortError");
}

export function isOperationJobPollingCancelled(caught: unknown) {
  return caught instanceof DOMException && caught.name === "AbortError";
}

function throwIfAborted(signal: AbortSignal) {
  if (signal.aborted) {
    throw abortError();
  }
}

function abortableDelay(milliseconds: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    throwIfAborted(signal);
    const timeout = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    function onAbort() {
      window.clearTimeout(timeout);
      reject(abortError());
    }
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function waitUntilPageVisible(signal: AbortSignal) {
  if (document.visibilityState !== "hidden") {
    return Promise.resolve();
  }
  return new Promise<void>((resolve, reject) => {
    throwIfAborted(signal);
    function cleanup() {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      signal.removeEventListener("abort", onAbort);
    }
    function onVisibilityChange() {
      if (document.visibilityState !== "hidden") {
        cleanup();
        resolve();
      }
    }
    function onAbort() {
      cleanup();
      reject(abortError());
    }
    document.addEventListener("visibilitychange", onVisibilityChange);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

async function pollOperationJob<Result>(
  options: WaitForOperationJobOptions<Result>,
  signal: AbortSignal
) {
  const {
    failureMessage,
    fetchJob,
    initialJob,
    maxDurationMs = DEFAULT_MAX_DURATION_MS,
    onProgress,
    pendingMessage,
    readResult,
    timeoutMessage,
  } = options;
  const deadline = Date.now() + maxDurationMs;
  let interval = INITIAL_POLL_INTERVAL_MS;
  let job = initialJob;

  while (true) {
    throwIfAborted(signal);
    onProgress(job.progressMessage || pendingMessage);
    if (job.status === "succeeded") {
      return readResult(job);
    }
    if (job.status === "failed") {
      throw new Error(job.errorMessage || failureMessage);
    }

    if (Date.now() >= deadline) {
      throw new Error(timeoutMessage);
    }
    await waitUntilPageVisible(signal);
    const visibleRemaining = deadline - Date.now();
    if (visibleRemaining <= 0) {
      throw new Error(timeoutMessage);
    }
    await abortableDelay(Math.min(interval, visibleRemaining), signal);
    await waitUntilPageVisible(signal);
    if (Date.now() >= deadline) {
      throw new Error(timeoutMessage);
    }

    try {
      job = await fetchJob(job.jobId, signal);
    } catch (caught) {
      if (signal.aborted) {
        throw abortError();
      }
      throw caught;
    }
    interval = Math.min(MAX_POLL_INTERVAL_MS, interval * POLL_BACKOFF_MULTIPLIER);
  }
}

export function useOperationJobPoller() {
  const controllerRef = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  useEffect(() => cancel, [cancel]);

  const waitForJob = useCallback(
    async <Result,>(options: WaitForOperationJobOptions<Result>) => {
      cancel();
      const controller = new AbortController();
      controllerRef.current = controller;
      try {
        return await pollOperationJob(options, controller.signal);
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }
      }
    },
    [cancel]
  );

  return { cancel, waitForJob };
}
