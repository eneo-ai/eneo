import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import axe from "axe-core";
import { createRawSnippet } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toastError } from "$lib/core/errors";
import { m } from "$lib/paraglide/messages";
import ConfirmDialog from "./ConfirmDialog.svelte";
import "../../app.css";

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

afterEach(async () => {
  delete document.documentElement.dataset.theme;
  document.body.classList.remove("bg-primary");
  await page.viewport(1280, 720);
});

async function settled() {
  // Measure resting colours and the finished zoom-in, not a hover or a half-drawn frame.
  await userEvent.unhover(document.body);
  await vi.waitFor(() => expect(document.getAnimations()).toHaveLength(0));
}

async function axeViolations(context: Element) {
  await settled();
  const result = await axe.run(context, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]
    }
  });
  return result.violations.flatMap((violation) =>
    violation.nodes.map((node) => `${violation.id}: ${node.html}`)
  );
}

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

  it("opens on Cancel, so a stray Enter confirms nothing", async () => {
    const onConfirm = vi.fn();
    render(ConfirmDialog, { ...baseProps, onConfirm });

    await expect.element(page.getByRole("alertdialog")).toBeVisible();
    await expect.element(page.getByRole("button", { name: m.cancel() })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await expect.element(page.getByRole("alertdialog")).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
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

  it.each(["light", "dark"] as const)(
    "keeps the dialog and an inline failure readable (%s)",
    async (scheme) => {
      document.documentElement.dataset.theme = scheme;
      // The app shell paints the page; without it dark text is measured on white.
      document.body.classList.add("bg-primary");
      render(ConfirmDialog, {
        ...baseProps,
        errorDisplay: "inline",
        onConfirm: () => Promise.reject(new Error("forbidden"))
      });

      await page.getByRole("button", { name: "Delete" }).click();
      await expect.element(page.getByRole("alert")).toBeVisible();

      expect(await axeViolations(page.getByRole("alertdialog").element())).toEqual([]);
    }
  );

  it("scrolls as a whole on a short viewport instead of clipping its body (400 % zoom)", async () => {
    await page.viewport(320, 256);
    render(ConfirmDialog, {
      ...baseProps,
      description: "Removing it cannot be undone. ".repeat(6),
      errorDisplay: "inline",
      onConfirm: () => Promise.reject(new Error("forbidden")),
      children: createRawSnippet(() => ({
        render: () => `<p>${"Everything it holds goes with it. ".repeat(8)}</p>`
      }))
    });
    await page.getByRole("button", { name: "Delete" }).click();
    await expect.element(page.getByRole("alert")).toBeInTheDocument();
    await settled();

    const content = page.getByRole("alertdialog").element() as HTMLElement;
    expect(content.getBoundingClientRect().bottom).toBeLessThanOrEqual(256);
    // Content behind `overflow: hidden` cannot be scrolled to with a mouse or a finger.
    const clipping = [content, ...content.querySelectorAll<HTMLElement>("*")].filter(
      (element) =>
        element.scrollHeight > element.clientHeight + 1 &&
        getComputedStyle(element).overflowY === "hidden"
    );
    expect(clipping.map((element) => element.outerHTML.slice(0, 100))).toEqual([]);

    for (const name of ["Delete", m.cancel()]) {
      const button = page.getByRole("button", { name }).element() as HTMLElement;
      button.scrollIntoView({ block: "nearest" });
      const rect = button.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      expect(button.contains(hit), name).toBe(true);
    }
  });
});
