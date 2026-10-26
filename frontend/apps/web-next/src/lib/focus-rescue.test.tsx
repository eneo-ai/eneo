// @vitest-environment jsdom
import { act, fireEvent, renderHook, screen, waitFor } from "@testing-library/react";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { RemovalFocusScope, useRemovalMutation } from "@/features/spaces/removal";
import { renderInApp } from "@/test/render";
import { isFocusLost, notifyFocusLost, useFocusRescue } from "./focus-rescue";

let panel: HTMLDivElement;

/** A focused control that the action then takes out of the page. */
function focusedRow(): HTMLButtonElement {
  const row = document.createElement("button");
  document.body.append(row);
  row.focus();
  return row;
}

/** The DOM reports a change to MutationObservers in a microtask. */
const observed = () => act(() => Promise.resolve());

describe("useFocusRescue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    panel = document.createElement("div");
    panel.tabIndex = -1;
    document.body.append(panel);
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  function rescuer() {
    const { result, unmount } = renderHook(() => useFocusRescue());
    return { rescue: result.current, unmount };
  }

  it("moves focus to the target when the focused row was removed", () => {
    focusedRow().remove();
    expect(document.activeElement).toBe(document.body);

    rescuer().rescue(panel);
    vi.advanceTimersToNextFrame();

    expect(document.activeElement).toBe(panel);
  });

  it("leaves focus alone when it is still on something", async () => {
    const other = focusedRow();

    rescuer().rescue(panel);
    vi.advanceTimersToNextFrame();
    expect(document.activeElement).toBe(other);
    // Nor when the page changes around it.
    document.body.append(document.createElement("p"));
    await observed();

    expect(document.activeElement).toBe(other);
  });

  it("does not restore focus after the target has been unmounted", async () => {
    const focus = vi.spyOn(panel, "focus");
    rescuer().rescue(panel);
    panel.remove();

    vi.advanceTimersToNextFrame();
    await observed();
    notifyFocusLost();

    expect(focus).not.toHaveBeenCalled();
  });

  it("leaves focus in a menu the user opened in the meantime", () => {
    focusedRow().remove();

    rescuer().rescue(panel);
    // Before the check the user opens a row's menu.
    document.body.insertAdjacentHTML(
      "beforeend",
      '<div role="menu" data-state="open"><div id="item" role="menuitem" tabindex="-1">Byt namn</div></div>'
    );
    document.getElementById("item")!.focus();
    vi.advanceTimersToNextFrame();

    expect(document.activeElement?.id).toBe("item");
  });

  it("asks a target given as a function at the check, for one the re-render brings", () => {
    focusedRow().remove();

    let later: HTMLElement | null = null;
    rescuer().rescue(() => later);
    later = panel;
    vi.advanceTimersToNextFrame();

    expect(document.activeElement).toBe(panel);
  });

  it("moves focus when the row leaves the page after the first check", async () => {
    const row = focusedRow();
    rescuer().rescue(panel);
    vi.advanceTimersToNextFrame();
    expect(document.activeElement).toBe(row);

    row.remove();
    await observed();

    expect(document.activeElement).toBe(panel);
  });

  it("moves focus when the focused button is disabled and the browser drops focus", () => {
    const button = focusedRow();
    rescuer().rescue(panel);
    vi.advanceTimersToNextFrame();

    button.disabled = true;
    // Chromium drops focus to <body> when the focused button becomes disabled;
    // jsdom leaves it there, so do what the browser does.
    document.body.tabIndex = -1;
    document.body.focus();
    document.body.removeAttribute("tabindex");
    vi.advanceTimersToNextFrame();

    expect(document.activeElement).toBe(panel);
  });

  it("moves focus at once when a dialog reports that its focus return failed", () => {
    document.body.insertAdjacentHTML(
      "beforeend",
      '<dialog open><button id="confirm">Ta bort</button></dialog>'
    );
    const confirm = document.getElementById("confirm")!;
    confirm.focus();
    rescuer().rescue(panel);
    vi.advanceTimersToNextFrame();
    expect(document.activeElement).toBe(confirm);

    // The dialog closed and the row that opened it is gone: nowhere to return to.
    confirm.closest("dialog")!.removeAttribute("open");
    notifyFocusLost();

    expect(document.activeElement).toBe(panel);
  });

  it.each([
    ["a key", () => fireEvent.keyDown(document.activeElement!, { key: "Tab" })],
    ["a pointer", () => fireEvent.pointerDown(document.body)]
  ])("ends once the user acts with %s: what goes next is the next action's", async (_, act) => {
    const row = focusedRow();
    rescuer().rescue(panel);
    vi.advanceTimersToNextFrame();

    act();
    row.remove();
    vi.advanceTimersToNextFrame();
    await observed();
    notifyFocusLost();

    expect(document.activeElement).toBe(document.body);
  });

  it("lets the rescue for the latest action go first", () => {
    focusedRow().remove();
    const older = document.createElement("div");
    older.tabIndex = -1;
    document.body.append(older);

    rescuer().rescue(older);
    rescuer().rescue(panel);
    vi.advanceTimersToNextFrame();

    expect(document.activeElement).toBe(panel);
  });

  it("keeps only the latest rescue the component asked for", () => {
    focusedRow().remove();
    const first = document.createElement("div");
    first.tabIndex = -1;
    document.body.append(first);

    const { rescue } = rescuer();
    rescue(first);
    rescue(panel);
    vi.advanceTimersToNextFrame();

    expect(document.activeElement).toBe(panel);
  });

  it("does not rescue after the owning component unmounted, whatever arrives later", async () => {
    const row = focusedRow();
    const { rescue, unmount } = rescuer();
    rescue(panel);
    unmount();

    row.remove();
    vi.advanceTimersToNextFrame();
    await observed();
    notifyFocusLost();

    expect(document.activeElement).toBe(document.body);
  });

  it("does nothing when asked after the component unmounted", () => {
    const frame = vi.spyOn(window, "requestAnimationFrame");
    const { rescue, unmount } = rescuer();
    unmount();
    focusedRow().remove();

    rescue(panel);
    vi.advanceTimersToNextFrame();

    expect(frame).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(document.body);
  });
});

