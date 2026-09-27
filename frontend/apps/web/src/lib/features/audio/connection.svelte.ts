// Whether the browser has a network connection, as its online and offline
// events say, and a callback for the moment it comes back.

export class ConnectionState {
  online = $state(typeof navigator === "undefined" ? true : navigator.onLine);
  #dispose: () => void;

  constructor(onBackOnline: () => void, target: EventTarget | undefined = globalThis.window) {
    const wentOnline = () => {
      this.online = true;
      onBackOnline();
    };
    const wentOffline = () => {
      this.online = false;
    };
    target?.addEventListener("online", wentOnline);
    target?.addEventListener("offline", wentOffline);
    this.#dispose = () => {
      target?.removeEventListener("online", wentOnline);
      target?.removeEventListener("offline", wentOffline);
    };
  }

  dispose(): void {
    this.#dispose();
  }
}
