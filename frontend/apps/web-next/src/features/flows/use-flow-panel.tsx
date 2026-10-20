"use client";

import { createContext, use, useState, useSyncExternalStore, type ReactNode } from "react";
import { FlowPanelStore, type FlowPanelTab } from "./flow-panel-store";

const FlowPanelContext = createContext<FlowPanelStore | null>(null);

/**
 * One flow panel store for a flow page. The chat view, the panel and the
 * lines under answers share it; outside a flow page there is none, and
 * `useFlowPanel` returns null.
 */
export function FlowPanelProvider({
  flowId,
  runId = null,
  tab = null,
  children
}: {
  /** The route's flow id, or null for a flow that is not created yet. */
  flowId: string | null;
  /** A run deep-linked in the address (`?run=`). */
  runId?: string | null;
  /** The tab the address asks for (`?tab=runs`). */
  tab?: FlowPanelTab | null;
  children: ReactNode;
}) {
  const [store] = useState(() => new FlowPanelStore({ flowId, runId, tab }));
  return <FlowPanelContext value={store}>{children}</FlowPanelContext>;
}

const noSubscription = () => () => {};
const zero = () => 0;

/** The flow page's panel store, re-rendering the caller on every change; null elsewhere. */
export function useFlowPanel(): FlowPanelStore | null {
  const store = use(FlowPanelContext);
  useSyncExternalStore(
    store?.subscribe ?? noSubscription,
    store?.getVersion ?? zero,
    store?.getVersion ?? zero
  );
  return store;
}
