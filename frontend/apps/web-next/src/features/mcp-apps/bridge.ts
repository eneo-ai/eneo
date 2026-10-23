import {
  AppBridge,
  PostMessageTransport,
  type McpUiHostContext,
  type McpUiResourcePermissions,
  type McpUiToolResultNotification
} from "@modelcontextprotocol/ext-apps/app-bridge";
import type { McpAppDisplayMode } from "./mcp-apps";

const MAX_INLINE_HEIGHT = 2000;
const MAX_MESSAGE_LENGTH = 4000;

/** What a tool call brought back, as the host hands it to its view. */
export type ToolCallOutcome = {
  result: string | null;
  structuredContent?: Record<string, unknown> | null;
  isError?: boolean;
};

export type McpAppToolState = {
  partialInput?: Record<string, unknown>;
  input?: Record<string, unknown>;
  resultReady: boolean;
};
export type McpAppToolResult = McpUiToolResultNotification["params"];
export type McpAppBridgeOptions = {
  iframe: HTMLIFrameElement;
  html: string;
  permissions?: McpUiResourcePermissions;
  getToolResult: () => Promise<ToolCallOutcome | null>;
  onSizeChanged?: (height: number) => void;
  /** The view has started; `displayModes` are the ones it says it supports. */
  onInitialized?: (displayModes: string[]) => void;
  displayMode: McpAppDisplayMode;
  onRequestDisplayMode?: (mode: McpAppDisplayMode) => McpAppDisplayMode;
  onCallTool?: (name: string, args: Record<string, unknown>) => Promise<McpAppToolResult>;
  onOpenLink?: (url: string) => Promise<boolean>;
  onMessage?: (text: string) => boolean;
  /**
   * What the view says is in front of the reader, to go with the next
   * question. Each update replaces the view's last one; no text withdraws it.
   */
  onModelContext?: (text: string) => boolean;
  hostContext?: () => McpUiHostContext;
};

/**
 * Eneo's lifecycle and policy adapter around the official SDK, which owns the
 * RPC and the negotiation. The SDK talks only to Eneo's trusted sandbox proxy
 * on the separate content origin; the server's HTML lives in the proxy's
 * opaque child, under the proxy's HTTP CSP.
 */
export class McpAppBridge {
  #options: McpAppBridgeOptions;
  #sdk: AppBridge;
  #resizes: ResizeObserver;
  #destroyed = false;
  #initialized = false;
  #tool: McpAppToolState = { resultReady: false };
  #partialQueued = false;
  #inputSent = false;
  #resultSent = false;
  #dimensionsReported = "";

