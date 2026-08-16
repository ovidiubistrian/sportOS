import type { ApiErrorBody } from "./types";

/**
 * Typed API client.
 *
 * The only sanctioned way for a frontend to reach the API — hand-written
 * `fetch` calls against our own backend are lint-blocked, so there is exactly
 * one place that knows about auth headers, tenant headers, idempotency keys
 * and the error envelope.
 */

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? {};
    this.requestId = body.request_id ?? null;
  }

  /**
   * Whether the session itself is gone, as opposed to this one request being
   * refused.
   *
   * Not every 401 means "sign in again". `STEP_UP_REQUIRED` is the server
   * asking for a second factor before one particular action — the session is
   * perfectly valid — and treating it as a lost session throws the person out
   * of the application for doing something sensitive, which is both wrong and
   * the exact moment they will least understand it.
   */
  get isAuthError(): boolean {
    return this.status === 401 && this.code !== "STEP_UP_REQUIRED";
  }

  /** The server wants a second factor before it will do this. */
  get needsStepUp(): boolean {
    return this.code === "STEP_UP_REQUIRED";
  }

  /** Field-level messages from a 422, keyed by field path. */
  get fieldErrors(): Record<string, string> {
    const fields = this.details.fields;
    if (!Array.isArray(fields)) return {};
    return Object.fromEntries(
      fields
        .filter((f): f is { field: string; message: string } =>
          Boolean(f && typeof f === "object" && "field" in f),
        )
        .map((f) => [f.field, f.message]),
    );
  }
}

export interface ClientOptions {
  baseUrl: string;
  getToken: () => string | null;
  getTenantId: () => string | null;
  onUnauthenticated?: () => void;
}

type Query = Record<string, string | number | boolean | undefined | null>;

export class ApiClient {
  constructor(private readonly options: ClientOptions) {}

  private url(path: string, query?: Query): string {
    const url = new URL(path, this.options.baseUrl);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
    return url.toString();
  }

  private async request<T>(
    method: string,
    path: string,
    init: {
      query?: Query;
      body?: unknown;
      form?: FormData;
      idempotencyKey?: string;
    } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" };

    const token = this.options.getToken();
    if (token) headers.Authorization = `Bearer ${token}`;

    // The server validates this against the caller's memberships; sending it
    // is a request for a tenant, never an assertion of authority.
    const tenantId = this.options.getTenantId();
    if (tenantId) headers["X-Tenant-Id"] = tenantId;

    if (init.body !== undefined) headers["Content-Type"] = "application/json";
    if (init.idempotencyKey) headers["Idempotency-Key"] = init.idempotencyKey;

    // A multipart body sets its own Content-Type, including the boundary the
    // browser generates. Setting it by hand produces a body the server cannot
    // parse, which is the classic silent upload failure.
    const body =
      init.form ?? (init.body === undefined ? undefined : JSON.stringify(init.body));

    const response = await fetch(this.url(path, init.query), { method, headers, body });

    if (response.status === 204) return undefined as T;

    const payload = await response.json().catch(() => null);

    if (!response.ok) {
      const body: ApiErrorBody = payload ?? {
        code: "INTERNAL_ERROR",
        message: response.statusText || "Request failed",
        details: {},
        request_id: response.headers.get("X-Request-Id"),
      };
      const error = new ApiError(response.status, body);
      if (error.isAuthError) this.options.onUnauthenticated?.();
      throw error;
    }

    return payload as T;
  }

  get<T>(path: string, query?: Query): Promise<T> {
    return this.request<T>("GET", path, { query });
  }

  post<T>(path: string, body?: unknown, idempotencyKey?: string): Promise<T> {
    return this.request<T>("POST", path, { body, idempotencyKey });
  }

  /** Multipart upload. The auth and tenant headers travel exactly as they do
      on every other call — an upload is not a special case for authorization. */
  upload<T>(path: string, form: FormData): Promise<T> {
    return this.request<T>("POST", path, { form });
  }

  patch<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>("PATCH", path, { body });
  }

  put<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>("PUT", path, { body });
  }

  delete<T>(path: string): Promise<T> {
    return this.request<T>("DELETE", path);
  }
}
