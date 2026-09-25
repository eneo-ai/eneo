import { afterEach, describe, expect, it, vi } from "vitest";
import { settleDialog } from "./settleDialog";

function held() {
  let resolve!: () => void;
  const promise = new Promise<void>((res) => (resolve = res));
  return { promise, resolve };
}

function focusable() {
  return { focus: vi.fn() } as unknown as HTMLElement & { focus: ReturnType<typeof vi.fn> };
}

function closeEvent() {
  return { preventDefault: vi.fn() } as unknown as Event & {
    preventDefault: ReturnType<typeof vi.fn>;
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("settleDialog", () => {
  it("closes, then focuses the new state only once the page has reloaded and the dialog closed", async () => {
    const reloaded = held();
    const target = focusable();
    const close = vi.fn();
    const focusAfter = vi.fn(() => target);
    const settler = settleDialog({ close, reload: () => reloaded.promise, focusAfter });

    const settled = settler.settle();
    expect(close).toHaveBeenCalledTimes(1);

    const event = closeEvent();
    settler.onCloseAutoFocus(event);
    // Focus does not go back to the opener, which the action may have removed.
    expect(event.preventDefault).toHaveBeenCalledTimes(1);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(focusAfter).not.toHaveBeenCalled();

    reloaded.resolve();
    await settled;
    expect(focusAfter).toHaveBeenCalledTimes(1);
    expect(target.focus).toHaveBeenCalledTimes(1);
  });

  it("asks where focus goes after the reload, so it finds what the reload rendered", async () => {
    let current = focusable();
    const replaced = focusable();
    const settler = settleDialog({
      close: vi.fn(),
      reload: async () => {
        current = replaced;
      },
      focusAfter: () => current
    });

    const settled = settler.settle();
    settler.onCloseAutoFocus(closeEvent());
    await settled;
    expect(replaced.focus).toHaveBeenCalledTimes(1);
  });

  it("does not wait forever for a close that never hands focus back", async () => {
    vi.useFakeTimers();
    const target = focusable();
    const settler = settleDialog({
      close: vi.fn(),
      reload: () => Promise.resolve(),
      focusAfter: () => target
    });

    const settled = settler.settle();
    await vi.advanceTimersByTimeAsync(999);
    expect(target.focus).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await settled;
    expect(target.focus).toHaveBeenCalledTimes(1);
  });

  it("still moves focus when the reload fails, then reports the failure", async () => {
    const target = focusable();
    const failure = new Error("offline");
    const settler = settleDialog({
      close: vi.fn(),
      reload: () => Promise.reject(failure),
      focusAfter: () => target
    });

    const settled = settler.settle();
    settler.onCloseAutoFocus(closeEvent());
    await expect(settled).rejects.toBe(failure);
    expect(target.focus).toHaveBeenCalledTimes(1);
  });

  it("leaves a plain close alone, also after reset following an earlier settle", async () => {
    const settler = settleDialog({
      close: vi.fn(),
      reload: () => Promise.resolve(),
      focusAfter: () => focusable()
    });

    const plain = closeEvent();
    settler.onCloseAutoFocus(plain);
    expect(plain.preventDefault).not.toHaveBeenCalled();

    const settled = settler.settle();
    settler.onCloseAutoFocus(closeEvent());
    await settled;

    // Opened again: Cancel or Escape returns focus to the opener as usual.
    settler.reset();
    const again = closeEvent();
    settler.onCloseAutoFocus(again);
    expect(again.preventDefault).not.toHaveBeenCalled();
  });
});
