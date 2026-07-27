// Single API transport (V2-A). Both lib/api.ts and lib/issuer.ts route through
// apiFetch so the Clerk bearer token is attached in ONE place — the frontend
// analogue of the backend's single auth choke point. A duplicated transport was
// exactly what let signed-in chat/research writes go out token-less.

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8103";

// A Clerk-aware component registers the token getter once (see components/Auth).
// Null getter => anonymous (read-only); write routes then 401 by design.
let _tokenGetter: (() => Promise<string | null>) | null = null;

export function setAuthTokenGetter(fn: (() => Promise<string | null>) | null): void {
  _tokenGetter = fn;
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options?.headers as Record<string, string>) ?? {}),
  };
  if (_tokenGetter) {
    const token = await _tokenGetter();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const text = await res.text();
    // Message format is load-bearing: callers slice the JSON body out of it.
    // status/body are attached so they don't have to (V2-E4).
    const err: ApiError = new Error(`API ${res.status}: ${text}`);
    err.status = res.status;
    try {
      err.body = JSON.parse(text);
    } catch {
      // non-JSON body (a proxy error page, say) — leave body undefined
    }
    throw err;
  }
  return res.json() as Promise<T>;
}

export type ApiError = Error & { status?: number; body?: unknown };

/**
 * The parsed error body, however the error reached us. Prefers the field
 * apiFetch attached and falls back to slicing JSON out of the message, so it
 * still works on errors that crossed a boundary as plain Errors.
 */
export function apiErrorBody(err: unknown): Record<string, unknown> | null {
  if (err && typeof err === "object" && "body" in err) {
    const b = (err as ApiError).body;
    if (b && typeof b === "object") return b as Record<string, unknown>;
  }
  const msg = err instanceof Error ? err.message : String(err);
  const i = msg.indexOf("{");
  if (i < 0) return null;
  try {
    const parsed = JSON.parse(msg.slice(i));
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

/** FastAPI wraps every HTTPException detail in `detail`; unwrap it. */
export function apiErrorDetail(err: unknown): Record<string, unknown> | null {
  const body = apiErrorBody(err);
  if (!body) return null;
  const d = body.detail;
  return d && typeof d === "object" ? (d as Record<string, unknown>) : body;
}
