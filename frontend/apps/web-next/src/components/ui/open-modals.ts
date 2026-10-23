"use client";

import { useEffect, useSyncExternalStore } from "react";

/*
 * The modal <dialog>s that are open, in the order they opened. A modal makes
 * the rest of the page inert and covers it, so the toaster (sonner.tsx) shows
 * its toasts inside the top-most one, where they are seen and announced.
 *
 * The app's dialog wrappers (DialogSurface in dialog.tsx, behind Dialog and
 * AlertDialog) report their <dialog> while it is open. Modals opened outside
 * them (Astryx Dialog, BottomSheet or MobileNav used directly) join when focus
 * moves into them, which the browser does on showModal(), and leave on their
 * `close` event. Two document listeners instead of watching every DOM
 * mutation, which ran on each streamed chat token.
 */

const openModals: HTMLDialogElement[] = [];
const listeners = new Set<() => void>();
let topModal: HTMLDialogElement | null = null;

function isOpenModal(dialog: HTMLDialogElement): boolean {
  // aria-modal: Astryx marks its modal dialogs, and jsdom never matches :modal.
  return (
    dialog.isConnected &&
    dialog.open &&
    (dialog.matches(":modal") || dialog.getAttribute("aria-modal") === "true")
  );
}

/** Drops dialogs that closed or left the page, and tells subscribers about a new top. */
function update() {
  for (let index = openModals.length - 1; index >= 0; index -= 1) {
    if (!isOpenModal(openModals[index]!)) openModals.splice(index, 1);
  }
  const top = openModals.at(-1) ?? null;
  if (top === topModal) return;
  topModal = top;
  for (const listener of listeners) listener();
}

function join(dialog: HTMLDialogElement) {
  if (!openModals.includes(dialog)) openModals.push(dialog);
  update();
}

/**
 * Reports an open modal <dialog> until the returned function is called (the
 * dialog closed or unmounted). Call it once the dialog is open.
 */
export function reportOpenModal(dialog: HTMLDialogElement): () => void {
  join(dialog);
  return () => {
    const index = openModals.indexOf(dialog);
    if (index !== -1) openModals.splice(index, 1);
    update();
  };
}

function onFocusIn(event: FocusEvent) {
  const dialog = event.target instanceof Element ? event.target.closest("dialog") : null;
  if (!dialog || openModals.includes(dialog)) return;
  // Read the state once showModal() has finished (jsdom focuses before it
  // sets `open`).
  queueMicrotask(() => {
    if (!openModals.includes(dialog) && isOpenModal(dialog)) join(dialog);
  });
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) {
    document.addEventListener("focusin", onFocusIn, true);
    // `close` does not bubble; the capture phase still passes the document.
    document.addEventListener("close", update, true);
    // A modal that opened before anyone listened (on page load).
    for (const dialog of document.querySelectorAll("dialog")) {
      if (!openModals.includes(dialog) && isOpenModal(dialog)) openModals.push(dialog);
    }
    update();
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      document.removeEventListener("focusin", onFocusIn, true);
      document.removeEventListener("close", update, true);
    }
  };
}

/** The modal <dialog> opened last, while one is open. */
export function useTopModalDialog(): HTMLDialogElement | null {
  return useSyncExternalStore(
    subscribe,
    () => topModal,
    () => null
  );
}

/** Astryx's live regions (useAnnounce, useClipboard's `announce`), in <body>. */
const LIVE_REGIONS = "[data-astryx-live-region]";

/**
 * Keeps Astryx's announcement live regions in the top-most open modal. Astryx
 * appends them to <body>, and behind a modal <body>'s content is inert and
 * hidden from screen readers, so an announcement made while a dialog is open
 * (a copy, a page change in a Pagination) would never be heard. Back in
 * <body> once the modals close. The regions are created on the first
 * announcement, so while a modal is open new children of <body> are adopted
 * too (its direct children only: cheap).
 */
export function useLiveRegionsIn(modal: HTMLDialogElement | null) {
  useEffect(() => {
    const host: HTMLElement = modal ?? document.body;
    const adopt = () => {
      for (const region of document.querySelectorAll(LIVE_REGIONS)) {
        if (region.parentElement !== host) host.append(region);
      }
    };
    adopt();
    if (!modal) return;
    const observer = new MutationObserver(adopt);
    observer.observe(document.body, { childList: true });
    return () => observer.disconnect();
  }, [modal]);
}
