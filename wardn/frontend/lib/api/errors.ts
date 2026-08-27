export class ApiError extends Error {
  readonly body: unknown;
  readonly method?: string;
  readonly path?: string;
  readonly requestId?: string;
  readonly status: number;

  constructor(status: number, body: unknown, fallback: string, options: ApiErrorOptions = {}) {
    super(apiErrorMessage(body, fallback), options);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.method = options.method;
    this.path = options.path;
    this.requestId = options.requestId ?? requestIdFromBody(body);
  }

  get isRetryable() {
    return this.status === 0 || this.status === 408 || this.status === 429 || this.status >= 500;
  }

  diagnostics() {
    return apiErrorDiagnostics(this);
  }
}

type ApiErrorOptions = ErrorOptions & {
  method?: string;
  path?: string;
  requestId?: string;
};

function nonEmptyString(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function requestIdFromBody(body: unknown): string | undefined {
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return undefined;
  }
  const record = body as Record<string, unknown>;
  return nonEmptyString(record.requestId) ?? nonEmptyString(record.request_id);
}

export function apiRequestId(response: Response, body?: unknown) {
  return (
    nonEmptyString(response.headers.get("x-request-id")) ??
    nonEmptyString(response.headers.get("x-correlation-id")) ??
    requestIdFromBody(body)
  );
}

function diagnosticPath(path: string | undefined) {
  if (!path) {
    return undefined;
  }
  try {
    const parsed = new URL(path, "http://wardn.local");
    return parsed.pathname;
  } catch {
    return path.split("?", 1)[0];
  }
}

export function apiErrorDiagnostics(error: ApiError) {
  return [
    "Wardn API error",
    `Time: ${new Date().toISOString()}`,
    `Request ID: ${error.requestId ?? "Unavailable"}`,
    `Request: ${[error.method, diagnosticPath(error.path)].filter(Boolean).join(" ") || "Unavailable"}`,
    `Status: ${error.status || "Network error"}`,
    `Message: ${error.message}`,
  ].join("\n");
}

export function apiErrorMessage(body: unknown, fallback: string): string {
  if (typeof body === "string" && body.trim()) {
    return body;
  }
  if (Array.isArray(body)) {
    const messages = body
      .map((item) => apiErrorMessage(item, ""))
      .filter(Boolean);
    return messages.length > 0 ? messages.join("; ") : fallback;
  }
  if (!body || typeof body !== "object") {
    return fallback;
  }
  const record = body as Record<string, unknown>;
  for (const key of ["detail", "message", "error"]) {
    const message = apiErrorMessage(record[key], "");
    if (message) {
      return message;
    }
  }
  if (typeof record.msg === "string" && record.msg.trim()) {
    const location = Array.isArray(record.loc)
      ? record.loc.filter((part) => part !== "body").join(".")
      : "";
    return location ? `${location}: ${record.msg}` : record.msg;
  }
  return fallback;
}

export async function readApiResponseBody(response: Response): Promise<unknown> {
  if ([204, 205, 304].includes(response.status)) {
    return undefined;
  }
  let text: string;
  try {
    text = await response.text();
  } catch (cause) {
    throw new ApiError(0, undefined, "Wardn API response could not be read.", { cause });
  }
  if (!text) {
    return undefined;
  }
  const contentType = response.headers.get("content-type")?.toLocaleLowerCase() ?? "";
  if (!contentType.includes("json")) {
    return text;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

export async function responseErrorMessage(response: Response, fallback: string) {
  return apiErrorMessage(await readApiResponseBody(response), fallback);
}
