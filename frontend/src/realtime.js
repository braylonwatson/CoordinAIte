export class LiveUnavailable extends Error {}

// One in-flight prediction per client, no queued mutations and no silent replay
// after a send. A lost reply can mean the server already committed the result.
export class LivePredictionClient {
  constructor(url, Socket = window.WebSocket) {
    this.url = url;
    this.Socket = Socket;
    this.socket = null;
    this.connecting = null;
    this.cancelConnect = null;
    this.pending = null;
    this.sequence = 0;
    this.retryAt = 0;
  }

  connect() {
    if (!this.url || !this.Socket || Date.now() < this.retryAt) {
      return Promise.reject(new LiveUnavailable("Live connection unavailable."));
    }
    if (this.socket?.readyState === 1) return Promise.resolve(this.socket);
    if (this.connecting) return this.connecting;
    const connection = new Promise((resolve, reject) => {
      let socket;
      try {
        const target = new URL(this.url);
        if (!["wss:", "ws:"].includes(target.protocol) ||
            (target.protocol === "ws:" && !["localhost", "127.0.0.1"].includes(target.hostname))) {
          throw new Error("Invalid live endpoint");
        }
        socket = new this.Socket(this.url);
      } catch {
        reject(new LiveUnavailable("Live connection unavailable."));
        return;
      }
      this.socket = socket;
      let opened = false;
      const fail = () => {
        clearTimeout(timer);
        if (this.socket === socket) this.socket = null;
        this.retryAt = Date.now() + 30000;
        if (!opened) reject(new LiveUnavailable("Live connection unavailable."));
        if (this.pending?.socket === socket) {
          this.pending.reject(new Error("Connection lost. Check the pending play before predicting again."));
        }
        socket.close();
      };
      const timer = setTimeout(fail, 1500);
      this.cancelConnect = fail;
      socket.onopen = () => {
        clearTimeout(timer);
        if (this.socket !== socket) return socket.close();
        opened = true;
        this.cancelConnect = null;
        resolve(socket);
      };
      socket.onerror = fail;
      socket.onclose = () => {
        clearTimeout(timer);
        if (this.socket === socket) this.socket = null;
        if (!opened) reject(new LiveUnavailable("Live connection unavailable."));
        if (this.pending?.socket === socket) {
          this.pending.reject(new Error("Connection lost. Check the pending play before predicting again."));
        }
      };
      socket.onmessage = (event) => {
        let message;
        try { message = JSON.parse(event.data); } catch { fail(); return; }
        if (this.pending?.socket === socket && message.id === this.pending.id) {
          this.pending.resolve(message);
        }
      };
    });
    this.connecting = connection;
    const clear = () => {
      if (this.connecting === connection) this.connecting = null;
    };
    connection.then(clear, clear);
    return connection;
  }

  async request(command, isCurrent = () => true) {
    const socket = await this.connect();
    if (!isCurrent()) throw new Error("Account or game changed while connecting.");
    if (this.pending) throw new Error("Wait for the current prediction to finish.");
    if (socket.readyState !== 1) throw new LiveUnavailable("Live connection unavailable.");
    const id = String(++this.sequence);
    return new Promise((resolve, reject) => {
      const finish = (callback, value) => {
        clearTimeout(timer);
        this.pending = null;
        callback(value);
      };
      const timer = setTimeout(() => {
        finish(reject, new Error("Prediction timed out. Check the pending play before predicting again."));
        this.close();
      }, 15000);
      this.pending = {
        id, socket,
        resolve: (value) => finish(resolve, value),
        reject: (error) => finish(reject, error),
      };
      // Even send() failures are treated as uncertain; never replay over REST.
      try { socket.send(JSON.stringify({ ...command, id })); }
      catch { this.pending.reject(new Error("Could not send prediction. Check the pending play before retrying.")); }
    });
  }

  close() {
    this.cancelConnect?.();
    this.cancelConnect = null;
    this.connecting = null;
    this.pending?.reject(new Error("Live prediction connection closed."));
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }
}
