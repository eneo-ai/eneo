// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from "./alert-dialog";
import { Button } from "./button";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function DeleteDialog({
  onDelete = () => {},
  onOpenChange
}: {
  onDelete?: (event: React.MouseEvent<HTMLButtonElement>) => void;
  onOpenChange?: (open: boolean) => void;
}) {
  return (
    <AlertDialog onOpenChange={onOpenChange}>
      <AlertDialogTrigger asChild>
        <Button variant="destructive">Radera</Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Radera samlingen?</AlertDialogTitle>
          <AlertDialogDescription>Filerna i samlingen raderas också.</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Avbryt</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={onDelete}>
            Radera samlingen
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

async function open(props: Parameters<typeof DeleteDialog>[0] = {}) {
  renderInApp(<DeleteDialog {...props} />);
  const trigger = screen.getByRole("button", { name: "Radera" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = await screen.findByRole("alertdialog", { name: "Radera samlingen?" });
  return { trigger, dialog };
}

describe("AlertDialog", () => {
  it("is a modal alert dialog that focuses Cancel and has no close button", async () => {
    const showModal = vi.spyOn(HTMLDialogElement.prototype, "showModal");
    const { dialog } = await open();

    expect(showModal).toHaveBeenCalledTimes(1);
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.getElementById(dialog.getAttribute("aria-describedby")!)?.textContent).toBe(
      "Filerna i samlingen raderas också."
    );
    expect(within(dialog).queryByRole("button", { name: "Stäng" })).toBeNull();
    await waitFor(() =>
      expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Avbryt" }))
    );
    await expectNoAxeViolations(document.body);
  });

  it("cancels with Escape and with Cancel, returning focus to the trigger", async () => {
    const onOpenChange = vi.fn();
    const { trigger, dialog } = await open({ onOpenChange });

    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    const reopened = await screen.findByRole("alertdialog", { name: "Radera samlingen?" });
    fireEvent.click(within(reopened).getByRole("button", { name: "Avbryt" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("closes after the action unless the action prevents it", async () => {
    const onDelete = vi.fn();
    const { dialog } = await open({ onDelete });
    fireEvent.click(within(dialog).getByRole("button", { name: "Radera samlingen" }));
    expect(onDelete).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());

    cleanup();
    const { dialog: kept } = await open({ onDelete: (event) => event.preventDefault() });
    fireEvent.click(within(kept).getByRole("button", { name: "Radera samlingen" }));
    expect(screen.getByRole("alertdialog", { name: "Radera samlingen?" })).toBeTruthy();
  });

  it("does not close from a click on the dialog box itself", async () => {
    const { dialog } = await open();
    fireEvent.click(dialog);
    expect(screen.getByRole("alertdialog", { name: "Radera samlingen?" })).toBeTruthy();
  });
});
