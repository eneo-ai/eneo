"use client";

import {
  createContext,
  use,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
  type RefObject
} from "react";
import { returnTarget } from "@/components/ui/dialog-focus";
import { useFocusRescue } from "@/lib/focus-rescue";

/**
 * The dialogs of a resource's menu (move, publish, delete), kept above the
 * rows and cards of a `ResourceCollection`.
 *
 * A collection shows rows on a phone and cards from 768 px, and turning the
 * device swaps one for the other: every item in it is remounted. A dialog
 * that lived in an item's menu component went with it, with whatever was
 * chosen in it (a Move's destination) and the mutation it had started. Here
 * the menus only ask (`open("move", service)`), and the one scope above the
 * collection holds what is open, so a turn across 768 px changes the layout
 * behind an open dialog and nothing else.
 *
 * `createResourceActions<Resource, "move" | "delete">()` gives one scope and
 * one hook per kind of resource; the scope is given the component that draws
 * the dialog for a `{ kind, resource }`, and calls `onClose` when it is done.
 */
export function createResourceActions<Resource, Kind extends string>() {
  const OpenContext = createContext<((kind: Kind, resource: Resource) => void) | null>(null);

  function ResourceActionScope({
    Dialog,
    focusTarget,
    children
  }: {
    Dialog: ComponentType<{ kind: Kind; resource: Resource; onClose: () => void }>;
    /** Where focus goes when the control that opened a dialog is gone (the page's heading). */
    focusTarget: RefObject<HTMLElement | null>;
    children: ReactNode;
  }) {
    // `opener`: the control that opened the dialog, a menu's button and not its item.
    const [selection, setSelection] = useState<{
      kind: Kind;
      resource: Resource;
      opener: HTMLElement | null;
    } | null>(null);
    const latest = useRef(selection);
    const rescue = useFocusRescue();

    const open = (kind: Kind, resource: Resource) => {
      latest.current = { kind, resource, opener: returnTarget() };
      setSelection(latest.current);
    };
    const close = (closing: NonNullable<typeof selection>) => {
      // A request can outlive its dialog (a move cancelled while it runs) and finish
      // after another dialog was opened: it closes its own dialog, never that one.
      if (latest.current !== closing) return;
      latest.current = null;
      setSelection(null);
      // Asked when the rescue runs: publishing moves the item to another list, which
      // removes the opener after the dialog has closed.
      rescue(() => (closing.opener?.isConnected ? closing.opener : focusTarget.current));
    };

    return (
      <OpenContext value={open}>
        {children}
        {selection ? (
          <Dialog
            kind={selection.kind}
            resource={selection.resource}
            onClose={() => close(selection)}
          />
        ) : null}
      </OpenContext>
    );
  }

  function useOpenResourceAction() {
    const open = use(OpenContext);
    if (!open) throw new Error("A resource menu must be inside its ResourceActionScope.");
    return open;
  }

  return { ResourceActionScope, useOpenResourceAction };
}
