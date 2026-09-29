import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toastError } from "$lib/core/errors";
import { m } from "$lib/paraglide/messages";
import ConfirmDialog from "./ConfirmDialog.svelte";

vi.mock("$lib/core/errors", async (importOriginal) => ({
  ...(await importOriginal<typeof import("$lib/core/errors")>()),
  toastError: vi.fn()
}));

function held() {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const baseProps = {
  open: true,
  title: "Delete service",
  description: "Do you really want to delete it?",
  confirmLabel: "Delete",
  pendingLabel: "Deleting…",
  errorContext: "Could not delete service"
};

beforeEach(() => {
  vi.mocked(toastError).mockReset();
});

describe("ConfirmDialog", () => {
  it("runs the action once, shows progress and closes when it succeeds", async () => {
    const request = held();
    const onConfirm = vi.fn(() => request.promise);
    render(ConfirmDialog, { ...baseProps, onConfirm });

    const confirm = page.getByRole("button", { name: "Delete" });
    await confirm.click();
    await expect
      .element(page.getByRole("button", { name: "Deleting…" }))
      .toHaveAttribute("aria-disabled", "true");
    await expect
      .element(page.getByRole("button", { name: m.cancel() }))
      .toHaveAttribute("aria-disabled", "true");
    await page.getByRole("button", { name: "Deleting…" }).click({ force: true });
    expect(onConfirm).toHaveBeenCalledTimes(1);

    request.resolve();
    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("stays open and reports the error when the action fails", async () => {
    const error = new Error("forbidden");
    render(ConfirmDialog, { ...baseProps, onConfirm: () => Promise.reject(error) });

    await page.getByRole("button", { name: "Delete" }).click();

    await vi.waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(error, "Could not delete service")
    );
    await expect.element(page.getByRole("alertdialog")).toBeVisible();
    await expect.element(page.getByRole("button", { name: "Delete" })).toBeEnabled();
    // Focus stays in the dialog, so a keyboard user can retry or cancel.
    expect(page.getByRole("alertdialog").element().contains(document.activeElement)).toBe(true);
  });

  it("cannot be dismissed while the action runs", async () => {
    const request = held();
    render(ConfirmDialog, { ...baseProps, onConfirm: () => request.promise });

    await page.getByRole("button", { name: "Delete" }).click();
    await userEvent.keyboard("{Escape}");
    await expect.element(page.getByRole("alertdialog")).toBeVisible();

    request.resolve();
    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("shows the failure inside the dialog in inline mode and clears it on retry", async () => {
    const onConfirm = vi
      .fn()
      .mockRejectedValueOnce(new Error("Still attached to an assistant"))
      .mockReturnValueOnce(new Promise(() => {}));
    render(ConfirmDialog, { ...baseProps, errorDisplay: "inline", onConfirm });

    await page.getByRole("button", { name: "Delete" }).click();

    await expect
      .element(page.getByRole("alert"))
      .toHaveTextContent(`Could not delete service: ${m.request_failed()}`);
    expect(toastError).not.toHaveBeenCalled();

    await page.getByRole("button", { name: "Delete" }).click();
    expect(page.getByRole("alert").elements()).toHaveLength(0);
  });
});
