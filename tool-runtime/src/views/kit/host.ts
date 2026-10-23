/// <reference lib="dom" />
import { createContext, use, useEffect, useRef, useState } from "react";
import { App, type McpUiHostContext } from "@modelcontextprotocol/ext-apps";

/** What a tool call brought back, as the host hands it to the view. */
export type ToolResult = {
  content?: { type: string; text?: string }[];
  structuredContent?: unknown;
  isError?: boolean;
};

export type Host = { app: App; context: McpUiHostContext; connected: boolean };

type Handlers = {
  onInput?: (input: Record<string, unknown>) => void;
  onResult: (result: ToolResult) => void;
};

/**
 * The view's side of the MCP Apps conversation: one connection for the life of the page, the
 * host's context as it changes, and the tool's input and result as they arrive. The page runs
 * in the host's sandboxed frame with no network and no storage, and talks by postMessage only.
 */
export function useHost(name: string, handlers: Handlers): Host {
  // Every view drawn in the kit's frame can also be shown in the larger view, so the host may
  // offer that itself instead of waiting for the frame's own button.
  const [app] = useState(
    () =>
      new App(
        { name, version: "1" },
        { availableDisplayModes: ["inline", "fullscreen"] },
        { autoResize: false },
      ),
  );
  const [context, setContext] = useState<McpUiHostContext>({});
  const [connected, setConnected] = useState(false);
  const latest = useRef(handlers);
  useEffect(() => {
    latest.current = handlers;
  });
  useEffect(() => {
    // Handlers are in place before the connection opens, so nothing the host sends is missed.
    app.ontoolinput = ({ arguments: input }) => latest.current.onInput?.(input ?? {});
    app.ontoolresult = (result) => latest.current.onResult(result as ToolResult);
    app.onhostcontextchanged = (next) => setContext((current) => ({ ...current, ...next }));
    app.onteardown = async () => ({});
    void app.connect().then(() => {
      setContext(app.getHostContext() ?? {});
      setConnected(true);
    });
  }, [app]);
  return { app, context, connected };
}

export const HostContext = createContext<Host | null>(null);

/** The host of the view a component is drawn in. */
export function useViewHost(): Host {
  const host = use(HostContext);
  if (!host) throw new Error("No view frame above this component");
  return host;
}

/** The reader's language: Swedish unless the host says otherwise. */
export function pick<T>(context: McpUiHostContext, texts: { sv: T; en: T }): T {
  return (context.locale ?? "sv").toLowerCase().startsWith("sv") ? texts.sv : texts.en;
}
