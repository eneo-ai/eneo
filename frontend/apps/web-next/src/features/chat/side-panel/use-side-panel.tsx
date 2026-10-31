"use client";

import { createContext, use, useState, useSyncExternalStore, type ReactNode } from "react";
import { signedOriginalUrl } from "@/features/files/signed-original-url";
import { browserApi } from "@/lib/api/browser";
import { SidePanelStore } from "./side-panel-store";

const SidePanelContext = createContext<SidePanelStore | null>(null);

/**
 * One side-panel store for a conversation. Everything under it (the message
 * list, the composer, the panel itself) reads and changes the same state.
 */
export function SidePanelProvider({ children }: { children: ReactNode }) {
  const [store] = useState(
    () => new SidePanelStore((file) => signedOriginalUrl(browserApi, file.id))
  );
  return <SidePanelContext value={store}>{children}</SidePanelContext>;
}

/**
 * The side panel of the surrounding conversation, re-rendering the caller on
 * every change, or null where messages render without one (a transcript);
 * file chips then keep to downloading.
 */
export function useSidePanel(): SidePanelStore | null {
  const store = use(SidePanelContext);
  useSyncExternalStore(store?.subscribe ?? noSubscription, store?.getVersion ?? zero);
  return store;
}

/** The side panel without re-rendering on its changes: for callers that use it only in event handlers. */
export function useSidePanelStore(): SidePanelStore | null {
  return use(SidePanelContext);
}

const noSubscription = () => () => {};
const zero = () => 0;
