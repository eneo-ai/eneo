// @vitest-environment jsdom
import { act, cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { PromptGuideDialog } from "./prompt-guide-dialog";
const start = vi.hoisted(() => vi.fn());
vi.mock("./helper-runs", () => ({
  startPromptGuideRun: start,
  continuePromptGuideRun: vi.fn(),
  updateHelperRunStatus: vi.fn().mockResolvedValue({})
}));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
const props = {
  onOpenChange: vi.fn(),
  targetId: "assistant",
  targetPrompt: "",
  hasUnsavedPromptChanges: false,
  onApply: vi.fn()
};
it("aborts the current helper stream on unmount", () => {
  start.mockReturnValue(new Promise(() => {}));
  const { unmount } = renderInApp(<PromptGuideDialog {...props} open />);
  const signal = start.mock.calls[0]![0].signal as AbortSignal;
  unmount();
  expect(signal.aborted).toBe(true);
});
it("ignores late chunks and completion from the previous dialog session", async () => {
  let rejectOld!: (error: Error) => void;
  start.mockImplementationOnce(
    () =>
      new Promise((_resolve, reject) => {
        rejectOld = reject;
      })
  );
  start.mockReturnValue(new Promise(() => {}));
  const { rerender } = renderInApp(<PromptGuideDialog {...props} open />);
  const first = start.mock.calls[0]![0];
  rerender(<PromptGuideDialog {...props} open={false} />);
  rerender(<PromptGuideDialog {...props} open />);
  expect(start).toHaveBeenCalledTimes(2);
  await act(async () => {
    first.onAnswer({ run: { id: "old" }, answer: "Old stale answer" });
    rejectOld(new Error("Aborted old request"));
  });
  expect(screen.queryByText("Old stale answer")).toBeNull();
  expect(screen.getByLabelText("Promptguiden skriver svar").getAttribute("aria-busy")).toBe("true");
});
