import { CONNECTED_EVENT, EVENT_PREFIX, EneoWidgetElement, type WidgetEventName } from "./element";
import type { PageContext } from "./protocol";

/**
 * `window.Eneo`: the command queue hosts can call before the script has
 * loaded (`Eneo('open')`), replayed once the loader and an element exist.
 *
 *   window.Eneo = window.Eneo || function () {
 *     (window.Eneo.q = window.Eneo.q || []).push(arguments);
 *   };
 */

type Listener = (detail?: unknown) => void;

type Command = "open" | "close" | "toggle" | "on" | "off" | "setContext";

export interface EneoApi {
  (command: Command, ...args: unknown[]): void;
  q?: ArrayLike<unknown>[];
  loaded?: boolean;
  version?: string;
  open(): void;
  close(): void;
  toggle(): void;
  on(event: WidgetEventName, listener: Listener): () => void;
  off(event: WidgetEventName, listener: Listener): void;
  setContext(context: PageContext): void;
}

const EVENTS: WidgetEventName[] = ["ready", "open", "close", "conversation_started", "unread"];

export function installApi(win: Window & { Eneo?: EneoApi }, version: string): EneoApi {
  if (win.Eneo?.loaded) return win.Eneo;

  const queued: ArrayLike<unknown>[] = Array.isArray(win.Eneo?.q) ? win.Eneo!.q! : [];
  const pending: Array<() => void> = [];
  const wrapped = new WeakMap<Listener, EventListener>();

  const element = (): EneoWidgetElement | null =>
    document.querySelector("eneo-widget") as EneoWidgetElement | null;

  // Commands that need an element wait for one; listeners attach immediately
  // because the element's events bubble to the document.
  function withElement(action: (el: EneoWidgetElement) => void): void {
    const el = element();
    if (el) action(el);
    else pending.push(() => action(element()!));
  }

  document.addEventListener(CONNECTED_EVENT, () => {
    const actions = pending.splice(0);
    for (const action of actions) action();
  });

  const api = function (command: Command, ...args: unknown[]): void {
    switch (command) {
      case "open":
        withElement((el) => el.openPanel());
        break;
      case "close":
        withElement((el) => el.closePanel());
        break;
      case "toggle":
        withElement((el) => el.toggle());
        break;
      case "setContext":
        withElement((el) => el.setContext((args[0] ?? {}) as PageContext));
        break;
      case "on":
        api.on(args[0] as WidgetEventName, args[1] as Listener);
        break;
      case "off":
        api.off(args[0] as WidgetEventName, args[1] as Listener);
        break;
    }
  } as EneoApi;

  api.open = () => api("open");
  api.close = () => api("close");
  api.toggle = () => api("toggle");
  api.setContext = (context) => api("setContext", context);
  api.on = (event, listener) => {
    if (EVENTS.indexOf(event) === -1 || typeof listener !== "function") return () => {};
    const handler: EventListener = (domEvent) => listener((domEvent as CustomEvent).detail);
    wrapped.set(listener, handler);
    document.addEventListener(EVENT_PREFIX + event, handler);
    return () => api.off(event, listener);
  };
  api.off = (event, listener) => {
    const handler = wrapped.get(listener);
    if (handler) document.removeEventListener(EVENT_PREFIX + event, handler);
  };
  api.loaded = true;
  api.version = version;
  win.Eneo = api;

  for (const call of queued) {
    const [command, ...args] = Array.prototype.slice.call(call) as [Command, ...unknown[]];
    api(command, ...args);
  }
  return api;
}
