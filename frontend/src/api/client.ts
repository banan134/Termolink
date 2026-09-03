/**
 * HTTP client for /api/v1 (docs/04): session cookie + X-CSRFToken, JSON in/out,
 * error envelope {"error": {code, message, fields, ...}} → ApiError.
 */

export type ErrorEnvelope = {
  code: string;
  message: string;
  fields?: Record<string, string[]>;
  retry_after_s?: number;
};

export class ApiError extends Error {
  status: number;
  code: string;
  fields: Record<string, string[]>;
  retryAfterS?: number;
  /** Extra keys of the error envelope (e.g. `reasons` for control_not_allowed). */
  extra: Record<string, unknown>;

  constructor(status: number, body: ErrorEnvelope | null) {
    super(body?.message ?? `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body?.code ?? (status === 0 ? "network" : "error");
    this.fields = body?.fields ?? {};
    this.retryAfterS = body?.retry_after_s;
    const known = new Set(["code", "message", "fields", "retry_after_s"]);
    this.extra = Object.fromEntries(Object.entries(body ?? {}).filter(([k]) => !known.has(k)));
  }
}

export function csrfToken(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
};

export async function api<T = unknown>(path: string, options: Options = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const token = csrfToken();
    if (token) headers["X-CSRFToken"] = token;
  }
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch {
    throw new ApiError(0, { code: "network", message: "Brak połączenia z serwerem." });
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!response.ok) {
    const envelope = (data as { error?: ErrorEnvelope } | null)?.error ?? null;
    throw new ApiError(response.status, envelope);
  }
  return data as T;
}

/** Ensure a csrftoken cookie exists before the first mutating call (Django sets it on GET). */
export async function primeCsrf(): Promise<void> {
  if (!csrfToken()) await fetch("/api/v1/auth/csrf", { credentials: "same-origin" });
}
