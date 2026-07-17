export class ApiError extends Error {
  readonly body: unknown;
  readonly status: number;

  constructor(status: number, body: unknown, fallback: string, options?: ErrorOptions) {
    super(apiErrorMessage(body, fallback), options);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  get isRetryable() {
    return this.status === 0 || this.status === 408 || this.status === 429 || this.status >= 500;
  }
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