  constructor(options: McpAppBridgeOptions) {
    this.#options = options;
    this.#sdk = new AppBridge(
      null,
      { name: "eneo", version: "1" },
      {
        ...(options.onCallTool ? { serverTools: {} } : {}),
        ...(options.onOpenLink ? { openLinks: {} } : {}),
        ...(options.onMessage ? { message: { text: {} } } : {}),
        ...(options.onModelContext ? { updateModelContext: { text: {} } } : {})
      },
      { hostContext: this.#context() }
    );
    this.#sdk.addEventListener("sandboxready", () => {
      if (this.#destroyed) return;
      void this.#sdk.sendSandboxResourceReady({
        html: options.html,
        sandbox: "allow-scripts",
        permissions: options.permissions
      });
    });
    this.#sdk.addEventListener("initialized", () => {
      if (this.#destroyed) return;
      this.#initialized = true;
      options.onInitialized?.(this.#sdk.getAppCapabilities()?.availableDisplayModes ?? []);
      this.#advance();
    });
    this.#sdk.addEventListener("sizechange", ({ height }) => {
      if (typeof height === "number" && Number.isFinite(height) && height >= 0) {
        options.onSizeChanged?.(Math.min(height, MAX_INLINE_HEIGHT));
      }
    });
    this.#sdk.onrequestdisplaymode = async ({ mode }) => ({
      mode:
        this.#initialized &&
        !this.#destroyed &&
        (mode === "inline" || mode === "fullscreen") &&
        options.onRequestDisplayMode
          ? options.onRequestDisplayMode(mode)
          : this.#options.displayMode
    });
    if (options.onCallTool)
      this.#sdk.oncalltool = async ({ name, arguments: args }) => {
        if (!this.#initialized || this.#destroyed) throw new Error("The view is not ready");
        return options.onCallTool!(name, args ?? {});
      };
    if (options.onOpenLink)
      this.#sdk.onopenlink = async ({ url }) => {
        let parsed: URL;
        try {
          parsed = new URL(url);
        } catch {
          return { isError: true };
        }
        if (!this.#initialized || !["https:", "http:"].includes(parsed.protocol)) {
          return { isError: true };
        }
        return (await options.onOpenLink!(parsed.href)) ? {} : { isError: true };
      };
    if (options.onMessage)
      this.#sdk.onmessage = async ({ role, content }) => {
        const text = content
          .map((block) => (block.type === "text" ? block.text : ""))
          .join("\n")
          .trim();
        return role === "user" &&
          this.#initialized &&
          text.length > 0 &&
          text.length <= MAX_MESSAGE_LENGTH &&
          options.onMessage!(text)
          ? {}
          : { isError: true };
      };
    if (options.onModelContext)
      this.#sdk.onupdatemodelcontext = async ({ content }) => {
        // Text is all that is taken; anything else in the update is left out.
        const text = (content ?? [])
          .map((block) => (block.type === "text" ? block.text : ""))
          .join("\n")
          .trim();
        if (!this.#initialized || !options.onModelContext!(text)) {
          throw new Error("The context was not taken");
        }
        return {};
      };
    this.#resizes = new ResizeObserver(() => {
      const next = JSON.stringify(this.#dimensions());
      if (next !== this.#dimensionsReported) {
        this.#dimensionsReported = next;
        this.contextChanged();
      }
    });
    this.#resizes.observe(options.iframe);
    void this.#sdk.connect(
      new PostMessageTransport(options.iframe.contentWindow!, options.iframe.contentWindow!)
    );
  }

  destroy() {
    if (this.#destroyed) return;
    // Notify before the component removes the frame. Never keep a transport
    // indefinitely when the app can no longer answer its teardown request.
    void this.teardown().finally(() => this.#sdk.close());
    this.#destroyed = true;
    this.#initialized = false;
    this.#resizes.disconnect();
  }

  async teardown(): Promise<void> {
    if (!this.#initialized || this.#destroyed) return;
    try {
      await this.#sdk.teardownResource({}, { timeout: 2000 });
    } catch {
      /* bounded teardown */
    }
  }

  setDisplayMode(mode: McpAppDisplayMode) {
    if (this.#options.displayMode === mode) return;
    this.#options.displayMode = mode;
    this.contextChanged();
  }

  #dimensions() {
    const { clientWidth: width, clientHeight: height } = this.#options.iframe;
    return this.#options.displayMode === "inline"
      ? { width, maxHeight: MAX_INLINE_HEIGHT }
      : { width, height };
  }

  #context(): McpUiHostContext {
    return {
      ...this.#options.hostContext?.(),
      displayMode: this.#options.displayMode,
      availableDisplayModes: this.#options.onRequestDisplayMode
        ? ["inline", "fullscreen"]
        : ["inline"],
      containerDimensions: this.#dimensions()
    };
  }

  contextChanged() {
    if (!this.#destroyed) this.#sdk.setHostContext(this.#context());
  }

  update(tool: McpAppToolState) {
    this.#tool = tool;
    this.#advance();
  }

  #advance() {
    if (!this.#initialized || this.#destroyed) return;
    if (!this.#inputSent) {
      const input =
        this.#tool.input ?? (this.#tool.resultReady ? (this.#tool.partialInput ?? {}) : undefined);
      if (input === undefined) {
        if (this.#partialQueued || this.#tool.partialInput === undefined) return;
        this.#partialQueued = true;
        requestAnimationFrame(() => {
          this.#partialQueued = false;
          if (!this.#destroyed && !this.#inputSent && this.#tool.partialInput) {
            void this.#sdk.sendToolInputPartial({ arguments: plain(this.#tool.partialInput) });
          }
        });
        return;
      }
      this.#inputSent = true;
      void this.#sdk.sendToolInput({ arguments: plain(input) });
    }
    if (this.#tool.resultReady && !this.#resultSent) {
      this.#resultSent = true;
      void this.#deliverResult();
    }
  }

  async #deliverResult() {
    try {
      const outcome = await this.#options.getToolResult();
      if (this.#destroyed) return;
      await this.#sdk.sendToolResult({
        content: outcome?.result == null ? [] : [{ type: "text", text: outcome.result }],
        ...(outcome?.structuredContent
          ? { structuredContent: plain(outcome.structuredContent) }
          : {}),
        ...(outcome?.isError ? { isError: true } : {})
      });
    } catch {
      this.#resultSent = false;
    }
  }
}

// Only JSON crosses postMessage's structured-clone boundary: no functions, no
// undefined values, nothing the SDK's partial parser may have left behind.
function plain<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}
