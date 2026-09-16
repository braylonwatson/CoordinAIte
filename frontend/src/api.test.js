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
  expect(fetch.mock.calls[1][1]).toMatchObject({ credentials: "omit", headers: { Authorization: "Bearer access-one" } });
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
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
