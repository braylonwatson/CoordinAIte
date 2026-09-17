import { apiFetch, authenticate, AUTH_EXPIRED, clearSession, restoreSession, setGuestGameToken, signOut } from "./api";

const result = (status, data = {}) => ({ status, ok: status >= 200 && status < 300, json: async () => data });
const login = { access_token: "access-one", user_id: 1, username: "Coach", email: "coach@example.com" };

beforeEach(() => {
  clearSession();
  setGuestGameToken(null);
  localStorage.clear();
  sessionStorage.clear();
  global.fetch = jest.fn();
});

test("sends login credentials and uses a bearer token without browser token storage", async () => {
  fetch.mockResolvedValueOnce(result(200, login)).mockResolvedValueOnce(result(200, []));
  await authenticate("login", { email: login.email, password: "strong-pass" });
  await apiFetch("/games");
  expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: "include", headers: { "X-CSRF-Protection": "1" } });
  expect(fetch.mock.calls[1][1]).toMatchObject({ credentials: "same-origin", headers: { Authorization: "Bearer access-one" } });
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
});

test("launches a dashboard behind a cookie-protected same-origin proxy", async () => {
  const previousApiUrl = process.env.REACT_APP_API_URL;
  process.env.REACT_APP_API_URL = "/api";
  let client;
  jest.isolateModules(() => { client = require("./api"); });
  const expired = jest.fn();
  window.addEventListener(AUTH_EXPIRED, expired);
  // Model the hosting layer independently of the application's bearer auth:
  // a valid access token cannot replace the deployment-access cookie.
  fetch.mockImplementation(async (url, options) => {
    const sameOrigin = new URL(url, window.location.origin).origin === window.location.origin;
    const sendsCookie = options.credentials === "include" ||
      (sameOrigin && options.credentials === "same-origin");
    if (!sendsCookie) return result(401, { protection: { vercel_auth_enabled: true } });
    if (url.endsWith("/login") || url.endsWith("/auth/refresh")) return result(200, login);
    if (options.headers.Authorization !== "Bearer access-one") return result(401);
    return result(200, { game_id: "account-game" });
  });
  try {
    await client.authenticate("login", { email: login.email, password: "strong-pass" });
    const response = await client.apiFetch("/set-teams", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ offense: "MIN", defense: "DEN" }),
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ game_id: "account-game" });
    expect(expired).not.toHaveBeenCalled();
    expect(fetch.mock.calls.filter(([url]) => url.endsWith("/auth/refresh"))).toHaveLength(0);
  } finally {
    window.removeEventListener(AUTH_EXPIRED, expired);
    if (previousApiUrl === undefined) delete process.env.REACT_APP_API_URL;
    else process.env.REACT_APP_API_URL = previousApiUrl;
  }
});

test("concurrent expired requests share one refresh and retry with the new token", async () => {
  fetch.mockImplementation(async (url, options) => {
    if (url.endsWith("/login")) return result(200, login);
    if (url.endsWith("/auth/refresh")) return result(200, { ...login, access_token: "access-two" });
    return options.headers.Authorization === "Bearer access-two" ? result(200, []) : result(401);
  });
  await authenticate("login", {});
  const responses = await Promise.all([apiFetch("/games"), apiFetch("/me/subscription")]);
  expect(responses.map((r) => r.status)).toEqual([200, 200]);
  expect(fetch.mock.calls.filter(([url]) => url.endsWith("/auth/refresh"))).toHaveLength(1);
});

test("refresh failure expires the UI session without replaying a mutation", async () => {
  const expired = jest.fn();
  window.addEventListener(AUTH_EXPIRED, expired);
  fetch.mockResolvedValueOnce(result(200, login)).mockResolvedValue(result(401));
  await authenticate("login", {});
  const response = await apiFetch("/log-play", { method: "POST", body: "{}" });
  expect(response.status).toBe(401);
  expect(expired).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls.filter(([url]) => url.endsWith("/log-play"))).toHaveLength(1);
  window.removeEventListener(AUTH_EXPIRED, expired);
});

test("guest access is private and cleared when starting an account-owned game", async () => {
  fetch.mockResolvedValue(result(200));
  setGuestGameToken("guest-secret");
  await apiFetch("/state?game_id=guest");
  expect(fetch.mock.calls[0][1].headers["X-Game-Token"]).toBe("guest-secret");
  setGuestGameToken(null);
  await apiFetch("/state?game_id=account");
  expect(fetch.mock.calls[1][1].headers["X-Game-Token"]).toBeUndefined();
});

test("does not replay a pending action as an account signed in from another tab", async () => {
  fetch.mockImplementation(async (url) => {
    if (url.endsWith("/login")) return result(200, login);
    if (url.endsWith("/auth/refresh")) return result(200, { ...login, user_id: 2, access_token: "another-account" });
    return result(401);
  });
  await authenticate("login", {});
  expect((await apiFetch("/games", { method: "POST", body: "{}" })).status).toBe(401);
  expect(fetch.mock.calls.filter(([url]) => url.endsWith("/games"))).toHaveLength(1);
});

test("a refresh finishing after logout cannot restore the discarded token", async () => {
  let finishRefresh;
  fetch.mockImplementation(async (url) => {
    if (url.endsWith("/login")) return result(200, login);
    if (url.endsWith("/auth/refresh")) return new Promise((resolve) => { finishRefresh = resolve; });
    if (url.endsWith("/auth/logout")) return result(204);
    return result(200);
  });
  await authenticate("login", {});
  const refresh = restoreSession();
  await signOut();
  finishRefresh(result(200, { ...login, access_token: "late-token" }));
  expect(await refresh).toBeNull();
  await apiFetch("/state");
  expect(fetch.mock.calls.at(-1)[1].headers.Authorization).toBeUndefined();
});
