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
    const [selection, setSelection] = useState<{ kind: Kind; resource: Resource } | null>(null);
    // The control that opened the dialog: a menu's button, not its item.
    const opener = useRef<HTMLElement | null>(null);
    const rescue = useFocusRescue();

    const open = (kind: Kind, resource: Resource) => {
      opener.current = returnTarget();
      setSelection({ kind, resource });
    };
    const close = () => {
      setSelection(null);
      rescue(opener.current?.isConnected ? opener.current : focusTarget.current);
      opener.current = null;
    };

    return (
      <OpenContext value={open}>
        {children}
        {selection ? <Dialog {...selection} onClose={close} /> : null}
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
