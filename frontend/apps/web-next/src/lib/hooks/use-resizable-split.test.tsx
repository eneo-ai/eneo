// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { useResizableSplit, type ResizableSplitOptions } from "./use-resizable-split";

const KEY = "test:split-width";

// jsdom has no PointerEvent; a MouseEvent carries what the handle reads.
window.PointerEvent ??= class extends MouseEvent {
  readonly pointerId: number;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 0;
  }
} as unknown as typeof PointerEvent;

/** A panel of 360 px or more beside a rest that keeps 484 px (the chat's side panel). */
function Split(options: Partial<ResizableSplitOptions>) {
  const { width, fits, separatorProps } = useResizableSplit({
    container: null,
    storageKey: KEY,
    defaultWidth: 520,
    minWidth: 360,
    maxFraction: 0.65,
    minRemaining: 484,
    ...options
  });
  return (
    <div>
      <div {...separatorProps} aria-label="Ändra bredd" />
      <output data-testid="state">{JSON.stringify({ width, fits })}</output>
    </div>
  );
}

const state = () =>
  JSON.parse(screen.getByTestId("state").textContent ?? "{}") as {
    width: number;
    fits: boolean | null;
  };
const handle = () => screen.getByRole("separator", { name: "Ändra bredd" });

beforeEach(() => window.localStorage.clear());
afterEach(cleanup);

describe("useResizableSplit", () => {
  it("cannot tell whether the panel fits before the container is measured", () => {
    renderInApp(<Split />);
    expect(state()).toEqual({ width: 520, fits: null });
  });

  it("narrows the panel so the rest keeps its share (an iPad sideways: 908 px)", () => {
    renderInApp(<Split container={908} />);
    expect(state()).toEqual({ width: 424, fits: true });
    expect(handle().getAttribute("aria-valuemax")).toBe("424");
  });

  it("does not fit when its smallest width would leave the rest too little", () => {
    renderInApp(<Split container={820} />);
    expect(state().fits).toBe(false);
  });

  it("restores a remembered width as far as the container allows, and again when it grows", () => {
    window.localStorage.setItem(KEY, "600");
    const { rerender } = renderInApp(<Split container={1200} />);
    expect(state().width).toBe(600);
    rerender(<Split container={908} />);
    expect(state().width).toBe(424);
    rerender(<Split container={1200} />);
    expect(state().width).toBe(600);
  });

  it("moves with the keys within its bounds and remembers the width", () => {
    renderInApp(<Split container={1200} />);
    fireEvent.keyDown(handle(), { key: "Home" });
    // 1200 − 484 is less than 65 % of 1200.
    expect(handle().getAttribute("aria-valuenow")).toBe("716");
    expect(window.localStorage.getItem(KEY)).toBe("716");
    fireEvent.keyDown(handle(), { key: "End" });
    expect(handle().getAttribute("aria-valuenow")).toBe("360");
    fireEvent.keyDown(handle(), { key: "ArrowLeft" });
    expect(handle().getAttribute("aria-valuenow")).toBe("384");
  });

  it("stops a drag at the largest width the rest allows", () => {
    renderInApp(<Split container={1200} />);
    const separator = handle();
    separator.setPointerCapture = () => {};
    separator.releasePointerCapture = () => {};
    fireEvent.pointerDown(separator, { button: 0, clientX: 600, pointerId: 1 });
    fireEvent.pointerMove(separator, { clientX: 100, pointerId: 1 });
    fireEvent.pointerUp(separator, { clientX: 100, pointerId: 1 });
    expect(state().width).toBe(716);
    expect(window.localStorage.getItem(KEY)).toBe("716");
  });

  it("keeps the remembered width when the handle is pressed without moving", () => {
    window.localStorage.setItem(KEY, "600");
    renderInApp(<Split container={908} />);
    const separator = handle();
    separator.setPointerCapture = () => {};
    separator.releasePointerCapture = () => {};
    fireEvent.pointerDown(separator, { button: 0, clientX: 600, pointerId: 1 });
    fireEvent.pointerUp(separator, { clientX: 600, pointerId: 1 });
    expect(window.localStorage.getItem(KEY)).toBe("600");
  });
});
