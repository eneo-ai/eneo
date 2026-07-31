/**
 * Manages the async lifecycle of loading an assistant for a flow step.
 *
 * Handles request-token–based cancellation so that stale loads from a
 * previous step never overwrite the current state.
 */

export interface AssistantLoaderCallbacks<T> {
  /** Actually loads the assistant by id. */
  loadAssistant: (id: string) => Promise<T>;
  /** Called when the loaded assistant is ready. */
  onLoaded: (assistant: T) => void;
  /** Called when loading fails. */
  onError: (error: unknown) => void;
  /** Called when loading starts. */
  onLoadingChange: (isLoading: boolean) => void;
  /** Returns the current step's assistant_id — used to guard against stale loads. */
  getCurrentAssistantId: () => string | null;
}

export interface AssistantLoader {
  /**
   * Start loading an assistant by id.
   * If a previous load is in flight, it will be cancelled (its callbacks won't fire).
   */
  load(assistantId: string): Promise<void>;
  /** Cancel any in-flight load. */
  cancel(): void;
}

export function createAssistantLoader<T>(callbacks: AssistantLoaderCallbacks<T>): AssistantLoader {
  let requestToken = 0;

  async function load(assistantId: string): Promise<void> {
    if (!assistantId) return;
    const token = ++requestToken;
    callbacks.onLoadingChange(true);
    try {
      const result = await callbacks.loadAssistant(assistantId);
      // Guard: if user switched steps during the load, discard.
      if (token !== requestToken) return;
      if (callbacks.getCurrentAssistantId() !== assistantId) return;
      callbacks.onLoaded(result);
    } catch (error) {
      if (token !== requestToken) return;
      console.error("Failed to load assistant for flow step:", error);
      callbacks.onError(error);
    } finally {
      if (token === requestToken) {
        callbacks.onLoadingChange(false);
      }
    }
  }

  function cancel(): void {
    ++requestToken;
  }

  return { load, cancel };
}
