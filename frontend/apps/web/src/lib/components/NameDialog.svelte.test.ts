import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toastError } from "$lib/core/errors";
import { m } from "$lib/paraglide/messages";
import NameDialog from "./NameDialog.svelte";

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
  title: "Rename group",
  label: "Group name",
  submitLabel: "Save",
  pendingLabel: "Saving…"
};

const nameField = () => page.getByRole("textbox", { name: "Group name" });

beforeEach(() => {
  vi.mocked(toastError).mockReset();
});

describe("NameDialog", () => {
  it("submits the trimmed name on Enter once, shows progress and closes when it succeeds", async () => {
    const request = held();
    const onSubmit = vi.fn(() => request.promise);
    render(NameDialog, { ...baseProps, onSubmit });

    await nameField().fill("  Reports  ");
    await userEvent.keyboard("{Enter}");

    await expect
      .element(page.getByRole("button", { name: "Saving…" }))
      .toHaveAttribute("aria-disabled", "true");
    await expect.element(page.getByRole("button", { name: m.cancel() })).toBeDisabled();
    await userEvent.keyboard("{Enter}");
    await page.getByRole("button", { name: "Saving…" }).click({ force: true });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("Reports");

    request.resolve();
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("keeps submit disabled while the name is empty or unchanged", async () => {
    render(NameDialog, { ...baseProps, initial: "Reports", onSubmit: vi.fn() });

    const save = page.getByRole("button", { name: "Save" });
    await expect.element(nameField()).toHaveValue("Reports");
    await expect.element(save).toBeDisabled();

    await nameField().fill("   ");
    await expect.element(save).toBeDisabled();

    await nameField().fill(" Reports ");
    await expect.element(save).toBeDisabled();

    await nameField().fill("Archive");
    await expect.element(save).toBeEnabled();
  });

  it("stays open and reports the error with the submitted name when it fails", async () => {
    const error = new Error("forbidden");
    render(NameDialog, {
      ...baseProps,
      initial: "Reports",
      errorContext: (name: string) => `Could not rename to ${name}`,
      onSubmit: () => Promise.reject(error)
    });

    await nameField().fill("Archive");
    await page.getByRole("button", { name: "Save" }).click();

    await vi.waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(error, "Could not rename to Archive")
    );
    await expect.element(page.getByRole("dialog")).toBeVisible();
    await expect.element(nameField()).toHaveValue("Archive");
    await expect.element(page.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("cannot be dismissed while the submit runs", async () => {
    const request = held();
    render(NameDialog, { ...baseProps, onSubmit: () => request.promise });

    await nameField().fill("Reports");
    await page.getByRole("button", { name: "Save" }).click();
    await userEvent.keyboard("{Escape}");
    await expect.element(page.getByRole("dialog")).toBeVisible();

    request.resolve();
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
  });

  it("starts from the initial name again when reopened", async () => {
    const { rerender } = render(NameDialog, {
      ...baseProps,
      initial: "Reports",
      onSubmit: vi.fn()
    });

    await nameField().fill("Draft that is thrown away");
    await page.getByRole("button", { name: m.cancel() }).click();
    await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();

    await rerender({ open: true });
    await expect.element(nameField()).toHaveValue("Reports");
  });
});
