import { useEffect, useState } from "react";

/*
 * When an action removes the focused element (a row that left the list after
 * a delete or deactivate, a button that went once its work was done),
 * keyboard users must not be left on <body> (ACCESSIBILITY.md rule 2). Astryx
 * has no hook for this: useFocusTrap only restores focus when a trap it owns
 * ends, and useListFocus moves focus between items that exist. Dialogs return
 * focus themselves (src/components/ui/dialog-focus.ts, which shares
 * isFocusLost and reports here when that failed); this is for the page behind
 * them.
 *
 * A rescue is owned by the component that asked for it (`useFocusRescue`) and
 * is event-driven: no timer guesses when the list will have re-rendered or
 * the dialog will have closed. The element leaves the page at a moment only
 * the DOM knows, so while any rescue is pending the document's own signals
 * are watched (a MutationObserver and a capturing focusout listener),
 * together with the dialog's report. Browsers fire no focus event when the
 * focused element is removed or disabled (Chromium does, Firefox and Safari
 * do not), so a focus listener alone could not be the signal; the mutation
 * is. A pending rescue ends when the user acts (a key or pointer press): from
 * then on focus is theirs, and whatever the next action removes is that
 * action's to rescue.
 */

/**
 * A menu that is still in the page but not shown: a closed Astryx menu (a
 * hidden popover) or a Radix menu playing its close animation. Focus left on
 * one of its items is on nothing the user can see.
 */
function isHiddenMenu(menu: Element): boolean {
  if (menu.closest('[hidden], [data-state="closed"]')) return true;
  const popover = menu.closest("[popover]");
  // Without the Popover API (jsdom) a popover's state cannot be read.
  if (!popover || typeof HTMLElement.prototype.showPopover !== "function") return false;
  return !popover.matches(":popover-open");
}

/**
 * Focus is on nothing, inside a dialog that has closed, or on an item of a
 * menu that is no longer shown. An open menu (one the user just opened) is
 * not lost focus.
 */
export function isFocusLost(): boolean {
  const active = document.activeElement;
  if (!active || active === document.body) return true;
  if (active.closest("dialog:not([open])")) return true;
  const menu = active.closest('[role="menu"]');
  return menu !== null && isHiddenMenu(menu);
}

/** An element, or a function asked for one at each check (one the re-render brings). */
export type FocusRescueTarget = HTMLElement | null | (() => HTMLElement | null);

type Rescuer = {
  /** Moves focus to the target when focus is lost; the rescue then ends. */
  check(): void;
  /** Ends the rescue without moving focus. */
  settle(): void;
};

/** Pending rescues, oldest first. The newest is the one for the latest action, so it checks first. */
const pending: Rescuer[] = [];

function runChecks() {
  for (const rescuer of [...pending].reverse()) rescuer.check();
}

function settleAll() {
  for (const rescuer of [...pending]) rescuer.settle();
}

/**
 * Reports that focus is lost right now, after the caller (a closing dialog)
 * tried to place it and could not. Every pending rescue checks at once.
 */
export function notifyFocusLost(): void {
  runChecks();
}

/**
 * Attributes whose change can take focus away without removing the element:
 * a disabled button drops focus to <body> in Chromium.
 */
const FOCUS_ATTRIBUTES = ["disabled", "hidden", "inert", "open"];

let observer: MutationObserver | null = null;
let frame = 0;

function onFocusOut() {
  // The old element loses focus before the next one gains it: check after that.
  checkNextFrame();
}

function checkNextFrame() {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(runChecks);
}

/** One watcher for the document, kept only while a rescue is pending. */
function watch() {
  if (observer) return;
  observer = new MutationObserver(runChecks);
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: FOCUS_ATTRIBUTES
  });
  document.addEventListener("focusout", onFocusOut, true);
  document.addEventListener("keydown", settleAll, true);
  document.addEventListener("pointerdown", settleAll, true);
}

function unwatch() {
  if (!observer || pending.length > 0) return;
  observer.disconnect();
  observer = null;
  document.removeEventListener("focusout", onFocusOut, true);
  document.removeEventListener("keydown", settleAll, true);
  document.removeEventListener("pointerdown", settleAll, true);
  cancelAnimationFrame(frame);
}

/** One component's rescuer: at most one pending rescue, the latest asked for. */
function createRescuer() {
  let mounted = true;
  let target: FocusRescueTarget = null;

  const rescuer: Rescuer = {
    check() {
      if (!pending.includes(rescuer) || !isFocusLost()) return;
      const element = typeof target === "function" ? target() : target;
      // Navigation or unmount may remove the target before focus is lost.
      if (!element?.isConnected) return;
      rescuer.settle();
      element.focus();
    },
    settle() {
      const index = pending.indexOf(rescuer);
      if (index < 0) return;
      pending.splice(index, 1);
      target = null;
      unwatch();
    }
  };

  return {
    rescue(next: FocusRescueTarget) {
      if (!mounted) return;
      const index = pending.indexOf(rescuer);
      if (index >= 0) pending.splice(index, 1);
      target = next;
      pending.push(rescuer);
      watch();
      checkNextFrame();
    },
    mount() {
      mounted = true;
    },
    unmount() {
      mounted = false;
      rescuer.settle();
    }
  };
}

/**
 * Rescues focus for the calling component: `rescue(target)` moves focus to
 * `target` (a list heading or panel with tabIndex -1) when focus is lost by
 * what the component did, now or once the DOM has caught up with it. The
 * rescue checks on the next frame, on every DOM change and focus move while
 * it is pending, and when a dialog reports that its focus return failed
 * (`notifyFocusLost`). It ends once it moved focus, when the user acts, or
 * when the component unmounts; `rescue` does nothing after that, so a
 * mutation callback that outlives its component never touches the document.
 * The component must outlive the change it rescues from: a list or page,
 * not the row that goes.
 */
export function useFocusRescue(): (target: FocusRescueTarget) => void {
  const [rescuer] = useState(createRescuer);
  useEffect(() => {
    rescuer.mount();
    return rescuer.unmount;
  }, [rescuer]);
  return rescuer.rescue;
}
