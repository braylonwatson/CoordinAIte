const API = (process.env.REACT_APP_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const AUTH_EXPIRED = "coordinaite:auth-expired";

// Access tokens live in memory. Only the browser handles the HttpOnly refresh
// cookie; neither token is persisted to localStorage or sessionStorage.
let accessToken = null;
let accountId = null;
let guestToken = null;
let refreshPromise = null;
let generation = 0;

const cookieHeaders = { "Content-Type": "application/json", "X-CSRF-Protection": "1" };

export function clearSession() {
  generation += 1;
  accessToken = null;
  accountId = null;
  refreshPromise = null;
}

export function setGuestGameToken(token) {
  guestToken = token || null;
}

function rememberLogin(data) {
  accessToken = data.access_token;
  accountId = data.user_id;
  return { user_id: data.user_id, name: data.username, email: data.email };
}

async function withRefreshLock(callback) {
  // Coordinate refresh-cookie rotation between tabs as well as within one tab.
  if (navigator.locks?.request) {
    return navigator.locks.request("coordinaite-auth-refresh", callback);
  }
  return callback();
}

export async function restoreSession() {
  if (!refreshPromise) {
    const startedAt = generation;
    const previousAccount = accountId;
    const pending = withRefreshLock(async () => {
      const response = await fetch(`${API}/auth/refresh`, {
        method: "POST", headers: cookieHeaders, credentials: "include",
      });
      if (!response.ok) {
        if (response.status === 401) return null;
        throw new Error("Unable to restore your session. Please try again.");
      }
      const data = await response.json();
      if (startedAt !== generation) return null;
      // Another tab may have signed into a different account. Never replay an
      // in-flight game mutation using that account's credentials.
      if (previousAccount !== null && previousAccount !== data.user_id) return null;
      rememberLogin(data);
      return data;
    });
    refreshPromise = pending;
    try {
      return await pending;
    } finally {
      if (refreshPromise === pending) refreshPromise = null;
    }
  }
  return refreshPromise;
}

export async function authenticate(mode, body) {
  const response = await withRefreshLock(() => fetch(`${API}/${mode}`, {
    method: "POST", headers: cookieHeaders, credentials: "include",
    body: JSON.stringify(body),
  }));
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === "string" ? data.detail : "Check your account details and try again.";
    throw new Error(message);
  }
  clearSession();
  return { user: rememberLogin(data), data };
}

export async function signOut() {
  const token = accessToken;
  clearSession();
  setGuestGameToken(null);
  const response = await withRefreshLock(() => fetch(`${API}/auth/logout`, {
    method: "POST", credentials: "include",
    headers: { ...cookieHeaders, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  }));
  if (!response.ok) throw new Error("Unable to finish signing out. Please try again.");
}

export async function apiFetch(path, options = {}) {
  const startedAt = generation;
  const usedToken = accessToken;
  const send = () => fetch(`${API}${path}`, {
    ...options,
    credentials: "omit",
    headers: {
      ...options.headers,
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...(guestToken ? { "X-Game-Token": guestToken } : {}),
    },
  });
  let response = await send();
  if (generation !== startedAt) throw new Error("Account changed while the request was running.");
  if (response.status === 401 && usedToken) {
    // If a concurrent call already refreshed, use that token. Otherwise every
    // pending call shares one refresh request, then retries at most once.
    const refreshed = accessToken !== usedToken || await restoreSession();
    if (generation !== startedAt) throw new Error("Account changed while the request was running.");
    if (refreshed) response = await send();
    if (response.status === 401) {
      clearSession();
      window.dispatchEvent(new Event(AUTH_EXPIRED));
    }
  }
  if (generation !== startedAt && response.status !== 401) {
    throw new Error("Account changed while the request was running.");
  }
  return response;
}
