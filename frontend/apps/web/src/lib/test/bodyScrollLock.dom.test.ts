import { cleanup, render, waitFor } from "@testing-library/svelte";
import { afterEach, expect, it, vi } from "vitest";

import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
import { settleBodyScrollLock } from "./bodyScrollLock";

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

async function openDialogThatLocksTheBody(): Promise<void> {
  render(ConfirmDialog, {
    props: { open: true, title: "Remove", confirmLabel: "Remove", onConfirm: vi.fn() }
  });
  await waitFor(() => expect(document.body.style.overflow).toBe("hidden"));
}

it("waits until an unmounted dialog has released the body scroll lock", async () => {
  // Kills the mutant that returns while the library's release timer is still
  // pending: the file would end with jsdom gone when the timer fires.
  await openDialogThatLocksTheBody();
  cleanup();
  expect(document.body.style.overflow).toBe("hidden");

  await settleBodyScrollLock();

  expect(document.body.style.overflow).not.toBe("hidden");
});

it("gives up when the lock is still held and the file left fake timers on", async () => {
  // Kills two mutants that would fail a whole file in this hook: a wait
  // without a bound, and a wait on the global timer a test has replaced.
  await openDialogThatLocksTheBody();
  vi.useFakeTimers();

  await settleBodyScrollLock();

  expect(document.body.style.overflow).toBe("hidden");
});
