const reply = (status, data = {}) => ({ status, ok: status < 300, json: async () => data });
const login = { access_token: "first-token", user_id: 1, username: "Coach" };
const originalSocket = window.WebSocket;
const originalUrl = process.env.REACT_APP_WS_URL;
let api;
let sockets;
let behavior;

beforeEach(() => {
  sockets = [];
  behavior = () => ({ status: 200, data: { prediction: "PASS" } });
  process.env.REACT_APP_WS_URL = "wss://live.example/ws/predictions";
  window.WebSocket = class {
    constructor() {
      this.readyState = 0;
      this.sent = [];
      sockets.push(this);
      setTimeout(() => { this.readyState = 1; this.onopen?.(); }, 0);
    }
    send(raw) {
      const command = JSON.parse(raw);
      this.sent.push(command);
      const response = behavior(command);
      if (response) this.onmessage({ data: JSON.stringify({ id: command.id, ...response }) });
      else this.close();
    }
    close() { this.readyState = 3; this.onclose?.(); }
  };
  jest.isolateModules(() => { api = require("./api"); });
  global.fetch = jest.fn().mockResolvedValue(reply(200, login));
});

afterEach(() => {
  api.clearSession();
  window.WebSocket = originalSocket;
  if (originalUrl === undefined) delete process.env.REACT_APP_WS_URL;
  else process.env.REACT_APP_WS_URL = originalUrl;
});

const predict = () => api.apiFetch("/predict", { method: "POST", body: "{}", livePrediction: true });

test("uses the live connection without an HTTP prediction", async () => {
  await api.authenticate("login", {});
  expect((await predict()).status).toBe(200);
  expect(sockets[0].sent[0].access_token).toBe("first-token");
  expect(fetch.mock.calls.filter(([url]) => url.endsWith("/predict"))).toHaveLength(0);
});

test("refreshes expired socket credentials only after an explicit 401 rejection", async () => {
  await api.authenticate("login", {});
  fetch.mockResolvedValue(reply(200, { ...login, access_token: "refreshed-token" }));
  behavior = (command) => command.access_token === "first-token"
    ? { status: 401, detail: "Expired" } : { status: 200, data: { prediction: "PASS" } };
  expect((await predict()).status).toBe(200);
  expect(sockets[0].sent.map((command) => command.access_token)).toEqual(["first-token", "refreshed-token"]);
  expect(fetch.mock.calls.filter(([url]) => url.endsWith("/auth/refresh"))).toHaveLength(1);
});

test("does not fall back to REST when the reply is lost after sending", async () => {
  await api.authenticate("login", {});
  behavior = () => null;
  await expect(predict()).rejects.toThrow("Connection lost");
  expect(fetch.mock.calls.filter(([url]) => url.endsWith("/predict"))).toHaveLength(0);
});

test("falls back to REST when the websocket constructor fails", async () => {
  window.WebSocket = class { constructor() { throw new Error("Network unavailable"); } };
  jest.isolateModules(() => { api = require("./api"); });
  await api.authenticate("login", {});
  expect((await predict()).status).toBe(200);
  const calls = fetch.mock.calls.filter(([url]) => url.endsWith("/predict"));
  expect(calls).toHaveLength(1);
  expect(calls[0][1]).not.toHaveProperty("livePrediction");
});
