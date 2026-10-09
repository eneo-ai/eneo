import { getContext, setContext } from "svelte";
import { SvelteSet } from "svelte/reactivity";
import type { FilePreview, PreviewCover } from "$lib/features/file-preview/FilePreview.svelte";

/**
 * The MCP App view shown beside the conversation.
 *
 * A view starts inline under its answer and moves here when it asks for more
 * room. The panel holds one thing at a time and is shared with the file
 * preview: a view covers the previewed file, which is shown again when the
 * view goes back to its answer.
 */
export class McpAppPane {
  /** The tool call whose view is shown, by its id. */
  callId = $state<string | null>(null);
  /**
   * The user closed the panel during the answer being written. A view of
   * that answer may then not take the panel again by itself.
   */
  dismissedThisAnswer = $state(false);
  /** Geometry anchor; the original iframe is visually positioned over it. */
  target = $state.raw<HTMLElement | null>(null);
  /**
   * The calls whose view the reader can bring into the panel: it has loaded,
   * has something to show and can use the room.
   */
  readonly offered = new SvelteSet<string>();
  #preview: Pick<FilePreview, "cover">;
  #cover: PreviewCover = { leave: () => this.close() };

  constructor(preview: Pick<FilePreview, "cover">) {
    this.#preview = preview;
  }

  get shown() {
    return this.callId !== null;
  }

  open(callId: string) {
    this.callId = callId;
    this.#preview.cover = this.#cover;
  }

  /** Returning inline keeps the same app instance and its state. */
  close() {
    this.callId = null;
    if (this.#preview.cover === this.#cover) this.#preview.cover = null;
  }

  /** The user closes the panel. */
  dismiss() {
    this.dismissedThisAnswer = true;
    this.close();
  }

  beginAnswer() {
    this.dismissedThisAnswer = false;
  }
}

const contextKey = Symbol("MCP App pane");

export function initMcpAppPane(preview: Pick<FilePreview, "cover">) {
  return setContext(contextKey, new McpAppPane(preview));
}

/** Undefined where a conversation is shown without a side panel; views then stay inline. */
export function getMcpAppPane(): McpAppPane | undefined {
  return getContext<McpAppPane | undefined>(contextKey);
}
