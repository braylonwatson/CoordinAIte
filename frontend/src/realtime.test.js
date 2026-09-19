import { LivePredictionClient, LiveUnavailable } from "./realtime";

class Socket {
  static instances = [];
  constructor(url) { this.url = url; this.readyState = 0; this.sent = []; Socket.instances.push(this); }
  open() { this.readyState = 1; this.onopen(); }
  send(data) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; this.onclose?.(); }
  reply(message) { this.onmessage({ data: JSON.stringify(message) }); }
}

let client;
beforeEach(() => {
  Socket.instances = [];
  jest.useFakeTimers();
  client = new LivePredictionClient("wss://live.example/ws/predictions", Socket);
});
afterEach(() => { client.close(); jest.useRealTimers(); });

test("reuses one connection and correlates replies without credentials in the URL", async () => {
  const first = client.request({ type: "predict", access_token: "secret" });
  const socket = Socket.instances[0];
  socket.open();
  await Promise.resolve();
  expect(socket.url).not.toContain("secret");
  socket.reply({ id: socket.sent[0].id, status: 200, data: { prediction: "PASS" } });
  expect((await first).data.prediction).toBe("PASS");
  const second = client.request({ type: "predict" });
  await Promise.resolve();
  socket.reply({ id: "old-reply", status: 200 });
  expect(client.pending).not.toBeNull();
  socket.reply({ id: socket.sent[1].id, status: 200 });
  await second;
  expect(Socket.instances).toHaveLength(1);
});

test("only a connection failure before send is safe for REST fallback", async () => {
  const request = client.request({ type: "predict" });
  const failure = expect(request).rejects.toBeInstanceOf(LiveUnavailable);
  jest.advanceTimersByTime(1500);
  await failure;
  expect(Socket.instances[0].sent).toHaveLength(0);
});

test("lost reply after send is uncertain and must never be replayed", async () => {
  const request = client.request({ type: "predict" });
  const socket = Socket.instances[0];
  socket.open();
  await Promise.resolve();
  const failure = request.catch((error) => error);
  socket.close();
  expect(await failure).not.toBeInstanceOf(LiveUnavailable);
  expect(socket.sent).toHaveLength(1);
});

test("timeout clears pending without a retry", async () => {
  const request = client.request({ type: "predict" });
  Socket.instances[0].open();
  await Promise.resolve();
  const failure = expect(request).rejects.toThrow("timed out");
  jest.advanceTimersByTime(15000);
  await failure;
  expect(client.pending).toBeNull();
  expect(Socket.instances[0].sent).toHaveLength(1);
});

test("account change while connecting prevents sending", async () => {
  const request = client.request({ access_token: "old-account" }, () => false);
  Socket.instances[0].open();
  await expect(request).rejects.toThrow("changed");
  expect(Socket.instances[0].sent).toHaveLength(0);
});

test("backpressure rejects another prediction until the first completes", async () => {
  const first = client.request({ type: "predict" });
  const socket = Socket.instances[0];
  socket.open();
  await Promise.resolve();
  await expect(client.request({ type: "predict" })).rejects.toThrow("Wait");
  socket.reply({ id: socket.sent[0].id, status: 200 });
  await first;
  expect(socket.sent).toHaveLength(1);
});
