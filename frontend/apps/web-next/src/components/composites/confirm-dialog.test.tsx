// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Button } from "@/components/ui/button";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ConfirmDialog, ConfirmDialogControlled } from "./confirm-dialog";

afterEach(cleanup);

function renderDeleteSpace(onConfirm: () => Promise<void>, pending = false) {
  return renderInApp(
    <ConfirmDialog
      trigger={<Button variant="destructive">Ta bort ytan</Button>}
      title="Ta bort yta"
      description="Det här går inte att ångra."
      confirmLabel="Ta bort"
      confirmValue="Avtal"
      confirmValueLabel="Skriv ytans namn"
      pending={pending}
      onConfirm={onConfirm}
    />
  );
}

async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Ta bort ytan" }));
  return screen.findByRole("alertdialog", { name: "Ta bort yta" });
}

describe("ConfirmDialog", () => {
  it("asks for the name in a labelled field with an id of its own", async () => {
    const onConfirm = vi.fn();
    renderInApp(
      <>
        <ConfirmDialog
          trigger={<Button>Första</Button>}
          title="Första"
          description="…"
          confirmLabel="Ta bort"
          confirmValue="a"
          confirmValueLabel="Skriv a"
          onConfirm={onConfirm}
        />
        <ConfirmDialog
          trigger={<Button>Andra</Button>}
          title="Andra"
          description="…"
          confirmLabel="Ta bort"
          confirmValue="b"
          confirmValueLabel="Skriv b"
          onConfirm={() => {}}
        />
      </>
    );
    fireEvent.click(screen.getByRole("button", { name: "Första" }));
    const first = await screen.findByRole("alertdialog", { name: "Första" });
    const field = within(first).getByRole("textbox", { name: "Skriv a" });
    expect(field.id).not.toBe("confirm-value");
    const remove = within(first).getByRole("button", { name: "Ta bort" });
    // Never disabled: confirming without the name says so at the field.
    expect(remove).toHaveProperty("disabled", false);
    fireEvent.click(remove);
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(field.getAttribute("aria-describedby")!)?.textContent).toBe(
      "Det stämmer inte. Skriv a exakt som det står."
    );
    expect(document.activeElement).toBe(field);
    expect(onConfirm).not.toHaveBeenCalled();
    await expectNoAxeViolations(document.body);

    fireEvent.change(field, { target: { value: "a" } });
    fireEvent.click(remove);
    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
  });

  it("stays open with what was typed when the action fails", async () => {
    const onConfirm = vi.fn(() => Promise.reject(new Error("409")));
    renderDeleteSpace(onConfirm);
    const dialog = await open();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Skriv ytans namn" }), {
      target: { value: "Avtal" }
    });

    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));

    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Ta bort" }).getAttribute("aria-busy")
      ).toBeNull()
    );
    expect(screen.getByRole("alertdialog", { name: "Ta bort yta" })).toBeTruthy();
    expect(within(dialog).getByRole("textbox", { name: "Skriv ytans namn" })).toHaveProperty(
      "value",
      "Avtal"
    );
  });

  it("closes after the action succeeds", async () => {
    renderDeleteSpace(() => Promise.resolve());
    const dialog = await open();
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Avtal" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });

  it("cannot be closed with Escape while the action runs", async () => {
    let finish = () => {};
    renderDeleteSpace(() => new Promise<void>((resolve) => (finish = resolve)));
    const dialog = await open();
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Avtal" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Avbryt" })).toHaveProperty(
        "disabled",
        true
      )
    );

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("alertdialog", { name: "Ta bort yta" })).toBeTruthy();

    finish();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });
});

describe("ConfirmDialogControlled", () => {
  it("keeps focus on the busy confirm button and ignores a press", async () => {
    const onConfirm = vi.fn();
    renderInApp(
      <ConfirmDialogControlled
        open
        onOpenChange={() => {}}
        title="Ta bort samling"
        description="Det här går inte att ångra."
        confirmLabel="Ta bort"
        pending
        onConfirm={onConfirm}
      />
    );
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort samling" });
    const remove = within(dialog).getByRole("button", { name: "Ta bort" });
    remove.focus();

    fireEvent.click(remove);

    expect(remove).toHaveProperty("disabled", false);
    expect(remove.getAttribute("aria-busy")).toBe("true");
    expect(document.activeElement).toBe(remove);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("does not ask its owner to close while pending", async () => {
    const onOpenChange = vi.fn();
    renderInApp(
      <ConfirmDialogControlled
        open
        onOpenChange={onOpenChange}
        title="Ta bort samling"
        description="Det här går inte att ångra."
        confirmLabel="Ta bort"
        pending
        onConfirm={() => {}}
      />
    );
    const dialog = await screen.findByRole("alertdialog", { name: "Ta bort samling" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("closes with Escape when idle", async () => {
    const onOpenChange = vi.fn();
    renderInApp(
      <ConfirmDialogControlled
        open
        onOpenChange={onOpenChange}
        title="Ta bort samling"
        description="Det här går inte att ångra."
        confirmLabel="Ta bort"
        onConfirm={() => {}}
      />
    );
    fireEvent.keyDown(await screen.findByRole("alertdialog"), { key: "Escape" });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
