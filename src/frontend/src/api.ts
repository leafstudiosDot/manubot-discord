let csrfToken: string | null = null;

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

export function setCsrfToken(token: string | null | undefined) {
  csrfToken = token || null;
}

export function clearCsrfToken() {
  csrfToken = null;
}

export function getCsrfToken() {
  return csrfToken;
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);

  if (!SAFE_METHODS.has(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  return fetch(input, {
    ...init,
    headers,
    credentials: init.credentials || "same-origin",
  });
}