describe("isFocusLost", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("is lost on the body and in a closed dialog, not on a button or an open menu", () => {
    document.body.innerHTML = `
      <button id="page">Sida</button>
      <dialog id="dialog"><button id="inside">Stäng</button></dialog>
      <div role="menu"><div id="item" role="menuitem" tabindex="-1">Byt namn</div></div>
    `;
    expect(isFocusLost()).toBe(true);
    document.getElementById("inside")!.focus();
    expect(isFocusLost()).toBe(true);
    document.getElementById("item")!.focus();
    expect(isFocusLost()).toBe(false);
    document.getElementById("page")!.focus();
    expect(isFocusLost()).toBe(false);
  });

  it("is lost on an item of a menu that is closing or hidden", () => {
    document.body.innerHTML = `
      <div role="menu" data-state="closed"><div id="radix" role="menuitem" tabindex="-1">A</div></div>
      <div hidden><div role="menu"><div id="hidden" role="menuitem" tabindex="-1">B</div></div></div>
    `;
    for (const id of ["radix", "hidden"]) {
      document.getElementById(id)!.focus();
      expect(isFocusLost()).toBe(true);
    }
  });

  it("reads an Astryx menu's popover state where the Popover API exists", () => {
    // jsdom has no Popover API: pretend it has, with an open or a hidden popover.
    Object.defineProperty(HTMLElement.prototype, "showPopover", {
      configurable: true,
      value: () => {}
    });
    const matches = Element.prototype.matches;
    let popoverOpen = false;
    const spy = vi.spyOn(Element.prototype, "matches").mockImplementation(function (
      this: Element,
      selector: string
    ) {
      return selector === ":popover-open" ? popoverOpen : matches.call(this, selector);
    });
    try {
      document.body.innerHTML = `
        <div popover="auto"><div role="menu"><div id="item" role="menuitem" tabindex="-1">A</div></div></div>
      `;
      document.getElementById("item")!.focus();
      expect(isFocusLost()).toBe(true);
      popoverOpen = true;
      expect(isFocusLost()).toBe(false);
    } finally {
      spy.mockRestore();
      delete (HTMLElement.prototype as Partial<HTMLElement>).showPopover;
    }
  });
});

/**
 * A list whose rows are deleted through one confirm dialog, as the prompt
 * library, skills and spaces pages do: the row that opened the dialog is gone
 * by the time the dialog closes, so the dialog has nowhere to return focus
 * and the list's scope rescues it to the heading.
 */
function DeletableList({ remove }: { remove: (id: string) => Promise<void> }) {
  const [rows, setRows] = useState(["Anna", "Per"]);
  const [deleting, setDeleting] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  return (
    <RemovalFocusScope target={headingRef}>
      <h2 ref={headingRef} tabIndex={-1}>
        Användare
      </h2>
      <ul>
        {rows.map((row) => (
          <li key={row}>
            <span>{row}</span>
            <button type="button" onClick={() => setDeleting(row)}>
              Ta bort {row}
            </button>
          </li>
        ))}
      </ul>
      <DeleteRowDialog
        row={deleting}
        remove={async (id) => {
          await remove(id);
          setRows((current) => current.filter((row) => row !== id));
        }}
        onClose={() => setDeleting(null)}
      />
    </RemovalFocusScope>
  );
}

function DeleteRowDialog({
  row,
  remove,
  onClose
}: {
  row: string | null;
  remove: (id: string) => Promise<void>;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const removal = useRemovalMutation({
    mutationFn: remove,
    refresh: () => queryClient.invalidateQueries({ queryKey: ["rows"] }),
    onRemoved: onClose
  });
  return (
    <ConfirmDialogControlled
      open={row !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Radera användare"
      description={`Vill du verkligen radera ${row}?`}
      confirmLabel="Ta bort"
      pending={removal.isPending}
      onConfirm={() => {
        if (row) removal.mutate(row);
      }}
    />
  );
}

describe("a row deleted through a dialog", () => {
  it("leaves focus on the list heading once the dialog has closed with its opener gone", async () => {
    let finish!: () => void;
    const remove = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)));
    renderInApp(<DeletableList remove={remove} />);

    const opener = screen.getByRole("button", { name: "Ta bort Per" });
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("alertdialog", { name: "Radera användare" });
    const confirm = screen.getByRole("button", { name: "Ta bort" });
    confirm.focus();
    fireEvent.click(confirm);

    await waitFor(() => expect(remove).toHaveBeenCalledWith("Per"));
    expect(document.activeElement).toBe(confirm);
    finish();

    await waitFor(() => expect(screen.queryByText("Per")).toBeNull());
    await waitFor(() => expect(dialog.hasAttribute("open")).toBe(false));
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Användare" }))
    );
  });
});
