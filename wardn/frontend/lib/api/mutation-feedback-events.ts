import type { ApiError } from "./errors";

export type MutationFeedbackEvent =
  | {
      id: string;
      message: string;
      type: "pending";
    }
  | {
      id: string;
      message: string;
      type: "success";
    }
  | {
      error: ApiError;
      id: string;
      message: string;
      retry?: () => Promise<unknown>;
      type: "error";
    };

const eventName = "wardn:mutation-feedback";

export function publishMutationFeedback(detail: MutationFeedbackEvent) {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent<MutationFeedbackEvent>(eventName, { detail }));
}

export function subscribeMutationFeedback(listener: (event: MutationFeedbackEvent) => void) {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const receive = (event: Event) => listener((event as CustomEvent<MutationFeedbackEvent>).detail);
  window.addEventListener(eventName, receive);
  return () => window.removeEventListener(eventName, receive);
}
