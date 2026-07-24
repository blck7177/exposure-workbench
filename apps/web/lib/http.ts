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
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}
