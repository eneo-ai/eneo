import { hasFlowRef, mergeFlowRefs, type FlowRef } from "./flow-tool-calls";

export type FlowPanelTab = "definition" | "runs" | "history";

const TABS: readonly FlowPanelTab[] = ["definition", "runs", "history"];

/** Whether a value (from a tab list or the address) names a panel tab. */
export function isFlowPanelTab(value: unknown): value is FlowPanelTab {
  return typeof value === "string" && (TABS as readonly string[]).includes(value);
}

/** The id the side panel knows the flow panel by (its `native` occupant). */
export const FLOW_PANEL_ID = "flow";

/** What the store knows about one flows tool call. */
type KnownCall = {
  ref: FlowRef;
  /** The stored result has been read (or is being read); it is read once. */
  settled: boolean;
  /** The flow was refetched when the call finished. */
  refreshed: boolean;
};

const EMPTY_CALL: KnownCall = {
  ref: { flowId: null, runId: null },
  settled: false,
  refreshed: false
};

/**
 * What the flow panel shows on a flow page: the flow the chat is bound to,
 * the run on show, the tab, and every flows tool call seen in the
 * conversation with the ids its arguments or result named.
 *
 * An external store (subscribe + version), like the side panel's: the chat
 * view, the panel and the lines under answers read one state, and the page
 * follows the bound flow id into the address bar. Effects only call methods
 * here; nothing sets React state from an effect.
 */
export class FlowPanelStore {
  #version = 0;
  #listeners = new Set<() => void>();
  #calls = new Map<string, KnownCall>();

  /** The flow the page is about, once known (the route's id, or the first call's). */
  flowId: string | null;
  /** The run on show in the runs tab. */
  runId: string | null;
  tab: FlowPanelTab;
  /**
   * Counts the times the panel asked to be shown: a flow bound, a run
   * started, a line under an answer pressed. The chat view opens the side
   * panel on each change.
   */
  openRequests = 0;

  constructor({
    flowId = null,
    runId = null,
    tab = null
  }: { flowId?: string | null; runId?: string | null; tab?: FlowPanelTab | null } = {}) {
    this.flowId = flowId;
    this.runId = runId;
    this.tab = tab ?? (runId ? "runs" : "definition");
    if (flowId) this.openRequests = 1;
  }

  subscribe = (listener: () => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  getVersion = () => this.#version;

  #emit() {
    this.#version++;
    for (const listener of this.#listeners) listener();
  }

  /** The reference a call is known by, or null for a call not seen yet. */
  refOf(callId: string): FlowRef | null {
    return this.#calls.get(callId)?.ref ?? null;
  }

  isSettled(callId: string): boolean {
    return this.#calls.get(callId)?.settled ?? false;
  }

  /** Marks the call's result as read; true the first time, so it is read once. */
  settle(callId: string): boolean {
    const known = this.#calls.get(callId) ?? EMPTY_CALL;
    if (known.settled) return false;
    this.#calls.set(callId, { ...known, settled: true });
    return true;
  }

  /** Marks the flow as refetched for this finished call; true the first time. */
  refresh(callId: string): boolean {
    const known = this.#calls.get(callId) ?? EMPTY_CALL;
    if (known.refreshed) return false;
    this.#calls.set(callId, { ...known, refreshed: true });
    return true;
  }

  /**
   * Records what a call named. A newly named flow binds the page (the first
   * flow seen is the page's flow); with `follow`, a newly named run opens the
   * runs tab on it (the latest answer's calls are followed, history is only
   * noted). Calls that name nothing new change nothing.
   */
  noteCall(callId: string, ref: FlowRef, { follow = true } = {}) {
    const known = this.#calls.get(callId) ?? EMPTY_CALL;
    const merged = mergeFlowRefs(known.ref, ref);
    const newFlow = merged.flowId !== null && known.ref.flowId === null;
    const newRun = merged.runId !== null && known.ref.runId === null;
    this.#calls.set(callId, { ...known, ref: merged });
    if (!newFlow && !newRun) return;
    if (newFlow && this.flowId === null) this.flowId = merged.flowId;
    if (!follow) return this.#emit();
    if (newRun && (merged.flowId === null || merged.flowId === this.flowId)) {
      this.runId = merged.runId;
      this.tab = "runs";
      this.openRequests++;
    } else if (newFlow && merged.flowId === this.flowId) {
      this.openRequests++;
    }
    this.#emit();
  }

  /** Shows the definition tab (and asks for the panel). */
  showDefinition() {
    this.tab = "definition";
    this.openRequests++;
    this.#emit();
  }

  /** Shows a run (null: the list) on the runs tab (and asks for the panel). */
  showRun(runId: string | null) {
    this.runId = runId;
    this.tab = "runs";
    this.openRequests++;
    this.#emit();
  }

  /** Shows what a call was about: its run, else the definition. */
  showCall(callId: string) {
    const ref = this.refOf(callId);
    if (ref?.runId && hasFlowRef(ref)) this.showRun(ref.runId);
    else this.showDefinition();
  }

  setTab(tab: FlowPanelTab) {
    if (this.tab === tab) return;
    this.tab = tab;
    this.#emit();
  }

  /** Back from a run to the list. */
  selectRun(runId: string | null) {
    if (this.runId === runId) return;
    this.runId = runId;
    this.#emit();
  }
}
