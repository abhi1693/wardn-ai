import { secretBackendErrorMessage } from "./secret-backend-errors";

export function secretBackendValidationMessage(payload: unknown, fallback: string) {
  if (payload && typeof payload === "object" && "message" in payload) {
    const message = (payload as { message?: unknown }).message;
    if (typeof message === "string" && message.trim().length > 0) {
      return message;
    }
  }
  return secretBackendErrorMessage(payload, fallback);
}

export function secretBackendValidationOk(payload: unknown) {
  return Boolean(payload && typeof payload === "object" && (payload as { ok?: unknown }).ok === true);
}
