// @vitest-environment jsdom
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import {
  Dialog as AstryxDialog,
  DialogHeader as AstryxDialogHeader
} from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "./alert-dialog";
import { Button } from "./button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "./dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "./dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./select";
import { Toaster } from "./sonner";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function RenameBody() {
  return (
    <>
      <DialogHeader>
        <DialogTitle>Byt namn på samlingen</DialogTitle>
        <DialogDescription>Namnet syns för alla medlemmar.</DialogDescription>
      </DialogHeader>
      <label className="flex flex-col gap-1">
        Namn
        <input defaultValue="Avtal" />
      </label>
      <DialogFooter>
        <DialogClose asChild>
          <Button variant="outline">Avbryt</Button>
        </DialogClose>
      </DialogFooter>
    </>
  );
}

function TriggeredDialog() {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button>Byt namn</Button>
      </DialogTrigger>
      <DialogContent>
        <RenameBody />
      </DialogContent>
    </Dialog>
  );
}

/** A dialog opened from a plain button, the way most call sites open theirs. */
function ControlledDialog() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Redigera
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <RenameBody />
        </DialogContent>
      </Dialog>
    </>
  );
}

async function openTriggered() {
  renderInApp(<TriggeredDialog />);
  const trigger = screen.getByRole("button", { name: "Byt namn" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = await screen.findByRole("dialog", { name: "Byt namn på samlingen" });
  return { trigger, dialog };
}

describe("Dialog", () => {
  it("is a native modal, named by its title and described, that focuses the title", async () => {
    const showModal = vi.spyOn(HTMLDialogElement.prototype, "showModal");
    const { trigger, dialog } = await openTriggered();

    // showModal(): the browser puts it in the top layer and makes the rest of
    // the page inert (jsdom only records the call).
    expect(showModal).toHaveBeenCalledTimes(1);
    expect(dialog.tagName).toBe("DIALOG");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.getElementById(dialog.getAttribute("aria-describedby")!)?.textContent).toBe(
      "Namnet syns för alla medlemmar."
    );
    expect(trigger.getAttribute("aria-haspopup")).toBe("dialog");
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(trigger.getAttribute("aria-controls")).toBe(dialog.id);
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(dialog).getByRole("heading", { name: "Byt namn på samlingen" })
      )
    );
    await expectNoAxeViolations(document.body);
  });

  it("keeps the page's Astryx buttons named while it is open", async () => {
    // Radix's hideOthers() left buttons with a live region (every Astryx
    // Button) exposed but hid their labels, so they were announced nameless.
    renderInApp(
      <>
        <AstryxButton label="Spara sidan" />
        <Dialog open onOpenChange={() => {}}>
          <DialogContent>
            <RenameBody />
          </DialogContent>
        </Dialog>
      </>
    );
    await screen.findByRole("dialog", { name: "Byt namn på samlingen" });
    expect(screen.getByRole("button", { name: "Spara sidan" })).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });

  it("closes with Escape and returns focus to its trigger", async () => {
    const { trigger, dialog } = await openTriggered();

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(dialog.hasAttribute("open")).toBe(false);
    // The content is gone with the dialog, as with Radix.
    expect(screen.queryByLabelText("Namn")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes from its ✕ button (Stäng) and from DialogClose", async () => {
    const { trigger, dialog } = await openTriggered();
    fireEvent.click(within(dialog).getByRole("button", { name: "Stäng" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(trigger);
    const reopened = await screen.findByRole("dialog", { name: "Byt namn på samlingen" });
    fireEvent.click(within(reopened).getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("asks its owner before closing, and never closes from a click on itself", async () => {
    const onOpenChange = vi.fn();
    renderInApp(
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent showCloseButton={false}>
          <RenameBody />
        </DialogContent>
      </Dialog>
    );
    const dialog = await screen.findByRole("dialog", { name: "Byt namn på samlingen" });
    expect(within(dialog).queryByRole("button", { name: "Stäng" })).toBeNull();

    fireEvent.keyDown(dialog, { key: "Escape" });
    // A click on the <dialog> itself is a backdrop click in a browser.
    fireEvent.click(dialog);

    expect(onOpenChange).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
    // The owner said no (a save is running): it stays open.
    expect(screen.getByRole("dialog", { name: "Byt namn på samlingen" })).toBeTruthy();
  });

  it("returns focus to the button that opened a controlled dialog", async () => {
    renderInApp(<ControlledDialog />);
    const opener = screen.getByRole("button", { name: "Redigera" });
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Byt namn på samlingen" });

    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(opener);
  });

  it("returns focus to the menu button when a menu item opened it", async () => {
    function MenuDialog() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button>Åtgärder</Button>
            </DropdownMenuTrigger>
            {/* Radix refocuses its trigger after the dialog opened; a browser
                refuses (the page behind a modal is inert), jsdom does not.
                Switched off so the test sees what the browser does. */}
            <DropdownMenuContent onCloseAutoFocus={(event) => event.preventDefault()}>
              <DropdownMenuItem onSelect={() => setOpen(true)}>Byt namn</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent>
              <RenameBody />
            </DialogContent>
          </Dialog>
        </>
      );
    }
    renderInApp(<MenuDialog />);
    const menuButton = screen.getByRole("button", { name: "Åtgärder" });
    menuButton.focus();
    fireEvent.keyDown(menuButton, { key: "Enter" });
    const item = await screen.findByRole("menuitem", { name: "Byt namn" });
    item.focus();
    fireEvent.click(item);
    const dialog = await screen.findByRole("dialog", { name: "Byt namn på samlingen" });

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(menuButton));
  });

  it("returns focus to the opener when the dialog unmounts while open", async () => {
    function Conditional() {
      const [shown, setShown] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setShown(true)}>
            Visa
          </button>
          {shown ? (
            <Dialog open onOpenChange={(open) => !open && setShown(false)}>
              <DialogContent>
                <RenameBody />
              </DialogContent>
            </Dialog>
          ) : null}
        </>
      );
    }
    renderInApp(<Conditional />);
    const opener = screen.getByRole("button", { name: "Visa" });
    opener.focus();
    fireEvent.click(opener);
    const dialog = await screen.findByRole("dialog", { name: "Byt namn på samlingen" });

    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(opener);
  });

  it("opens a Select inside the dialog, in the dialog's layer", async () => {
    renderInApp(
      <Dialog open onOpenChange={() => {}}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Välj modell</DialogTitle>
          </DialogHeader>
          <Select defaultValue="a">
            <SelectTrigger aria-label="Modell">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="a">Modell A</SelectItem>
              <SelectItem value="b">Modell B</SelectItem>
            </SelectContent>
          </Select>
        </DialogContent>
      </Dialog>
    );
    const dialog = await screen.findByRole("dialog", { name: "Välj modell" });
    const trigger = within(dialog).getByRole("combobox", { name: "Modell" });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "Enter" });

    // Portalled into the <dialog>, not <body>: outside it would be inert and
    // behind the dialog.
    const listbox = await screen.findByRole("listbox");
    expect(dialog.contains(listbox)).toBe(true);

    // One Escape closes one layer: the listbox, not the dialog.
    fireEvent.keyDown(listbox, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    expect(screen.getByRole("dialog", { name: "Välj modell" })).toBeTruthy();
  });

  it("shows toasts inside the open dialog, where they are seen and announced", async () => {
    renderInApp(
      <>
        <Toaster />
        <ControlledDialog />
      </>
    );
    fireEvent.click(screen.getByRole("button", { name: "Redigera" }));
    const dialog = await screen.findByRole("dialog", { name: "Byt namn på samlingen" });
    await waitFor(() =>
      expect(within(dialog).getByRole("region", { name: /Aviseringar/ })).toBeTruthy()
    );

    toast.error("Namnet kunde inte sparas");

    expect(await within(dialog).findByText("Namnet kunde inte sparas")).toBeTruthy();
    toast.dismiss();
  });

  it("returns focus to a button the browser never focused on press (Safari, iOS)", async () => {
    renderInApp(<ControlledDialog />);
    const opener = screen.getByRole("button", { name: "Redigera" });
    // Safari fires the pointer events and the click but leaves focus on <body>.
    fireEvent.pointerDown(opener);
    fireEvent.click(opener);
    expect(document.activeElement).not.toBe(opener);
    const dialog = await screen.findByRole("dialog", { name: "Byt namn på samlingen" });

    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(opener);
  });

  it("closes the dialog opened last with Escape, also when it was opened before", async () => {
    // Astryx orders its Escape stack by first registration: a dialog kept
    // mounted from an earlier opening would sit below one opened since.
    function Siblings() {
      const [first, setFirst] = useState(false);
      const [second, setSecond] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setFirst(true)}>
            Öppna första
          </button>
          <button type="button" onClick={() => setSecond(true)}>
            Öppna andra
          </button>
          <Dialog open={first} onOpenChange={setFirst}>
            <DialogContent>
              <DialogTitle>Första</DialogTitle>
            </DialogContent>
          </Dialog>
          <Dialog open={second} onOpenChange={setSecond}>
            <DialogContent>
              <DialogTitle>Andra</DialogTitle>
              <button type="button" onClick={() => setFirst(true)}>
                Öppna första härifrån
              </button>
            </DialogContent>
          </Dialog>
        </>
      );
    }
    renderInApp(<Siblings />);
    fireEvent.click(screen.getByRole("button", { name: "Öppna första" }));
    const first = await screen.findByRole("dialog", { name: "Första" });
    fireEvent.keyDown(first, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Första" })).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Öppna andra" }));
    const second = await screen.findByRole("dialog", { name: "Andra" });
    fireEvent.click(within(second).getByRole("button", { name: "Öppna första härifrån" }));
    const reopened = await screen.findByRole("dialog", { name: "Första" });

    fireEvent.keyDown(reopened, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Första" })).toBeNull());
    expect(screen.getByRole("dialog", { name: "Andra" })).toBeTruthy();
  });

  it("stacks the footer in DOM order, so focus order follows what is seen", () => {
    renderInApp(
      <Dialog open onOpenChange={() => {}}>
        <DialogContent>
          <RenameBody />
        </DialogContent>
      </Dialog>
    );
    const footer = document.querySelector('[data-slot="dialog-footer"]')!;
    expect(footer.className).not.toMatch(/reverse/);
  });

  it("never submits a form from its trigger or close button", async () => {
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    renderInApp(
      <form onSubmit={onSubmit}>
        <Dialog>
          <DialogTrigger asChild>
            <Button>Byt namn</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogTitle>Byt namn på samlingen</DialogTitle>
            <form onSubmit={onSubmit}>
              <DialogFooter>
                <DialogClose asChild>
                  <Button variant="outline">Avbryt</Button>
                </DialogClose>
                <Button type="submit">Spara</Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </form>
    );
    fireEvent.click(screen.getByRole("button", { name: "Byt namn" }));
    const dialog = await screen.findByRole("dialog", { name: "Byt namn på samlingen" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("moves toasts to the dialog opened last and back to the page when all close", async () => {
    function Stacked() {
      const [second, setSecond] = useState(false);
      return (
        <>
          <ControlledDialog />
          <Dialog open={second} onOpenChange={setSecond}>
            <DialogContent>
              <DialogTitle>Andra</DialogTitle>
            </DialogContent>
          </Dialog>
          <button type="button" onClick={() => setSecond(true)}>
            Öppna andra
          </button>
        </>
      );
    }
    renderInApp(
      <>
        <Toaster />
        <Stacked />
      </>
    );
    const toasterIn = (element: HTMLElement) =>
      within(element).queryByRole("region", { name: /Aviseringar/ });

    fireEvent.click(screen.getByRole("button", { name: "Redigera" }));
    const first = await screen.findByRole("dialog", { name: "Byt namn på samlingen" });
    await waitFor(() => expect(toasterIn(first)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Öppna andra" }));
    const second = await screen.findByRole("dialog", { name: "Andra" });
    await waitFor(() => expect(toasterIn(second)).toBeTruthy());
    expect(toasterIn(first)).toBeNull();

    fireEvent.keyDown(second, { key: "Escape" });
    await waitFor(() => expect(toasterIn(first)).toBeTruthy());
    fireEvent.keyDown(first, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getAllByRole("region", { name: /Aviseringar/ })).toHaveLength(1);
  });

  it("keeps Astryx announcements audible while it is open (the page behind is inert)", async () => {
    function Announcer() {
      const announce = useAnnounce();
      return (
        <button type="button" onClick={() => announce("Kopierat")}>
          Kopiera
        </button>
      );
    }
    function WithAnnouncer() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Öppna
          </button>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent>
              <DialogTitle>Nyckel</DialogTitle>
              <Announcer />
            </DialogContent>
          </Dialog>
        </>
      );
    }
    renderInApp(
      <>
        <Toaster />
        <WithAnnouncer />
      </>
    );
    fireEvent.click(screen.getByRole("button", { name: "Öppna" }));
    const dialog = await screen.findByRole("dialog", { name: "Nyckel" });

    fireEvent.click(within(dialog).getByRole("button", { name: "Kopiera" }));

    await waitFor(() =>
      expect(dialog.querySelector('[data-astryx-live-region="polite"]')?.textContent).toBe(
        "Kopierat"
      )
    );
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() =>
      expect(document.querySelector('[data-astryx-live-region="polite"]')?.parentElement).toBe(
        document.body
      )
    );
  });

  it("also shows toasts in a modal opened outside these wrappers (Astryx Dialog)", async () => {
    renderInApp(
      <>
        <Toaster />
        <AstryxDialog isOpen onOpenChange={() => {}}>
          <AstryxDialogHeader title="Ny yta" />
        </AstryxDialog>
      </>
    );
    const dialog = await screen.findByRole("dialog", { name: "Ny yta" });
    await waitFor(() =>
      expect(within(dialog).getByRole("region", { name: /Aviseringar/ })).toBeTruthy()
    );
  });
});

describe("AlertDialog", () => {
  it("never submits a form from Cancel or the action", async () => {
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    const onAction = vi.fn();
    renderInApp(
      <AlertDialog open onOpenChange={() => {}}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Ta bort samlingen?</AlertDialogTitle>
          </AlertDialogHeader>
          <form onSubmit={onSubmit}>
            <AlertDialogFooter>
              <AlertDialogCancel>Avbryt</AlertDialogCancel>
              <AlertDialogAction onClick={onAction}>Ta bort</AlertDialogAction>
            </AlertDialogFooter>
          </form>
        </AlertDialogContent>
      </AlertDialog>
    );
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort samlingen?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));

    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
